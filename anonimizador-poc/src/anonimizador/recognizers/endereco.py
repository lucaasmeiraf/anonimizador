"""Endereço — best-effort, por padrão de logradouro.

Não há como fazer isso bem só com regex: endereço é texto livre com variação
enorme. O que este reconhecedor faz é capturar o esqueleto usual
("<tipo de logradouro> <nome>, <número>") para dar ao redator uma tarja
plausível, e deixar o NER cobrir o restante via LOCATION. O número que sair no
eval deve ser lido como piso, não como capacidade.
"""

from presidio_analyzer import Pattern

from .base import ChecksumRecognizer

_TIPOS = r"(?:Rua|Av\.?|Avenida|Travessa|Alameda|Praça|Rodovia|Estrada|Largo|Viela|Quadra)"

PATTERNS = [
    Pattern(
        "Logradouro com número",
        rf"\b{_TIPOS}\s+[A-ZÁÂÃÀÉÊÍÓÔÕÚÇ][\w'ÁÂÃÀÉÊÍÓÔÕÚÇáâãàéêíóôõúç.\- ]{{2,60}},\s*(?:n[º°.]?\s*)?\d{{1,6}}",
        0.5,
    ),
]

CONTEXT = [
    "endereço", "residente", "domiciliado", "logradouro", "sede", "estabelecido",
    "com sede", "residente e domiciliado",
]


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("ENDERECO", PATTERNS, CONTEXT, None)
