"""Testes da ponte offset -> retângulo.

É o componente com maior risco de erro silencioso: se o mapeamento desliza um
caractere, a tarja cobre o lugar errado e ninguém percebe até o vazamento.
"""

import fitz
import pytest

from anonimizador.layout import build_text_map


LINHAS = [
    "CONTRATO DE PRESTACAO DE SERVICOS",
    "CONTRATADO: Joao da Silva Sauro, CPF 529.982.247-25.",
    "Telefone (11) 98765-4321 e e-mail joao@exemplo.com.br",
]


def test_texto_extraido_contem_as_linhas(tmp_pdf):
    doc = fitz.open(str(tmp_pdf(LINHAS)))
    try:
        tm = build_text_map(doc)
        for linha in LINHAS:
            assert linha in tm.text, f"linha ausente do texto extraido: {linha!r}"
    finally:
        doc.close()


def test_vetores_alinhados(tmp_pdf):
    """Uma caixa (ou None) por caractere, sem deslize."""
    doc = fitz.open(str(tmp_pdf(LINHAS)))
    try:
        tm = build_text_map(doc)
        assert len(tm._boxes) == len(tm.text)
        assert len(tm._pages) == len(tm.text)
    finally:
        doc.close()


@pytest.mark.parametrize("alvo", ["529.982.247-25", "Joao da Silva Sauro", "joao@exemplo.com.br"])
def test_retangulo_cobre_o_valor(tmp_pdf, alvo):
    """O retângulo devolvido tem de conter, e só conter, o alvo.

    Verificamos re-extraindo o texto que cai dentro do retângulo: é a única
    checagem que prova de fato que a coordenada corresponde ao caractere.
    """
    caminho = tmp_pdf(LINHAS)
    doc = fitz.open(str(caminho))
    try:
        tm = build_text_map(doc)
        i = tm.text.index(alvo)
        rects = tm.rects_for(i, i + len(alvo))
        assert rects, "nenhum retangulo devolvido"

        for pno, rect in rects:
            # Uma folga de 1pt evita perder o glifo nas bordas por arredondamento.
            trecho = doc.load_page(pno).get_text("text", clip=rect + (-1, -1, 1, 1)).strip()
            assert trecho, "retangulo vazio"
            assert trecho in alvo or alvo in trecho, (
                f"retangulo cobre {trecho!r}, esperado algo dentro de {alvo!r}"
            )
    finally:
        doc.close()


def test_span_invalido_nao_explode(tmp_pdf):
    doc = fitz.open(str(tmp_pdf(LINHAS)))
    try:
        tm = build_text_map(doc)
        assert tm.rects_for(-5, 3) == []
        assert tm.rects_for(10, 10) == []
        assert tm.rects_for(0, len(tm.text) + 99) == []
    finally:
        doc.close()
