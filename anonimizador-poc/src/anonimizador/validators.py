"""Validadores de dígito verificador para identificadores brasileiros.

Funções puras, sem I/O e sem dependências externas — é aqui que mora a
precisão dos reconhecedores estruturados. Cada função recebe a string bruta
(com ou sem máscara) e devolve ``True`` apenas se o checksum fechar.

Regra geral adotada: sequências de dígitos repetidos (``000...``, ``111...``)
são rejeitadas mesmo quando o cálculo do módulo fecha. Elas fecham por
construção em vários desses algoritmos e são a principal fonte de falso
positivo em documentos reais (numeração de formulário, preenchimento de
teste, linhas pontilhadas convertidas em dígitos por OCR).
"""

from __future__ import annotations

import re

__all__ = [
    "only_digits",
    "is_repeated",
    "validate_cpf",
    "validate_cnpj",
    "validate_cns",
    "validate_pis",
    "cnh_dvs",
    "validate_cnh",
    "validate_titulo_eleitor",
    "validate_processo_cnj",
    "validate_ddd",
    "DDDS_VALIDOS",
]

_NON_DIGIT = re.compile(r"\D")


def only_digits(value: str) -> str:
    """Remove tudo que não for dígito."""
    return _NON_DIGIT.sub("", value or "")


def is_repeated(digits: str) -> bool:
    """``True`` se todos os dígitos forem iguais (ex.: ``11111111111``)."""
    return len(digits) > 0 and digits == digits[0] * len(digits)


def _mod11_dv(digits: str, weights: list[int]) -> int:
    """Dígito verificador clássico mod-11 (resto < 2 vira 0)."""
    total = sum(int(d) * w for d, w in zip(digits, weights))
    resto = total % 11
    return 0 if resto < 2 else 11 - resto


# --------------------------------------------------------------------------
# CPF — 11 dígitos, dois DV por mod-11 com pesos decrescentes.
# --------------------------------------------------------------------------
def validate_cpf(value: str) -> bool:
    d = only_digits(value)
    if len(d) != 11 or is_repeated(d):
        return False
    dv1 = _mod11_dv(d[:9], list(range(10, 1, -1)))
    dv2 = _mod11_dv(d[:10], list(range(11, 1, -1)))
    return d[9] == str(dv1) and d[10] == str(dv2)


# --------------------------------------------------------------------------
# CNPJ — 14 dígitos, pesos cíclicos 2..9.
# --------------------------------------------------------------------------
_CNPJ_W1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_CNPJ_W2 = [6] + _CNPJ_W1


def validate_cnpj(value: str) -> bool:
    d = only_digits(value)
    if len(d) != 14 or is_repeated(d):
        return False
    dv1 = _mod11_dv(d[:12], _CNPJ_W1)
    dv2 = _mod11_dv(d[:13], _CNPJ_W2)
    return d[12] == str(dv1) and d[13] == str(dv2)


# --------------------------------------------------------------------------
# CNS — Cartão Nacional de Saúde. 15 dígitos, duas famílias de algoritmo.
# Definitivo (começa com 1 ou 2): soma ponderada 15..1 múltipla de 11.
# Provisório (começa com 7, 8 ou 9): soma ponderada 15..1 múltipla de 11.
# --------------------------------------------------------------------------
def validate_cns(value: str) -> bool:
    d = only_digits(value)
    if len(d) != 15 or is_repeated(d):
        return False
    if d[0] not in "12789":
        return False
    soma = sum(int(x) * (15 - i) for i, x in enumerate(d))
    return soma % 11 == 0


# --------------------------------------------------------------------------
# PIS/PASEP/NIT — 11 dígitos, pesos 3,2,9,8,7,6,5,4,3,2.
# --------------------------------------------------------------------------
_PIS_W = [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def validate_pis(value: str) -> bool:
    d = only_digits(value)
    if len(d) != 11 or is_repeated(d):
        return False
    total = sum(int(x) * w for x, w in zip(d[:10], _PIS_W))
    resto = total % 11
    dv = 0 if resto < 2 else 11 - resto
    return d[10] == str(dv)


# --------------------------------------------------------------------------
# CNH — 11 dígitos, dois DV com regra de ajuste do Denatran.
#
# Atenção: o algoritmo da CNH circula em pelo menos duas variantes
# incompatíveis (com e sem o desconto de 2 no segundo DV, e com clamps
# diferentes quando o resto cai em 10). Não existe publicação normativa
# facilmente citável que resolva a divergência. Consequência prática para a
# Fase 0: CNH fica na faixa "medida, sem gate" do goal, e geração e validação
# compartilham **a mesma** função de DV — assim o corpus é internamente
# consistente e o número reportado mede o reconhecedor, não a variante.
# Se a CNH virar entidade crítica na Fase 1, validar contra uma amostra real
# do cliente antes de confiar no checksum.
# --------------------------------------------------------------------------
def cnh_dvs(base9: str) -> tuple[int, int]:
    """Calcula os dois DV a partir dos 9 primeiros dígitos."""
    dv1 = sum(int(base9[i]) * (9 - i) for i in range(9)) % 11
    desconto = 0
    if dv1 >= 10:
        dv1, desconto = 0, 2

    dv2 = sum(int(base9[i]) * (1 + i) for i in range(9)) % 11 - desconto
    if dv2 < 0:
        dv2 += 11
    if dv2 >= 10:
        dv2 = 0
    return dv1, dv2


def validate_cnh(value: str) -> bool:
    d = only_digits(value)
    if len(d) != 11 or is_repeated(d):
        return False
    dv1, dv2 = cnh_dvs(d[:9])
    return d[9] == str(dv1) and d[10] == str(dv2)


# --------------------------------------------------------------------------
# Título de eleitor — 12 dígitos: 8 sequenciais + 2 de UF + 2 DV.
# --------------------------------------------------------------------------
def validate_titulo_eleitor(value: str) -> bool:
    d = only_digits(value)
    if len(d) != 12 or is_repeated(d):
        return False

    uf = int(d[8:10])
    if not (1 <= uf <= 28):  # 01..28 são os códigos de UF válidos
        return False

    soma1 = sum(int(d[i]) * (2 + i) for i in range(8))
    dv1 = soma1 % 11
    if dv1 == 10:
        dv1 = 0

    soma2 = int(d[8]) * 7 + int(d[9]) * 8 + dv1 * 9
    dv2 = soma2 % 11
    if dv2 == 10:
        dv2 = 0

    return d[10] == str(dv1) and d[11] == str(dv2)


# --------------------------------------------------------------------------
# Numeração única de processo judicial (Res. CNJ 65/2008):
# NNNNNNN-DD.AAAA.J.TR.OOOO — DV por mod-97-10 (ISO 7064), igual ao IBAN.
# --------------------------------------------------------------------------
_CNJ_RE = re.compile(r"^(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})$")


def validate_processo_cnj(value: str) -> bool:
    m = _CNJ_RE.match((value or "").strip())
    if not m:
        return False
    numero, dv, ano, justica, tribunal, origem = m.groups()
    # Move o DV para o fim e acrescenta "00", conforme ISO 7064 mod-97-10.
    base = f"{numero}{ano}{justica}{tribunal}{origem}00"
    return (98 - int(base) % 97) == int(dv)


# --------------------------------------------------------------------------
# DDD — não é checksum, mas é uma lista finita e fechada. Serve como filtro
# barato de falso positivo para telefone (descarta "(00)" e afins).
# --------------------------------------------------------------------------
DDDS_VALIDOS = frozenset(
    {
        11, 12, 13, 14, 15, 16, 17, 18, 19,
        21, 22, 24, 27, 28,
        31, 32, 33, 34, 35, 37, 38,
        41, 42, 43, 44, 45, 46, 47, 48, 49,
        51, 53, 54, 55,
        61, 62, 63, 64, 65, 66, 67, 68, 69,
        71, 73, 74, 75, 77, 79,
        81, 82, 83, 84, 85, 86, 87, 88, 89,
        91, 92, 93, 94, 95, 96, 97, 98, 99,
    }
)


def validate_ddd(value: str) -> bool:
    d = only_digits(value)
    return len(d) == 2 and int(d) in DDDS_VALIDOS
