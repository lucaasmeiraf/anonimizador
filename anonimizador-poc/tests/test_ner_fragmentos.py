"""Pedaços de uma mesma palavra, devolvidos pelo NER como spans separados.

A agregação ``simple`` do HuggingFace parte a palavra quando o modelo rotula
uma subpalavra do meio como início de entidade. Medido em 2026-09-23 no
corpus, com `bert-lenerbr`: 1.393 pares colados de ``DATE_TIME`` e 386 de
``PERSON``.

Em tarja ninguém via: os retângulos encostam e formam uma barra só. Em modo
código, "Eloah" virava ``[P-AAAA][P-BBBB]`` — o mesmo nome deixava de ter o
mesmo código, e caixas de 2,8pt reprovavam o documento inteiro. Foi assim
que apareceu: relatado pelo usuário, com ``LOCATION@363-364``.

Os testes chamam o método direto, sem carregar modelo.
"""

from anonimizador.ner import TransformersNerRecognizer

colar = TransformersNerRecognizer._colar_fragmentos


def test_pedacos_colados_da_mesma_entidade_viram_um():
    # "20/12/2025" em cinco pedaços: 20 | / | 12 | / | 2025
    pedacos = [
        (0, 2, "DATE_TIME", 0.9),
        (2, 3, "DATE_TIME", 0.6),
        (3, 5, "DATE_TIME", 0.9),
        (5, 6, "DATE_TIME", 0.6),
        (6, 10, "DATE_TIME", 0.95),
    ]
    assert colar(pedacos) == [(0, 10, "DATE_TIME", 0.95)]


def test_nome_partido_no_meio_volta_a_ser_um_nome():
    # "Eloah" como "El" + "oah"
    assert colar([(10, 12, "PERSON", 0.8), (12, 15, "PERSON", 0.7)]) == [
        (10, 15, "PERSON", 0.8)
    ]


def test_separado_por_espaco_continua_separado():
    """Medido: os pares de PERSON separados só por espaço eram duas pessoas.

    ``'Diogo da Rocha\\nLeandro Pereira'`` — juntar daria um código para as
    duas, e quem lesse o documento veria um ator onde havia dois.
    """
    dois = [(0, 14, "PERSON", 0.9), (15, 30, "PERSON", 0.9)]
    assert colar(dois) == dois


def test_entidades_diferentes_coladas_nao_se_misturam():
    pedacos = [(0, 5, "LOCATION", 0.9), (5, 8, "PERSON", 0.9)]
    assert colar(pedacos) == pedacos


def test_ordem_de_entrada_nao_muda_o_resultado():
    """Invariante 10: detecção determinística."""
    pedacos = [(3, 5, "DATE_TIME", 0.9), (0, 2, "DATE_TIME", 0.9), (2, 3, "DATE_TIME", 0.6)]
    assert colar(pedacos) == colar(sorted(pedacos)) == [(0, 5, "DATE_TIME", 0.9)]


def test_lista_vazia():
    assert colar([]) == []


# --- quebra de linha ---------------------------------------------------------
cortar = TransformersNerRecognizer._cortar_na_quebra


def test_span_que_atravessa_a_quebra_vira_dois():
    """`rh-013`: o NER devolveu 'Cauê Viana\\nAna', encostado no nome seguinte.

    Inteiro, ele se sobrepunha a 'Ana Sophia Aparecida', perdia a disputa e
    era descartado — e "Cauê Viana" saía sem tarja.
    """
    texto = "Cauê Viana\nAna Sophia Aparecida"
    assert cortar(texto, 0, 14) == [(0, 10), (11, 14)]


def test_span_sem_quebra_fica_como_esta():
    assert cortar("Maria da Silva", 0, 14) == [(0, 14)]


def test_corte_nao_perde_cobertura():
    """Todo caractere que não é quebra continua coberto por alguma parte."""
    texto = "a\nbc\n\nd"
    partes = cortar(texto, 0, len(texto))
    coberto = {i for s, e in partes for i in range(s, e)}
    assert coberto == {i for i, c in enumerate(texto) if c != "\n"}


def test_colar_nao_junta_de_volta_por_cima_da_quebra():
    texto = "Cauê Viana\nAna"
    partes = [(s, e, "PERSON", 1.0) for s, e in cortar(texto, 0, len(texto))]
    assert colar(partes) == partes
