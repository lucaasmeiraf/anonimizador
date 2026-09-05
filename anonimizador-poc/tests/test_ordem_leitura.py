"""A1 — a ordem de leitura sobrevive à substituição por token?

Primeiro item da Fase A, antes do operador `pseudonimo` de propósito: é o
teste que decide se a abordagem serve.

O motivo é o caso de uso. Um documento pseudonimizado existe para ser **lido
por outro leitor** — uma pessoa acompanhando quem fez o quê, ou um modelo de
linguagem analisando o processo. Os dois consomem o *texto extraído*, não a
imagem da página. Um PDF que parece perfeito na tela mas cuja extração
devolve os tokens amontoados no fim da página é inútil para os dois.

MEDIÇÃO DE 2026-09-05 — o veredito é "serve, com uma condição".

A geometria sai perfeita: o retângulo do token coincide com o do valor
original na mesma coluna e na mesma linha (diferença de 0,13pt em y, que é o
ajuste de baseline). Nada de posição se perde.

O que sai errado é só a **ordem do content stream**: os tokens são anexados
ao fim do fluxo da página. A consequência é que o resultado depende de como
quem lê extrai o texto:

    PyMuPDF     get_text()                  ordem do stream    ERRADO
    PyMuPDF     get_text(sort=True)         geometria          certo
    pdfplumber  extract_text()              geometria          certo
    pdfplumber  extract_text(text_flow)     ordem do stream    ERRADO

Os dois modos geométricos leem certo; os dois modos de stream leem errado. E
os padrões das bibliotecas divergem — o do PyMuPDF erra, o do pdfplumber
acerta. Portanto **não dá para garantir a ordem só entregando o PDF**: ou o
consumidor ordena por geometria, ou o texto precisa ser entregue por um
caminho que não dependa do stream.

Este arquivo trava as duas metades: o que já é garantido (geometria e
extração geométrica) e o defeito conhecido, para que ele não seja
redescoberto por acidente nem "consertado" sem medição.
"""

from __future__ import annotations

import fitz
import pytest

# Frases construídas para que a posição do token seja verificável sem
# ambiguidade: cada valor tem uma palavra âncora antes e outra depois.
LINHAS = [
    "ATA DE REUNIAO — SECRETARIA DE ADMINISTRACAO",
    "",
    "O servidor Mariana Aparecida Souza compareceu a sessao de abertura.",
    "Coube a Mariana Aparecida Souza relatar o andamento do processo.",
    "O interessado Joaquim Ferreira Lima apresentou defesa escrita.",
    "Ao final, Joaquim Ferreira Lima retirou-se antes da votacao.",
]

# valor -> token. Curtos de propósito: a aresta de largura é o item A4, e aqui
# ela seria ruído.
TOKENS = {
    "Mariana Aparecida Souza": "[P-7F3A]",
    "Joaquim Ferreira Lima": "[P-2C81]",
}

# (âncora anterior, token esperado, âncora posterior)
POSICOES = [
    ("servidor", "[P-7F3A]", "compareceu"),
    ("Coube a", "[P-7F3A]", "relatar"),
    ("interessado", "[P-2C81]", "apresentou"),
    ("Ao final,", "[P-2C81]", "retirou-se"),
]


def _pseudonimizar(caminho_entrada, caminho_saida) -> None:
    """Substitui valores por tokens usando o mecanismo nativo do PyMuPDF.

    Deliberadamente **não** usa `pdf_redactor.redact_document`: o operador
    `pseudonimo` ainda não existe (A2), e o objetivo é medir o mecanismo de
    inserção de texto isolado, sem carregar junto o comportamento do redator.
    """
    doc = fitz.open(str(caminho_entrada))
    try:
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            for valor, token in TOKENS.items():
                for rect in page.search_for(valor):
                    page.add_redact_annot(
                        rect, text=token, fontname="helv", fontsize=9
                    )
            page.apply_redactions()
            page.clean_contents()
        doc.save(
            str(caminho_saida),
            garbage=4,
            deflate=True,
            clean=True,
            incremental=False,
        )
    finally:
        doc.close()


@pytest.fixture
def pdf_pseudonimizado(tmp_pdf, tmp_path):
    entrada = tmp_pdf(LINHAS, nome="ata.pdf")
    saida = tmp_path / "ata-pseudonimizada.pdf"
    _pseudonimizar(entrada, saida)
    return entrada, saida


def _texto(caminho, **kwargs) -> str:
    doc = fitz.open(str(caminho))
    try:
        return doc.load_page(0).get_text(**kwargs)
    finally:
        doc.close()


def _ordem_preservada(texto: str, antes: str, token: str, depois: str) -> bool:
    """O token está NO TRECHO entre as duas âncoras?

    Procurar a primeira ocorrência do token no documento inteiro daria falso
    negativo no segundo caso de cada pessoa — e falso positivo se os tokens
    fossem todos parar no fim da página.
    """
    pos_antes = texto.find(antes)
    if pos_antes == -1:
        return False
    pos_depois = texto.find(depois, pos_antes)
    if pos_depois == -1:
        return False
    return token in texto[pos_antes:pos_depois]


# --------------------------------------------------------------------------
# O que já está garantido
# --------------------------------------------------------------------------


def test_valores_originais_sumiram(pdf_pseudonimizado):
    """Pré-requisito: se o valor não saiu, nada mais importa."""
    _, saida = pdf_pseudonimizado
    texto = _texto(saida)
    for valor in TOKENS:
        assert valor not in texto


def test_todo_token_esta_presente(pdf_pseudonimizado):
    """Aresta 1 da sondagem: token descartado em silêncio.

    Cada valor aparece duas vezes no documento, então cada token tem de
    aparecer duas vezes.
    """
    _, saida = pdf_pseudonimizado
    texto = _texto(saida)
    for token in TOKENS.values():
        assert texto.count(token) == 2, (
            f"{token}: esperadas 2 ocorrencias, achadas {texto.count(token)}"
        )


def test_token_ocupa_a_geometria_do_valor(pdf_pseudonimizado):
    """A garantia de base: o token está onde o valor estava.

    É desta medição que sai o veredito do A1. Se a geometria coincide, a
    informação de posição não se perdeu — o problema é só de ordenação, e tem
    conserto do lado de quem lê. Se não coincidisse, a abordagem estaria
    morta e seria preciso outra forma de inserir texto.
    """
    entrada, saida = pdf_pseudonimizado

    orig = fitz.open(str(entrada))
    try:
        pagina = orig.load_page(0)
        origem = sorted(
            (round(r.y0), round(r.x0, 2))
            for valor in TOKENS
            for r in pagina.search_for(valor)
        )
    finally:
        orig.close()

    doc = fitz.open(str(saida))
    try:
        destino = sorted(
            (round(w[1]), round(w[0], 2))
            for w in doc.load_page(0).get_text("words")
            if w[4].startswith("[P-")
        )
    finally:
        doc.close()

    assert len(destino) == len(origem) == 4
    assert destino == origem, (
        f"token fora da posicao do valor: origem={origem} destino={destino}"
    )


@pytest.mark.parametrize("antes,token,depois", POSICOES)
def test_extracao_geometrica_le_na_ordem(pdf_pseudonimizado, antes, token, depois):
    """PyMuPDF ordenando por geometria: o token cai entre as âncoras certas."""
    _, saida = pdf_pseudonimizado
    texto = _texto(saida, sort=True)
    assert _ordem_preservada(texto, antes, token, depois), (
        f"ordem quebrada entre {antes!r} e {depois!r}:\n{texto}"
    )


@pytest.mark.parametrize("antes,token,depois", POSICOES)
def test_extrator_de_terceiro_le_na_ordem(pdf_pseudonimizado, antes, token, depois):
    """O destino do arquivo é uma ferramenta que não é esta.

    pdfplumber é o que a maior parte das esteiras de ingestão para LLM usa, e
    no modo padrão ele ordena por geometria.
    """
    import pdfplumber

    _, saida = pdf_pseudonimizado
    with pdfplumber.open(str(saida)) as pdf:
        texto = pdf.pages[0].extract_text()
    assert _ordem_preservada(texto, antes, token, depois), (
        f"ordem quebrada entre {antes!r} e {depois!r}:\n{texto}"
    )


# --------------------------------------------------------------------------
# O defeito conhecido — travado para não ser redescoberto por acidente
# --------------------------------------------------------------------------


def test_ordem_do_content_stream_esta_quebrada(pdf_pseudonimizado):
    """Documenta o defeito medido, em vez de fingir que ele não existe.

    Os tokens são anexados ao fim do fluxo de texto da página. Quem extrai
    seguindo o content stream — `get_text()` sem `sort`, pdfplumber com
    `use_text_flow=True` — recebe o documento sem os tokens no lugar e com
    todos eles empilhados no fim.

    Este teste **passa enquanto o defeito existir**. Se alguém consertar a
    ordem do stream, ele falha, e esse é o sinal correto: o conserto precisa
    vir junto com a atualização desta docstring e do veredito no goal.
    """
    _, saida = pdf_pseudonimizado
    texto = _texto(saida)

    quebradas = [
        (antes, token, depois)
        for antes, token, depois in POSICOES
        if not _ordem_preservada(texto, antes, token, depois)
    ]
    assert len(quebradas) == 4, (
        "a ordem do content stream mudou de comportamento; "
        f"quebradas={len(quebradas)} de 4. Reveja o veredito do A1."
    )

    # E a forma exata do defeito: os tokens vêm todos depois do corpo.
    fim_do_corpo = texto.find("votacao.")
    assert fim_do_corpo != -1
    for token in TOKENS.values():
        assert texto.find(token) > fim_do_corpo
