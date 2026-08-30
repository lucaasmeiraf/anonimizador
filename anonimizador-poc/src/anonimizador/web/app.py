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
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import config
from ..pipeline import DetectionPipeline
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
def apagar_doc(doc_id: str) -> dict:
    if not sessoes.remover(doc_id):
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

    doc = fitz.open(str(sessao.original))
    try:
        # `get_text("words")` devolve (x0, y0, x1, y1, palavra, bloco, linha, n)
        # já na ordem de leitura que o PyMuPDF extrai.
        palavras = doc.load_page(numero).get_text("words")
    finally:
        doc.close()

    return {
        "pagina": numero,
        "palavras": [
            {
                "t": p[4],
                "x0": p[0],
                "y0": p[1],
                "x1": p[2],
                "y1": p[3],
                "linha": (p[5], p[6]),
            }
            for p in palavras
        ],
    }


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
    sessao.aprovar()
    return sessao.to_dict()


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


app.mount("/static", StaticFiles(directory=str(ESTATICOS)), name="static")
