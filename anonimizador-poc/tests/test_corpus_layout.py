"""Blocos de layout do corpus: tabela, duas colunas e multiplas paginas.

O que estes testes protegem e a propriedade da qual todas as metricas
dependem: **o gabarito tem de apontar para o texto certo**. Se `montar_texto`
e `renderizar` discordarem sobre a ordem ou sobre os offsets, o eval passa a
medir o gerador em vez do detector, e faz isso silenciosamente.
"""

import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from generate_corpus import (  # noqa: E402
    MARGEM_X,
    Documento,
    montar_texto,
    quebrar_linhas,
    renderizar,
)

X3 = [MARGEM_X, MARGEM_X + 190.0, MARGEM_X + 330.0]
X2 = [MARGEM_X, MARGEM_X + 268.0]


def _offsets_batem(texto: str, gabarito: list[dict]) -> bool:
    return all(texto[g["start"]:g["end"]] == g["value"] for g in gabarito)


def test_tabela_gera_offsets_exatos():
    doc = Documento("t", "teste")
    doc.add("RELACAO NOMINAL")
    doc.add_tabela(
        X3,
        [
            ["Nome", "CPF", "Nascimento"],
            [[("Maria Souza", "PERSON")], [("529.982.247-25", "CPF")], "01/02/1990"],
        ],
    )
    texto, gabarito = montar_texto(doc)
    assert _offsets_batem(texto, gabarito)
    assert {g["label"] for g in gabarito} == {"PERSON", "CPF"}


def test_celulas_da_mesma_linha_ficam_na_mesma_linha_do_texto():
    doc = Documento("t", "teste")
    doc.add_tabela(X3, [["a", "b", "c"]])
    texto, _ = montar_texto(doc)
    assert texto.splitlines()[0].split() == ["a", "b", "c"]


def test_colunas_saem_em_ordem_logica_de_leitura():
    """No texto-fonte a coluna da esquerda vem inteira antes da direita.

    E o oposto da ordem em que o PyMuPDF devolve a pagina, e e proposital:
    `align.py` reprojeta o gabarito, e o detector passa a ser medido sob a
    mesma degradacao de contexto que um PDF de duas colunas causa de verdade.
    """
    doc = Documento("t", "teste")
    doc.add_colunas(X2, [["esq1", "esq2"], ["dir1", "dir2"]])
    texto, _ = montar_texto(doc)
    assert texto.splitlines() == ["esq1", "esq2", "dir1", "dir2"]


def test_colunas_gera_offsets_exatos():
    doc = Documento("t", "teste")
    doc.add_colunas(
        X2,
        [
            [[("Ana Lima", "PERSON")], ["CPF ", ("529.982.247-25", "CPF")]],
            [[("Bruno Reis", "PERSON")], ["CPF ", ("111.444.777-35", "CPF")]],
        ],
    )
    texto, gabarito = montar_texto(doc)
    assert _offsets_batem(texto, gabarito)
    assert len(gabarito) == 4


def test_segmento_solto_dentro_de_celula_e_normalizado():
    """Uma celula pode misturar rotulado e cru: ["CPF ", (valor, "CPF")]."""
    doc = Documento("t", "teste")
    doc.add_tabela(X2, [[["CPF ", ("529.982.247-25", "CPF")], "obs"]])
    texto, gabarito = montar_texto(doc)
    assert _offsets_batem(texto, gabarito)
    assert texto.startswith("CPF 529.982.247-25")


def test_refluxo_nunca_parte_um_valor(tmp_path: Path):
    """A disciplina central do corpus, agora tambem dentro de colunas."""
    valor = "529.982.247-25"
    doc = Documento("t", "teste")
    doc.add_colunas(
        X2,
        [
            [["preenchimento " * 6, ("Ana Lima", "PERSON"), " CPF ", (valor, "CPF")]],
            [["outro " * 8, (valor, "CPF")]],
        ],
    )
    texto, gabarito = montar_texto(quebrar_linhas(doc))
    assert _offsets_batem(texto, gabarito)
    for g in gabarito:
        assert "\n" not in g["value"]


def test_renderiza_multiplas_paginas_e_o_texto_volta(tmp_path: Path):
    doc = Documento("t", "teste")
    for i in range(140):
        doc.add(f"linha de preenchimento numero {i}")
    doc.add_tabela(X3, [[("Carla Nunes", "PERSON")], ["CPF", "obs", "fim"]])
    caminho = tmp_path / "multi.pdf"
    renderizar(quebrar_linhas(doc), caminho)

    pdf = fitz.open(str(caminho))
    try:
        assert pdf.page_count >= 3
        extraido = "".join(p.get_text() for p in pdf)
    finally:
        pdf.close()
    assert "Carla Nunes" in extraido
    assert "linha de preenchimento numero 139" in extraido


def test_propriedade_linhas_expoe_so_o_corpo():
    doc = Documento("t", "teste")
    doc.add("corpo")
    doc.add_tabela(X2, [["a", "b"]])
    assert [seg for linha in doc.linhas for seg, _ in linha] == ["corpo"]
