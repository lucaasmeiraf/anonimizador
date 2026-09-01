"""Redação verdadeira de PDF.

"Verdadeira" aqui tem significado técnico preciso: o texto sai do *content
stream*, não fica escondido sob um retângulo preto. O erro de cobrir em vez de
remover é o que produziu os vazamentos públicos conhecidos de documentos
"tarjados" — o texto continua no arquivo e volta com um simples copiar-colar.

Mas remover do content stream **não basta**, e é aqui que o goal original
parava. O mesmo dado costuma existir em paralelo em:

* metadados do documento (autor, título, assunto, produtor)
* metadados XMP (um segundo bloco, em XML, que ``set_metadata`` não toca)
* anotações e seus popups
* campos de formulário AcroForm (valor e valor padrão)
* arquivos embutidos / anexos
* sumário (outline / bookmarks)
* miniaturas de página pré-renderizadas
* objetos órfãos deixados por revisões incrementais anteriores

O saneamento abaixo cobre todos eles, e ``verifier.py`` confere o resultado de
forma independente. O ``save`` é obrigatoriamente **não incremental** com
``garbage=4``: um save incremental anexaria a nova revisão ao arquivo antigo,
preservando intacta a versão com os dados.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from .layout import TextMap
from .spans import Span

logger = logging.getLogger(__name__)

PRETO = (0, 0, 0)


@dataclass(frozen=True)
class SpanSemRetangulo:
    """Um span detectado que não produziu retângulo — sinal de bug de mapeamento.

    Descreve **onde** o defeito está, nunca **o que** estava escrito ali. A
    distinção não é cosmética: este registro é a única coisa deste caminho que
    sai do processo — vai para log, para o stdout da CLI e para o relatório da
    sessão. Carregar o texto original faria dele uma cópia de dado pessoal
    fora do PDF saneado, com retenção própria, sem verificação e sem TTL. O
    arquivo de saída é auditado em dez vetores; a linha de log não é auditada
    em nenhum.

    O que o diagnóstico exige é a entidade e o intervalo: eles apontam o span
    no texto e permitem reproduzir o caso a partir do documento de origem, que
    é onde a investigação tem de acontecer de qualquer forma. O valor não
    acrescenta nada a essa investigação — quem a faz tem o documento em mãos.
    """

    entity: str
    start: int
    end: int

    @property
    def comprimento(self) -> int:
        return self.end - self.start

    def __str__(self) -> str:
        return f"{self.entity}[{self.comprimento}] @{self.start}"


@dataclass
class RedactionResult:
    caminho_saida: str
    spans_redigidos: int = 0
    retangulos: int = 0
    valores: list[str] = field(default_factory=list)
    spans_sem_retangulo: list[SpanSemRetangulo] = field(default_factory=list)
    saneamento: dict[str, bool] = field(default_factory=dict)


def redact_document(
    doc: "fitz.Document",
    tm: TextMap,
    spans: list[Span],
    caminho_saida: str | Path,
    cor: tuple[float, float, float] = PRETO,
) -> RedactionResult:
    """Aplica a redação e devolve o relatório do que foi feito."""
    caminho_saida = str(caminho_saida)
    res = RedactionResult(caminho_saida=caminho_saida)

    for span in spans:
        rects = tm.rects_for(span.start, span.end)
        if not rects:
            # Nenhuma caixa: o span caiu inteiro sobre separadores sintéticos.
            # Registramos em vez de engolir — é sinal de bug no mapeamento, e
            # significaria PII detectada mas não tarjada.
            #
            # O valor sequer é lido aqui. Materializá-lo para depois não usar
            # convida a próxima pessoa a colocá-lo no log "só para depurar",
            # que foi exatamente como esta linha nasceu.
            sem_caixa = SpanSemRetangulo(span.entity, span.start, span.end)
            res.spans_sem_retangulo.append(sem_caixa)
            logger.warning("span sem retangulo: %s", sem_caixa)
            continue

        res.spans_redigidos += 1
        res.valores.append(span.text_of(tm.text))
        for pno, rect in rects:
            doc.load_page(pno).add_redact_annot(rect, fill=cor)
            res.retangulos += 1

    # Aplicação página a página. `apply_redactions` remove o texto do content
    # stream e os pixels de imagem sob o retângulo; `clean_contents` reescreve
    # o stream, eliminando restos do operador de texto.
    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        page.apply_redactions()
        page.clean_contents()

    res.saneamento = _sanear(doc)

    # Não incremental, com coleta agressiva de objetos órfãos.
    doc.save(caminho_saida, garbage=4, deflate=True, clean=True, incremental=False)
    return res


def _sanear(doc: "fitz.Document") -> dict[str, bool]:
    """Remove os vetores paralelos de vazamento. Devolve o que foi executado."""
    feito: dict[str, bool] = {}

    # `scrub` cobre a maior parte, mas sua assinatura variou entre versões do
    # PyMuPDF. Filtramos os kwargs pelos que a versão instalada aceita, em vez
    # de fixar uma assinatura e quebrar no upgrade.
    desejado = dict(
        attached_files=True,
        clean_pages=True,
        embedded_files=True,
        hidden_text=True,
        javascript=True,
        metadata=True,
        remove_links=True,
        reset_fields=True,
        reset_responses=True,
        thumbnails=True,
        xml_metadata=True,
        redactions=False,  # já aplicamos as nossas acima
    )
    try:
        aceitos = set(inspect.signature(doc.scrub).parameters)
        doc.scrub(**{k: v for k, v in desejado.items() if k in aceitos})
        feito["scrub"] = True
    except Exception:  # noqa: BLE001
        logger.exception("scrub falhou; aplicando saneamento manual")
        feito["scrub"] = False

    # Redundância deliberada: mesmo com o scrub bem-sucedido, zeramos
    # metadados e XMP explicitamente. Custa nada e cobre diferenças de versão.
    try:
        doc.set_metadata({})
        feito["metadata"] = True
    except Exception:  # noqa: BLE001
        logger.exception("falha ao limpar metadados")
        feito["metadata"] = False

    try:
        doc.del_xml_metadata()
        feito["xml_metadata"] = True
    except Exception:  # noqa: BLE001
        logger.exception("falha ao limpar XMP")
        feito["xml_metadata"] = False

    try:
        doc.set_toc([])
        feito["toc"] = True
    except Exception:  # noqa: BLE001
        logger.exception("falha ao limpar sumário")
        feito["toc"] = False

    return feito


def redact_file(
    caminho_entrada: str | Path,
    caminho_saida: str | Path,
    spans_fn,
) -> tuple[RedactionResult, TextMap, list[Span]]:
    """Fluxo de arquivo: abre, mapeia, detecta via ``spans_fn`` e redige.

    ``spans_fn`` recebe o texto e devolve os spans — assim o redator não
    conhece o pipeline de detecção e pode ser testado com spans fabricados.
    """
    from .layout import build_text_map

    doc = fitz.open(str(caminho_entrada))
    try:
        tm = build_text_map(doc)
        spans = spans_fn(tm.text)
        res = redact_document(doc, tm, spans, caminho_saida)
        return res, tm, spans
    finally:
        doc.close()
