# Ciclo de vida da Fase 0. Tudo roda dentro do container — nenhum alvo aqui
# instala ou executa Python no host.
#
# No Windows sem `make`, use ./run.ps1 <alvo>, que faz exatamente o mesmo.

COMPOSE := docker compose
GPU     := -f docker-compose.yml -f docker-compose.gpu.yml

.PHONY: help build test test-all corpus eval eval-fast diagnostico gate-usabilidade gate-usabilidade-apurar ui ui-down ui-proof ui-llm llm-proof db-upgrade db-revision db-shell offline-proof shell demo clean gpu-build gpu-eval

help:
	@echo ""
	@echo "  build          constroi a imagem (unica etapa com rede)"
	@echo "  test           testes rapidos (sem carregar modelos)"
	@echo "  test-all       todos os testes, inclusive os marcados slow"
	@echo "  corpus         gera 50 PDFs sinteticos + gabarito"
	@echo "  eval           avaliacao completa nas 3 configuracoes de NER"
	@echo "  eval-fast      avaliacao so com spaCy (iteracao rapida)"
	@echo "  diagnostico    por que PERSON vaza: nao detectado ou rotulo errado"
	@echo "  gate-usabilidade         monta a sessao de revisao com pessoas"
	@echo "  gate-usabilidade-apurar  le o registro.csv preenchido"
	@echo "  ui             sobe a interface de revisao em http://127.0.0.1:8000"
	@echo "  ui-down        derruba a interface"
	@echo "  ui-proof       prova que a UI responde E nao tem egress"
	@echo "  ui-llm         sobe a UI + o servico de analise por LLM externa"
	@echo "  llm-proof      prova que o ui segue sem egress e que o analise nao ve o original"
	@echo "  db-upgrade     aplica as migracoes do banco de identidade"
	@echo "  db-revision    gera migracao nova: make db-revision M=\"descricao\""
	@echo "  db-shell       psql no banco de identidade"
	@echo "  offline-proof  prova que o pipeline roda sem rede"
	@echo "  demo           redige um documento do corpus e mostra o resultado"
	@echo "  shell          shell interativo no container"
	@echo "  gpu-build      constroi a imagem com torch CUDA"
	@echo "  gpu-eval       avaliacao usando GPU"
	@echo "  ui-recarregar  recarrega a UI depois de qualquer alteracao"
	@echo "  usuario        cria usuario para o modo com login"
	@echo "  tunel          expoe a UI por um tunel temporario, para demonstrar"
	@echo "  clean          remove saidas geradas"
	@echo ""

build:
	$(COMPOSE) build

test:
	$(COMPOSE) run --rm test -q -m "not slow"

test-all:
	$(COMPOSE) run --rm test -q

corpus:
	$(COMPOSE) run --rm corpus

eval:
	$(COMPOSE) run --rm eval

eval-fast:
	$(COMPOSE) run --rm cli eval --ner spacy

diagnostico:
	$(COMPOSE) run --rm diagnostico

# Nao mede sozinho: prepara a medicao com pessoas e apura o resultado.
# O roteiro da sessao esta em eval/gate-usabilidade-roteiro.md.
gate-usabilidade:
	$(COMPOSE) run --rm gate-usabilidade

gate-usabilidade-apurar:
	$(COMPOSE) run --rm gate-usabilidade --apurar /app/eval/gate-usabilidade/registro.csv

ui:
	$(COMPOSE) up -d ui ui-proxy
	@echo "aguardando a UI subir..."
	@for i in $$(seq 1 90); do curl -sf -m 3 http://127.0.0.1:8000/api/saude >/dev/null && break || sleep 2; done
	@echo ""
	@$(COMPOSE) exec -T ui python -m anonimizador.web.modo
	@echo "  interface em http://127.0.0.1:8000"
	@echo "  o modelo leva ~30 s para carregar; acompanhe com:"
	@echo "    $(COMPOSE) logs -f ui"
	@echo ""

# Cria o primeiro usuario para o modo com login. Roda pelo `cli-db`, que e o
# servico na rede `interna` — o `cli` tem `network_mode: none` e nao alcanca o
# Postgres. A senha e sorteada e aparece uma vez.
#
#   make usuario EMAIL=voce@exemplo.org INQUILINO="Seu Orgao"
# No Windows sem make, o mesmo alvo existe no run.ps1 e aceita as DUAS
# sintaxes — a de la e esta:
#   .\run.ps1 usuario -Email voce@exemplo.org -Inquilino "Seu Orgao"
usuario:
	$(COMPOSE) run --rm --entrypoint python cli-db -m anonimizador.cli criar-usuario --email "$(EMAIL)" --inquilino "$(INQUILINO)" --papel "$(or $(PAPEL),dono)"

# Recarrega a interface depois de QUALQUER alteracao. Um comando, sem decidir
# nada: recria os containers e espera a UI responder.
#
# Existe porque a regra de "o que exige reiniciar" nao deveria ser trabalho de
# quem usa:
#
#   .env ou docker-compose.yml   `up -d` ja recria (a config resolvida mudou)
#   codigo Python                precisa recriar — o uvicorn carrega os
#                                modulos na subida, e nao roda em --reload
#   CSS, JS, HTML                nada: os estaticos levam carimbo de versao,
#                                basta recarregar a pagina
#
# Na duvida, rode isto. O custo e os ~30 s do modelo carregando.
#
# Recria APENAS o `ui`. O `ui-proxy` fica de pe de proposito: e ele que
# segura a porta publicada, e recria-lo derrubaria um tunel do cloudflared
# apontado para 127.0.0.1:8000 — a URL que voce ja mandou para alguem.
# O proxy resolve `ui` por DNS a cada conexao, entao o container novo e
# encontrado sozinho; so as requisicoes em voo se perdem.
ui-recarregar:
	$(COMPOSE) up -d ui-proxy
	$(COMPOSE) up -d --force-recreate ui
	@echo "aguardando a UI subir..."
	@for i in $$(seq 1 90); do curl -sf -m 3 http://127.0.0.1:8000/api/saude >/dev/null && break || sleep 2; done
	@echo ""
	@$(COMPOSE) exec -T ui python -m anonimizador.web.modo

# Expoe a UI por um tunel temporario do Cloudflare, para demonstrar o sistema
# a alguem fora da sua rede. Nenhuma porta aberta no roteador, nenhuma conta:
# o `cloudflared` conecta de dentro para fora e devolve uma URL aleatoria que
# morre quando voce fecha.
#
# A TRAVA NAO E CERIMONIA: sem login, publicar a URL deixa qualquer um subir
# documento e qualquer um com um doc_id abrir o documento de outra pessoa.
tunel:
	@curl -sf -m 3 http://127.0.0.1:8000/api/saude >/dev/null || { echo "  a UI nao esta no ar. Suba com: make ui"; exit 1; }
	@$(COMPOSE) exec -T ui python -m anonimizador.web.modo --exigir-login
	@command -v cloudflared >/dev/null || { echo "  cloudflared nao encontrado: https://github.com/cloudflare/cloudflared"; exit 1; }
	cloudflared tunnel --url http://127.0.0.1:8000

ui-down:
	$(COMPOSE) down --remove-orphans

# Duas metades, e as duas precisam valer: a porta responde do host, e o
# container que processa documento nao alcanca o mundo.
ui-proof:
	$(COMPOSE) up -d ui ui-proxy
	@echo "aguardando a UI subir..."
	@for i in $$(seq 1 60); do 		curl -sf -m 3 http://127.0.0.1:8000/api/saude >/dev/null && break || sleep 2; 	done
	@echo ""
	@echo "--- metade 1: a porta responde do host ---"
	curl -sf -m 5 http://127.0.0.1:8000/api/saude
	@echo ""
	@echo "--- metade 2: o servico ui nao tem egress ---"
	$(COMPOSE) exec -T ui python -m anonimizador.web.prova_rede

# Sobe a UI com o servico de analise. A chave sai do .env.
ui-llm:
	$(COMPOSE) up -d ui ui-proxy analise
	@echo ""
	@echo "  interface : http://127.0.0.1:8000"
	@$(COMPOSE) exec -T analise python -c "import os;print('  chave     :', 'configurada' if os.getenv('OPENROUTER_API_KEY') else 'AUSENTE -- copie .env.example para .env')"

# A prova que importa depois de abrir a rede: o servico que processa documento
# continua sem egress, mesmo com o servico de analise no ar ao lado dele.
llm-proof:
	$(COMPOSE) up -d ui analise
	@echo ""
	@echo "--- 1: o servico ui NAO tem egress ---"
	$(COMPOSE) exec -T ui python -m anonimizador.web.prova_rede
	@echo ""
	@echo "--- 2: o servico analise NAO enxerga documento em claro ---"
	$(COMPOSE) exec -T analise python -m anonimizador.web.prova_isolamento
	@echo ""
	@echo "--- 3: o servico analise TEM egress (e o unico que precisa) ---"
	$(COMPOSE) exec -T analise python -c "import socket; socket.create_connection(('1.1.1.1',443),timeout=5).close(); print('  egress presente: ok')"

# Migracoes do banco de identidade. Esquema que muda sem historico e o que
# impede atualizar a instalacao de um cliente.
db-upgrade:
	$(COMPOSE) run --rm cli-db upgrade head

db-revision:
	@test -n "$(M)" || (echo 'uso: make db-revision M="descricao da mudanca"'; exit 1)
	$(COMPOSE) run --rm cli-db revision --autogenerate -m "$(M)"

db-shell:
	$(COMPOSE) exec postgres psql -U $${POSTGRES_USER:-anonimizador} -d $${POSTGRES_DB:-anonimizador}

offline-proof:
	$(COMPOSE) run --rm offline-proof

demo:
	$(COMPOSE) run --rm cli redact \
		--in /app/eval/datasets/contrato-000.pdf \
		--out /app/out/contrato-000.redigido.pdf

shell:
	$(COMPOSE) run --rm dev

gpu-build:
	$(COMPOSE) $(GPU) build

gpu-eval:
	$(COMPOSE) $(GPU) run --rm eval

clean:
	rm -rf out/* eval/datasets/* eval/report.md
