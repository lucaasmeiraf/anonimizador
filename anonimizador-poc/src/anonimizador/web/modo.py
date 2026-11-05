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


def exigir_login() -> tuple[bool, list[str]]:
    """O sistema está em modo com login? Devolve também o que dizer se não.

    Existe para que a decisão de "pode expor esta porta?" seja **uma**, em
    Python e testada, e não duas em shell. Até 2026-11-04 ela estava escrita
    duas vezes — uma no `Makefile`, outra no `run.ps1` — como um `grep` pela
    string "COM LOGIN" na saída deste módulo. Um `grep` que casa por engano
    abre o sistema para a internet; um que deixa de casar quando o texto muda
    só irrita. Os dois erros são evitáveis com uma função.
    """
    if EXIGIR_LOGIN_ATIVO():
        return True, []
    return False, [
        "  RECUSADO: o sistema está em modo LOCAL, sem login.",
        "",
        "  Publicar esta URL deixaria qualquer pessoa subir documento, e quem",
        "  tivesse um doc_id abriria o documento de outra. Antes:",
        "",
        "    1. crie um usuário   (make usuario / run.ps1 usuario)",
        "    2. ANON_EXIGIR_LOGIN=1 no .env",
        "    3. recarregue        (make ui-recarregar)",
    ]


def EXIGIR_LOGIN_ATIVO() -> bool:
    """Lido de `app` para não haver duas fontes da mesma verdade."""
    return bool(app_mod.EXIGIR_LOGIN)


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else argv

    # `--exigir-login`: não imprime o estado, **decide**. Código de saída 0
    # quando há login; 1 quando não há, com o motivo no stderr. É o que o
    # alvo `tunel` consulta, nos dois sistemas de build.
    if "--exigir-login" in argv:
        ok, recado = exigir_login()
        if not ok:
            for linha in recado:
                print(linha, file=sys.stderr)
        return 0 if ok else 1

    for linha in descrever():
        print(linha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
