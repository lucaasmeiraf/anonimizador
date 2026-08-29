"""Modelo de span e resolução de sobreposição — lógica pura.

Separado de ``pipeline.py`` de propósito: aqui não há Presidio, spaCy nem
torch. É a parte do sistema que decide *qual* detecção prevalece, e é a que
mais precisa ser testável sem carregar 2 GB de modelo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from . import config


@dataclass(frozen=True)
class Span:
    """Um trecho detectado, em offsets de caractere do texto analisado."""

    start: int
    end: int
    entity: str
    score: float

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end

    def text_of(self, texto: str) -> str:
        return texto[self.start:self.end]


def resolver_sobreposicoes(spans: list[Span]) -> list[Span]:
    """Seleção gulosa de spans disjuntos.

    Critério de desempate, em ordem: precedência da entidade (checksum antes
    de NER), span mais longo, score maior, posição. Determinístico — dois eval
    runs sobre o mesmo corpus produzem exatamente o mesmo resultado, então uma
    variação de métrica é sempre variação de código.
    """
    ordenados = sorted(
        spans,
        key=lambda s: (
            -config.peso_precedencia(s.entity),
            -s.length,
            -s.score,
            s.start,
        ),
    )
    aceitos: list[Span] = []
    for cand in ordenados:
        if any(cand.overlaps(a) for a in aceitos):
            continue
        aceitos.append(cand)
    return sorted(aceitos, key=lambda s: (s.start, s.end))


def spans_para_redigir(spans: Iterable[Span]) -> list[Span]:
    """Filtra as entidades que efetivamente vão para a tarja."""
    return [s for s in spans if s.entity in config.ENTIDADES_REDIGIDAS]
