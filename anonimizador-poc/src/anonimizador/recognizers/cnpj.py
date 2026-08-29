"""CNPJ — 14 dígitos com dois DV mod-11 de pesos cíclicos."""

from presidio_analyzer import Pattern

from ..validators import validate_cnpj
from .base import ChecksumRecognizer

PATTERNS = [
    Pattern("CNPJ mascarado", r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", 0.7),
    Pattern("CNPJ cru", r"(?<!\d)\d{14}(?!\d)", 0.3),
]

CONTEXT = [
    "cnpj", "c.n.p.j", "cadastro nacional da pessoa jurídica",
    "inscrita no cnpj", "cnpj/mf", "cnpj nº", "pessoa jurídica",
]


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("CNPJ", PATTERNS, CONTEXT, validate_cnpj)
