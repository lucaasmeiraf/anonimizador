"""Testes dos validadores de checksum.

Duas frentes, de propósito:

1. **Valores conhecidos** — CPF/CNPJ públicos de teste, cujo resultado é
   verificável fora deste repositório. Quebram a circularidade de testar um
   algoritmo com o gerador escrito a partir do mesmo algoritmo.
2. **Ida e volta gerador↔validador** — em volume, com semente fixa, e a
   propriedade de que alterar qualquer dígito derruba a validação.
"""

from __future__ import annotations

import random

import pytest

from anonimizador import fakes, validators as v


# --------------------------------------------------------------------------
# 1. Valores conhecidos
# --------------------------------------------------------------------------
CPFS_VALIDOS = ["529.982.247-25", "111.444.777-35", "52998224725"]
CPFS_INVALIDOS = [
    "529.982.247-26",   # DV errado
    "111.111.111-11",   # repetido (fecha o mod-11, mas é lixo)
    "000.000.000-00",
    "1234567890",       # curto
    "123456789012",     # longo
    "",
]

CNPJS_VALIDOS = ["11.222.333/0001-81", "11222333000181"]
CNPJS_INVALIDOS = ["11.222.333/0001-82", "00.000.000/0000-00", "1122233300018"]


@pytest.mark.parametrize("valor", CPFS_VALIDOS)
def test_cpf_valido(valor):
    assert v.validate_cpf(valor)


@pytest.mark.parametrize("valor", CPFS_INVALIDOS)
def test_cpf_invalido(valor):
    assert not v.validate_cpf(valor)


@pytest.mark.parametrize("valor", CNPJS_VALIDOS)
def test_cnpj_valido(valor):
    assert v.validate_cnpj(valor)


@pytest.mark.parametrize("valor", CNPJS_INVALIDOS)
def test_cnpj_invalido(valor):
    assert not v.validate_cnpj(valor)


# --------------------------------------------------------------------------
# 2. Ida e volta gerador ↔ validador
# --------------------------------------------------------------------------
ROUNDTRIP = [
    ("cpf", fakes.fake_cpf, v.validate_cpf),
    ("cnpj", fakes.fake_cnpj, v.validate_cnpj),
    ("cns", fakes.fake_cns, v.validate_cns),
    ("pis", fakes.fake_pis, v.validate_pis),
    ("cnh", fakes.fake_cnh, v.validate_cnh),
    ("titulo", fakes.fake_titulo_eleitor, v.validate_titulo_eleitor),
    ("cnj", fakes.fake_processo_cnj, v.validate_processo_cnj),
]


@pytest.mark.parametrize("nome,gerar,validar", ROUNDTRIP, ids=[r[0] for r in ROUNDTRIP])
def test_roundtrip(nome, gerar, validar):
    rng = random.Random(20260829)
    for _ in range(500):
        assert validar(gerar(rng)), f"{nome}: gerador produziu valor que o validador rejeita"


@pytest.mark.parametrize("nome,gerar,validar", ROUNDTRIP, ids=[r[0] for r in ROUNDTRIP])
def test_digito_alterado_reprova(nome, gerar, validar):
    """Alterar um dígito deve derrubar a validação na esmagadora maioria dos
    casos. Não exigimos 100%: em mod-11 uma troca pode, por acaso, recair em
    outro valor válido. Exigimos que o validador não seja permissivo."""
    rng = random.Random(7)
    reprovados = 0
    total = 300
    for _ in range(total):
        valor = gerar(rng)
        pos = [i for i, c in enumerate(valor) if c.isdigit()]
        i = rng.choice(pos)
        novo = str((int(valor[i]) + rng.randint(1, 9)) % 10)
        mutado = valor[:i] + novo + valor[i + 1:]
        if not validar(mutado):
            reprovados += 1
    assert reprovados / total > 0.85, f"{nome}: validador permissivo demais ({reprovados}/{total})"


# --------------------------------------------------------------------------
# DDD
# --------------------------------------------------------------------------
def test_ddd():
    assert v.validate_ddd("11")
    assert v.validate_ddd("(85)")
    assert not v.validate_ddd("00")
    assert not v.validate_ddd("20")   # não alocado
    assert not v.validate_ddd("123")


def test_only_digits_e_repetido():
    assert v.only_digits("123.456-78") == "12345678"
    assert v.is_repeated("7777")
    assert not v.is_repeated("7778")
    assert not v.is_repeated("")
