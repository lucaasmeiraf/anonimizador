"""O operador `pseudonimo` dentro do PDF — A4, A5 e A8 do `goal-fase-2.md`.

`pseudonimo.py` já sabia trocar valor por token **em texto**. O que faltava, e
é o que estes testes cobrem, é escrever o token de volta no PDF sem cair em
nenhum dos dois modos de falha que a Fase 0 usou para justificar travar o
operador:

1. **o token não cabe na caixa do valor** e o arquivo sai deformado;
2. **o token é descartado** e o gate aprova, porque a checagem de ausência vê
   o original sumido e conclui "limpo".

O primeiro não é hipótese. Medido em 2026-09-16: ``add_redact_annot(text=...)``
não recusa texto largo demais — **encolhe a fonte em silêncio**. Um token de
48,0pt numa caixa de 43,0pt saiu escrito a 7,0pt no meio de uma linha de 9,0pt,
com o arquivo pronto, legível e errado. O teste do corpo abaixo é o que
impede isso de voltar.
"""

import fitz
import pytest

from anonimizador.layout import build_text_map
from anonimizador.pdf_redactor import (
    PseudonimoImpossivelNoPDF,
    TokenSemGlifo,
    redact_document,
)
from anonimizador.spans import Span
from anonimizador.verifier import verify

CORPO = 9

LINHAS = [
    "ATA DE REUNIAO",
    "O servidor Mariana Aparecida Souza compareceu a sessao.",
    "Coube a Mariana Aparecida Souza relatar o processo.",
    "CEP 01310-100 nesta cidade.",
]

NOME = "Mariana Aparecida Souza"
CEP = "01310-100"


@pytest.fixture
def documento(tmp_pdf):
    """PDF de teste com o texto mapeado, pronto para receber spans."""

    def _abrir(linhas=LINHAS, nome="ata.pdf"):
        caminho = tmp_pdf(linhas, nome=nome)
        doc = fitz.open(str(caminho))
        return doc, build_text_map(doc)

    return _abrir


def _spans_do_nome(tm):
    """As **duas** ocorrências do nome.

    O documento de teste repete o nome de propósito — é o que exercita o
    determinismo do token. A consequência é que qualquer teste de ausência
    precisa redigir as duas: deixar uma para trás faz o `verify` acusar
    vazamento com toda a razão.
    """
    return [_span(tm, NOME, "PERSON"), _span(tm, NOME, "PERSON", ocorrencia=1)]


def _span(tm, valor, entidade, ocorrencia=0):
    pos = -1
    for _ in range(ocorrencia + 1):
        pos = tm.text.find(valor, pos + 1)
        assert pos != -1, f"valor ausente no texto extraido: {valor!r}"
    return Span(start=pos, end=pos + len(valor), entity=entidade, score=1.0)


def _texto_da_saida(caminho) -> str:
    doc = fitz.open(str(caminho))
    try:
        return "\n".join(
            doc.load_page(i).get_text(sort=True) for i in range(doc.page_count)
        )
    finally:
        doc.close()


def _corpos_do_token(caminho, token) -> list[float]:
    """Corpo da fonte com que cada ocorrência do token foi escrita."""
    doc = fitz.open(str(caminho))
    try:
        corpos = []
        for i in range(doc.page_count):
            for bloco in doc.load_page(i).get_text("dict")["blocks"]:
                for linha in bloco.get("lines", []):
                    for sp in linha["spans"]:
                        if token in sp["text"]:
                            corpos.append(sp["size"])
        return corpos
    finally:
        doc.close()


# --------------------------------------------------------------------------
# O caminho feliz
# --------------------------------------------------------------------------
def test_token_ocupa_o_lugar_do_valor(documento, tmp_path):
    doc, tm = documento()
    spans = [_span(tm, NOME, "PERSON"), _span(tm, NOME, "PERSON", ocorrencia=1)]
    saida = tmp_path / "ata-pseudo.pdf"

    res = redact_document(
        doc, tm, spans, saida, tokens={(s.start, s.end): "[P-7F3A]" for s in spans}
    )
    doc.close()

    texto = _texto_da_saida(saida)
    assert NOME not in texto
    assert texto.count("[P-7F3A]") == 2
    assert res.tokens_escritos == ["[P-7F3A]", "[P-7F3A]"]


def test_gate_confere_ausencia_do_valor_e_presenca_do_token(documento, tmp_path):
    """O A5: onze vetores, e o décimo primeiro é o que impede o falso silêncio."""
    doc, tm = documento()
    spans = _spans_do_nome(tm)
    saida = tmp_path / "ata-pseudo.pdf"
    res = redact_document(
        doc, tm, spans, saida, tokens={(s.start, s.end): "[P-7F3A]" for s in spans}
    )
    doc.close()

    rel = verify(saida, res.valores, tokens=res.tokens_escritos)
    assert rel.ok, rel.leaks
    assert "tokens-presentes" in rel.vetores_executados


def test_gate_reprova_token_que_sumiu_do_pdf(documento, tmp_path):
    """A aresta 1: o valor sai, o token não entra, e a ausência diz "limpo".

    Sem o vetor de presença este relatório seria aprovado — o original de
    fato sumiu. É o falso silêncio da tabela do `CLAUDE.md` §1, com o gate
    carimbando.
    """
    doc, tm = documento()
    spans = _spans_do_nome(tm)
    saida = tmp_path / "ata-tarjada.pdf"
    res = redact_document(doc, tm, spans, saida)  # tarja: nenhum token escrito
    doc.close()

    rel = verify(saida, res.valores, tokens=["[P-7F3A]"])
    assert not rel.ok
    # O valor sumiu de todos os dez vetores; o único achado é o token que
    # nunca foi escrito. Sem o vetor 11 este relatório seria `ok`.
    assert [lk.vetor for lk in rel.leaks] == ["token-ausente"]


# --------------------------------------------------------------------------
# A4 — não cabe, reprova
# --------------------------------------------------------------------------
def test_token_largo_demais_reprova_o_documento(documento, tmp_path):
    """`[CEP-2C81]` mede 48,0pt; `01310-100` ocupa 43,0pt. Não cabe."""
    doc, tm = documento()
    span = _span(tm, CEP, "CEP")
    saida = tmp_path / "nao-devia-existir.pdf"

    with pytest.raises(PseudonimoImpossivelNoPDF) as erro:
        redact_document(doc, tm, [span], saida, tokens={(span.start, span.end): "[CEP-2C81]"})
    doc.close()

    assert not saida.exists(), "documento reprovado não pode deixar arquivo em disco"
    (caso,) = erro.value.casos
    assert caso.entity == "CEP"
    assert caso.largura_token > caso.largura_caixa


def test_reprova_antes_de_escrever_o_token_que_cabia(documento, tmp_path):
    """Um cabe, outro não: nenhum é escrito.

    Medir tudo antes de mutar é o que evita o arquivo meio pronto — e é o que
    faz o erro listar os dois problemas de uma vez, em vez de um por execução.
    """
    doc, tm = documento()
    nome = _span(tm, NOME, "PERSON")
    cep = _span(tm, CEP, "CEP")
    saida = tmp_path / "nao-devia-existir.pdf"

    with pytest.raises(PseudonimoImpossivelNoPDF) as erro:
        redact_document(
            doc,
            tm,
            [nome, cep],
            saida,
            tokens={
                (nome.start, nome.end): "[P-7F3A]",
                (cep.start, cep.end): "[CEP-2C81]",
            },
        )
    doc.close()

    assert not saida.exists()
    assert [c.entity for c in erro.value.casos] == ["CEP"]


def test_a_reprovacao_nao_carrega_o_valor_original(documento, tmp_path):
    """Invariante 4: nem a mensagem de erro exibe PII.

    O token pode aparecer — é sorteado, não deriva do valor. O original, não.
    """
    doc, tm = documento()
    span = _span(tm, CEP, "CEP")

    with pytest.raises(PseudonimoImpossivelNoPDF) as erro:
        redact_document(
            doc, tm, [span], tmp_path / "x.pdf", tokens={(span.start, span.end): "[CEP-2C81]"}
        )
    doc.close()

    mensagem = str(erro.value)
    assert CEP not in mensagem
    assert "[CEP-2C81]" in mensagem


def test_o_corpo_do_token_acompanha_a_linha(documento, tmp_path):
    """A trava contra o encolhimento silencioso do PyMuPDF.

    Se alguém remover a conferência de largura, o PyMuPDF volta a escrever o
    token com a fonte reduzida e **nada mais falha**: o valor sumiu, o token
    está lá, o gate aprova. Só o corpo denuncia.
    """
    doc, tm = documento()
    spans = _spans_do_nome(tm)
    saida = tmp_path / "ata-pseudo.pdf"
    redact_document(
        doc, tm, spans, saida, tokens={(s.start, s.end): "[P-7F3A]" for s in spans}
    )
    doc.close()

    corpos = _corpos_do_token(saida, "[P-7F3A]")
    assert corpos, "token não foi encontrado na saída"
    for corpo in corpos:
        assert corpo == pytest.approx(CORPO, abs=0.5), (
            f"token escrito a {corpo:.2f}pt numa linha de {CORPO}pt — "
            "é o encolhimento silencioso medido em 2026-09-16"
        )


# --------------------------------------------------------------------------
# A8 — glifo
# --------------------------------------------------------------------------
def test_sigla_fora_da_codificacao_falha_alto(documento, tmp_path):
    """Sigla que a fonte base-14 não sabe desenhar morre aqui, não no leitor.

    Medido ao escrever este teste, e vale registrar porque contraria a
    suposição com que ele nasceu: **acento não é o problema**. WinAnsi cobre
    o latim acentuado inteiro, então `[ÓRG-1A2B]` desenha sem susto. O que
    cai aqui é o que está fora da codificação — grego, cirílico, seta, emoji.
    """
    doc, tm = documento()
    span = _span(tm, NOME, "PERSON")

    with pytest.raises(TokenSemGlifo):
        redact_document(
            doc, tm, [span], tmp_path / "x.pdf", tokens={(span.start, span.end): "[ΩRG-1A2B]"}
        )
    doc.close()


def test_sigla_acentuada_e_aceita(documento, tmp_path):
    """O outro lado da medição acima: acento passa, e deve passar."""
    doc, tm = documento()
    spans = _spans_do_nome(tm)
    saida = tmp_path / "acentuada.pdf"

    res = redact_document(
        doc, tm, spans, saida, tokens={(s.start, s.end): "[ÓRG-1A2B]" for s in spans}
    )
    doc.close()
    assert verify(saida, res.valores, tokens=res.tokens_escritos).ok


# --------------------------------------------------------------------------
# O que não pode regredir
# --------------------------------------------------------------------------
def test_tarja_sem_tokens_continua_igual(documento, tmp_path):
    """Sem `tokens`, o caminho da tarja é o de sempre: nada escrito, valor fora."""
    doc, tm = documento()
    spans = _spans_do_nome(tm)
    saida = tmp_path / "ata-tarjada.pdf"

    res = redact_document(doc, tm, spans, saida)
    doc.close()

    assert res.tokens_escritos == []
    assert NOME not in _texto_da_saida(saida)
    assert verify(saida, res.valores).ok


def test_valor_partido_em_duas_linhas_recebe_um_token_so(documento, tmp_path):
    """Nome que atravessa a quebra de linha não pode virar dois atores.

    ``rects_for`` devolve uma caixa por linha visual — de propósito, para não
    tarjar o texto inocente entre elas. Escrever o token em cada caixa faria
    quem lê enxergar duas pessoas onde havia uma.
    """
    doc, tm = documento(
        linhas=["O servidor Mariana Aparecida", "Souza compareceu a sessao."],
        nome="quebrada.pdf",
    )
    inicio = tm.text.find("Mariana Aparecida")
    fim = tm.text.find("Souza") + len("Souza")
    span = Span(start=inicio, end=fim, entity="PERSON", score=1.0)
    assert len(tm.rects_for(span.start, span.end)) == 2, "o caso não foi montado"

    saida = tmp_path / "quebrada-pseudo.pdf"
    res = redact_document(doc, tm, [span], saida, tokens={(span.start, span.end): "[P-7F3A]"})
    doc.close()

    assert res.tokens_escritos == ["[P-7F3A]"]
    assert _texto_da_saida(saida).count("[P-7F3A]") == 1


def test_a_ordem_de_leitura_geometrica_continua_valendo(documento, tmp_path):
    """O critério de viabilidade do A1, agora sobre a implementação real.

    O A1 mediu o mecanismo do PyMuPDF (`add_redact_annot(text=...)`) e deu o
    veredito: geometria perfeita, ordem do content stream quebrada. Este
    módulo escreve o token de outro jeito — `insert_text` depois da remoção —,
    então aquele veredito **não se transfere sozinho**.

    O que se exige aqui é o lado que decide a viabilidade: quem extrai por
    geometria lê o token na posição do valor, não no fim da página. A ordem
    do stream continua sendo o defeito conhecido, e é por isso que o
    entregável para LLM é o artefato de texto, não o PDF.
    """
    doc, tm = documento()
    spans = _spans_do_nome(tm)
    saida = tmp_path / "ata-pseudo.pdf"
    redact_document(
        doc, tm, spans, saida, tokens={(s.start, s.end): "[P-7F3A]" for s in spans}
    )
    doc.close()

    lido = _texto_da_saida(saida)  # get_text(sort=True): extração geométrica
    for antes, depois in (("O servidor", "compareceu"), ("Coube a", "relatar")):
        i = lido.find(antes)
        j = lido.find(depois, i)
        assert i != -1 and j != -1, f"âncoras não encontradas: {antes!r}/{depois!r}"
        assert "[P-7F3A]" in lido[i:j], (
            f"token fora de posição entre {antes!r} e {depois!r} — "
            "a geometria deixou de ser preservada"
        )
