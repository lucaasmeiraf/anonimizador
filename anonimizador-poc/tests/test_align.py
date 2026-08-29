"""Projeção do gabarito — a peça que garante que o eval mede o detector."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from align import alinhar  # noqa: E402


def test_texto_identico():
    fonte = "Joao da Silva, CPF 529.982.247-25."
    gold = [{"label": "CPF", "value": "529.982.247-25", "start": 19, "end": 33}]
    r = alinhar(fonte, fonte, gold)
    assert len(r.gold) == 1
    assert (r.gold[0].start, r.gold[0].end) == (19, 33)
    assert not r.defeitos


def test_espacamento_divergente():
    """A extração inseriu espaços extras: os offsets mudam, o valor não."""
    fonte = "Joao da Silva, CPF 529.982.247-25."
    extraido = "Joao  da  Silva ,  CPF  529.982.247-25 ."
    gold = [{"label": "CPF", "value": "529.982.247-25", "start": 19, "end": 33}]
    r = alinhar(fonte, extraido, gold)
    assert len(r.gold) == 1
    assert extraido[r.gold[0].start:r.gold[0].end] == "529.982.247-25"


def test_valor_ausente_vira_defeito_e_nao_falso_negativo():
    fonte = "Joao da Silva, CPF 529.982.247-25."
    extraido = "Joao da Silva, CPF [ilegivel]."
    gold = [{"label": "CPF", "value": "529.982.247-25", "start": 19, "end": 33}]
    r = alinhar(fonte, extraido, gold)
    assert not r.gold
    assert len(r.defeitos) == 1


def test_ocorrencias_repetidas_nao_colapsam():
    fonte = "Silva contratou Silva para representar Silva."
    gold = [
        {"label": "PERSON", "value": "Silva", "start": 0, "end": 5},
        {"label": "PERSON", "value": "Silva", "start": 16, "end": 21},
        {"label": "PERSON", "value": "Silva", "start": 39, "end": 44},
    ]
    r = alinhar(fonte, fonte, gold)
    assert len({(g.start, g.end) for g in r.gold}) == 3
