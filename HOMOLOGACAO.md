# Homologação — onde estamos e o que falta

Avaliação feita em **2026-09-24**, lendo todos os `goal-fase-*.md`, os
`docs/01..07`, `PROXIMOS-PASSOS.md`, `DEFEITOS.md` e o documento de ideia
original (hoje só no histórico do git), e medindo o sistema no ar. Responde
a duas perguntas: *quanto do escopo está pronto* e *já dá para homologar*.

Este arquivo é fotografia, não fila. A fila continua em `PROXIMOS-PASSOS.md`;
aqui fica o critério para abrir a homologação e o caminho até lá.

---

## 1. Quanto do escopo está pronto

A base é o escopo inicial (documento de ideia, Fases 0–4) com as adaptações
registradas nos goals: cofre descartado (2B), token sem cofre acrescentado
(2A), LLM externa em vez de local (Fase 3, decisão de 2026-09-05), e a Fase 4
redefinida como identidade, inquilino e trilha.

**Os pesos são julgamento, não medição.** Servem para dar ordem de grandeza e
para mostrar onde está o que falta — não para acompanhar décimos.

| Frente | Peso | Feito | Situação |
|---|---:|---:|---|
| Detecção, tarja e conferência (Fase 0) | 20 | 95% | todos os gates batidos; resta o vazamento de `rh-028` |
| Tela de revisão (Fase 1) | 20 | 90% | tudo construído; o gate de usabilidade com pessoas nunca rodou (`registro.csv` só tem o cabeçalho) |
| Código no lugar do dado, PDF e texto (2A) | 10 | 100% | A1–A9 fechados |
| Cofre reversível (2B) | 0 | — | descartado por decisão; fora da conta |
| Análise por IA externa (Fase 3, Bloco 3) | 10 | 85% | funciona, envio real verificado; faltam retenção no OpenRouter e parecer jurídico |
| Login, inquilino e trilha (Fase 4) | 15 | ~10% | Postgres e migração existem; `app.py` não usa o banco; não há login |
| Conformidade e ida ao mercado | 15 | ~20% | abertos RN-03, RN-04, RN-05, RN-07 e a decisão de quem hospeda |
| Operação e empacotamento | 10 | ~50% | Docker e air-gap prontos; faltam lote, TLS, instalador, atualização |

- **Produto comercial completo** (planos PF e Empresa): **~65%**.
- **Produto de uma pessoa, numa máquina** — o que se homologa hoje: **~92%**.

Fora da conta, por não terem sido iniciados nem decididos como obrigatórios:
Conexões com nuvem e copiloto local (Fase 3, Blocos 1 e 2).

---

## 2. O que foi verificado em 2026-09-24

- Suíte completa (rápidos + lentos) verde.
- `prova_rede` no `ui`: TCP, DNS e subprocesso bloqueados.
  `prova_isolamento` no `analise`: nenhum documento em claro alcançável.
- **Documento de 102 páginas** (sintético, 34 documentos do corpus
  concatenados). Até aqui o maior documento medido tinha 3 páginas (RNF-08).

  | Etapa | Tempo |
  |---|---:|
  | envio + detecção (1.713 trechos) | 69–74 s |
  | pré-verificação | 47 s |
  | aprovação (redação + verificação) | 45 s |
  | página renderizada | 0,09 s |

  O `ui` ficou em 3,1 GB de memória. A verificação **reprovou** o documento
  com 47 ocorrências (lorem ipsum e sobrenomes soltos que se repetem entre os
  documentos concatenados) e recusou o download — comportamento correto.
  Consequência prática: em documento longo, o normal é algumas rodadas de
  "substituir todas as ocorrências", cada uma com ~45 s de pré-verificação.

- **Não verificado nesta avaliação:** `make eval` (os números citados são do
  `eval/report.md` de 2026-09-23), o envio real à IA, a tela no navegador e
  carga concorrente além de uma sonda de saúde.

---

## 3. Achados, e o que já foi feito com eles

1. **O envio de um documento travava o servidor para todo mundo.** ✅
   Corrigido em 2026-09-24. `criar_doc` era `async def` e rodava a detecção
   no laço de eventos: durante os 69 s do documento de 102 páginas,
   `/api/saude` ficou 60 s sem resposta. Agora a rota roda no pool de threads,
   e toda detecção passa por `app.detectar`, sob uma trava — uma detecção por
   vez, porque nem o Presidio nem o pipeline do transformers se declaram
   seguros para chamada concorrente. Remedido no mesmo documento: pior
   resposta da sonda caiu de 60 s para 0,47 s. `tests/test_envio_nao_trava.py`
   reprova se a rota voltar a bloquear (conferido: com `async def`, reprova).
2. **Documentação com números velhos.** ✅ README (recall de 92,5% e "um terço
   de falso positivo", quando o eval atual mede 99,9% e ~4%), `CLAUDE.md`
   (334 testes) e `docs/02-requisitos.md` (estados da Fase 0) atualizados.
3. **Ruído de fim de linha no `git status`.** ✅ `.gitattributes` com
   `* text=auto eol=lf`; o `git status` passou a mostrar só mudança real.
4. **`docs/04-implantacao.md`, "O que ainda não é produto", está defasado** —
   ainda recomenda fazer o cofre e diz que a análise por IA "falta tela".
   Pendente.

---

## 4. Veredito: pode homologar?

### Sim — homologação controlada

Nestas condições, e só nelas:

- [ ] **Uma pessoa por instância**, acessando por `127.0.0.1` na própria
      máquina. Não existe login: quem alcança a porta usa.
- [ ] Documento sintético, **ou** documento real **dentro do ambiente do
      cliente** (Passo 13 de `docs/04-implantacao.md`), revisado por alguém do
      cliente. Nunca documento de cliente no ambiente de desenvolvimento
      (invariante 11).
- [ ] **Análise por IA desligada** (`make ui`, não `make ui-llm`), ou usada só
      com documento sintético — enquanto os itens 2 e 3 de
      `PROXIMOS-PASSOS.md` estiverem abertos.
- [ ] PDF com texto selecionável. Digitalizado é recusado (não há OCR).
- [ ] Quem homologa lê a tabela "O que ele **não** faz" do `README.md` antes.
- [ ] A homologação **produz as medições que faltam**: o gate de usabilidade
      (`eval/gate-usabilidade-roteiro.md`, 3 a 5 pessoas que não conheçam os
      documentos) e a taxa de erro no domínio do cliente, aceita por escrito.

### Não — ainda não

| Cenário | O que bloqueia |
|---|---|
| Servidor compartilhado na rede (KVM, VM do cliente acessada por várias pessoas) | **falta só TLS** — login (Bloco 2) e posse por documento (Bloco 3) entregues em 2026-11-03/04; a trilha (Bloco 4) continua aberta |
| Documento real enviado à IA externa | retenção no OpenRouter (item 2) e parecer jurídico sobre o texto com código (item 3) |
| Instalar no ambiente do cliente sem consultar o jurídico | **leitura a confirmar com quem assina:** entregar a instalação a terceiro, mesmo para homologar, pode já contar como distribuição e disparar a AGPL do PyMuPDF (RN-04) |
| Entrega comercial | RN-04 e RN-05 |

---

## 5. Para onde vamos

**Feito para abrir a homologação controlada** (2026-09-24): achados 1, 2 e 3.

**Durante a homologação**
1. Medir o gate de usabilidade com pessoas reais.
2. Validação com documento real no ambiente do cliente, com a taxa de erro
   aceita por escrito.

**Em paralelo, e não é código**
3. Retenção no OpenRouter, fixada e verificada — `PROXIMOS-PASSOS.md` item 2.
4. Parecer jurídico sobre o texto com código — item 3.
5. RN-04 (PyMuPDF) e RN-05 (LeNER-Br).
6. Decidir quem hospeda o plano PF — `docs/07-modelo-de-produto.md` §2. É a
   decisão que define a forma da Fase 4.

**Depois — o maior bloco restante (~15 dos ~35 pontos que faltam)**
7. Fase 4: login, inquilino, posse de documento, TLS e trilha. É o que
   destrava a homologação multiusuário.
8. Qualidade da detecção: `rh-028`, eval em modo código, nome quebrado entre
   linhas — itens 4 a 7 de `PROXIMOS-PASSOS.md`.
9. Atualizar `docs/04-implantacao.md` (achado 4).
