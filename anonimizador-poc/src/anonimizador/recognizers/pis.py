"""PIS/PASEP/NIT — 11 dígitos com DV mod-11. Onipresente em documento de RH."""

from presidio_analyzer import Pattern

from ..validators import validate_pis
from .base import ChecksumRecognizer

PATTERNS = [
    Pattern("PIS mascarado", r"\b\d{3}\.\d{5}\.\d{2}-\d\b", 0.7),
    Pattern("PIS cru", r"(?<!\d)\d{11}(?!\d)", 0.25),
]

CONTEXT = [
    "pis", "pasep", "pis/pasep", "nit", "nis", "número de inscrição",
    "inscrição do trabalhador", "fgts", "ctps",
]


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("PIS_PASEP", PATTERNS, CONTEXT, validate_pis)
