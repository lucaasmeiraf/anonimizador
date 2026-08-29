"""RG — sem checksum nacional uniforme.

Cada SSP estadual usa seu próprio formato e sua própria (ou nenhuma) regra de
DV. Por isso o RG **não tem gate** na Fase 0: ele depende inteiramente das
palavras-âncora, e o número que sai do eval serve para calibrar contexto, não
para prometer precisão.

O padrão no formato de São Paulo (com DV mod-11 e 'X' para resto 10) é
verificado quando aplicável; nos demais formatos devolvemos ``None`` e
deixamos o score do padrão + contexto decidirem.
"""

import re

from presidio_analyzer import Pattern

from .base import ChecksumRecognizer

PATTERNS = [
    Pattern("RG mascarado", r"\b\d{1,2}\.\d{3}\.\d{3}-[\dXx]\b", 0.5),
    Pattern("RG com traço", r"(?<![\d.])\d{7,9}-[\dXx]\b", 0.4),
    Pattern("RG cru", r"(?<!\d)\d{7,9}(?!\d)", 0.15),
]

CONTEXT = [
    "rg", "r.g", "registro geral", "identidade", "carteira de identidade",
    "cédula de identidade", "portador do rg", "rg nº", "ssp", "expedido por",
    "órgão expedidor", "documento de identidade",
]

_SP = re.compile(r"^(\d{2})\.?(\d{3})\.?(\d{3})-?([\dXx])$")


def _validate_rg(text: str):
    """Só opina quando o formato é o de SP; caso contrário, abstém-se."""
    m = _SP.match(text.strip())
    if not m:
        return None
    base = "".join(m.groups()[:3])
    dv = m.group(4).upper()
    resto = sum(int(base[i]) * (2 + i) for i in range(8)) % 11
    esperado = "X" if resto == 10 else str(resto)
    return dv == esperado


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("RG", PATTERNS, CONTEXT, _validate_rg)
