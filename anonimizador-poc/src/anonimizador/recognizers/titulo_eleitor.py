"""Título de eleitor — 12 dígitos: 8 sequenciais + 2 de UF + 2 DV."""

from presidio_analyzer import Pattern

from ..validators import validate_titulo_eleitor
from .base import ChecksumRecognizer

PATTERNS = [
    Pattern("Título espaçado", r"(?<!\d)\d{4}[\s.]\d{4}[\s.]\d{4}(?!\d)", 0.5),
    Pattern("Título cru", r"(?<!\d)\d{12}(?!\d)", 0.3),
]

CONTEXT = [
    "título de eleitor", "titulo eleitoral", "inscrição eleitoral", "zona",
    "seção", "tre", "eleitor",
]


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("TITULO_ELEITOR", PATTERNS, CONTEXT, validate_titulo_eleitor)
