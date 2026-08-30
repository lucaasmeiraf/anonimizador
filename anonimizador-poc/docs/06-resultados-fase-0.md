# 06 — Resultados da Fase 0 e decisões em aberto

Leitura dos números do `eval/report.md`, o que eles mudaram em relação à
primeira rodada, e o que continua sem resposta. Este documento interpreta; o
`report.md` é gerado e só apresenta.

Estado em 2026-08-29. Corpus semente `20260829`, 50 documentos de 3 páginas,
2410 entidades.

---

## 1. O resumo, se você só ler um parágrafo

Os identificadores com checksum estão resolvidos: CPF, CNPJ, RG, CEP,
telefone, e-mail, CNS, PIS/PASEP, processo CNJ, CNH e título de eleitor saem
todos com F1 estrito 1.000 e zero falso positivo, **nas três configurações de
NER** — não dependem de modelo. O `layout.py`, que era o maior risco técnico
da fase, converteu 100% dos spans em retângulo, agora com tabelas, duas
colunas e três páginas. O que não está resolvido é `PERSON`: a melhor
configuração ainda deixa nome de pessoa passar em 1 documento a cada 50, e a
escolha de qual configuração levar para a Fase 1 depende de um critério que
o goal ainda não fixou (seção 4).

---

## 2. A primeira rodada mediu o caso fácil, e concluiu errado

A rodada inicial usou 50 documentos de **uma página, uma coluna, sem tabela**.
Com esse corpus, o gate de `PERSON` foi atingido pelo `spacy`, e o relatório
recomendou levá-lo para a Fase 1.

O corpus foi então reconstruído com o layout que documento de órgão público de
fato tem — tabelas de células lado a lado, seções de duas colunas, três
páginas. O resultado se inverteu:

| Configuração | PERSON F1 relaxado (1 pág.) | PERSON F1 relaxado (3 pág., tabelas, colunas) |
|---|---:|---:|
| `spacy` | 0.802 ✅ | **0.267** ❌ |
| `bert-lenerbr` | 0.728 ❌ | 0.787 ❌ |
| `bertimbau-harem` | 0.639 ❌ | **0.854** ✅ |

**A causa é a ordem de extração.** O PyMuPDF devolve uma página de duas
colunas em ordem de varredura: linha 1 da esquerda, linha 1 da direita, linha
2 da esquerda, e assim por diante. O texto que chega ao detector tem as duas
colunas intercaladas. O `spacy` depende fortemente do contexto sintático da
frase e desaba (2455 falsos positivos); os transformers degradam bem menos.

Isso não é defeito do corpus nem do `layout.py`. É a condição real de qualquer
PDF de duas colunas, e a primeira rodada simplesmente não a exercitava.

> **Consequência de método:** um corpus sintético fácil não produz um número
> otimista — produz um número que aponta para a decisão errada. A recomendação
> "leve o `spacy`" teria custado a Fase 1 inteira.

---

## 3. Correções aplicadas nesta rodada

### 3.1 Registry em idioma errado (bloqueava o eval)

`build_registry()` criava o `RecognizerRegistry` sem `supported_languages`. O
padrão do Presidio é `["en"]`, e o `AnalyzerEngine` recusa a combinação
registry(en) + engine(pt). O eval abortava na primeira configuração.

Nenhum teste pegou isso porque nenhum dos testes rápidos constrói o
`DetectionPipeline`. Continua assim: a construção do pipeline carrega modelos
e só cabe em teste marcado `slow`.

### 3.2 CNH com rótulo trocado

CNH, CPF e PIS/PASEP têm todos 11 dígitos, e **um mesmo número pode satisfazer
mais de um checksum** — acontece em 2 dos 10 documentos com CNH do corpus.
Nesse empate, `config.PRECEDENCIA` decidia por ordem estática (CPF antes de
PIS antes de CNH) e ignorava a única evidência que desambigua: a palavra-âncora
imediatamente anterior no texto (`CNH nº 22393559907`).

O trecho continuava sendo tarjado — nunca houve risco de vazamento — mas o
rótulo saía errado, o que derrubava o recall de CNH para 0.800 e criava um
falso positivo fantasma em CPF e outro em PIS/PASEP. Um evento, contado como
três defeitos.

`spans.desambiguar_por_ancora` resolve o empate pela âncora e é
deliberadamente conservadora: sem âncora, ou com âncoras conflitantes na mesma
janela, não decide e devolve o caso à precedência estática. Trocar um rótulo
errado determinístico por um imprevisível seria pior — é o rótulo que decide o
operador de anonimização aplicado.

Resultado: CNH, CPF e PIS/PASEP em 1.000/1.000, zero falso positivo, nas três
configurações.

### 3.3 Verifier misturando duas perguntas

O verifier conferia os valores que **decidimos tarjar**. Um falso positivo em
texto repetido — o `spacy` marcava `Senhor(a` como parte de um nome, e o
ofício tem `Senhor(a) Servidor(a),` mais adiante — era contado como vazamento
de dado pessoal.

Agora são duas checagens separadas:

- **Vazamento de PII** — valores do *gabarito* que sobreviveram no PDF. É o
  gate. Um caso reprova.
- **Resíduo de ocorrência** — strings tarjadas que reaparecem sem tarja.
  Diagnóstico de recall dentro do documento, não gate.

No caminho apareceu um segundo erro no gate: ele cobrava redação de
`ORGANIZATION`, `LOCATION` e `DATE_TIME`, que `ENTIDADES_REDIGIDAS` preserva
de propósito — em documento público o nome do órgão e a data do ato costumam
ser justamente o que precisa permanecer legível. O gate reprovava a fase por
cumprir a política. Corrigido: só entram no gate os rótulos que a política
manda tarjar.

### 3.4 Corpus com o layout que importa

`generate_corpus.py` passou a ter três regimes de bloco: `corpo`, `tabela`
(células lado a lado, cada uma um `insert_text` próprio na mesma altura) e
`colunas` (duas colunas independentes). Documentos foram de 1 para 3 páginas e
de 610 para 2410 entidades, com PII nas três páginas (970/793/647).

O texto-fonte é montado em **ordem lógica de leitura** (coluna esquerda
inteira, depois a direita) enquanto o PDF extrai em ordem de varredura. A
divergência é intencional: `align.py` reprojeta o gabarito no texto extraído,
e o detector passa a ser medido sob a degradação de contexto real. **Zero
defeito de alinhamento** em 2410 entidades — a reprojeção aguenta.

---

## 4. Decisão em aberto: o critério de recomendação

O `report.md` recomenda a configuração com melhor F1 de `PERSON`. Isso já
apontou para a configuração errada **duas vezes**, pelo mesmo motivo: F1
equilibra precisão e recall, e num anonimizador esses erros não têm o mesmo
custo. Falso positivo tarja uma palavra à toa; falso negativo vaza dado
pessoal.

Números da rodada atual:

| Configuração | Precisão PERSON | Recall PERSON | Cobertura de chars | Documentos sem vazar |
|---|---:|---:|---:|---:|
| `spacy` | 0.166 | 0.687 | 0.845 | **1/50** |
| `bert-lenerbr` | 0.685 | **0.925** | 0.983 | **49/50** |
| `bertimbau-harem` | **0.809** | 0.903 | **0.997** | 39/50 |

O `bertimbau-harem` ganha o gate por F1 (0.854 contra 0.787), graças à
precisão. O `bert-lenerbr` ganha onde o produto é julgado: vaza em 1 documento
contra 11.

> **Isto precisa de decisão humana, não de código.** As opções são: (a) manter
> o gate de F1 como está no goal e aceitar `bertimbau-harem`; (b) trocar o
> critério de recomendação para taxa de documentos sem vazamento, e levar
> `bert-lenerbr`; (c) manter os dois gates, exigindo que a configuração
> escolhida passe em F1 **e** lidere em não-vazamento.

> **Decidido em 2026-08-30 pela opção (b): `bert-lenerbr`.** Registrada como
> D1 em `goal-fase-1.md`, com a justificativa completa. Em resumo: a interface
> de revisão torna a assimetria decisiva — falso positivo é uma tarja sobrando,
> que o revisor vê e desliga; falso negativo é uma tarja faltando, que ele
> precisa notar pela ausência. O diagnóstico da seção 6 confirmou a decisão:
> somando vazamento total e exposição parcial real, `bert-lenerbr` fica em 3
> casos contra 17 do `bertimbau-harem`.

Observação para (a): a diferença de cobertura de caracteres entre as duas
(0.997 contra 0.983) favorece o `bertimbau`, mas cobertura é ponderada por
caractere sobre todas as entidades, enquanto o gate de vazamento é binário por
documento. São métricas que respondem perguntas diferentes, e a segunda é a
que corresponde ao que o cliente percebe.

---

## 4-B. O ponto cego do checksum, encontrado em documento real

Registrado aqui porque contradiz, em parte, a conclusão da seção 1.

A Fase 0 afirmou que os identificadores com checksum estavam **resolvidos** —
F1 estrito 1.000, zero falso positivo, independente do modelo. Isso continua
verdade para o que foi medido. O que não estava medido era o caso em que o
dígito verificador **não fecha**.

Quatro PDFs de teste reais foram processados em 2026-08-30:

| Documento | Padrões com forma de CPF | Checksum válido | Detectados |
|---|---:|---:|---:|
| `Contrato_..._4P` | 13 | **0** | 0 |
| `Processo_SEI_..._4P` | 11 | **0** | 0 |
| `documento_..._01_contrato` | 6 | **0** | 0 |
| `documento_..._02_sei` | 5 | **0** | 0 |

**35 números com forma de CPF, nenhum detectado.** Os documentos diziam, em
texto, `CPF fictício nº`. A CNH do segundo documento passou pelo mesmo
caminho.

O mecanismo: `ChecksumRecognizer.validate_result` devolvia `False` quando o
mod-11 falhava, e `False` no Presidio significa **descartar**. O candidato
morria antes de o enriquecedor de contexto olhar a palavra `CPF:`
imediatamente anterior.

> O corpus sintético não podia ter encontrado isso, e a razão é a mesma da
> seção 2: ele só gerava identificador **válido**. Um caminho que o corpus não
> exercita é um caminho sobre o qual o `report.md` é silencioso — e silêncio,
> de novo, foi lido como ausência de problema.

Isso importa fora do documento de teste: 23 dos 35 tinham âncora explícita, e
o caso real equivalente é ficha com dígito trocado, minuta com identificador
fictício e PDF vindo de OCR. Nos três o número continua sendo dado pessoal.

O conserto está em `recognizers/base.py` (três níveis de evidência) e o corpus
passou a gerar identificadores com DV inválido, ancorados e em célula de
tabela sem âncora, para que o caminho seja **medido** em vez de suposto.

### O que a mudança custou: nada

Afrouxar o reconhecedor com o melhor número do projeto exigia medição, não
intuição. Rodada de 2026-08-30, corpus com 51 CPFs de DV inválido no gabarito:

| Entidade | Suporte (antes → depois) | Precisão | Recall | F1 estrito | FP |
|---|---|---:|---:|---:|---:|
| CPF | 660 → **711** | 1.000 | 1.000 | 1.000 | **0** |
| CNPJ | 44 → 47 | 1.000 | 1.000 | 1.000 | **0** |
| CNH | 20 → 27 | 1.000 | 1.000 | 1.000 | **0** |

Os identificadores com DV inválido entraram no suporte e foram **todos**
detectados, com fronteiras exatas, sem introduzir um único falso positivo. O
que segura a precisão é o quarto nível: forma crua, sem âncora e sem checksum
continua descartada — número de nota fiscal e de protocolo seguem ignorados.

Confirmado no documento real que originou o achado: os 5 CPFs do
`documento_..._02_sei` passaram a ser detectados e tarjados, marcados como
`checksum_invalido`. RG e CNPJ do mesmo documento também, pelo mesmo motivo.

---

## 5. O que continua sem medição

Registrado aqui para não virar suposição de que está coberto.

| Lacuna | Por quê | Consequência |
|---|---|---|
| Valor de PII quebrado entre linhas | O gerador nunca parte um segmento — disciplina do goal, para não medir o gerador em vez do detector | `layout.rects_for` tem código para span que cruza linha, e ele **não é exercitado pelo corpus** |
| Latência em documento de dezenas/centenas de páginas | Corpus tem 3 páginas | 0.53 s/página com transformer extrapola para ~53 s num documento de 100 páginas, mas é extrapolação de 3 pontos |
| Identificador indireto por contexto | Não está no gabarito | A cobertura de caracteres é **silenciosa** sobre esse risco, não tranquilizadora. Ver `05-politica-llm.md`, seção 3.2 |
| PDF escaneado / OCR | Fora do escopo da Fase 0 | Nada aqui vale para documento em imagem |
| ~~Identificador com checksum inválido~~ | ~~o corpus só gerava válidos~~ | **medido a partir de 2026-08-30 — ver seção 4-B** |
| Documento real de cliente | Proibido nesta fase (RS-01) | Todos os números valem sobre corpus sintético |

---

## 6. Falsos positivos ainda altos em rótulos best-effort

`ORGANIZATION` e `LOCATION` seguem fracos em todas as configurações. Não são
tarjados por padrão, então não afetam o gate nem o vazamento, mas afetam a
usabilidade: são eles que enchem a tela de revisão de sugestão ruim.

Um caso concreto e sistemático: sobrenomes que parecem topônimo. `Casa Grande`
aparece como sobrenome no corpus e é classificado como `LOCATION` pelos dois
transformers, o que produziu vazamento de `PERSON` em `contrato-000` e
`peticao-001` no `bertimbau-harem`. Vale investigar antes da Fase 1 se um
reconhecedor de contexto (`Sr.`, `Sra.`, `portador(a) do`) resolve a classe.

`eval/diagnostico_person.py` (`make diagnostico`) mediu isso, e a hipótese
vale para **100% dos casos**:

| Configuração | vazou — rótulo errado | vazou — **nenhum span** |
|---|---:|---:|
| `bert-lenerbr` | 1 | **0** |
| `bertimbau-harem` | 14 | **0** |

Em 710 entidades `PERSON` por configuração, **nenhum nome passou
despercebido**. Todo vazamento é o mesmo defeito: o modelo viu o nome e o
classificou como `LOCATION` (13 casos) ou `ORGANIZATION` (2) — rótulos que
`ENTIDADES_REDIGIDAS` preserva de propósito.

Isso reclassifica o problema. Não é limite de detecção; é interação entre erro
de classificação e política de preservação, num subconjunto reconhecível —
sobrenomes que também são topônimo. O reconhecedor de contexto é o conserto
certo, e está registrado como D4 em `goal-fase-1.md`. O detalhe caso a caso
sai em `eval/diagnostico-person.md`, gerado por `make diagnostico` (artefato,
não versionado — como o `report.md`).

---

## 7. Estado do código

Commitado e enviado ao remoto em 2026-08-30 (`a7ec970` e anteriores).
A tabela permanece como registro do que esta rodada mudou.

| Arquivo | Mudança |
|---|---|
| `src/anonimizador/recognizers/__init__.py` | `supported_languages=[language]` no registry |
| `src/anonimizador/config.py` | `AMBIGUAS_MESMA_FORMA`, `ANCORAS_DESAMBIGUACAO`, `JANELA_ANCORA` |
| `src/anonimizador/spans.py` | `desambiguar_por_ancora`; `resolver_sobreposicoes` aceita o texto |
| `src/anonimizador/pipeline.py` | passa o texto para a resolução de spans |
| `src/anonimizador/politica.py` | **novo** — `PerfilPolitica` serializável |
| `eval/generate_corpus.py` | blocos de layout: tabela, colunas, multipágina |
| `eval/run_eval.py` | gate separado de diagnóstico; seção de erros no relatório |
| `tests/test_desambiguacao.py` | **novo** — 8 testes |
| `tests/test_corpus_layout.py` | **novo** — 8 testes |
| `tests/test_politica.py` | **novo** — 13 testes |
| `docs/05-politica-llm.md` | **novo** — política de uso de LLM |
| `docs/06-resultados-fase-0.md` | **novo** — este documento |

83 testes passando (eram 53). `make eval` roda em ~5 min em CPU.

---

## 8. Próximo passo combinado

Projetar a interface de anonimização, com seleção do tipo de tratamento por
entidade. O contrato já existe (`politica.PerfilPolitica`), com a trava de que
apenas `tarja` e `manter` estão implementados — `pseudonimo` e `mascara` são
recusados por `validar_perfil` até que a reescrita de texto no PDF exista.

A decisão da seção 4 foi tomada (`bert-lenerbr`) e é o que define quanta
revisão humana a tela precisa oferecer.

O escopo completo — stack, API, ciclo de vida dos dados, o conflito entre porta
publicada e `network_mode: none`, e onde o chat entra — está em
**`goal-fase-1.md`**.
