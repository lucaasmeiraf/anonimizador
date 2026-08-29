"""E-mail — padrão pragmático, sem tentar implementar a RFC 5322 inteira."""

from presidio_analyzer import Pattern

from .base import ChecksumRecognizer

PATTERNS = [
    Pattern(
        "E-mail",
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        0.75,
    ),
]

CONTEXT = ["e-mail", "email", "correio eletrônico", "contato", "endereço eletrônico"]


def _validate_email(text: str):
    local, _, dominio = text.rpartition("@")
    if not local or not dominio or ".." in text:
        return False
    return not dominio.startswith(".") and not dominio.endswith(".")


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("EMAIL", PATTERNS, CONTEXT, _validate_email)
