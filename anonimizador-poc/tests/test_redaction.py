"""Redação verdadeira + verificação, sem depender de modelo de NER.

Os spans são fabricados à mão de propósito: isto testa o redator e o
verificador isoladamente, para que uma falha aqui não seja confundida com uma
falha de detecção.
"""

import fitz
import pytest

from anonimizador.layout import build_text_map
from anonimizador.pdf_redactor import redact_document
from anonimizador.spans import Span
from anonimizador.verifier import verify

SEGREDOS = ["529.982.247-25", "Joao da Silva Sauro", "joao@exemplo.com.br"]
LINHAS = [
    "CONTRATO DE PRESTACAO DE SERVICOS",
    "CONTRATADO: Joao da Silva Sauro, CPF 529.982.247-25.",
    "Contato: joao@exemplo.com.br",
]
METADATA_SUJA = {
    "title": "contrato de Joao da Silva Sauro",
    "author": "Joao da Silva Sauro",
    "subject": "CPF 529.982.247-25",
    "keywords": "joao@exemplo.com.br",
}


def _spans(tm):
    spans = []
    for valor in SEGREDOS:
        i = tm.text.index(valor)
        spans.append(Span(i, i + len(valor), "PERSON", 1.0))
    return spans


def test_redacao_remove_dos_dez_vetores(tmp_pdf, tmp_path):
    entrada = tmp_pdf(LINHAS, metadata=METADATA_SUJA)
    saida = tmp_path / "redigido.pdf"

    doc = fitz.open(str(entrada))
    try:
        tm = build_text_map(doc)
        res = redact_document(doc, tm, _spans(tm), saida)
    finally:
        doc.close()

    assert res.spans_redigidos == len(SEGREDOS)
    assert not res.spans_sem_retangulo

    relatorio = verify(saida, SEGREDOS)
    assert relatorio.ok, "vazamento apos redacao: " + "; ".join(str(x) for x in relatorio.leaks)
    assert len(relatorio.vetores_executados) >= 9


def test_verificador_pega_documento_nao_redigido(tmp_pdf):
    """Controle negativo: sem essa checagem, um verificador quebrado passaria
    despercebido como 'nenhum vazamento'."""
    entrada = tmp_pdf(LINHAS, metadata=METADATA_SUJA)
    relatorio = verify(entrada, SEGREDOS)
    assert not relatorio.ok
    vetores = {leak.vetor for leak in relatorio.leaks}
    assert "texto-pymupdf" in vetores
    assert "metadados" in vetores


def test_texto_vizinho_sobrevive(tmp_pdf, tmp_path):
    """A tarja não pode comer o texto ao redor."""
    entrada = tmp_pdf(LINHAS, metadata=METADATA_SUJA)
    saida = tmp_path / "redigido.pdf"
    doc = fitz.open(str(entrada))
    try:
        tm = build_text_map(doc)
        redact_document(doc, tm, _spans(tm), saida)
    finally:
        doc.close()

    final = fitz.open(str(saida))
    try:
        texto = "\n".join(final.load_page(i).get_text("text") for i in range(final.page_count))
    finally:
        final.close()
    assert "CONTRATO DE PRESTACAO DE SERVICOS" in texto
    assert "CONTRATADO" in texto
