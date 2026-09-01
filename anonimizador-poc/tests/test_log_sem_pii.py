"""Nenhum valor de PII sai deste processo por log ou por stdout.

O caminho testado é o de `spans_sem_retangulo`: um span detectado que não
produziu região visível na página. Ele é raro e é justamente por isso que
passou despercebido — só dispara quando o mapeamento offset → retângulo falha,
que é o caso em que alguém *vai* ler o log.

O que estava errado: o registro carregava o texto do trecho, e o texto de um
trecho que o detector apontou é, por definição, dado pessoal. O PDF de saída é
auditado em dez vetores; a linha de log não é auditada em nenhum, não tem TTL
e não é apagada com a sessão.

Estes testes fixam as duas metades da correção: o aviso continua existindo
(engolir o sinal seria pior que o vazamento), e ele não carrega o valor.
"""

import logging

import fitz

from anonimizador.layout import TextMap, build_text_map
from anonimizador.pdf_redactor import SpanSemRetangulo, redact_document
from anonimizador.spans import Span

CPF_VALOR = "529.982.247-25"
NOME = "Joao da Silva Sauro"
TEXTO = f"CONTRATADO: {NOME}, CPF {CPF_VALOR}."


def _mapa_sem_caixas() -> TextMap:
    """`TextMap` com texto real e nenhuma caixa.

    Reproduz de forma determinística a única condição que leva um span ao
    caminho `spans_sem_retangulo`. Num documento real isso acontece quando o
    span cai inteiro sobre os separadores sintéticos que `build_text_map`
    insere entre linhas e blocos — que não têm caixa própria. Provocar a
    condição direta evita amarrar o teste à geometria de um PDF específico,
    que mudaria com a fonte.
    """
    return TextMap(
        text=TEXTO,
        _boxes=[None] * len(TEXTO),
        _pages=[0] * len(TEXTO),
        page_offsets=[(0, len(TEXTO))],
    )


def _spans() -> list[Span]:
    i_nome = TEXTO.index(NOME)
    i_cpf = TEXTO.index(CPF_VALOR)
    return [
        Span(i_nome, i_nome + len(NOME), "PERSON", 1.0),
        Span(i_cpf, i_cpf + len(CPF_VALOR), "CPF", 1.0),
    ]


def test_span_sem_retangulo_nao_loga_o_valor(tmp_pdf, tmp_path, caplog):
    entrada = tmp_pdf(["linha qualquer"])
    saida = tmp_path / "redigido.pdf"

    doc = fitz.open(str(entrada))
    try:
        with caplog.at_level(logging.WARNING, logger="anonimizador.pdf_redactor"):
            res = redact_document(doc, tm := _mapa_sem_caixas(), _spans(), saida)
    finally:
        doc.close()

    # Se isto falhar, o teste parou de exercitar o caminho sob teste e as
    # asserções abaixo passariam por vacuidade.
    assert len(res.spans_sem_retangulo) == 2
    assert tm.text == TEXTO

    registrado = "\n".join(r.getMessage() for r in caplog.records)

    # Metade 1: o sinal continua existindo. Um span detectado e não tarjado é
    # PII que escapou da redação; silenciar o aviso seria trocar um vazamento
    # de log por um vazamento de documento.
    assert "span sem retangulo" in registrado

    # Metade 2: e não carrega o valor, em nenhuma das formas em que ele
    # poderia reaparecer.
    for proibido in (NOME, "Sauro", CPF_VALOR, "52998224725", "529", "247"):
        assert proibido not in registrado, f"valor vazou no log como {proibido!r}"

    # O que sobra é o que o diagnóstico precisa: qual entidade, onde.
    assert "PERSON" in registrado
    assert "CPF[14]" in registrado


def test_registro_nao_tem_campo_capaz_de_carregar_texto():
    """Trava estrutural, e é ela que impede a regressão.

    O `repr` de um dataclass mostra todos os campos. Se alguém reintroduzir um
    campo com o valor "só para depurar", este teste cai — antes de o dado
    chegar ao log, ao stdout da CLI ou ao relatório da sessão, que são os três
    consumidores deste objeto.
    """
    sem_caixa = SpanSemRetangulo("CPF", 10, 24)

    assert sem_caixa.comprimento == 14
    assert str(sem_caixa) == "CPF[14] @10"
    assert repr(sem_caixa) == "SpanSemRetangulo(entity='CPF', start=10, end=24)"


def test_valores_redigidos_continuam_alimentando_o_verificador(tmp_pdf, tmp_path):
    """A correção não pode cegar o verificador.

    `res.valores` continua carregando o texto **de propósito**: é uso em
    memória, dentro do processo, e é o que `verify` procura no PDF final. Sem
    ele o gate de download não teria o que conferir. A regra é sobre o que
    *sai* do processo, não sobre o que circula dentro dele.
    """
    entrada = tmp_pdf(["CONTRATADO: Joao da Silva Sauro", f"CPF {CPF_VALOR}"])
    saida = tmp_path / "redigido.pdf"

    doc = fitz.open(str(entrada))
    try:
        tm = build_text_map(doc)
        i = tm.text.index(CPF_VALOR)
        res = redact_document(doc, tm, [Span(i, i + len(CPF_VALOR), "CPF", 1.0)], saida)
    finally:
        doc.close()

    assert res.spans_redigidos == 1
    assert not res.spans_sem_retangulo
    assert CPF_VALOR in res.valores
