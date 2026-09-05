"""Prova, de dentro do container ``analise``, que ele não alcança documento.

O serviço ``analise`` é o único que faz conteúdo sair da máquina. A promessa
que o desenho faz é que ele recebe **apenas** o texto já pseudonimizado e já
verificado, entregue pelo ``ui`` — nunca o PDF original, nunca a pasta da
sessão em revisão.

Isso é afirmação sobre configuração, e configuração cala quando quebra. Este
script verifica em vez de confiar.

## Por que ele existe

Escrito depois que o alvo ``llm-proof`` reprovou na primeira execução, em
2026-09-05. O ``docker-compose.yml`` monta só ``./src`` neste serviço — mas o
``Dockerfile`` faz ``COPY . /app`` e não havia ``.dockerignore``, então
``out/`` era **assado na imagem** no momento do build. O container enxergava
``/app/out/sessoes``.

Estava vazio, e não houve vazamento. Mas um build feito com uma sessão em
revisão teria copiado o PDF original em claro para dentro de uma imagem — com
retenção própria, sem TTL e sem verificação, que é exatamente o que a
invariante 9 proíbe. E a mesma falha assaria o ``.env`` com a chave da API.

O conserto tem duas camadas (``.dockerignore`` e ``tmpfs``), e este script é o
que impede as duas de apodrecerem em silêncio.

    docker compose exec -T analise python -m anonimizador.web.prova_isolamento
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Caminhos onde documento em claro pode aparecer. `out/sessoes` é onde o
# original vive durante a revisão; `data` é a pasta de trabalho da CLI.
CAMINHOS = [
    Path("/app/out"),
    Path("/app/data"),
    Path("/app/eval/datasets"),
]

# Extensões que caracterizam documento, e não código ou configuração.
SUFIXOS = {".pdf", ".txt", ".json"}


def achar_documentos(raiz: Path) -> list[Path]:
    if not raiz.exists():
        return []
    try:
        return [
            p
            for p in raiz.rglob("*")
            if p.is_file() and p.suffix.lower() in SUFIXOS
        ]
    except OSError:
        # Sem permissão de leitura também é isolamento — e é o resultado bom.
        return []


def main() -> int:
    print("\n=== PROVA DE ISOLAMENTO DO SERVICO DE ANALISE ===\n")
    problemas: list[str] = []

    for raiz in CAMINHOS:
        achados = achar_documentos(raiz)
        if achados:
            problemas.append(f"{raiz}: {len(achados)} arquivo(s)")
            # Nomes, não conteúdo: o nome basta para localizar a falha, e ler
            # o arquivo aqui seria repetir o erro que estamos detectando.
            amostra = ", ".join(p.name for p in achados[:5])
            print(f"  {str(raiz):24} VAZOU     {len(achados)} arquivo(s): {amostra}")
        else:
            estado = "vazio" if raiz.exists() else "inexistente"
            print(f"  {str(raiz):24} ok        ({estado})")

    # A chave não pode ter sido assada na imagem: no runtime ela chega por
    # variável de ambiente, e o arquivo não deve existir aqui.
    env = Path("/app/.env")
    if env.exists():
        problemas.append("/app/.env presente na imagem")
        print(f"  {'/app/.env':24} VAZOU     credencial assada na imagem")
    else:
        print(f"  {'/app/.env':24} ok        (ausente)")

    # E a chave precisa estar presente como ambiente, senão o serviço não tem
    # o que fazer — mas isso é aviso, não reprovação do isolamento.
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        print("\n  aviso: OPENROUTER_API_KEY ausente; copie .env.example para .env")

    if problemas:
        print("\nREPROVADO — o servico com egress alcanca documento em claro:")
        for p in problemas:
            print(f"  - {p}")
        print()
        return 1

    print("\nAPROVADO — nenhum documento em claro alcancavel deste container.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
