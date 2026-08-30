"""Geradores de identificadores brasileiros **sintéticos e válidos**.

Existem para alimentar o corpus de avaliação: um identificador com checksum
correto é indispensável para exercitar os reconhecedores, mas nenhum destes
números tem qualquer vínculo com pessoa real — são construídos a partir de um
gerador pseudoaleatório semeado, e o corpus inteiro é reprodutível.

Os DV são calculados aqui pela regra de *geração*; ``validators.py`` os
recalcula pela regra de *verificação*. A ida e volta entre os dois módulos é
testada em ``tests/test_validators.py``.
"""

from __future__ import annotations

import random

from .validators import cnh_dvs, is_repeated

__all__ = [
    "fake_cpf",
    "fake_cnpj",
    "fake_cns",
    "fake_pis",
    "fake_cnh",
    "fake_titulo_eleitor",
    "fake_cpf_invalido",
    "fake_cnpj_invalido",
    "fake_cnh_invalida",
    "fake_processo_cnj",
    "fake_rg_sp",
    "fake_cep",
    "fake_telefone",
]

_DDDS = [11, 21, 31, 41, 47, 51, 61, 62, 71, 81, 85, 91]


def _fmt(digits: str, mask: str) -> str:
    """Aplica uma máscara onde ``#`` é substituído por um dígito."""
    out, it = [], iter(digits)
    for ch in mask:
        out.append(next(it) if ch == "#" else ch)
    return "".join(out)


def _mod11_dv(digits: str, weights: list[int]) -> int:
    resto = sum(int(d) * w for d, w in zip(digits, weights)) % 11
    return 0 if resto < 2 else 11 - resto


def fake_cpf(rng: random.Random, masked: bool = True) -> str:
    while True:
        base = "".join(str(rng.randint(0, 9)) for _ in range(9))
        if len(set(base)) == 1:
            continue
        d1 = _mod11_dv(base, list(range(10, 1, -1)))
        d2 = _mod11_dv(base + str(d1), list(range(11, 1, -1)))
        digits = f"{base}{d1}{d2}"
        if len(set(digits)) > 1:
            return _fmt(digits, "###.###.###-##") if masked else digits


def fake_cnpj(rng: random.Random, masked: bool = True) -> str:
    w1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    w2 = [6] + w1
    base = "".join(str(rng.randint(0, 9)) for _ in range(8)) + "0001"
    d1 = _mod11_dv(base, w1)
    d2 = _mod11_dv(base + str(d1), w2)
    digits = f"{base}{d1}{d2}"
    return _fmt(digits, "##.###.###/####-##") if masked else digits


def fake_cns(rng: random.Random, masked: bool = True) -> str:
    """CNS definitivo (prefixo 1 ou 2), 15 dígitos."""
    while True:
        base = str(rng.choice([1, 2])) + "".join(str(rng.randint(0, 9)) for _ in range(10))
        soma = sum(int(x) * (15 - i) for i, x in enumerate(base))
        resto = soma % 11
        dv = 11 - resto
        if dv == 11:
            dv = 0
        if dv == 10:
            # Regra do Datasus: reprocessa com o sufixo "001".
            soma += 2
            resto = soma % 11
            dv = 11 - resto
            if dv in (10, 11):
                continue
            digits = f"{base}001{dv}"
        else:
            digits = f"{base}000{dv}"
        if len(digits) == 15:
            return _fmt(digits, "### #### #### ####") if masked else digits


def fake_pis(rng: random.Random, masked: bool = True) -> str:
    w = [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    base = "".join(str(rng.randint(0, 9)) for _ in range(10))
    resto = sum(int(x) * k for x, k in zip(base, w)) % 11
    dv = 0 if resto < 2 else 11 - resto
    digits = f"{base}{dv}"
    return _fmt(digits, "###.#####.##-#") if masked else digits


def fake_cnh(rng: random.Random) -> str:
    """Usa a mesma rotina de DV do validador — ver a nota sobre as variantes
    conflitantes do algoritmo da CNH em ``validators.cnh_dvs``."""
    while True:
        base = "".join(str(rng.randint(0, 9)) for _ in range(9))
        if len(set(base)) == 1:
            continue
        dv1, dv2 = cnh_dvs(base)
        digits = f"{base}{dv1}{dv2}"
        if len(digits) == 11 and not is_repeated(digits):
            return digits


def fake_titulo_eleitor(rng: random.Random, masked: bool = True) -> str:
    base = "".join(str(rng.randint(0, 9)) for _ in range(8))
    uf = f"{rng.randint(1, 28):02d}"
    dv1 = sum(int(base[i]) * (2 + i) for i in range(8)) % 11
    if dv1 == 10:
        dv1 = 0
    dv2 = (int(uf[0]) * 7 + int(uf[1]) * 8 + dv1 * 9) % 11
    if dv2 == 10:
        dv2 = 0
    digits = f"{base}{uf}{dv1}{dv2}"
    return _fmt(digits, "#### #### ####") if masked else digits


def fake_processo_cnj(rng: random.Random) -> str:
    """NNNNNNN-DD.AAAA.J.TR.OOOO com DV por mod-97-10 (ISO 7064)."""
    numero = f"{rng.randint(1, 9999999):07d}"
    ano = str(rng.randint(2015, 2026))
    justica = str(rng.choice([1, 2, 4, 5, 8]))
    tribunal = f"{rng.randint(1, 26):02d}"
    origem = f"{rng.randint(1, 9999):04d}"
    dv = 98 - int(f"{numero}{ano}{justica}{tribunal}{origem}00") % 97
    return f"{numero}-{dv:02d}.{ano}.{justica}.{tribunal}.{origem}"


def fake_rg_sp(rng: random.Random) -> str:
    """RG no formato de São Paulo. Não há checksum nacional uniforme — o DV
    aqui é o mod-11 usado pelo SSP-SP, com 'X' para o resto 10."""
    base = "".join(str(rng.randint(0, 9)) for _ in range(8))
    soma = sum(int(base[i]) * (2 + i) for i in range(8))
    resto = soma % 11
    dv = "X" if resto == 10 else str(resto)
    return f"{base[0:2]}.{base[2:5]}.{base[5:8]}-{dv}"


def fake_cep(rng: random.Random) -> str:
    return f"{rng.randint(1000, 99999):05d}-{rng.randint(0, 999):03d}"


def fake_telefone(rng: random.Random, celular: bool = True) -> str:
    ddd = rng.choice(_DDDS)
    if celular:
        num = f"9{rng.randint(1000, 9999):04d}{rng.randint(0, 9999):04d}"
        return f"({ddd}) {num[0:5]}-{num[5:]}"
    num = f"{rng.randint(2000, 5999):04d}{rng.randint(0, 9999):04d}"
    return f"({ddd}) {num[0:4]}-{num[4:]}"


# --------------------------------------------------------------------------
# Identificadores com checksum INVÁLIDO
# --------------------------------------------------------------------------
# Não são um capricho: documento real vem cheio deles. Modelo de contrato,
# material de treinamento e minuta usam "CPF fictício nº 123.456.789-00"; ficha
# preenchida à mão tem dígito trocado; PDF vindo de OCR troca 8 por 3.
#
# O reconhecedor da Fase 0 descarta tudo isso — `validate_result` devolve
# `False` e o Presidio joga o candidato fora antes mesmo do enriquecedor de
# contexto olhar a palavra "CPF" logo antes. O número fica legível no PDF
# "anonimizado".
#
# Enquanto o corpus só teve identificador válido, esse caminho nunca foi
# medido, e qualquer mudança nele seria feita no escuro. Estes geradores
# existem para que ele passe a ser.


def _quebrar_dv(digits: str) -> str:
    """Troca o último dígito por outro, invalidando o checksum."""
    ultimo = int(digits[-1])
    return digits[:-1] + str((ultimo + 1) % 10)


def fake_cpf_invalido(rng: random.Random, masked: bool = True) -> str:
    """CPF com forma correta e DV errado — o "CPF fictício" dos modelos."""
    digits = _quebrar_dv(fake_cpf(rng, masked=False))
    return _fmt(digits, "###.###.###-##") if masked else digits


def fake_cnpj_invalido(rng: random.Random, masked: bool = True) -> str:
    digits = _quebrar_dv(fake_cnpj(rng, masked=False))
    return _fmt(digits, "##.###.###/####-##") if masked else digits


def fake_cnh_invalida(rng: random.Random) -> str:
    return _quebrar_dv(fake_cnh(rng))
