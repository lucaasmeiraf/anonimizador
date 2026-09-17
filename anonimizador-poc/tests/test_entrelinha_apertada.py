"""D-01: a tarja não pode alcançar a linha de cima nem a de baixo.

O defeito, medido em 2026-09-16 num documento realista: quando a entrelinha é
mais apertada que a caixa do caractere, as fileiras se sobrepõem, e
``apply_redactions`` — que remove todo caractere cuja caixa **encosta** no
retângulo — leva junto o texto das linhas vizinhas, no mesmo intervalo
horizontal.

O que torna isto perigoso não é o tamanho do estrago, é a combinação: spans
corretos, retângulos corretos, valores removidos e ``verify`` aprovando. O
gate não tem como perceber — ele confere o que **saiu**, e aqui saiu demais.
Sai `ORGANIZATION` junto, que nasce em `manter` porque a LAI exige que o órgão
do ato continue legível.

Por que estes testes montam o PDF à mão em vez de usarem a fixture
``tmp_pdf``: ela escreve linhas a 13pt de distância com corpo 9, cuja caixa
mede 12,37pt — **nunca sobrepõem**. O corpus do eval tem a mesma propriedade,
em 50 de 50 documentos. A suíte inteira era cega para este caso, e é por isso
que ele chegou até aqui.
"""

import fitz
import pytest

from anonimizador.layout import build_text_map
from anonimizador.pdf_redactor import redact_document
from anonimizador.spans import Span
from anonimizador.verifier import verify

CORPO = 9

# Caixa do caractere a 9pt mede 12,37pt, então a invasão é 12,37 - entrelinha.
#
#   10pt -> invade 2,37pt   quebra hoje
#   11pt -> invade 1,37pt   quebra hoje (o documento real invadia 1,82pt)
#   12pt -> invade 0,37pt   NÃO quebra: pouco para alcançar o vizinho
#   14pt -> folga 1,63pt    caso confortável, o do corpus do eval
#
# O de 12pt fica na lista de propósito, apesar de passar hoje: é a fronteira,
# e se a correção mexer nela alguém precisa reparar. O de 14pt é a direção
# oposta — falha se a correção quebrar o que já estava certo.
ENTRELINHAS = [10, 11, 12, 14]

LINHAS = [
    "Orgao expedidor: Instituto Exemplo de Pesquisa Aplicada",
    "Servidora responsavel: Mariana Aparecida Souza, matricula 4471",
    "Endereco funcional: Avenida das Palmeiras, 1840, Sala 702",
]
VALOR = "Mariana Aparecida Souza"

# Palavras que precisam sobreviver: estão nas linhas de cima e de baixo, no
# mesmo intervalo horizontal do valor.
VIZINHAS = ["Instituto", "Exemplo", "Palmeiras", "Sala"]


def _pdf(tmp_path, entrelinha, nome="apertado.pdf"):
    pdf = fitz.open()
    page = pdf.new_page()
    y = 80
    for linha in LINHAS:
        page.insert_text((56, y), linha, fontname="helv", fontsize=CORPO)
        y += entrelinha
    caminho = tmp_path / nome
    pdf.save(str(caminho), garbage=4, deflate=True)
    pdf.close()
    return caminho


def _invasao(caminho):
    """Quanto a caixa de uma fileira invade a da seguinte, em pt."""
    doc = fitz.open(str(caminho))
    try:
        caixas = [
            l["bbox"]
            for b in doc.load_page(0).get_text("dict")["blocks"]
            for l in b.get("lines", [])
        ]
    finally:
        doc.close()
    caixas.sort(key=lambda bb: bb[1])
    return max((a[3] - b[1] for a, b in zip(caixas, caixas[1:])), default=0.0)


def _redigir(caminho, saida):
    doc = fitz.open(str(caminho))
    try:
        tm = build_text_map(doc)
        i = tm.text.find(VALOR)
        assert i != -1, "o valor não foi encontrado no texto extraído"
        span = Span(start=i, end=i + len(VALOR), entity="PERSON", score=1.0)
        res = redact_document(doc, tm, [span], saida)
    finally:
        doc.close()
    saido = fitz.open(str(saida))
    try:
        texto = saido.load_page(0).get_text(sort=True)
    finally:
        saido.close()
    return res, texto


def test_o_caso_existe(tmp_path):
    """A guarda: se o PDF de teste não sobrepõe fileiras, nada abaixo prova nada.

    É o mesmo erro que deixou o defeito passar — um documento que não exercita
    o caso faz o teste passar por ausência, não por correção.
    """
    assert _invasao(_pdf(tmp_path, 10)) > 2.0
    assert _invasao(_pdf(tmp_path, 11)) > 1.0
    assert _invasao(_pdf(tmp_path, 12)) > 0.0
    # Negativo é folga entre as fileiras, não invasão.
    assert _invasao(_pdf(tmp_path, 14)) < 0.0, "14pt devia ser o caso folgado"


@pytest.mark.parametrize("entrelinha", ENTRELINHAS)
def test_a_tarja_nao_come_as_linhas_vizinhas(tmp_path, entrelinha):
    """O valor sai; as palavras de cima e de baixo ficam."""
    entrada = _pdf(tmp_path, entrelinha)
    _, texto = _redigir(entrada, tmp_path / f"out-{entrelinha}.pdf")

    assert VALOR not in texto, "o valor tinha de sair"
    comidas = [p for p in VIZINHAS if p not in texto]
    assert not comidas, (
        f"entrelinha {entrelinha}pt (invasao {_invasao(entrada):.2f}pt): "
        f"a tarja comeu {comidas} das linhas vizinhas"
    )


@pytest.mark.parametrize("entrelinha", ENTRELINHAS)
def test_o_gate_continua_aprovando(tmp_path, entrelinha):
    """A correção não pode custar cobertura: o valor sai dos dez vetores.

    É a direção que importa mais. Encolher retângulo demais deixaria PII
    descoberta — pior que o defeito que a correção conserta.
    """
    entrada = _pdf(tmp_path, entrelinha)
    res, _ = _redigir(entrada, tmp_path / f"gate-{entrelinha}.pdf")
    rel = verify(tmp_path / f"gate-{entrelinha}.pdf", res.valores)
    assert rel.ok, rel.leaks


def test_entrelinha_absurda_prefere_cobrir_o_valor(tmp_path):
    """Quando não sobra faixa livre, a tarja volta a encostar — de propósito.

    Com 6pt de entrelinha e caixa de 12,37pt, as fileiras invadem 6,37pt: não
    existe recorte que evite o vizinho e ainda cubra o valor. A trava do
    ``FRACAO_MINIMA`` decide o empate, e decide pelo lado certo — retângulo
    pequeno demais deixaria PII no documento, que é pior do que comer a linha
    de cima.

    O que este teste exige é só isso: **o valor sai**. Que o vizinho sofra
    neste caso extremo é a escolha, não o defeito.
    """
    entrada = _pdf(tmp_path, 6, nome="absurdo.pdf")
    assert _invasao(entrada) > 6.0, "o caso extremo não foi montado"

    res, texto = _redigir(entrada, tmp_path / "absurdo-out.pdf")
    assert VALOR not in texto
    assert verify(tmp_path / "absurdo-out.pdf", res.valores).ok
