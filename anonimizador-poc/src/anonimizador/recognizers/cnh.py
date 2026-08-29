"""CNH — 11 dígitos, indistinguível de CPF/PIS pela forma.

Por isso o score do padrão é deliberadamente baixo (0.2): sozinho ele fica
abaixo do limiar e é descartado. Só sobe acima do corte quando o enriquecedor
de contexto encontra uma âncora ("CNH nº", "habilitação", "registro"). Sem
essa disciplina, CNH transformaria todo CPF do documento num falso positivo
duplicado.

Ver também a nota sobre as variantes conflitantes do algoritmo em
``validators.cnh_dvs``.
"""

from presidio_analyzer import Pattern

from ..validators import validate_cnh
from .base import ChecksumRecognizer

PATTERNS = [
    Pattern("CNH", r"(?<!\d)\d{11}(?!\d)", 0.2),
]

CONTEXT = [
    "cnh", "carteira nacional de habilitação", "habilitação", "registro cnh",
    "número de registro", "renach", "condutor", "detran",
]


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("CNH", PATTERNS, CONTEXT, validate_cnh)
