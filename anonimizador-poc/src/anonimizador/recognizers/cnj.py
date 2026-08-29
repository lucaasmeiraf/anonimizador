"""Numeração única de processo judicial (Resolução CNJ 65/2008).

Formato NNNNNNN-DD.AAAA.J.TR.OOOO com DV por mod-97-10 (ISO 7064) — o mesmo
esquema do IBAN. É o identificador mais confiável de todo o conjunto: o padrão
é rígido e o checksum é forte, então praticamente não produz falso positivo.

Vale notar que o número do processo em si costuma ser público; ele entra aqui
porque é um **quase-identificador** poderoso — reidentifica as partes com uma
consulta processual.
"""

from presidio_analyzer import Pattern

from ..validators import validate_processo_cnj
from .base import ChecksumRecognizer

PATTERNS = [
    Pattern(
        "Processo CNJ",
        r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b",
        0.8,
    ),
    Pattern("Processo CNJ cru", r"(?<!\d)\d{20}(?!\d)", 0.4),
]

CONTEXT = [
    "processo", "autos", "processo nº", "autos nº", "ação", "execução",
    "distribuído", "vara", "comarca", "tribunal",
]


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("PROCESSO_CNJ", PATTERNS, CONTEXT, validate_processo_cnj)
