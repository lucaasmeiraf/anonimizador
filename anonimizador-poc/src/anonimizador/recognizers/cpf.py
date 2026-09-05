"""CPF — 11 dígitos com dois DV mod-11.

Duas formas: mascarada (alta confiança já no padrão) e crua. A forma crua é
ambígua com PIS e CNH, que também têm 11 dígitos; o checksum desempata, e o
que sobrar de conflito é resolvido pela precedência em ``config.PRECEDENCIA``.
"""

from presidio_analyzer import Pattern

from ..validators import validate_cpf
from .base import ChecksumRecognizer

PATTERNS = [
    Pattern("CPF mascarado", r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", 0.6),
    Pattern("CPF cru", r"(?<!\d)\d{11}(?!\d)", 0.3),
]

CONTEXT = [
    "cpf", "c.p.f", "cadastro de pessoa física", "cadastro de pessoas físicas",
    "inscrito no cpf", "portador do cpf", "cpf/mf", "cpf nº", "cpf n°",
    # Pelo mesmo motivo do CNPJ: uma chave PIX de pessoa física é quase sempre
    # o CPF, e nesse campo ele aparece sem pontuação — a forma que o `base.py`
    # descarta quando não há âncora nem checksum válido. "chave pix" e não
    # "pix", porque a janela casa por substring e pegaria "pixel".
    "chave pix", "chave-pix",
]


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("CPF", PATTERNS, CONTEXT, validate_cpf)
