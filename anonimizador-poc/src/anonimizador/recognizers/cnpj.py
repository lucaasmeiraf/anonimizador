"""CNPJ — 14 dígitos com dois DV mod-11 de pesos cíclicos."""

from presidio_analyzer import Pattern

from ..validators import validate_cnpj
from .base import ChecksumRecognizer

PATTERNS = [
    Pattern("CNPJ mascarado", r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", 0.7),
    Pattern("CNPJ cru", r"(?<!\d)\d{14}(?!\d)", 0.3),
]

CONTEXT = [
    "cnpj", "c.n.p.j", "cadastro nacional da pessoa jurídica",
    "inscrita no cnpj", "cnpj/mf", "cnpj nº", "pessoa jurídica",
    # Uma chave PIX **é** um CNPJ quando a pessoa jurídica a cadastra assim, e
    # nesse campo ela costuma aparecer sem pontuação — que é justamente a forma
    # que o `base.py` descarta sem âncora.
    #
    # Medido em 2026-09-05: um documento com `CNPJ fictício: 61.904.327/...`
    # numa passagem e `Chave PIX: 61904327000118` noutra tinha só a primeira
    # detectada. A segunda sobrevivia à redação, o `verify` a encontrava pela
    # variante numérica e reprovava o documento inteiro — o usuário ficava sem
    # entregável e sem saber o que consertar.
    #
    # "chave pix" e não "pix": a janela de âncora casa por substring, e "pix"
    # sozinho casaria dentro de "pixel" num documento técnico.
    "chave pix", "chave-pix",
]


def build() -> ChecksumRecognizer:
    return ChecksumRecognizer("CNPJ", PATTERNS, CONTEXT, validate_cnpj)
