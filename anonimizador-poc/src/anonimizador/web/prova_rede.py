"""Prova, de dentro do container ``ui``, que ele não tem saída de rede.

O ``offline-proof`` da Fase 0 sabota o módulo ``socket`` do processo. Isso não
serve aqui por dois motivos:

* o serviço de UI **precisa** de socket — ele atende HTTP;
* a sabotagem é in-process e ``subprocess`` escapa dela. Isso foi medido, não
  suposto: um ``python -c`` filho conectou em 1.1.1.1:443 normalmente com o
  módulo sabotado no pai.

Então a garantia aqui é outra, e mais forte: o container está numa rede
``internal: true``, sem rota para fora. Não é disciplina de código, é ausência
de caminho no kernel — e por isso vale para subprocesso, extensão em C e
qualquer coisa que a pilha de dependências resolva fazer.

Este script **verifica** essa afirmação em vez de confiar nela. Sai com código
1 se qualquer tentativa de egress tiver sucesso.

    docker compose exec -T ui python -m anonimizador.web.prova_rede
"""

from __future__ import annotations

import socket
import subprocess
import sys

TIMEOUT = 5

# IPs literais, para separar "sem DNS" de "sem rota". Um container que resolve
# nome mas não conecta ainda vaza por DNS; um que nem resolve, não.
ALVOS_TCP = [
    ("1.1.1.1", 443),
    ("8.8.8.8", 53),
    ("140.82.121.4", 443),  # github
]
ALVOS_DNS = ["pypi.org", "huggingface.co"]


def tentar_tcp(host: str, porta: int) -> tuple[bool, str]:
    try:
        s = socket.create_connection((host, porta), timeout=TIMEOUT)
        s.close()
        return True, "conectou"
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


def tentar_dns(nome: str) -> tuple[bool, str]:
    try:
        return True, socket.gethostbyname(nome)
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


def tentar_subprocesso() -> tuple[bool, str]:
    """O caminho que a sabotagem in-process não cobre."""
    codigo = (
        "import socket;"
        f"socket.create_connection(('1.1.1.1',443),timeout={TIMEOUT})"
    )
    try:
        r = subprocess.run(
            [sys.executable, "-c", codigo],
            capture_output=True,
            timeout=TIMEOUT * 4,
        )
        return r.returncode == 0, f"rc={r.returncode}"
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


def main() -> int:
    print("\n=== PROVA DE AUSÊNCIA DE EGRESS NO SERVIÇO DE UI ===\n")
    vazamentos = []

    for host, porta in ALVOS_TCP:
        ok, detalhe = tentar_tcp(host, porta)
        marca = "VAZOU" if ok else "bloqueado"
        print(f"  tcp    {host}:{porta:<5}  {marca:<10} ({detalhe})")
        if ok:
            vazamentos.append(f"tcp {host}:{porta}")

    for nome in ALVOS_DNS:
        ok, detalhe = tentar_dns(nome)
        marca = "VAZOU" if ok else "bloqueado"
        print(f"  dns    {nome:<20} {marca:<10} ({detalhe})")
        if ok:
            vazamentos.append(f"dns {nome}")

    ok, detalhe = tentar_subprocesso()
    marca = "VAZOU" if ok else "bloqueado"
    print(f"  subproc 1.1.1.1:443        {marca:<10} ({detalhe})")
    if ok:
        vazamentos.append("subprocesso")

    print()
    if vazamentos:
        print(f"REPROVADO — {len(vazamentos)} caminho(s) de saída abertos:")
        for v in vazamentos:
            print(f"  - {v}")
        print(
            "\nO serviço que processa documentos tem saída de rede. "
            "Confira `networks: [interna]` e `internal: true` no compose.\n"
        )
        return 1

    print("APROVADO — nenhum caminho de saída, subprocesso incluído.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
