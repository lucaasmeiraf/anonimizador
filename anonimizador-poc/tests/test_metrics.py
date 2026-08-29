"""Métricas — as três leituras precisam discordar nos casos certos."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from align import GoldSpan  # noqa: E402
from metrics import Resultado, acumular  # noqa: E402

from anonimizador.spans import Span  # noqa: E402


def test_acerto_perfeito():
    r = Resultado()
    acumular(r, [GoldSpan("CPF", "x" * 14, 10, 24)], [Span(10, 24, "CPF", 1.0)])
    assert r.estrito["CPF"].f1 == 1.0
    assert r.relaxado["CPF"].f1 == 1.0
    assert r.cobertura_chars == 1.0


def test_fronteira_deslocada_separa_estrito_de_relaxado():
    """"Dr. Joao" vs "Joao": erra o estrito, acerta o relaxado, e a cobertura
    fica parcial. É exatamente por isso que o gate de PERSON usa o relaxado."""
    r = Resultado()
    acumular(r, [GoldSpan("PERSON", "Dr. Joao", 0, 8)], [Span(4, 8, "PERSON", 0.9)])
    assert r.estrito["PERSON"].f1 == 0.0
    assert r.relaxado["PERSON"].f1 == 1.0
    assert 0 < r.cobertura_chars < 1


def test_tipo_errado_ainda_cobre():
    """Rotular CPF como RG erra as duas F1 mas NÃO vaza — a cobertura mostra."""
    r = Resultado()
    acumular(r, [GoldSpan("CPF", "x" * 14, 0, 14)], [Span(0, 14, "RG", 0.9)])
    assert r.estrito["CPF"].f1 == 0.0
    assert r.relaxado["CPF"].f1 == 0.0
    assert r.cobertura_chars == 1.0


def test_nao_detectado_e_falso_negativo():
    r = Resultado()
    acumular(r, [GoldSpan("CPF", "x" * 14, 0, 14)], [])
    assert r.estrito["CPF"].fn == 1
    assert r.cobertura_chars == 0.0


def test_falso_positivo_contabilizado():
    r = Resultado()
    acumular(r, [], [Span(0, 14, "CPF", 1.0)])
    assert r.estrito["CPF"].fp == 1
    assert r.estrito["CPF"].precisao == 0.0
