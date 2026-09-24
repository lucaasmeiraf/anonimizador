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
from contextlib import asynccontextmanager
from pathlib import Path

import fitz  # PyMuPDF
import httpx
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import config
from ..pipeline import DetectionPipeline
from ..pdf_redactor import PseudonimoImpossivelNoPDF
from ..politica import PerfilPolitica, PoliticaInvalida
from .sessao import Sessao, Sessoes, SpanUI, perfil_padrao

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

sessoes = Sessoes(RAIZ_SESSOES)
_pipeline: DetectionPipeline | None = None


def pipeline() -> DetectionPipeline:
    global _pipeline
    if _pipeline is None:
        logger.info("carregando pipeline de deteccao (%s)...", config.NER_PADRAO)
        _pipeline = DetectionPipeline()
        logger.info("pipeline pronto")
    return _pipeline


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    # Carrega o modelo na subida, não na primeira requisição: o usuário não
    # deve pagar 30 s de carregamento achando que é o documento dele.
    pipeline().analyze("Aquecimento: CPF 529.982.247-25 de João da Silva.")
    # Sobrou documento em claro de uma execução anterior? Vai embora agora.
    sessoes.limpar_orfaos()
    sessoes.expirar()
    yield


app = FastAPI(
    title="Anonimizador — revisão",
    docs_url=None,
    redoc_url=None,
    lifespan=ciclo_de_vida,
)


def pegar_sessao(doc_id: str) -> Sessao:
    sessoes.expirar()
    s = sessoes.obter(doc_id)
    if s is None:
        raise HTTPException(404, "sessão inexistente ou expirada")
    return s


# --------------------------------------------------------------------------
# Documento
# --------------------------------------------------------------------------
@app.post("/api/doc")
async def criar_doc(arquivo: UploadFile = File(...)) -> dict:
    dados = await arquivo.read()
    if not dados:
        raise HTTPException(400, "arquivo vazio")
    if len(dados) > MAX_BYTES:
        raise HTTPException(413, f"arquivo acima de {MAX_BYTES // (1024 * 1024)} MB")
    if not dados.startswith(b"%PDF"):
        raise HTTPException(415, "só PDF nesta fase")

    sessao = sessoes.criar(arquivo.filename or "documento.pdf", dados)
    sessao.perfil = perfil_padrao()

    if not sessao.tm.text.strip():
        # PDF sem texto extraível é quase sempre digitalização. A Fase 0 não
        # faz OCR, e uma tela vazia sem explicação faria o usuário concluir
        # que o documento está limpo.
        sessoes.remover(sessao.doc_id)
        raise HTTPException(
            422,
            "nenhum texto extraível: provavelmente um PDF escaneado. "
            "OCR está fora do escopo desta fase.",
        )

    detectados = pipeline().analyze(sessao.tm.text)
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
    return sessao.preverificar()


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
        lambda texto, limiar: pipeline().analyze(texto, score_threshold=limiar)
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
    return {"ok": True, "ner": config.NER_PADRAO, "entidades": len(config.ENTIDADES_ATIVAS)}


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
