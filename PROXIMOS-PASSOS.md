# Próximos passos

Estado em **2026-09-23**, depois de três commits do dia: `a1e4e7a` (CNH e PIS
deixam de roubar o rótulo do CPF), `785b42d` (nome e data deixam de sair em
pedaços da detecção) e `aa2ee5c` (modo código sem reprovação + tela de IA).

Este arquivo é a fila, em ordem. Cada item diz **por que** está nessa
posição e **como se sabe que terminou** — sem o segundo, um item vira
"melhorar X" e nunca fecha. O detalhe mora na fonte indicada; aqui fica só o
suficiente para escolher o próximo.

Quando um item fechar, sai daqui e o registro vai para onde ele pertence
(`DEFEITOS.md`, o goal da fase, o `git log`). Este arquivo não é histórico.

---

## O que bloqueia usar com documento real

O fluxo de ponta a ponta existe: revisar → PDF (tarja ou código) → texto com
código → envio a modelo externo. Os três itens abaixo são o que falta para ele
poder receber um documento que não seja sintético.

### 1. Um envio real ao modelo externo, com documento sintético

**Por quê.** É o único caminho do sistema que faz conteúdo sair da máquina, e
**nunca rodou de ponta a ponta**. Os testes usam um dublê do serviço
`analise`; a tela foi vista, mas sem envio. A chave do OpenRouter entrou no
`.env` em 2026-09-23.

**Terminou quando:** com um PDF de `eval/datasets/`, pela tela, (a) a resposta
aparece e usa os códigos; (b) `envios` na sessão registra modelo, caracteres e
tokens, e **nada** do conteúdo; (c) o log do `analise` também não tem
conteúdo; (d) um documento com um nome deliberadamente não marcado é
**recusado** pela re-detecção, com o cartão "substituir todas as
ocorrências", e nada sai. Custa crédito — poucos centavos por envio.

**Fonte:** `goal-fase-3.md` §2.9.

### 2. Retenção no OpenRouter, fixada e verificada

**Por quê.** Alguns provedores treinam com o que recebem. É configuração da
conta (`openrouter.ai/settings/privacy`), não deste código — e por isso mesmo
ninguém a verifica por padrão. A tela diz ao usuário que a ferramenta **não**
confere isso, o que é verdade e precisa continuar sendo dito até o item fechar.

**Terminou quando:** a configuração da conta usada está registrada (qual
política, quais provedores permitidos, data da verificação) em
`docs/05-politica-llm.md` §2.6, e o modelo padrão (`OPENROUTER_MODEL`) é de um
provedor que a respeita.

**Fonte:** `goal-fase-3.md` §2.9 e Bloco 3.

### 3. Confirmação jurídica do que o código no lugar do nome **é**

**Por quê.** O `README.md` diz que as duas saídas estão "no mesmo patamar de
proteção" e que "nem nós conseguimos voltar ao original". Sobre a ferramenta,
é verdade: o código é sorteado e nenhum mapa é guardado. Mas **quem enviou tem
o original**, e o original é exatamente a "informação adicional mantida
separadamente" que caracteriza dado pseudonimizado — que continua sendo dado
pessoal. Para quem guarda o original, o arquivo com código provavelmente
**não** sai do escopo da LGPD. Para um terceiro que só recebe o arquivo, a
leitura pode ser outra. Levantado pelo usuário em 2026-09-23.

A regra do `CLAUDE.md` §6 se aplica inteira: a citação de artigo aqui é de
memória (RN-07) e o enquadramento é do jurídico do cliente, não deste código.

**Terminou quando:** há resposta por escrito de quem assina juridicamente
sobre (a) o status do PDF com código e do texto com código, para quem guarda o
original e para quem recebe; (b) o texto do aviso de envio na tela; (c) a
frase comercial "o documento sai, mas pseudonimizado". E o `README.md`, a tela
(`index.html`, bloco `bloco-modo`) e `test_a_tela_afirma_a_irreversibilidade…`
foram ajustados ao que a resposta disser.

**Fonte:** `CLAUDE.md` §6, `goal-fase-2.md` §3, `goal-fase-3.md` §2.

---

## Qualidade da detecção

Números de referência (`make eval`, 2026-09-23, `bert-lenerbr`, padrão da UI):
PERSON F1 relaxado **0,979**, recall **0,999**; DATE_TIME **1,000**; **49/50**
documentos sem vazamento.

### 4. O vazamento que sobrou: `rh-028`, "Bento da Mata"

**Por quê.** É o único documento que ainda vaza com o detector padrão, e ele
já vazava antes das correções do dia — então a causa é outra. Com envio
externo, cada vazamento é incidente com terceiro. Com `bertimbau-harem` são 8
documentos (`contrato-000`, `rh-013`, `rh-028`, `contrato-030`, `rh-033`,
`rh-043`, `oficio-044`, `oficio-049`).

**Terminou quando:** a causa está escrita (não detectado? rótulo errado?
perdeu disputa de sobreposição?) — `make diagnostico` responde as duas
primeiras — e, se for corrigível, o eval mostra 50/50 sem nenhum outro número
piorar nas duas direções.

**Fonte:** `eval/report.md`, "Verificação pós-redação".

### 5. O eval não mede o modo código

**Por quê.** Toda a medição roda em tarja. Os defeitos de 2026-09-23 (palavra
em pedaços, token que não cabia) existiam havia semanas e só apareceram porque
o usuário usou a tela em modo código. Nada impede que o próximo apareça do
mesmo jeito.

**Terminou quando:** `run_eval.py` roda também em modo código e o relatório
traz, por configuração: trechos em código, trechos em tarja por falta de
espaço (por entidade), tokens distintos por documento, e a mesma verificação
pós-redação — com o vetor de presença de token.

### 6. Nome quebrado entre linhas recebe dois códigos

**Por quê.** Custo aceito da correção de `785b42d`: o span do NER é cortado na
quebra de linha para não atravessar até o nome seguinte. Um nome que quebra
num parágrafo justificado vira dois trechos — em tarja não se vê; em código,
lê-se como duas pessoas. **Não vaza.** Não foi medido quantas vezes acontece.

**Terminou quando:** está medido no corpus. Se for frequente, a correção
provável é reunir as partes quando o span bruto do NER era um só **e** nenhuma
delas perde disputa de sobreposição — a informação existe no momento do corte
(`TransformersNerRecognizer._cortar_na_quebra`).

### 7. Palavras de lorem ipsum marcadas como pessoa

**Por quê.** Após as correções, o NER marca "Dolores" e "Eligendi" como
PERSON em alguns documentos, e as outras ocorrências aparecem como "resíduo"
(47/50 sem resíduo, era 50/50). Não é dado pessoal — é o gerador de corpus que
usa lorem ipsum —, mas mascara resíduo de verdade no relatório.

**Terminou quando:** decidido entre trocar o texto de preenchimento do
`generate_corpus.py` por português plausível (muda o corpus; precisa refazer
todas as linhas de base) ou registrar isso como ruído conhecido no relatório.

---

## Dívidas pequenas, que custam barato agora e caro depois

### 8. A taxa do aviso de envio é número escrito à mão

`NOMES_ESCAPADOS_EM_50` em `web/static/app.js` repete o que o eval mediu. No
dia em que o detector mudar e ninguém lembrar, a tela afirma uma taxa que já
não é a do sistema. **Terminou quando** o número vier do último `eval/report.md`
(servido pela API) ou quando um teste reprovar se os dois divergirem.

### 9. Ninguém roda a suíte lenta

Sobra do D-03: `make test` desmarca os testes `slow` de propósito, e por isso
eles ficaram vermelhos por meses sem ninguém ver. **Terminou quando** alguma
coisa rodar `make test-all` sozinha — um hook de pre-push, um job agendado — e
reclamar alto.

### 10. Ruído de fim de linha no `git status`

~45 arquivos aparecem como modificados só porque estão em CRLF no disco e LF
no repositório. Esconde mudança de verdade e obriga a filtrar a cada commit.
**Terminou quando** houver `.gitattributes` com `* text=auto eol=lf` (ou a
decisão contrária registrada) e o `git status` limpo mostrar só mudança real.

### 11. Docstring velha em `Sessao.gerar_texto_pseudonimizado`

Diz que `validar_perfil` "continua recusando `pseudonimo`" — deixou de ser
verdade em 2026-09-16. Um comentário errado aqui é o tipo de coisa que o
`CLAUDE.md` §5 manda ler antes de mudar a linha.

---

## O que já estava na fila e continua

- **Gate de usabilidade da Fase 1** com pessoas reais — `goal-fase-1.md`,
  `eval/gate-usabilidade/`.
- **Licenças antes de qualquer entrega comercial**: PyMuPDF AGPL-3.0 ou
  licença Artifex (RN-04) e o checkpoint LeNER-Br sem licença declarada
  (RN-05) — `docs/02-requisitos.md`.
- **Fase 3, Blocos 0–2**: conexões com nuvem e copiloto local —
  `goal-fase-3.md` §4.
- **Fase 4**: identidade, inquilino e trilha — `goal-fase-4.md`.
- **Fase 2B (cofre)** segue estacionada por decisão de 2026-09-05; só volta se
  a reversibilidade virar requisito de cliente.
