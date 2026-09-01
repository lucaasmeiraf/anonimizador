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

#### D1 confirmada em 2026-08-31, com `make diagnostico` re-executado

O `eval/diagnostico-person.md` que estava em disco era de uma **geração
anterior do corpus**: 9 dos 14 nomes que ele listava não existem mais nos PDFs
de `eval/datasets`. A confirmação foi refeita sobre o corpus atual.

> **Cuidado de reprodutibilidade que isto expôs.** Nem o corpus nem os
> relatórios de avaliação são versionados — os dois são artefatos locais.
>
> `make corpus` **é** determinístico: a semente é fixa (`--seed`, padrão
> `20260829`). O que muda os nomes é alterar o **gerador**, porque cada bloco
> novo consome sorteios e desloca toda a sequência seguinte — e foi o que
> aconteceu quando `generate_corpus.py` ganhou os blocos de tabela e de duas
> colunas. Mesma semente, gerador diferente, nomes diferentes.
>
> O efeito prático é o mesmo: um relatório em disco não descreve
> necessariamente o corpus em disco. Toda leitura de número deve vir de uma
> execução feita **depois** da geração do corpus que ela descreve, e é por
> isso que a confirmação de D1 foi refeita em vez de lida do arquivo.

| Configuração | coberto | coberto em parte | vazou — rótulo errado | vazou — nenhum span |
|---|---:|---:|---:|---:|
| `bert-lenerbr` | 636 | 124 | **1** | **0** |
| `bertimbau-harem` | 741 | 8 | 11 | 1 |

**D1 se mantém, e por uma margem maior do que a registrada acima:**
`bert-lenerbr` vaza `PERSON` em **1 documento**, `bertimbau-harem` em **9**.
O critério continua sendo taxa de documento sem vazamento, e ele continua
apontando para o mesmo lado.

Uma correção ao que `docs/06-resultados-fase-0.md` afirmava: *"em 710
entidades por configuração, nenhum nome passou despercebido"* deixou de valer
para o `bertimbau-harem`, que no corpus atual tem 1 caso sem span algum
(`rh-043`, 'Mateus Câmara'). Para o `bert-lenerbr` a afirmação continua exata:
**0 nomes não detectados**, e o único vazamento é de rótulo.

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

### D4 — ~~Reconhecedor de contexto de pessoa~~ → **revisada em 2026-08-31**

**A proposta original está registrada abaixo, riscada, porque a medição a
refutou.** Ela dizia: promover `LOCATION`/`ORGANIZATION` a `PERSON` quando
houvesse âncora de pessoa na vizinhança (`Sr.`, `Sra.`, `Dr.`, `Dra.`,
`portador(a) do`, `CPF` adjacente), reusando a máquina de
`spans.desambiguar_por_ancora`.

Antes de implementar, medimos quantos dos vazamentos reais têm essa âncora nos
45 caracteres anteriores. O resultado, sobre os 12 casos das duas
configurações no corpus atual:

| | Casos |
|---|---:|
| com âncora linguística de pessoa | **0** |
| âncora cruzada (pertencia a outra linha da tabela) | 1 |
| cabeçalho de coluna (`Nome | CPF | Nascimento`) | 1 |
| sem âncora nenhuma | 10 |

**Todos os 12 estão em célula de tabela**, precedidos de CPF, telefone ou data
de nascimento — não de título. Exemplos, do `rh-028` e do `contrato-030`:

```
  Tel. (85) 94446-5528
  Bento da Mata          <- vaza, rotulado LOCATION
  Laís Rios

  682.960.263-76
  14/01/1977
  Dom da Costa           <- vaza, rotulado LOCATION
```

Isso não é azar de amostra, é o mecanismo: **o NER erra exatamente onde não há
contexto, e onde não há contexto também não há âncora para uma regra usar.**
Um reconhecedor de âncora só acrescentaria cobertura onde o NER já acerta — em
prosa, que responde por 636 dos 761 `PERSON` cobertos e por nenhum vazamento.

Decisão: **não implementar o reconhecedor de âncora.** O ganho medido seria
0 de 12, contra risco real de falso positivo em construções como
`Sr. Presidente` e `Dr. Hospital Municipal`.

O conserto certo é **estrutural**, não linguístico: identificar a coluna da
tabela pelo cabeçalho (`Nome`, `Interessado`, `Servidor`, `Colaborador`,
`Paciente`) e marcar as células daquela coluna como `PERSON`, usando a
geometria que o `TextMap` já carrega. Fica registrado como trabalho de fase
própria, com dois riscos a enfrentar no escopo dele: ajustar-se demais ao
gerador do corpus sintético, e o custo de tocar `layout.py`, que é o módulo de
maior risco técnico do sistema.

Vale a disciplina que a proposta original já trazia, e que segue valendo para
o substituto: **conservador**. Sem sinal claro, não decide. Trocar um rótulo
errado determinístico por um imprevisível seria pior — é o rótulo que decide o
operador aplicado.

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

- Reversibilidade / pseudonimização — `goal-fase-2.md`, que também explica por
  que o documento produzido hoje **não** tem como ser desanonimizado.
- Conexões com nuvem e análise por LLM externa — `goal-fase-3.md`, que trata
  as duas juntas porque as duas pedem para abrir a rede.
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

## Defeito conhecido, não resolvido — estouro de 512 tokens no NER

Observado em 2026-08-31, durante a colheita do gate de usabilidade: **1
documento em 300** produziu

```
RuntimeError: The size of tensor a (522) must match the size of tensor b (512)
```

vindo de `modeling_bert.py`. É o limite de 512 posições do BERT sendo
ultrapassado por um bloco de 522 tokens.

O que está estabelecido:

- **Não é o caso óbvio.** Texto longo com pontuação (730 palavras) e tabela
  longa sem pontuação nenhuma (1.800 palavras, 200 nomes) foram testados e
  passam. O gatilho é mais estreito e **não foi reproduzido**.
- **Uma exceção no reconhecedor de NER sobe** — testado por injeção. Presidio
  não a engole nesse nível. Na interface isso viraria erro visível, não tela
  vazia, o que é o comportamento certo.
- **Mas alguma camada mais funda engoliu esta**, porque a colheita processou
  os 300 candidatos e terminou com código 0. Ou seja: para aquele documento, o
  NER contribuiu de forma parcial ou nula, **sem erro visível**.

O terceiro ponto é o que preocupa: é a assinatura do *falso silêncio* — um
documento em que os nomes não seriam detectados e a tela não diria nada. Não
está confirmado que chega até a UI nesse formato.

**Impacto no gate de usabilidade: nenhum.** O filtro de "exatamente um
vazamento" exclui documentos com NER quebrado, porque uma falha de NER produz
*muitos* nomes sem cobertura, não um. Os 4 documentos da sessão foram
verificados um a um: 17 a 24 `PERSON` detectados em cada, e em todos o nome do
gabarito realmente escapa da tarja.

**Próximo passo quando este item for pego:** reproduzir com a semente 20260901
sobre 300 candidatos isolando o documento que falha, e decidir entre truncar
com janela deslizante ou fatiar o texto antes do NER. Fatiar é o certo —
truncar perderia detecção no fim do documento, em silêncio.

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
- [x] Rodar, ler, e confirmar ou revisar **D1** com os números. Re-executado
      em 2026-08-31 sobre o corpus atual — o relatório versionado era de uma
      geração anterior. **D1 confirmada**: 1 documento com vazamento contra 9.
- [x] Se "rótulo errado" for a causa dominante: reconhecedor de contexto de
      pessoa (`Sr.`, `Sra.`, `Dr.`, `portador(a) do`, proximidade de CPF),
      com testes, e re-rodar o `eval`.
      → **Medido e recusado.** "Rótulo errado" é a causa dominante (12 de 13),
      mas a âncora que este item pressupõe não existe em nenhum dos casos:
      todos os 12 estão em célula de tabela, precedidos de CPF, telefone ou
      data. Ganho medido do reconhecedor: 0 de 12. O conserto certo é
      estrutural (coluna de tabela pelo cabeçalho) e virou trabalho de fase
      própria. Ver **D4**, revisada.

**Bloco 2 — API**
- [x] Sessão de documento com TTL, `DELETE` e varredura de órfãs na subida.
- [x] `POST /api/doc`: upload, detecção, inventário, spans com retângulos.
- [x] Render de página como PNG (`Cache-Control: private`).
- [x] `PATCH /api/doc/{id}/span` e `PUT /api/doc/{id}/perfil`.
- [x] `POST /api/doc/{id}/aprovar`: redação + verificação, relatório estruturado.
- [x] `GET /api/doc/{id}/download` com o gate de `verify().ok`.
- [x] Qualquer edição invalida a aprovação e apaga o PDF já gerado.
- [x] Nenhum valor de PII em log no módulo web — só id de span e contagem.
- [x] Corrigir `pdf_redactor.logger.warning("span sem retângulo: %r", valor)`,
      que ainda logava o valor. Herdado da Fase 0. A causa era o tipo do campo
      `RedactionResult.spans_sem_retangulo` (`list[str]` de valores); passou a
      ser `SpanSemRetangulo(entity, start, end)`, e com isso o mesmo defeito
      saiu também do `cli.py`, que imprimia até 5 valores no stdout.
      `tests/test_log_sem_pii.py` trava a invariante, inclusive contra a
      reintrodução de um campo de texto no registro.

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
      **Instrumento pronto** (`eval/gate_usabilidade.py`, alvos
      `gate-usabilidade` e `gate-usabilidade-apurar`, roteiro em
      `eval/gate-usabilidade-roteiro.md`). Falta a medição, que depende de 3 a
      5 pessoas que não conheçam os documentos — nem eu nem quem escreveu o
      código servem como sujeito.

      O vazamento não é simulado: o instrumento gera candidatos, roda o
      pipeline real e fica só com os documentos em que o `bert-lenerbr` de
      fato deixa um `PERSON` sem cobertura. Suprimir um span na aplicação
      para "criar" a falha exigiria um gancho de teste no caminho do gate,
      que é onde este sistema não pode ter gancho.

      O aproveitamento medido é de ~1 documento em 50, e isso é a medida de
      quão bom o modelo é — não um defeito do instrumento.

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
  ✔ Confirmada em 2026-08-31 (1 documento com vazamento contra 9). No mesmo
  movimento, **D4 foi revisada**: a causa dos vazamentos é estrutural, não
  linguística, e o reconhecedor de âncora que ela propunha não corrigiria
  nenhum caso.

---

## Fora de escopo desta fase — não implementar agora

Autenticação, contas, lote, fila, cofre reversível, pseudonimização, OCR,
copiloto LLM, hospedagem de produção, precificação. Cada um desses tem fase
própria; misturar aqui atrasa a única pergunta que a Fase 1 existe para
responder — se uma pessoa consegue revisar, corrigir e assinar embaixo.
