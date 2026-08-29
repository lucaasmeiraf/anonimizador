"""CNS — Cartão Nacional de Saúde. 15 dígitos, soma ponderada múltipla de 11.

Entidade central em prontuário: identifica o paciente no SUS e, por
associação, revela dado de saúde — que é dado pessoal sensível pelo art. 5º,
II da LGPD.
"""

from presidio_analyzer import Pattern

from ..validators import validate_cns
from .base import ChecksumRecognizer

PATTERNS = [
    Pattern("CNS espaçado", r"(?<!\d)\d{3}[\s.]\d{4}[\s.]\d{4}[\s.]\d{4}(?!\d)", 0.6),
    Pattern("CNS cru", r"(?<!\d)\d{15}(?!\d)", 0.4),
]

CONTEXT = [
    "cns", "cartão nacional de saúde", "cartão sus", "sus", "número do cartão",
    "cartão nacional", "prontuário", "paciente",
]


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("CNS", PATTERNS, CONTEXT, validate_cns)
