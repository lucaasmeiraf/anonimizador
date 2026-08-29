"""Resolução de spans sobrepostos — lógica pura, sem modelo."""

from anonimizador.spans import Span, resolver_sobreposicoes, spans_para_redigir


def test_checksum_vence_ner():
    """Um CPF dentro de um trecho marcado como PERSON: o CPF prevalece."""
    person = Span(0, 30, "PERSON", 0.95)
    cpf = Span(10, 24, "CPF", 1.0)
    saida = resolver_sobreposicoes([person, cpf])
    assert [s.entity for s in saida] == ["CPF"]


def test_spans_disjuntos_sobrevivem():
    spans = [Span(0, 10, "PERSON", 0.9), Span(20, 34, "CPF", 1.0)]
    assert len(resolver_sobreposicoes(spans)) == 2


def test_saida_ordenada_e_disjunta():
    spans = [
        Span(50, 60, "EMAIL", 0.8),
        Span(0, 14, "CPF", 1.0),
        Span(5, 20, "PERSON", 0.9),
        Span(55, 70, "PERSON", 0.7),
    ]
    saida = resolver_sobreposicoes(spans)
    assert saida == sorted(saida, key=lambda s: s.start)
    for i, a in enumerate(saida):
        for b in saida[i + 1:]:
            assert not a.overlaps(b)


def test_determinismo():
    spans = [Span(0, 10, "PERSON", 0.9), Span(3, 12, "LOCATION", 0.9)]
    assert resolver_sobreposicoes(spans) == resolver_sobreposicoes(list(reversed(spans)))


def test_filtro_de_redacao():
    spans = [Span(0, 5, "CPF", 1.0), Span(10, 20, "ORGANIZATION", 0.9)]
    # ORGANIZATION é medida mas não tarjada por padrão (ver config).
    assert [s.entity for s in spans_para_redigir(spans)] == ["CPF"]
