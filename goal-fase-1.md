# /goal — Fase 1: Interface de Revisão e Aprovação

> Sucede a `goal-fase-0.md`. A Fase 0 respondeu *"a stack local aguenta, e com
> que qualidade?"*. Esta fase responde *"uma pessoa consegue confiar no
> resultado e assinar embaixo?"* — que é uma pergunta de produto, não de
> modelo.

## Objetivo

Entregar uma interface web local onde o usuário:

1. Envia um PDF e vê **original e anonimizado lado a lado**, com as tarjas
   propostas destacadas;
2. **Corrige a proposta** antes de qualquer coisa ser gerada — desliga tarja
   errada, adiciona a que faltou;
3. **Aprova**, e só então o PDF redigido é produzido, verificado e liberado
   para download.

O produto da Fase 1 é o **fluxo de revisão humana**. A detecção já existe e
não muda de natureza aqui; o que muda é que ela deixa de ser um número num
relatório e passa a ser uma proposta que alguém aceita ou recusa, com
responsabilidade nominal.

---

## Decisões herdadas da Fase 0

### D1 — Configuração de NER: `bert-lenerbr`

Fecha a decisão em aberto da seção 4 de `docs/06-resultados-fase-0.md`, pela
**opção (b)**: o critério de recomendação passa a ser *taxa de documentos sem
vazamento*, não F1.

| | `bert-lenerbr` | `bertimbau-harem` |
|---|---:|---:|
| F1 PERSON relaxado (gate da Fase 0) | 0.787 | **0.854** |
| Recall PERSON | **0.925** | 0.903 |
| Precisão PERSON | 0.685 | **0.809** |
| **Documentos sem vazar PII** | **49/50** | 39/50 |

O `bertimbau-harem` vence o gate de F1 e perde onde o produto é julgado: 11
documentos vazando nome de pessoa contra 1.

**A interface é o que torna essa troca correta, e não apenas defensável.** Os
dois erros têm custo assimétrico para um revisor humano:

- Falso positivo (custo do `bert-lenerbr`) — uma tarja sobrando na tela. O
  revisor **vê** e descarta com um clique.
- Falso negativo (custo do `bertimbau-harem`) — uma tarja faltando. O revisor
  precisa notar uma **ausência**, em dezenas de páginas. É muito mais difícil.

Erro que o humano corrige barato vence erro que o humano precisa caçar.

> **Ressalva que precisa ficar registrada, porque é fácil concluir demais
> daqui.** Falso positivo não é risco de LGPD, mas *não* é gratuito. Cada tarja
> errada apaga texto que não era dado pessoal — e a Fase 0 usa redação
> verdadeira, então o texto some de vez, não fica ilegível. Um documento com
> tarja demais perde valor probatório e pode virar retrabalho manual. O que
> torna o custo aceitável é **exatamente** o botão de desligar a tarja antes de
> gerar: sem revisão humana, precisão baixa seria um problema sério, não um
> incômodo. É por isso que D1 e o fluxo de revisão são uma decisão só.

### D2 — Operadores disponíveis: apenas `tarja` e `manter`

`politica.validar_perfil` recusa `pseudonimo` e `mascara` porque a reescrita de
texto no PDF não existe. A interface **não pode oferecer** o que o executor não
faz — a trava existe para impedir o pior modo de falha do sistema: o usuário
pede pseudônimo, nada é aplicado, e o relatório diz que foi anonimizado.

Pseudonimização é Fase 2, com cofre.

### D3 — Causa dos vazamentos: medida, e não é limite de modelo

`make diagnostico` rodou sobre o corpus inteiro. O relatório sai em
`eval/diagnostico-person.md` (gerado, não versionado):

| Configuração | coberto | parcial | vazou — rótulo errado | vazou — **nenhum span** |
|---|---:|---:|---:|---:|
| `bert-lenerbr` | 601 | 108 | 1 | **0** |
| `bertimbau-harem` | 688 | 8 | 14 | **0** |

**Zero vazamentos por falta de detecção, nas duas configurações.** Em 710 e
710 entidades `PERSON`, nenhum nome passou despercebido. Todos os 15
vazamentos do corpus são o mesmo defeito: o modelo **viu** o nome e o
classificou como `LOCATION` (13 casos) ou `ORGANIZATION` (2), rótulos que
`ENTIDADES_REDIGIDAS` preserva de propósito.

A hipótese da seção 6 de `06-resultados-fase-0.md`, levantada a partir de
`Casa Grande`, vale para **100%** dos casos.

> Isso reclassifica o problema. Não é "o modelo é fraco em nome de pessoa" —
> é uma interação entre erro de classificação e política de preservação, num
> subconjunto reconhecível: sobrenomes que também são topônimo (`Casa Grande`,
> `da Mata`, `Câmara`, `da Rosa`, `Santos`, `da Cruz`, `Moura`, `Pinto`).
> Um reconhecedor de contexto de pessoa é o conserto certo, e é barato.

**Cobertura parcial.** O `bert-lenerbr` tem 108 casos contra 8, o que parecia
pesar contra D1. Não pesa: **106 dos 108 (98%) deixaram descoberto apenas um
tratamento** — `Sr.`, `Dr.`, `Dra.`, `Sra.`, `Srta.` — que o gerador de corpus
inclui no `value` do gabarito. Não expõe ninguém. Só 2 casos deixaram nome
descoberto. No `bertimbau-harem`, ao contrário, nenhum dos 8 é título, e 3
deixaram sobrenome legível (`Casa Grande`, `Rios`, `ri da Rosa`).

**D1 confirmada.** Somando vazamento total e exposição parcial real:
`bert-lenerbr` 3, `bertimbau-harem` 17.

### D4 — Próximo trabalho de detecção: reconhecedor de contexto de pessoa

Consequência direta de D3, e o item de maior retorno por esforço que restou na
detecção. Promover `LOCATION`/`ORGANIZATION` a `PERSON` quando houver âncora
de pessoa na vizinhança (`Sr.`, `Sra.`, `Dr.`, `Dra.`, `portador(a) do`,
`CPF` adjacente), reusando a máquina que `spans.desambiguar_por_ancora` já
tem para identificadores de 11 dígitos.

Vale a mesma disciplina de lá: **conservador**. Sem âncora, ou com âncoras
conflitantes, não decide. Trocar um rótulo errado determinístico por um
imprevisível seria pior — é o rótulo que decide o operador aplicado.

---

## Perguntas que esta fase precisa responder (decision gates)

- Um revisor consegue percorrer um documento de N páginas e **encontrar uma
  tarja faltante** em tempo aceitável? *(É o gate de usabilidade que justifica
  D1. Medir com documento sintético onde sabemos onde está a falha.)*
- ~~A porta da interface pode ser publicada **sem devolver egress ao
  container**?~~ **Respondida** — ver "Ambiente". Cinco configurações testadas;
  uma serve. `make ui-proof` verifica as duas metades.
- O PDF liberado para download passa em `verify()` em **100%** dos casos,
  incluindo os spans adicionados manualmente pelo usuário?
- O tempo entre "Aprovar" e "baixar" é aceitável para documento de dezenas de
  páginas? *(A detecção já rodou no upload; o que roda aqui é só redação +
  verificação.)*
- A renderização de página server-side aguenta documento longo sem estourar
  memória ou tempo de resposta?

---

## Escopo

**Dentro da Fase 1:**

- Upload de um PDF de texto selecionável, um por vez.
- Visualização lado a lado, com **rolagem sincronizada** entre os painéis.
- Retângulos de tarja sobrepostos ao painel direito, **clicáveis** para ligar
  e desligar individualmente.
- Painel de política: ligar/desligar por **entidade** (`PERSON`, `CPF`, …),
  usando `PerfilPolitica`. Só `tarja` e `manter` (D2).
- Inventário do documento: contagem por tipo de entidade.
- Campo "buscar termo → tarjar todas as ocorrências" — resolve o caso
  *"esse campo não foi anonimizado"* de forma exata e determinística.
- Botão **Aprovar** → `redact_document()` + `verify()` → download.
- **Gate de download:** o arquivo só é liberado se `verify().ok` for `True`.
  Falhou, a tela mostra a falha e não oferece o arquivo.
- Ciclo de vida explícito da sessão: apagar original, preview e redigido.

**Fora da Fase 1:**

- Processamento em lote / fila.
- Autenticação, contas, multiusuário, planos.
- Cofre reversível e pseudonimização (Fase 2).
- Copiloto LLM (Fase 3 — ver "Chat" abaixo; o caminho determinístico entra
  agora, a LLM não).
- OCR de PDF escaneado.
- Edição de qualquer coisa no documento que não seja tarja.

---

## O princípio que decide o resto do desenho

**O preview nunca é o entregável.**

A tela mostra uma projeção: imagem da página com retângulos desenhados por
cima. O arquivo que o usuário baixa vem de `redact_document()` +
`verify()` executados de verdade, no momento do "Aprovar".

Sem essa separação, a interface vira uma camada capaz de mentir sobre o que o
pipeline fez — o pior defeito possível num anonimizador, porque o erro é
invisível justamente para quem confiou na tela.

Corolário: o gate de vazamento do `run_eval.py` deixa de ser um teste de
laboratório e passa a ser **controle de produção**. É o mesmo `verify()`, com
os mesmos 10 vetores, decidindo se o botão de download existe.

### Por que retângulo interativo, e não dois PDFs

A alternativa mais simples seria gerar o PDF redigido no upload e mostrar dois
visualizadores. Foi descartada: com o PDF pronto, o revisor só pode aprovar ou
rejeitar o lote inteiro. Com retângulos sobrepostos ele **conserta**, e o
"processando" que antecede o download passa a ser trabalho real.

O backend para isso já existe: `layout.TextMap.rects_for(inicio, fim)` devolve
`(página, retângulo)` — exatamente o que o front-end precisa. O contrato sai
de graça.

---

## Ambiente: porta publicada vs. ausência de rede

A Fase 0 roda tudo com `network_mode: none`, que é a **prova executável** da
restrição de soberania — não uma promessa de configuração, uma ausência de
interface de rede.

Uma interface web precisa de porta publicada, e `network_mode: none` não
publica porta. Isso é um conflito real e é o item de maior risco desta fase.

### Resolvido em 2026-08-30, por medição

Cinco configurações foram testadas neste ambiente (Docker Desktop / WSL2). As
duas colunas precisam ser verdes ao mesmo tempo, e só a última consegue:

| Configuração | Porta responde do host | Egress bloqueado |
|---|---|---|
| `network_mode: none` | ❌ não publica porta | ✅ |
| rede `internal: true`, porta publicada | ❌ inalcançável | ✅ |
| bridge com `enable_ip_masquerade=false` | ✅ | ❌ **vazou** |
| sabotagem in-process do `socket` | ✅ | ⚠️ parcial |
| **`ui` em rede interna + `ui-proxy`** | ✅ | ✅ |

Dois resultados que contrariam a leitura ingênua da documentação, e por isso
foram medidos:

- **`enable_ip_masquerade=false` não bloqueia nada** no Docker Desktop. A VM
  do WSL2 faz o próprio NAT, e a opção de bridge do Docker não tem jurisdição
  sobre isso. TCP e DNS saíram normalmente.
- **A sabotagem in-process não sobrevive a `subprocess`.** Um `python -c`
  filho conectou em `1.1.1.1:443` com o módulo `socket` do pai sabotado. Ela
  bloqueia a pilha Python do processo, não o processo.

### O desenho adotado

O serviço `ui` — que faz detecção, redação, verificação e render — fica numa
rede `internal: true`. Sem rota para fora, garantido pelo kernel, subprocesso
incluído. Ele é inalcançável do host de propósito.

O `ui-proxy` (`src/anonimizador/web/forward.py`) é o **único** processo com
saída de rede. Ele copia bytes entre a porta publicada e o `ui`. Não interpreta
HTTP, não faz parsing de PDF, não importa nada além da biblioteca padrão, não
escreve em disco.

O que isso compra: **toda a pilha de ML fica sem rede.** torch, transformers,
presidio, huggingface, PyMuPDF — a superfície de dependência inteira, que é
onde o risco de telemetria de fato mora — roda sob a garantia forte.

> **Limite honesto.** Os bytes do documento passam pelo `ui-proxy`, e ele tem
> saída de rede. A garantia não é "o documento nunca toca um processo com
> rede"; é "o único processo com rede é auditável em cinco minutos e não tem
> árvore de dependências". Um atacante com execução de código ali exfiltra. O
> que o desenho elimina é o vetor realista — uma dependência da pilha de ML
> telefonando para casa — não um adversário com RCE.

A porta é publicada só em `127.0.0.1`: não escuta em interface externa da
máquina.

Critério de aceite, atendido: `make ui-proof` verifica as **duas** metades — a
porta responde do host, e `anonimizador.web.prova_rede`, rodando dentro do
`ui`, confirma que TCP, DNS e subprocesso não saem. Sai com código 1 se
qualquer caminho estiver aberto.

O resto do ambiente é herdado sem mudança: `python:3.12-slim`, modelos gravados
na imagem, nada instalado no host.

---

## Stack técnica

- **FastAPI + Uvicorn** — API e servidor de arquivos estáticos.
- **HTML + JavaScript sem build step.** Sem npm no runtime, sem framework
  compilado. Um `Dockerfile` que precisa de Node só para a UI é atrito
  desproporcional para esta fase.
- **Sem CDN. Nenhuma.** O container não tem rede; `pdf.js` vindo de CDN
  simplesmente não carrega. As páginas são renderizadas **server-side** como
  PNG via `page.get_pixmap()` (PyMuPDF, já é dependência) e os retângulos são
  desenhados em `<canvas>` por cima. Zero dependência nova no navegador.
- **Reaproveitado sem alteração:** `DetectionPipeline`, `layout.TextMap`,
  `pdf_redactor.redact_document`, `verifier.verify`, `politica.PerfilPolitica`.

Dependências novas: `fastapi`, `uvicorn`, `python-multipart`. Só isso.

---

## API

| Rota | O que faz |
|---|---|
| `POST /doc` | upload → `DetectionPipeline` → `{doc_id, paginas, spans[], inventario}` |
| `GET /doc/{id}/pagina/{n}.png` | página renderizada, com `?escala=` |
| `PATCH /doc/{id}/spans` | liga/desliga span; adiciona por termo |
| `PUT /doc/{id}/perfil` | operador por entidade, validado por `validar_perfil` |
| `POST /doc/{id}/aprovar` | `redact_document` + `verify` → relatório |
| `GET /doc/{id}/download` | **409** se não aprovado ou se `verify` falhou |
| `DELETE /doc/{id}` | apaga original, preview e redigido |

Formato de span na API:

```json
{ "id": "s12", "entity": "PERSON", "score": 0.91, "valor": "Ana Souza",
  "ativo": true, "origem": "detector",
  "rects": [{"pagina": 0, "x0": 72.0, "y0": 310.4, "x1": 158.2, "y1": 322.0}] }
```

`origem` distingue `detector` de `usuario` — necessário para auditoria e para
o relatório de conformidade não afirmar que o pipeline achou o que a pessoa
apontou.

---

## Ciclo de vida dos dados

LGPD se aplica à ferramenta, não só ao documento dela.

- Original em claro fica em disco durante a sessão. Diretório por sessão sob
  `/app/out`, TTL curto, `DELETE` explícito ao fim, varredura de expirados no
  start.
- **Nenhum log com valor de PII.** Corrigir o que já existe:
  `pdf_redactor.py` chama `logger.warning("span sem retângulo: %r", valor)` —
  loga o valor. Em PoC é aceitável; num serviço é uma cópia de dado pessoal
  fora do PDF saneado, com retenção própria e sem verificação. Trocar por
  offset + hash.
- O valor da PII **vai** para o navegador — é inevitável, o revisor precisa ver
  o que está sendo tarjado. Fica no browser do próprio dono do documento e não
  é persistido em nenhum outro lugar.

---

## Chat: o que entra agora e o que não entra

O pedido de origem: *"o campo tal não foi anonimizado, preciso que anonimize-o"*,
escrito num chatbox.

### O que entra na Fase 1 — caminho determinístico, sem LLM

O usuário cita o valor; o backend acha **todas** as ocorrências em
`TextMap.text`, cria os spans com `origem: "usuario"`, e mostra para
confirmação. Exato, instantâneo, auditável, risco zero.

É o campo "buscar termo" da lista de escopo, com apresentação de conversa. Ele
resolve a maior parte do caso real e **não precisa de modelo nenhum**.

### O que não entra — e a razão exata

`docs/05-politica-llm.md` impõe **R2: a LLM nunca recebe valor de PII e nunca
escreve um**. No exemplo acima quem coloca PII no prompt é o próprio usuário,
ao digitar o nome que faltou. Mandar essa mensagem para a LLM viola R2 pela
porta da frente — e viola com dado que o usuário forneceu voluntariamente, o
que não o torna menos PII num log.

O desenho que respeita R2, para a **Fase 3**:

```
mensagem do usuário
      │
      ├─ roda o DETECTOR na própria mensagem
      │
      ├─ contém valor de PII, ou casa com texto do documento?
      │      └─→ CAMINHO 1: busca literal. A LLM não é chamada.
      │
      └─ fala de CLASSES ("anonimize também os endereços",
         "mantenha as datas do ato")
             └─→ CAMINHO 2: LLM traduz intenção → PerfilPolitica
                 (recebe só a frase + a lista de entidades)
```

O caminho 2 é exatamente a seção 2.1 da política, já autorizada. A triagem é o
próprio detector: o mesmo componente que protege o documento protege o prompt,
e a garantia vira inspeção de código em vez de auditoria de log.

Em ambos, R3 vale — volta como **proposta pendente**, nunca como estado
aplicado.

**O que não sabemos, registrado para não virar suposição:**

- Não existe LLM alguma no projeto. `requirements.txt` não tem Ollama, cliente
  nem modelo. Nada disso foi prototipado.
- Nenhum modelo local foi escolhido nem medido. Se um modelo pequeno o
  bastante para o container faz intenção→JSON em português com confiabilidade
  aceitável é plausível, **não medido**.
- Latência não medida. A LLM disputaria CPU com o transformer de NER no mesmo
  container, que já gasta 0.53 s/página.
- Ollama fala por HTTP em `localhost`, o que *deveria* funcionar sob
  `network_mode: none`, mas **não foi testado**.

---

## Limitações do que a redação faz hoje, a expor na interface

Não são defeitos novos; são propriedades da Fase 0 que a UI passa a ter
obrigação de comunicar, porque agora existe um humano assinando embaixo.

| Fato | Por que o usuário precisa saber |
|---|---|
| `scrub(remove_links=True)` remove **todos** os hyperlinks | inclusive os inofensivos |
| `set_toc([])` apaga o sumário inteiro | não só entradas com PII |
| Metadados são zerados por completo | autor, título, data de criação, produtor |
| Redação **invalida assinatura digital** | documento de órgão público costuma vir assinado (ICP-Brasil); é matemático, não tem contorno. **Não testado, não está no corpus.** |
| PDF escaneado não é suportado | não há texto para remover; a tarja seria retângulo sobre pixels |
| Layout, paginação e fontes ficam intactos | não há reflow — a estrutura do original é preservada |

Os três primeiros são refináveis (remover só o que contém PII), ao custo de
trocar uma regra simples e verificável por uma condicional. Fica registrado
como opção, não como tarefa.

---

## Tarefas / entregáveis

**Bloco 0 — Rede e fundação** *(bloqueia todo o resto)*
- [x] Resolver a publicação de porta **sem egress**. Cinco configurações
      testadas; a tabela em "Ambiente" registra o resultado de cada uma.
- [x] `make ui-proof`: porta responde do host **e**
      `anonimizador.web.prova_rede` confirma zero egress de dentro do `ui`.
- [x] Serviços `ui` e `ui-proxy` no compose, redes `interna`/`externa`,
      alvos no `Makefile` e no `run.ps1`.
- [x] `fastapi`, `uvicorn`, `python-multipart`, `httpx` no `requirements.txt`.

**Bloco 1 — Diagnóstico e confirmação de D1**
- [x] `eval/diagnostico_person.py` + alvo `make diagnostico`.
- [ ] Rodar, ler, e confirmar ou revisar **D1** com os números.
- [ ] Se "rótulo errado" for a causa dominante: reconhecedor de contexto de
      pessoa (`Sr.`, `Sra.`, `Dr.`, `portador(a) do`, proximidade de CPF),
      com testes, e re-rodar o `eval`.

**Bloco 2 — API**
- [x] Sessão de documento com TTL, `DELETE` e varredura de órfãs na subida.
- [x] `POST /api/doc`: upload, detecção, inventário, spans com retângulos.
- [x] Render de página como PNG (`Cache-Control: private`).
- [x] `PATCH /api/doc/{id}/span` e `PUT /api/doc/{id}/perfil`.
- [x] `POST /api/doc/{id}/aprovar`: redação + verificação, relatório estruturado.
- [x] `GET /api/doc/{id}/download` com o gate de `verify().ok`.
- [x] Qualquer edição invalida a aprovação e apaga o PDF já gerado.
- [x] Nenhum valor de PII em log no módulo web — só id de span e contagem.
- [ ] Corrigir `pdf_redactor.logger.warning("span sem retângulo: %r", valor)`,
      que ainda loga o valor. Herdado da Fase 0.

**Bloco 3 — Interface**
- [x] Layout lado a lado com rolagem sincronizada.
- [x] Retângulos clicáveis, posicionados em % da página (independem de zoom,
      tamanho da janela e de a imagem ter carregado).
- [x] Painel de política e inventário, com contagem `tarjados/total`.
- [x] Campo de busca → tarjar todas as ocorrências.
- [x] Estado de "processando" real durante a aprovação.
- [x] Tela de resultado da verificação, incluindo o caminho de falha —
      quando reprova, **não existe link de download**.
- [x] Aviso visível das limitações (links, sumário, metadados, assinatura).
- [ ] Medir o gate de usabilidade: um revisor acha a tarja faltante?

**Bloco 4 — Testes** — `tests/test_web.py`, 23 testes
- [x] `download` recusa antes de aprovar (409) e depois de qualquer edição.
- [x] O perfil recusa `pseudonimo`, `mascara` e entidade desconhecida (422).
- [x] Span adicionado pelo usuário é sempre tarjado, mesmo com perfil
      restritivo, e entra na verificação.
- [x] Verificação **independente**: o PDF baixado é reaberto e nenhum valor
      do gabarito sobrevive; metadados zerados.
- [x] PDF escaneado (sem texto extraível) falha alto em vez de mostrar tela
      vazia.
- [x] Fluxo completo sobre um documento do corpus, fora de teste:
      `contrato-000`, 78 spans, 47 tarjas, 0 vazamentos em 10 vetores.

---

## Dados de teste

Vale integralmente a regra da Fase 0: **exclusivamente dados sintéticos**. O
corpus de 50 documentos já existe e serve. Nenhum documento real de cliente
entra em ambiente de dev ou demo — validação com documento real, se houver, é
etapa separada, no ambiente controlado do cliente.

---

## Critérios de aceite

- `make offline-proof` verde **com a UI no ar**, provando ausência de egress.
- Nenhum PDF é liberado para download sem `verify().ok == True`. Testado,
  inclusive o caminho de falha.
- Spans adicionados pelo usuário entram na verificação como qualquer outro.
- A interface não oferece `pseudonimo` nem `mascara`, e a API os recusa.
- Nenhum valor de PII aparece em log.
- Sessão apagável, e apagada — original incluído.
- Um documento do corpus percorre o fluxo inteiro: upload → revisão → correção
  manual → aprovar → verificar → baixar.
- **D1 confirmada ou revisada** com os números do `make diagnostico`.

---

## Fora de escopo desta fase — não implementar agora

Autenticação, contas, lote, fila, cofre reversível, pseudonimização, OCR,
copiloto LLM, hospedagem de produção, precificação. Cada um desses tem fase
própria; misturar aqui atrasa a única pergunta que a Fase 1 existe para
responder — se uma pessoa consegue revisar, corrigir e assinar embaixo.
