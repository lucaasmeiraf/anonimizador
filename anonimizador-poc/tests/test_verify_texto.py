"""O gate do artefato de texto.

A invariante 2 do CLAUDE.md não fala em PDF, fala em entregável: nada sai sem
verificação aprovada. Estes testes cobrem as duas metades que `verify_texto`
confere, e a segunda é a que não é óbvia — token ausente com valor removido
passaria por qualquer checagem que só procurasse o original.
"""

from __future__ import annotations

from anonimizador.verifier import verify_texto


def test_texto_limpo_aprova():
    rel = verify_texto("O servidor [P-7F3A] compareceu.", ["Mariana Souza"])
    assert rel.ok
    assert rel.vetores_executados == ["texto"]


def test_valor_sobrevivente_reprova():
    rel = verify_texto(
        "O servidor Mariana Souza compareceu.", ["Mariana Souza"]
    )
    assert not rel.ok
    assert rel.leaks[0].vetor == "texto"


def test_valor_reaparecendo_com_espacamento_diferente_reprova():
    """`_variantes` é reaproveitado: é onde mora a inteligência da busca."""
    rel = verify_texto("nome: Mariana   Souza fim", ["Mariana Souza"])
    assert not rel.ok


def test_cpf_reaparecendo_sem_pontuacao_reprova():
    rel = verify_texto("id 52998224725 fim", ["529.982.247-25"])
    assert not rel.ok


def test_token_ausente_reprova_mesmo_com_o_valor_removido():
    """A aresta 1 da sondagem, no caminho de texto.

    O valor saiu e o token não entrou: uma checagem que só procurasse o
    original diria "limpo", porque o original de fato sumiu. Falso silêncio
    com o gate aprovando é a pior combinação possível neste sistema.
    """
    rel = verify_texto(
        "O servidor  compareceu.",
        ["Mariana Souza"],
        tokens=["[P-7F3A]"],
    )
    assert not rel.ok
    assert rel.leaks[0].vetor == "token-ausente"
    assert rel.leaks[0].valor == "[P-7F3A]"


def test_tokens_presentes_aprovam():
    rel = verify_texto(
        "O servidor [P-7F3A] falou com [P-2C81].",
        ["Mariana Souza", "Joaquim Lima"],
        tokens=["[P-7F3A]", "[P-2C81]"],
    )
    assert rel.ok
    assert rel.vetores_executados == ["texto", "tokens-presentes"]


def test_o_relatorio_nao_insinua_dez_vetores():
    """Quem lê "verificado" não pode supor a verificação do PDF.

    São dez vetores lá porque há dez estruturas onde um valor pode
    sobreviver num PDF. Numa string existe uma.
    """
    rel = verify_texto("texto qualquer", ["Mariana Souza"])
    assert len(rel.vetores_executados) == 1
    assert "streams" not in rel.vetores_executados
    assert "xmp" not in rel.vetores_executados
