"""Telefone BR — sem checksum, mas o DDD é uma lista finita e fechada.

Validar o DDD contra a lista da Anatel é um filtro barato que elimina boa
parte do falso positivo (datas, valores, numeração de processo fatiada).
"""

from presidio_analyzer import Pattern

from ..validators import only_digits, validate_ddd
from .base import ChecksumRecognizer

PATTERNS = [
    Pattern(
        "Telefone com DDD entre parênteses",
        r"\(\d{2}\)\s?9?\d{4}[-\s]?\d{4}\b",
        0.6,
    ),
    Pattern(
        "Telefone com +55",
        r"\+55\s?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b",
        0.7,
    ),
    Pattern(
        "Telefone sem parênteses",
        r"(?<!\d)\d{2}\s9?\d{4}[-\s]\d{4}(?!\d)",
        0.4,
    ),
]

CONTEXT = [
    "telefone", "tel", "fone", "celular", "whatsapp", "contato", "ramal",
    "telefone para contato", "tel.", "cel.",
]


def _validate_telefone(text: str):
    d = only_digits(text)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) not in (10, 11):
        return False
    if not validate_ddd(d[:2]):
        return False
    # Celular de 11 dígitos tem de começar com 9 após o DDD; fixo de 10 começa
    # em 2..5. Fora disso é ruído numérico.
    if len(d) == 11 and d[2] != "9":
        return False
    if len(d) == 10 and d[2] not in "2345":
        return False
    return True


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("TELEFONE", PATTERNS, CONTEXT, _validate_telefone)
