"""Diz, em uma linha, em que modo o serviço está rodando.

Existe porque "a tela de login não apareceu" custou uma rodada de diagnóstico
em 2026-11-03, e a causa era simples: a variável não estava no `.env`. O
estado era invisível — o serviço subia igual nos dois modos e nada na saída do
comando dizia qual estava valendo.

Um serviço que pode rodar **aberto** ou **com login** precisa dizer qual, toda
vez que sobe. Não é conveniência: o modo errado aqui é servir o documento de
todos para qualquer um, e descobrir isso por acidente é tarde.

Roda dentro do container, pelo `make ui` e pelo `make ui-recarregar`.
"""

from __future__ import annotations

import os

from . import app as app_mod


def descrever() -> list[str]:
    if app_mod.EXIGIR_LOGIN:
        return [
            "  modo: COM LOGIN  (ANON_EXIGIR_LOGIN=1)",
            "  a tela de entrada aparece, e toda rota de documento exige sessão.",
        ]

    linhas = [
        "  modo: LOCAL  (sem login)",
        "  correto com a porta em 127.0.0.1, onde o perímetro é o endereço.",
    ]
    # Avisa só quando faz diferença: se não há usuário cadastrado, "ligue o
    # login" sem mais nada trancaria a pessoa do lado de fora.
    if not os.getenv("ANON_DB_URL"):
        linhas.append("  sem banco de identidade; ligar o login exige um.")
    else:
        linhas.append(
            "  para exigir login: ANON_EXIGIR_LOGIN=1 no .env, crie um usuário "
            "antes (make usuario), e rode make ui-recarregar."
        )
    return linhas


def main() -> int:
    for linha in descrever():
        print(linha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
