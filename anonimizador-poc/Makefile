# Ciclo de vida da Fase 0. Tudo roda dentro do container — nenhum alvo aqui
# instala ou executa Python no host.
#
# No Windows sem `make`, use ./run.ps1 <alvo>, que faz exatamente o mesmo.

COMPOSE := docker compose
GPU     := -f docker-compose.yml -f docker-compose.gpu.yml

.PHONY: help build test test-all corpus eval eval-fast diagnostico ui ui-down ui-proof offline-proof shell demo clean gpu-build gpu-eval

help:
	@echo ""
	@echo "  build          constroi a imagem (unica etapa com rede)"
	@echo "  test           testes rapidos (sem carregar modelos)"
	@echo "  test-all       todos os testes, inclusive os marcados slow"
	@echo "  corpus         gera 50 PDFs sinteticos + gabarito"
	@echo "  eval           avaliacao completa nas 3 configuracoes de NER"
	@echo "  eval-fast      avaliacao so com spaCy (iteracao rapida)"
	@echo "  diagnostico    por que PERSON vaza: nao detectado ou rotulo errado"
	@echo "  ui             sobe a interface de revisao em http://127.0.0.1:8000"
	@echo "  ui-down        derruba a interface"
	@echo "  ui-proof       prova que a UI responde E nao tem egress"
	@echo "  offline-proof  prova que o pipeline roda sem rede"
	@echo "  demo           redige um documento do corpus e mostra o resultado"
	@echo "  shell          shell interativo no container"
	@echo "  gpu-build      constroi a imagem com torch CUDA"
	@echo "  gpu-eval       avaliacao usando GPU"
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

ui:
	$(COMPOSE) up -d ui ui-proxy
	@echo ""
	@echo "  interface em http://127.0.0.1:8000"
	@echo "  o modelo leva ~30 s para carregar; acompanhe com:"
	@echo "    $(COMPOSE) logs -f ui"
	@echo ""

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
