#!/usr/bin/env bash
# Provisiona o Anonimizador num VPS Linux. Idempotente: rodar duas vezes nao
# estraga nada.
#
#   scp -r anonimizador-poc usuario@vps:~/            # ou git clone no VPS
#   ssh usuario@vps
#   cd anonimizador-poc && bash provisionar-vps.sh
#
# O passo a passo manual, com a explicacao de cada decisao, esta em
# docs/04-implantacao.md, Parte D. Este script executa os passos D2 a D5 e
# PARA antes do D6 (proxy reverso e TLS), que depende do seu dominio.
#
# O QUE ELE NAO FAZ, de proposito:
#
#   * nao abre porta no firewall;
#   * nao publica a porta em 0.0.0.0 — ela continua em 127.0.0.1, e quem fica
#     de frente para a internet e o proxy reverso no host (D6);
#   * nao inventa senha de banco sem te mostrar;
#   * nao liga o login sozinho sem haver um usuario, porque isso trancaria
#     voce do lado de fora.

set -euo pipefail

cd "$(dirname "$0")"

azul()  { printf '\n\033[1;34m== %s\033[0m\n' "$1"; }
erro()  { printf '\033[1;31m%s\033[0m\n' "$1" >&2; }

# --------------------------------------------------------------------------
azul "1. Conferindo a maquina"
# --------------------------------------------------------------------------
# Numeros medidos, nao estimados: a imagem tem ~4 GB, o `ui` em repouso usa
# ~1,5 GB e chegou a 3,1 GB num documento de 102 paginas. Com 4 GB a maquina
# sobrevive a documento pequeno e morre por OOM num grande — e o modo de
# falha e o container reiniciando no meio de uma revisao.
ram_mb=$(free -m | awk '/^Mem:/{print $2}')
disco_gb=$(df -BG --output=avail . | tail -1 | tr -dc '0-9')
echo "  RAM: ${ram_mb} MB   disco livre: ${disco_gb} GB"

if [ "$ram_mb" -lt 7000 ]; then
    erro "  AVISO: menos de 8 GB de RAM. Documento longo vai derrubar o ui."
    erro "  Siga assim se for so para demonstrar com documento pequeno."
fi
if [ "$disco_gb" -lt 20 ]; then
    erro "  ERRO: menos de 20 GB livres. A imagem sozinha tem ~4 GB."
    exit 1
fi

# --------------------------------------------------------------------------
azul "2. Docker"
# --------------------------------------------------------------------------
if ! command -v docker >/dev/null; then
    echo "  instalando..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    erro "  Docker instalado. SAIA E ENTRE DE NOVO no SSH, e rode este script"
    erro "  outra vez — a mudanca de grupo so vale numa sessao nova."
    exit 0
fi
docker compose version >/dev/null || { erro "  docker compose ausente"; exit 1; }
echo "  ok: $(docker --version)"

# --------------------------------------------------------------------------
azul "3. Arquivo .env"
# --------------------------------------------------------------------------
# Nao vem no clone, de proposito: carrega senhas.
if [ ! -f .env ]; then
    cp .env.example .env
    senha=$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)
    # `POSTGRES_PASSWORD=` existe vazio no exemplo; preenche no lugar.
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${senha}|" .env
    echo "  .env criado, com senha de banco sorteada."
else
    echo "  .env ja existe; preservado."
fi

if ! grep -q '^POSTGRES_PASSWORD=.\+' .env; then
    erro "  ERRO: POSTGRES_PASSWORD vazio no .env. O Postgres se recusa a subir"
    erro "  sem senha — preencha e rode de novo."
    exit 1
fi

# --------------------------------------------------------------------------
azul "4. Imagem"
# --------------------------------------------------------------------------
if docker image inspect anonimizador-poc:fase0 >/dev/null 2>&1; then
    echo "  imagem ja existe; pulando a construcao."
else
    echo "  construindo. Unica etapa com rede; demora bastante."
    echo "  Se este VPS tiver 1 ou 2 vCPU, considere cancelar e transportar a"
    echo "  imagem pronta: docker save | gzip, scp, gunzip | docker load."
    docker compose build
fi

# --------------------------------------------------------------------------
azul "5. Banco e migracoes"
# --------------------------------------------------------------------------
docker compose up -d postgres
echo "  aguardando o Postgres aceitar conexao..."
for _ in $(seq 1 60); do
    if docker compose exec -T postgres pg_isready -q 2>/dev/null; then break; fi
    sleep 2
done
docker compose run --rm cli-db upgrade head

# --------------------------------------------------------------------------
azul "6. Primeiro usuario"
# --------------------------------------------------------------------------
# A ordem importa: criar o usuario ANTES de exigir login, ou voce se tranca
# do lado de fora.
tem_usuario=$(docker compose exec -T postgres psql -U "${POSTGRES_USER:-anonimizador}" \
    -d "${POSTGRES_DB:-anonimizador}" -tAc "SELECT count(*) FROM usuario;" 2>/dev/null || echo 0)

if [ "${tem_usuario:-0}" -gt 0 ]; then
    echo "  ja existe(m) ${tem_usuario} usuario(s); nenhum criado."
else
    read -r -p "  e-mail do primeiro usuario: " email
    read -r -p "  nome do inquilino (orgao/escritorio): " inquilino
    docker compose run --rm --entrypoint python cli-db -m anonimizador.cli \
        criar-usuario --email "$email" --inquilino "$inquilino" --papel dono
    erro "  ANOTE A SENHA ACIMA. Ela aparece uma vez e vale para um login so."
fi

# --------------------------------------------------------------------------
azul "7. Exigir login"
# --------------------------------------------------------------------------
if grep -q '^ANON_EXIGIR_LOGIN=1' .env; then
    echo "  ja exigido."
else
    sed -i 's|^ANON_EXIGIR_LOGIN=.*|ANON_EXIGIR_LOGIN=1|' .env
    grep -q '^ANON_EXIGIR_LOGIN=1' .env || echo 'ANON_EXIGIR_LOGIN=1' >> .env
    echo "  ligado no .env."
fi

# --------------------------------------------------------------------------
azul "8. Subindo"
# --------------------------------------------------------------------------
# A sobreposicao acrescenta `restart: unless-stopped`. Sem ela, um reboot do
# VPS derruba o sistema e ele nao volta.
docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d ui ui-proxy

echo "  aguardando a UI (o modelo leva ~30 s)..."
pronta=0
for _ in $(seq 1 90); do
    if curl -sf -m 3 http://127.0.0.1:8000/api/saude >/dev/null 2>&1; then pronta=1; break; fi
    sleep 2
done
[ "$pronta" = 1 ] || { erro "  a UI nao respondeu. Veja: docker compose logs ui"; exit 1; }

docker compose exec -T ui python -m anonimizador.web.modo

# --------------------------------------------------------------------------
azul "9. Prova de perimetro"
# --------------------------------------------------------------------------
docker compose exec -T ui python -m anonimizador.web.prova_rede

# --------------------------------------------------------------------------
azul "Pronto — e o que FALTA"
# --------------------------------------------------------------------------
cat <<'FIM'
  O sistema esta no ar em 127.0.0.1:8000, DENTRO do VPS. Ninguem de fora
  alcanca ainda, e isso e intencional.

  Falta o Passo D6 de docs/04-implantacao.md: proxy reverso no host, com TLS
  e limite por IP. Sem ele:

    * senha de login viajaria em HTTP claro, e o cookie de sessao junto;
    * nao ha limite por IP — e o D-04 e explicito: o encaminhador degrada
      previsivelmente sob pressao, ele nao se defende.

  Nao exponha a porta em 0.0.0.0. Quem fica de frente e o proxy.

  E leia o Passo D7 antes de abrir para terceiros: posse por documento ja
  existe, mas a trilha nao, e a RN-04 (AGPL do PyMuPDF) muda de forma quando
  o sistema vira servico acessivel pela rede.
FIM
