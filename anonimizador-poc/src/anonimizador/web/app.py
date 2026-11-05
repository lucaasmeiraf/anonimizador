"""API da interface de revisão.

Transporte HTTP e nada mais: toda regra sobre o que é tarjado e quando o
arquivo pode ser baixado está em ``sessao.py``. O que este módulo garante é
que não existe rota que contorne aquelas regras — em particular, que
``/download`` não serve arquivo que a verificação não aprovou.

O modelo de NER é carregado **uma vez**, na subida. São ~1 GB de pesos; fazer
isso por requisição tornaria o upload inutilizável.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import fitz  # PyMuPDF
import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import config, db
from ..pipeline import DetectionPipeline
from ..pdf_redactor import PseudonimoImpossivelNoPDF
from ..db.modelos import PLATAFORMA
from ..politica import PerfilPolitica, PoliticaInvalida
from . import auth, posse, usuarios
from .sessao import (
    DocumentoIlegivel,
    PdfProtegido,
    Sessao,
    SessaoEncerrada,
    Sessoes,
    SpanUI,
    perfil_padrao,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("anonimizador.web")

RAIZ_SESSOES = Path(os.getenv("ANON_SESSOES", "/app/out/sessoes"))
ESTATICOS = Path(__file__).parent / "static"

# Limite de upload. Um PDF de centenas de páginas é caso legítimo, mas a
# latência de detecção cresce linear e a Fase 0 só mediu até 3 páginas.
MAX_BYTES = int(os.getenv("ANON_MAX_UPLOAD", str(50 * 1024 * 1024)))

# Serviço de análise por LLM externa. Vive noutro container, com egress; este
# aqui não tem rota para fora. Ausente o serviço, a rota de análise responde
# 502 — nunca tenta falar direto com a internet.
ANALISE_URL = os.getenv("ANON_ANALISE_URL", "http://analise:8100").rstrip("/")
ANALISE_TIMEOUT = float(os.getenv("ANON_ANALISE_TIMEOUT", "180"))

# --------------------------------------------------------------------------
# Modo de acesso — Bloco 2 da Fase 4
# --------------------------------------------------------------------------
# O sistema tem DOIS modos legítimos, e a diferença não é de conveniência:
#
#   * **local** (padrão): a porta sai em `127.0.0.1` e o perímetro É o
#     endereço — só quem está na máquina alcança. É o produto homologado hoje
#     (`HOMOLOGACAO.md`): uma pessoa, uma máquina, sem login.
#
#   * **com login** (`ANON_EXIGIR_LOGIN=1`): a porta pode ser pública, e aí
#     quem é você passa a ser pergunta que o sistema precisa responder.
#
# A chave é um interruptor explícito, e não detecção automática, porque
# adivinhar errado aqui tem um lado catastrófico: servir o documento de todos
# para qualquer um. Quem publica a porta liga o interruptor; o padrão nunca
# "descobre" que agora pode ficar aberto.
EXIGIR_LOGIN = os.getenv("ANON_EXIGIR_LOGIN", "").strip() in ("1", "true", "sim")

COOKIE_SESSAO = "anon_sessao"
COOKIE_CSRF = "anon_csrf"
CABECALHO_CSRF = "x-csrf-token"

# `Secure` no cookie. Padrão ligado — e funciona no teste local porque o
# navegador trata `127.0.0.1` como contexto seguro mesmo em HTTP. Só desligar
# para depurar atrás de um proxy que termine TLS de forma esquisita.
COOKIE_SEGURO = os.getenv("ANON_COOKIE_INSEGURO", "").strip() not in ("1", "true")

sessoes = Sessoes(RAIZ_SESSOES)
_pipeline: DetectionPipeline | None = None

# Uma detecção por vez. As rotas que detectam rodam no pool de threads do
# FastAPI (são `def`, não `async def`), então duas pessoas enviando ao mesmo
# tempo chegariam juntas ao mesmo `AnalyzerEngine` e ao mesmo pipeline do
# transformers — e nenhum dos dois se declara seguro para chamada concorrente.
# Serializar não custa vazão: a detecção já ocupa todos os núcleos da CPU.
# O que ela não pode mais é travar o servidor inteiro enquanto roda.
_trava_deteccao = threading.Lock()


def pipeline() -> DetectionPipeline:
    global _pipeline
    if _pipeline is None:
        logger.info("carregando pipeline de deteccao (%s)...", config.NER_PADRAO)
        _pipeline = DetectionPipeline()
        logger.info("pipeline pronto")
    return _pipeline


def detectar(texto: str, score_threshold: float | None = None):
    """Todo caminho de detecção da API passa por aqui, sob a trava."""
    with _trava_deteccao:
        if score_threshold is None:
            return pipeline().analyze(texto)
        return pipeline().analyze(texto, score_threshold=score_threshold)


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    # Carrega o modelo na subida, não na primeira requisição: o usuário não
    # deve pagar 30 s de carregamento achando que é o documento dele.
    pipeline().analyze("Aquecimento: CPF 529.982.247-25 de João da Silva.")
    # Sobrou documento em claro de uma execução anterior? Vai embora agora.
    sessoes.limpar_orfaos()
    sessoes.expirar()

    # Banco de identidade. Só é exigido quando há login a exigir — os testes
    # rodam sem Postgres alcançável (`network_mode: none`), e o modo local não
    # precisa dele.
    #
    # Quando o login É exigido, banco fora do ar derruba a subida, de
    # propósito. A alternativa seria descobrir na primeira requisição, e aí só
    # há dois desfechos: toda requisição devolve 500, inútil, ou alguém
    # "conserta" deixando seguir sem autenticação, catastrófico.
    if EXIGIR_LOGIN:
        db.iniciar()
        logger.info("login EXIGIDO; banco de identidade ligado")
    else:
        try:
            db.iniciar()
            logger.info("banco de identidade ligado (login nao exigido)")
        except db.BancoIndisponivel as exc:
            logger.info("sem banco de identidade: %s", exc)
        logger.warning(
            "login NAO exigido. Correto apenas com a porta em 127.0.0.1, onde "
            "o perimetro e o endereco. Em porta publica, ligue "
            "ANON_EXIGIR_LOGIN=1."
        )
    yield


app = FastAPI(
    title="Anonimizador — revisão",
    docs_url=None,
    redoc_url=None,
    lifespan=ciclo_de_vida,
)


# --------------------------------------------------------------------------
# Identidade — Bloco 2 da Fase 4
# --------------------------------------------------------------------------
def usuario_atual(request: Request):
    """Resolve o cookie em usuário. **Falha fechada.**

    Em modo local devolve ``None`` e ninguém pergunta nada — o perímetro é o
    endereço. Com `ANON_EXIGIR_LOGIN=1`, sessão ausente, desconhecida,
    expirada ou de usuário desativado é **401**, nunca "segue como anônimo".
    É a dependência que o `goal-fase-4.md` §Bloco 2 pede.

    O objeto do usuário sobrevive ao fim da transação porque o `sessionmaker`
    usa `expire_on_commit=False`; sem isso, ler `papel` depois do `commit`
    dispararia uma consulta numa sessão já fechada.
    """
    if not EXIGIR_LOGIN:
        return None
    with db.sessao() as s:
        u = auth.usuario_da_sessao(s, request.cookies.get(COOKIE_SESSAO))
        if u is None:
            raise HTTPException(401, "sessão ausente ou expirada; entre de novo")
        return u


def conferir_csrf(request: Request) -> None:
    """Dupla submissão de token, exigida só quando há cookie de sessão.

    CSRF é um ataque que **monta em cookie**: o navegador da vítima envia o
    cookie sozinho, e o site do atacante colhe o efeito. Sem cookie de sessão
    não há o que montar, e é por isso que a conferência não se aplica ao modo
    local — aplicá-la ali quebraria todo cliente de linha de comando sem
    ganhar segurança nenhuma.

    `SameSite=Lax` no cookie já barra a maior parte. Este é o cinto além do
    suspensório, e é o que cobre o caso que o `Lax` não cobre: navegador
    antigo, e requisição de topo com método seguro que o servidor trate como
    insegura.

    A comparação é `compare_digest` — tempo constante. Comparar com `==`
    vazaria o token caractere a caractere pelo tempo de resposta.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    cookie = request.cookies.get(COOKIE_CSRF)
    if not cookie:
        return
    enviado = request.headers.get(CABECALHO_CSRF, "")
    if not secrets.compare_digest(cookie, enviado):
        raise HTTPException(403, "token anti-CSRF ausente ou incorreto")


def _plantar_cookies(resposta: Response, token: str) -> str:
    """Cookie de sessão (ilegível ao JS) e cookie anti-CSRF (legível).

    O par é deliberado. O de sessão é `HttpOnly` para que um XSS não consiga
    roubá-lo; o anti-CSRF **precisa** ser legível, porque é o JS da própria
    página que o copia para o cabeçalho — e isso é seguro porque o site do
    atacante não consegue ler cookie de outro domínio.
    """
    csrf = secrets.token_urlsafe(32)
    comum = dict(secure=COOKIE_SEGURO, samesite="lax", path="/")
    resposta.set_cookie(COOKIE_SESSAO, token, httponly=True, **comum)
    resposta.set_cookie(COOKIE_CSRF, csrf, httponly=False, **comum)
    return csrf


def _apagar_cookies(resposta: Response) -> None:
    for nome in (COOKIE_SESSAO, COOKIE_CSRF):
        resposta.delete_cookie(nome, path="/")


class Credencial(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    # Teto na senha: o Argon2 aceita entrada de qualquer tamanho, e sem limite
    # um corpo de megabytes viraria trabalho de CPU gratuito para o atacante.
    senha: str = Field(min_length=1, max_length=1024)


class TrocaDeSenha(BaseModel):
    atual: str = Field(min_length=1, max_length=1024)
    nova: str = Field(min_length=12, max_length=1024)


@app.post("/api/login")
def login(corpo: Credencial, request: Request, resposta: Response) -> dict:
    if not EXIGIR_LOGIN:
        raise HTTPException(409, "este servidor roda em modo local, sem login")
    ip = request.client.host if request.client else None
    try:
        with db.sessao() as s:
            aberta = auth.autenticar(s, corpo.email, corpo.senha, ip)
    except auth.ExcessoDeTentativas as exc:
        # 429 e não 401: a diferença é acionável para quem está do outro lado.
        # Não registra tentativa: ela já estava barrada, e contar de novo
        # transformaria a trava em bloqueio permanente a cada nova batida.
        raise HTTPException(429, str(exc)) from exc
    except auth.FalhaDeLogin as exc:
        # Transação PRÓPRIA para a tentativa falha. A de cima acabou em
        # exceção e foi desfeita — gravar lá dentro era o defeito que deixava
        # o limite de tentativa contando zero. Ver `auth.autenticar`.
        with db.sessao() as s:
            auth.registrar_falha(s, corpo.email, ip)
        raise HTTPException(401, str(exc)) from exc

    csrf = _plantar_cookies(resposta, aberta.token)
    return {
        "papel": aberta.papel,
        "inquilino_id": aberta.inquilino_id,
        "troca_senha_obrigatoria": aberta.troca_senha_obrigatoria,
        "csrf": csrf,
    }


@app.get("/api/eu")
def eu(request: Request) -> dict:
    """Quem está logado, para a tela decidir o que mostrar na abertura.

    Rota separada e não um campo de `/api/saude` porque as duas respondem
    perguntas diferentes: saúde é do serviço e precisa ficar aberta para
    monitoramento; esta é da sessão.

    Em modo local devolve `exige_login: false` e a tela nem oferece entrada.
    Com login exigido e sem sessão, **401** — e é o 401 que faz a tela de
    login aparecer.
    """
    if not EXIGIR_LOGIN:
        return {"exige_login": False}
    with db.sessao() as s:
        u = auth.usuario_da_sessao(s, request.cookies.get(COOKIE_SESSAO))
        if u is None:
            raise HTTPException(401, "sessão ausente ou expirada")
        return {
            "exige_login": True,
            "email": u.email,
            "papel": u.papel,
            "troca_senha_obrigatoria": u.troca_senha_obrigatoria,
        }


# --------------------------------------------------------------------------
# Administração de usuários — Bloco 2b, pela tela
# --------------------------------------------------------------------------
# Só o `dono` do inquilino alcança estas rotas, e só sobre gente do inquilino
# dele. As regras moram em `usuarios.py`; aqui é transporte e código de
# status, como no resto de `app.py`.
#
# **Não existe rota de autocadastro**, e a ausência é a funcionalidade:
# `tests/test_usuarios.py` falha se alguma aparecer.
class NovoUsuario(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    papel: str = "operador"


class AtivoDoUsuario(BaseModel):
    ativo: bool


def _traduzir(exc: Exception) -> HTTPException:
    """403 para falta de papel, 422 para dado ruim. Nunca 500."""
    if isinstance(exc, usuarios.NaoAutorizado):
        return HTTPException(403, str(exc))
    return HTTPException(422, str(exc))


@app.get("/api/usuarios")
def listar_usuarios(usuario=Depends(usuario_atual)) -> dict:
    if usuario is None:
        raise HTTPException(409, "este servidor roda em modo local, sem login")
    try:
        with db.sessao() as s:
            return {"usuarios": usuarios.listar(s, s.get(type(usuario), usuario.id))}
    except (usuarios.NaoAutorizado, usuarios.DadosInvalidos) as exc:
        raise _traduzir(exc) from exc


@app.post("/api/usuarios", dependencies=[Depends(conferir_csrf)])
def criar_usuario(corpo: NovoUsuario, usuario=Depends(usuario_atual)) -> dict:
    """Cria e devolve a senha temporária — **a única vez que ela existe**.

    Ela não é guardada em claro em lugar nenhum: no banco só há o hash. Quem
    chamou precisa mostrá-la na hora, e a tela avisa que ela não volta.
    """
    if usuario is None:
        raise HTTPException(409, "este servidor roda em modo local, sem login")
    try:
        with db.sessao() as s:
            novo_id, senha = usuarios.criar(
                s, s.get(type(usuario), usuario.id), corpo.email, corpo.papel
            )
    except (usuarios.NaoAutorizado, usuarios.DadosInvalidos) as exc:
        raise _traduzir(exc) from exc
    return {"id": novo_id, "email": corpo.email.strip().lower(), "senha": senha}


@app.post("/api/usuarios/{usuario_id}/senha", dependencies=[Depends(conferir_csrf)])
def redefinir_senha_de(usuario_id: str, usuario=Depends(usuario_atual)) -> dict:
    if usuario is None:
        raise HTTPException(409, "este servidor roda em modo local, sem login")
    try:
        with db.sessao() as s:
            senha = usuarios.redefinir_senha(
                s, s.get(type(usuario), usuario.id), usuario_id
            )
    except (usuarios.NaoAutorizado, usuarios.DadosInvalidos) as exc:
        raise _traduzir(exc) from exc
    return {"senha": senha}


@app.patch("/api/usuarios/{usuario_id}", dependencies=[Depends(conferir_csrf)])
def alternar_usuario(
    usuario_id: str, corpo: AtivoDoUsuario, usuario=Depends(usuario_atual)
) -> dict:
    if usuario is None:
        raise HTTPException(409, "este servidor roda em modo local, sem login")
    try:
        with db.sessao() as s:
            return usuarios.alternar_ativo(
                s, s.get(type(usuario), usuario.id), usuario_id, corpo.ativo
            )
    except (usuarios.NaoAutorizado, usuarios.DadosInvalidos) as exc:
        raise _traduzir(exc) from exc


@app.post("/api/logout", dependencies=[Depends(conferir_csrf)])
def logout(request: Request, resposta: Response) -> dict:
    """Apaga a linha da sessão, não só o cookie. Ver `auth.fechar_sessao`."""
    encerrada = False
    if EXIGIR_LOGIN:
        with db.sessao() as s:
            encerrada = auth.fechar_sessao(s, request.cookies.get(COOKIE_SESSAO))
    _apagar_cookies(resposta)
    return {"encerrada": encerrada}


@app.post("/api/senha", dependencies=[Depends(conferir_csrf)])
def trocar_senha(
    corpo: TrocaDeSenha, resposta: Response, usuario=Depends(usuario_atual)
) -> dict:
    """Troca a senha e derruba **todas** as sessões, inclusive esta.

    Derrubar a própria sessão é intencional: quem troca a senha porque suspeita
    de acesso indevido precisa que o outro lado caia. O preço é um login novo,
    e é pequeno.
    """
    if usuario is None:
        raise HTTPException(409, "este servidor roda em modo local, sem login")
    try:
        with db.sessao() as s:
            auth.trocar_senha(s, s.get(type(usuario), usuario.id), corpo.atual, corpo.nova)
    except auth.FalhaDeLogin as exc:
        raise HTTPException(401, str(exc)) from exc
    _apagar_cookies(resposta)
    return {"trocada": True, "entrar_de_novo": True}


def pegar_sessao(doc_id: str, usuario=Depends(usuario_atual)) -> Sessao:
    """O gargalo de toda rota de documento — e agora também o de login.

    A exigência de sessão entra **aqui**, num lugar só, e não rota a rota:
    `tests/test_posse_rotas.py` percorre `app.routes` e falha se alguma rota
    de documento não passar por esta função, então proteger o gargalo protege
    todas, inclusive a que alguém acrescentar depois.

    Duas perguntas, nesta ordem: **quem é você** (`usuario_atual`, que levanta
    401 sem sessão) e **este documento é seu** (`posse.alcanca`, Bloco 3).

    A segunda responde **404, nunca 403**. O 403 diria "existe, mas não é
    seu", que é informação a mais do que o chamador precisa — confirmar que um
    processo existe neste servidor já diz algo sobre quem é cliente de quem.
    Por isso a recusa por posse é indistinguível de documento inexistente.
    """
    sessoes.expirar()
    s = sessoes.obter(doc_id)
    if s is None:
        raise HTTPException(404, "sessão inexistente ou expirada")

    if usuario is not None:
        with db.sessao() as bd:
            if not posse.alcanca(bd, doc_id, usuario):
                logger.warning("acesso negado ao documento por falta de posse")
                raise HTTPException(404, "sessão inexistente ou expirada")
    return s


# --------------------------------------------------------------------------
# Documento
# --------------------------------------------------------------------------
@app.post("/api/doc")
def criar_doc(
    arquivo: UploadFile = File(...),
    usuario=Depends(usuario_atual),
    _csrf=Depends(conferir_csrf),
) -> dict:
    # `def`, não `async def`: a detecção é CPU pura e leva ~0,7 s por página
    # (102 páginas mediram 69 s). Dentro de `async def` ela roda no laço de
    # eventos, e durante esse tempo o servidor inteiro para de responder —
    # medido em 2026-09-24: `/api/saude` ficou 60 s sem resposta, e a tela de
    # qualquer outra pessoa congelaria junto. Como `def`, o FastAPI a leva ao
    # pool de threads. `tests/test_envio_nao_trava.py` trava isto.
    if usuario is not None and usuario.papel == PLATAFORMA:
        # `plataforma` administra: cria inquilino, aprova cadastro. Nao abre
        # documento, e e decisao de seguranca — um super-usuario que atravessa
        # inquilinos E le documento e porta dos fundos por desenho
        # (`goal-fase-4.md` §3).
        #
        # 403 e nao 404 aqui porque a pessoa conhece o proprio papel: nao ha o
        # que esconder, e "nao existe" seria confuso num caminho de criacao.
        # Para LER documento alheio o codigo continua sendo 404.
        #
        # `posse.registrar` tambem recusa, e continua recusando: aquela e a
        # trava contra defeito de rota, esta e a resposta ao usuario.
        raise HTTPException(
            403, "o papel plataforma administra o sistema e não abre documento"
        )

    dados = arquivo.file.read()
    if not dados:
        raise HTTPException(400, "arquivo vazio")
    if len(dados) > MAX_BYTES:
        raise HTTPException(413, f"arquivo acima de {MAX_BYTES // (1024 * 1024)} MB")
    if not dados.startswith(b"%PDF"):
        raise HTTPException(415, "só PDF nesta fase")

    try:
        sessao = sessoes.criar(arquivo.filename or "documento.pdf", dados)
    except PdfProtegido as exc:
        raise HTTPException(
            422,
            "este PDF está protegido por senha; remova a proteção (salve uma "
            "cópia sem senha no leitor de PDF) e envie de novo",
        ) from exc
    except DocumentoIlegivel as exc:
        raise HTTPException(422, "não foi possível ler este arquivo como PDF") from exc

    if usuario is not None:
        # A posse nasce junto com o documento. Gravar depois de detectar
        # deixaria uma janela — de dezenas de segundos num documento longo —
        # em que o documento existe e não é de ninguém, e nela o
        # `pegar_sessao` recusaria até para quem acabou de enviar.
        with db.sessao() as bd:
            posse.registrar(bd, sessao.doc_id, usuario)

    sessao.perfil = perfil_padrao()

    if not sessao.tm.text.strip():
        # PDF sem texto extraível é quase sempre digitalização. A Fase 0 não
        # faz OCR, e uma tela vazia sem explicação faria o usuário concluir
        # que o documento está limpo.
        sessoes.remover(sessao.doc_id)
        if usuario is not None:
            with db.sessao() as bd:
                posse.esquecer(bd, sessao.doc_id)
        raise HTTPException(
            422,
            "nenhum texto extraível: provavelmente um PDF escaneado. "
            "OCR está fora do escopo desta fase.",
        )

    detectados = detectar(sessao.tm.text)
    for i, sp in enumerate(detectados, 1):
        sid = f"s{i}"
        sessao.spans[sid] = SpanUI(
            id=sid,
            entity=sp.entity,
            score=sp.score,
            start=sp.start,
            end=sp.end,
            valor=sp.text_of(sessao.tm.text),
            nota=sp.nota,
        )
    logger.info("sessao %s: %d spans detectados", sessao.doc_id, len(detectados))
    return sessao.to_dict()


@app.get("/api/doc/{doc_id}")
def ler_doc(sessao: Sessao = Depends(pegar_sessao)) -> dict:
    return sessao.to_dict()


@app.delete("/api/doc/{doc_id}")
def apagar_doc(sessao: Sessao = Depends(pegar_sessao)) -> dict:
    # Passa por `pegar_sessao` como as demais, e não por `doc_id` cru. A
    # diferença não aparece hoje — o gargalo é onde a verificação de posse
    # entra na Fase 4, e apagar documento alheio é a última coisa que pode
    # ficar de fora dela. `test_posse_rotas.py` trava isto.
    if not sessoes.remover(sessao.doc_id):
        raise HTTPException(404, "sessão inexistente")
    if EXIGIR_LOGIN:
        with db.sessao() as bd:
            posse.esquecer(bd, sessao.doc_id)
    return {"removida": True}


@app.get("/api/doc/{doc_id}/pagina/{numero}.png")
def pagina_png(numero: int, escala: float = 2.0, sessao: Sessao = Depends(pegar_sessao)):
    if not 0 <= numero < len(sessao.paginas):
        raise HTTPException(404, "página inexistente")
    escala = max(0.5, min(escala, 4.0))

    doc = fitz.open(str(sessao.original))
    try:
        pix = doc.load_page(numero).get_pixmap(matrix=fitz.Matrix(escala, escala))
        png = pix.tobytes("png")
    finally:
        doc.close()
    # `private`: é conteúdo de documento do usuário; não pode ser cacheado por
    # intermediário compartilhado.
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


# --------------------------------------------------------------------------
# Edição da proposta
# --------------------------------------------------------------------------
class AlternarSpan(BaseModel):
    span_id: str
    ativo: bool


@app.patch("/api/doc/{doc_id}/span")
def alternar_span(corpo: AlternarSpan, sessao: Sessao = Depends(pegar_sessao)) -> dict:
    if corpo.span_id not in sessao.spans:
        raise HTTPException(404, "span inexistente")
    sessao.alternar(corpo.span_id, corpo.ativo)
    return sessao.to_dict()


@app.patch("/api/doc/{doc_id}/span/iguais")
def alternar_iguais(corpo: AlternarSpan, sessao: Sessao = Depends(pegar_sessao)) -> dict:
    """O clique individual para todos os trechos com o mesmo valor.
    O que conta como "igual" é decidido em `Sessao.alternar_iguais`."""
    if corpo.span_id not in sessao.spans:
        raise HTTPException(404, "span inexistente")
    n = sessao.alternar_iguais(corpo.span_id, corpo.ativo)
    resposta = sessao.to_dict()
    resposta["alterados"] = n
    return resposta


class MudarEntidade(BaseModel):
    span_id: str
    entidade: str


@app.patch("/api/doc/{doc_id}/span/entidade")
def mudar_entidade(corpo: MudarEntidade, sessao: Sessao = Depends(pegar_sessao)) -> dict:
    if corpo.span_id not in sessao.spans:
        raise HTTPException(404, "span inexistente")
    try:
        sessao.mudar_entidade(corpo.span_id, corpo.entidade)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return sessao.to_dict()


@app.delete("/api/doc/{doc_id}/span/{span_id}")
def remover_span(span_id: str, sessao: Sessao = Depends(pegar_sessao)) -> dict:
    """Apaga um trecho que o usuário adicionou. Só os dele."""
    try:
        sessao.remover_span(span_id)
    except KeyError as exc:
        raise HTTPException(404, "span inexistente") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return sessao.to_dict()


class AlternarManuais(BaseModel):
    ativo: bool


@app.patch("/api/doc/{doc_id}/manuais")
def alternar_manuais(
    corpo: AlternarManuais, sessao: Sessao = Depends(pegar_sessao)
) -> dict:
    """Liga ou desliga em lote os trechos que o usuário apontou.

    `PATCH` e não `PUT /perfil`: isto não muda política de entidade, muda o
    estado de trechos específicos — o mesmo que o clique individual faz, em
    lote. Ver `Sessao.alternar_manuais`.
    """
    n = sessao.alternar_manuais(corpo.ativo)
    resposta = sessao.to_dict()
    resposta["alterados"] = n
    return resposta


class AlternarEntidade(BaseModel):
    entidade: str
    ligar: bool


@app.patch("/api/doc/{doc_id}/entidade")
def alternar_entidade(
    corpo: AlternarEntidade, sessao: Sessao = Depends(pegar_sessao)
) -> dict:
    """A caixa da classe no inventário. Ver `Sessao.alternar_entidade`."""
    try:
        sessao.alternar_entidade(corpo.entidade, corpo.ligar)
    except (ValueError, PoliticaInvalida) as exc:
        raise HTTPException(400, str(exc)) from exc
    return sessao.to_dict()


@app.delete("/api/doc/{doc_id}/manuais")
def remover_manuais(sessao: Sessao = Depends(pegar_sessao)) -> dict:
    n = sessao.remover_manuais()
    resposta = sessao.to_dict()
    resposta["removidos"] = n
    return resposta


@app.get("/api/doc/{doc_id}/texto/{numero}")
def texto_da_pagina(numero: int, sessao: Sessao = Depends(pegar_sessao)) -> dict:
    """Palavras da página com suas caixas, para a camada de seleção.

    A página é servida como imagem, então não há texto selecionável — o
    usuário não consegue copiar um trecho para apontar o que faltou, que é
    justamente o fluxo mais natural. Esta rota devolve as palavras e onde elas
    estão; o front-end desenha texto transparente por cima da imagem e o
    navegador cuida de seleção e cópia.

    Vem do PDF **original**: é o que está sendo revisado. Serve à mesma sessão
    que já entregou a imagem da página, então não expõe nada novo.
    """
    if not 0 <= numero < len(sessao.paginas):
        raise HTTPException(404, "página inexistente")
    # Vem do `TextMap` da sessão, não de `get_text("words")`: cada palavra
    # traz o offset dela no texto completo, e é isso que permite converter
    # uma seleção do navegador em um intervalo exato de caracteres.
    return {"pagina": numero, "palavras": sessao.tm.palavras_da_pagina(numero)}


class Intervalo(BaseModel):
    inicio: int = Field(ge=0)
    fim: int = Field(ge=1)
    # O texto que o usuário viu selecionado. Não é o que define a tarja — os
    # offsets definem —, é o que permite ao servidor conferir que eles apontam
    # para o mesmo lugar. Ver `Sessao._conferir_intervalo`.
    texto: str = Field(default="", max_length=4000)


@app.post("/api/doc/{doc_id}/intervalo")
def tarjar_intervalo(
    corpo: Intervalo, sessao: Sessao = Depends(pegar_sessao)
) -> dict:
    """Tarja exatamente o trecho selecionado — só ele.

    Diferente de `/termo`, que cobre todas as ocorrências: selecionar é
    apontar *esta*, digitar é descrever um valor.
    """
    try:
        criado = sessao.adicionar_intervalo(corpo.inicio, corpo.fim, corpo.texto)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    resposta = sessao.to_dict()
    resposta["adicionados"] = 1
    resposta["span_id"] = criado.id
    return resposta


class Termo(BaseModel):
    termo: str = Field(min_length=2, max_length=200)


@app.post("/api/doc/{doc_id}/termo")
def adicionar_termo(corpo: Termo, sessao: Sessao = Depends(pegar_sessao)) -> dict:
    """Caminho determinístico do chat: o usuário aponta, o backend acha todas.

    Sem LLM. O usuário cita o valor que faltou e todas as ocorrências literais
    viram span. Exato e auditável — ver `goal-fase-1.md`, seção "Chat".
    """
    try:
        criados = sessao.adicionar_por_termo(corpo.termo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    resposta = sessao.to_dict()
    resposta["adicionados"] = len(criados)
    return resposta


@app.get("/api/doc/{doc_id}/contar")
def contar_termo(termo: str, sessao: Sessao = Depends(pegar_sessao)) -> dict:
    """Quantas ocorrências `/termo` marcaria e quantas a verificação acha —
    sem criar nada. Ver `Sessao.contar_termo`."""
    if len(termo) > 200:
        raise HTTPException(400, "termo longo demais")
    try:
        return sessao.contar_termo(termo)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class PerfilEntrada(BaseModel):
    nome: str = "personalizado"
    descricao: str = ""
    padrao: str = "tarja"
    regras: dict[str, str] = Field(default_factory=dict)


@app.put("/api/doc/{doc_id}/perfil")
def aplicar_perfil(
    corpo: PerfilEntrada, sessao: Sessao = Depends(pegar_sessao)
) -> dict:
    perfil = PerfilPolitica(
        nome=corpo.nome,
        descricao=corpo.descricao,
        padrao=corpo.padrao,
        regras=corpo.regras,
    )
    try:
        sessao.aplicar_perfil(perfil)
    except PoliticaInvalida as exc:
        # 422 e não 400: a requisição está bem formada, o que ela pede é que
        # não é executável. `pseudonimo` e `mascara` caem aqui.
        raise HTTPException(422, str(exc)) from exc
    return sessao.to_dict()


# --------------------------------------------------------------------------
# Aprovação e download
# --------------------------------------------------------------------------
@app.post("/api/doc/{doc_id}/aprovar")
def aprovar(sessao: Sessao = Depends(pegar_sessao)) -> dict:
    if not sessao.spans_ativos():
        raise HTTPException(400, "nenhuma tarja ativa: não há o que anonimizar")
    try:
        sessao.aprovar()
    except PseudonimoImpossivelNoPDF as exc:
        # 422 e não 500: a requisição está correta e o documento é que não
        # comporta o que o perfil pede. A mensagem carrega token, entidade e
        # larguras — nunca o valor —, que é o que permite ao usuário decidir
        # entre trocar aquelas entidades para tarja ou aceitar o documento
        # como está.
        raise HTTPException(422, str(exc)) from exc
    return sessao.to_dict()


@app.post("/api/doc/{doc_id}/preverificar")
def preverificar(sessao: Sessao = Depends(pegar_sessao)) -> dict:
    """A verificação da aprovação, rodada durante a revisão.

    Não devolve arquivo nem aprova nada: o PDF de prova é apagado antes da
    resposta, e baixar continua exigindo `/aprovar`. Ver `Sessao.preverificar`.
    """
    try:
        return sessao.preverificar()
    except SessaoEncerrada as exc:
        raise HTTPException(410, "sessão encerrada") from exc


@app.get("/api/doc/{doc_id}/download")
def baixar(sessao: Sessao = Depends(pegar_sessao)):
    """O gate. Não existe caminho que sirva arquivo não verificado.

    `pode_baixar` exige aprovação **e** `verify().ok`. Qualquer edição depois
    da aprovação a invalida (`Sessao._invalidar`), então o arquivo servido
    aqui é sempre o que foi verificado, nunca uma versão anterior.
    """
    if not sessao.pode_baixar:
        raise HTTPException(
            409,
            "documento não aprovado ou reprovado na verificação; "
            "não há arquivo liberado",
        )
    nome = Path(sessao.nome_arquivo).stem
    return FileResponse(
        str(sessao.redigido),
        media_type="application/pdf",
        filename=f"{nome}.anonimizado.pdf",
    )


@app.post("/api/doc/{doc_id}/pseudonimizar")
def pseudonimizar(sessao: Sessao = Depends(pegar_sessao)) -> dict:
    """Gera o texto com token no lugar de cada valor.

    Artefato separado do PDF, com gate próprio. A decisão do que é substituído
    é a mesma da tarja — mora em `sessao.py`, não aqui: esta rota é transporte.
    """
    if not sessao.spans_ativos():
        raise HTTPException(400, "nenhum span ativo: não há o que pseudonimizar")
    sessao.gerar_texto_pseudonimizado()
    return sessao.to_dict()


class PedidoAnalise(BaseModel):
    prompt: str = "Resuma este documento, dizendo quem fez o quê."
    modelo: str = ""


@app.post("/api/doc/{doc_id}/analisar")
def analisar(
    corpo: PedidoAnalise, sessao: Sessao = Depends(pegar_sessao)
) -> dict:
    """Manda o texto pseudonimizado para análise por LLM externa.

    Esta rota é a única do sistema que faz conteúdo sair da máquina, e ela
    própria **não** tem saída de rede: o serviço `ui` vive numa rede
    `internal: true`. Quem fala com o OpenRouter é o serviço `analise`, que não
    monta a pasta das sessões e portanto nunca vê o original.

    Três travas antes de qualquer byte sair, na ordem:

    1. o texto existe e passou por `verify_texto` (`pode_baixar_texto`);
    2. a re-detecção sobre o texto de saída não acha nada que a política
       mandava substituir (`conferir_antes_do_envio`);
    3. o envio é por documento, numa chamada explícita — não existe
       configuração global que ligue isso e depois seja esquecida.

    Nenhuma delas prova que tudo que era dado pessoal foi detectado. Isso não
    é provável por nenhuma verificação automática, e está dito em
    `docs/05-politica-llm.md` §2.6.
    """
    if not sessao.pode_baixar_texto:
        raise HTTPException(
            409,
            "não há texto pseudonimizado verificado; gere-o antes de analisar",
        )

    achados = sessao.conferir_antes_do_envio(
        lambda texto, limiar: detectar(texto, score_threshold=limiar)
    )
    if achados:
        # Entidade e posição, nunca o valor — ver `conferir_antes_do_envio`.
        raise HTTPException(
            409,
            {
                "erro": "a conferência de pré-envio encontrou dado que deveria "
                        "ter sido substituído; nada foi enviado",
                "achados": achados,
            },
        )

    texto = sessao.texto_pseudo.read_text(encoding="utf-8")
    try:
        resposta = httpx.post(
            f"{ANALISE_URL}/analisar",
            json={"texto": texto, "prompt": corpo.prompt, "modelo": corpo.modelo},
            timeout=ANALISE_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            502, f"serviço de análise indisponível: {type(exc).__name__}"
        ) from exc

    if resposta.status_code != 200:
        detalhe = resposta.json().get("erro", resposta.text[:300])
        raise HTTPException(resposta.status_code, detalhe)

    resultado = resposta.json()
    registro = sessao.registrar_envio("openrouter", resultado)
    return {"analise": resultado, "envio": registro}


@app.get("/api/doc/{doc_id}/download/texto")
def baixar_texto(sessao: Sessao = Depends(pegar_sessao)):
    """O mesmo gate do PDF, para o artefato de texto.

    `pode_baixar_texto` exige `verify_texto().ok`, que confere as duas metades:
    nenhum valor original sobreviveu **e** nenhum token se perdeu. Qualquer
    edição posterior invalida e apaga o arquivo (`Sessao._invalidar`).
    """
    if not sessao.pode_baixar_texto:
        raise HTTPException(
            409,
            "texto não gerado ou reprovado na verificação; "
            "não há arquivo liberado",
        )
    nome = Path(sessao.nome_arquivo).stem
    return FileResponse(
        str(sessao.texto_pseudo),
        media_type="text/plain; charset=utf-8",
        filename=f"{nome}.pseudonimizado.txt",
    )


# --------------------------------------------------------------------------
# Estáticos
# --------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def raiz() -> HTMLResponse:
    """Serve a página, carimbando CSS e JS com a data de modificação deles.

    Sem isso o navegador guarda `app.js` e `estilo.css` e continua rodando a
    versão antiga depois de uma correção — o usuário recarrega, não vê
    mudança, e conclui que o conserto não funcionou. É um modo de falha
    especialmente ruim aqui, porque leva a investigar o lugar errado.

    O carimbo muda quando o arquivo muda, então o cache continua valendo entre
    duas versões iguais e é descartado exatamente quando precisa ser.
    """
    html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
    for arquivo in ("estilo.css", "app.js"):
        caminho = ESTATICOS / arquivo
        versao = int(caminho.stat().st_mtime) if caminho.exists() else 0
        html = html.replace(f"/static/{arquivo}", f"/static/{arquivo}?v={versao}")
    return HTMLResponse(
        html,
        # A própria página nunca é cacheada: ela é minúscula e é o que carrega
        # os carimbos novos.
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/saude")
def saude() -> dict:
    return {
        "ok": True,
        "ner": config.NER_PADRAO,
        "entidades": len(config.ENTIDADES_ATIVAS),
        # A tela inicial mostra os tipos e o limite reais, não uma cópia
        # escrita à mão que envelhece quando a configuração muda.
        "tipos": list(config.ENTIDADES_ATIVAS),
        "limite_mb": MAX_BYTES // (1024 * 1024),
    }


@app.get("/api/analise/saude")
def saude_analise() -> dict:
    """Diz à tela se o envio para análise existe **agora**.

    Com `make ui` o serviço `analise` não sobe, e com ele no ar sem chave toda
    chamada falha. Nos dois casos a tela não oferece o envio: botão que só
    existe para devolver erro é operador declarado sem executor, a mesma coisa
    que a invariante 5 recusa na política.

    A chamada vai para o `analise` pela rede interna, não para fora — este
    serviço continua sem egress. O timeout é curto porque a resposta decide
    só se um bloco aparece; esperar 180s por ela travaria a abertura da tela.
    """
    try:
        r = httpx.get(f"{ANALISE_URL}/saude", timeout=3.0)
        dados = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {"disponivel": False, "motivo": "serviço de análise fora do ar"}
    if not dados.get("chave_configurada"):
        return {"disponivel": False, "motivo": "chave do OpenRouter não configurada"}
    return {"disponivel": True, "modelo": dados.get("modelo_padrao")}


app.mount("/static", StaticFiles(directory=str(ESTATICOS)), name="static")
