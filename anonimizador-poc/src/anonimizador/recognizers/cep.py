"""CEP — 8 dígitos, sem dígito verificador.

Validar CEP de verdade exigiria a base de faixas dos Correios, que não é
redistribuível livremente e ficaria desatualizada dentro do container offline.
Ficamos no padrão + contexto e reportamos o recall honestamente.
"""

from presidio_analyzer import Pattern

from .base import ChecksumRecognizer

PATTERNS = [
    Pattern("CEP mascarado", r"\b\d{5}-\d{3}\b", 0.5),
    Pattern("CEP cru", r"(?<!\d)\d{8}(?!\d)", 0.1),
]

CONTEXT = [
    "cep", "c.e.p", "código postal", "endereço", "logradouro", "rua",
    "avenida", "bairro", "município", "residente", "domiciliado",
]


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("CEP", PATTERNS, CONTEXT, None)
