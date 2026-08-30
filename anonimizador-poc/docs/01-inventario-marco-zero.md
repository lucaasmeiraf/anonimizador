# 01 — Inventário do Marco Zero

Tudo o que existe no projeto neste momento: dependências, modelos, artefatos de
código, licenças e o estado de verificação de cada parte. Data de corte:
**29/08/2026**, commit inicial da Fase 0.

Este documento é descritivo, não aspiracional. O que está aqui existe no
repositório; o que falta está listado em [`04-implantacao.md`](04-implantacao.md),
seção "O que ainda não é produto".

---

## 1. Resumo executivo

| Dimensão | Estado |
|---|---|
| Fase | 0 — prova de conceito com veredicto numérico |
| Linhas de Python | ~3.500 em 30 arquivos |
| Ambiente | container Docker, Python 3.12, sem rede em execução |
| Dependências externas em runtime | **nenhuma** — modelos gravados na imagem |
| Testes | 14 de lógica pura verificados; integração pendente de container |
| Risco de licença | **1 alto** (PyMuPDF/AGPL) e **1 médio** (modelo sem licença declarada) |

---

## 2. Dependências de software

### 2.1 Python e base

| Componente | Versão | Licença | Papel |
|---|---|---|---|
| Python | 3.12 (imagem `python:3.12-slim`) | PSF | runtime |
| Debian slim | bookworm (base da imagem oficial) | mista, DFSG | SO do container |

**Por que 3.12 e não 3.14:** o PyMuPDF ainda não publica wheels `cp314`. spaCy e
torch já publicam — o bloqueio é especificamente o PyMuPDF. A máquina de
desenvolvimento tem Python 3.14, e é justamente por isso que o container fixa a
versão: o host deixa de importar.

### 2.2 Bibliotecas

| Pacote | Versão fixada | Licença | Papel | Risco |
|---|---|---|---|---|
| `presidio-analyzer` | 2.2.364 | MIT | registro de reconhecedores, enriquecimento por contexto | baixo |
| `presidio-anonymizer` | 2.2.364 | MIT | operadores de anonimização (usado a partir da Fase 2) | baixo |
| `spacy` | 3.8.16 | MIT | tokenização, lematização, NER baseline | baixo |
| `transformers` | 4.57.1 | Apache-2.0 | pipeline de token-classification | baixo |
| `torch` | 2.9.1 (índice CPU) | BSD-3-Clause | backend dos transformers | baixo |
| `PyMuPDF` | 1.28.2 | **AGPL-3.0 ou comercial Artifex** | extração com layout, redação, saneamento | **ALTO** |
| `pdfplumber` | 0.11.10 | MIT | segunda extração, para checagem cruzada | baixo |
| `Faker` | 40.37.0 | MIT | nomes e endereços fictícios do corpus | baixo |
| `pytest` | 8.4.2 | MIT | testes | baixo |

Todas as versões foram conferidas no PyPI em 29/08/2026, com artefato para
Linux disponível.

> **Risco alto — PyMuPDF é AGPL-3.0.**
> O PyMuPDF é licenciado sob AGPL-3.0 **ou** licença comercial da Artifex. A
> AGPL exige que, se o software for distribuído **ou disponibilizado por rede a
> usuários**, o código-fonte completo do produto derivado seja disponibilizado
> sob AGPL. Um produto vendido a cliente — on-premise ou como serviço —
> dispara essa obrigação.
>
> Três saídas, todas legítimas:
> 1. **Comprar a licença comercial da Artifex.** Caminho normal para produto
>    proprietário. Precisa de cotação; é custo recorrente a orçar antes da
>    proposta comercial.
> 2. **Distribuir o produto sob AGPL-3.0.** Compatível com o discurso de
>    soberania e transparência ("podemos abrir o código-fonte"), e pode ser
>    vantagem competitiva no setor público. Impede o modelo proprietário.
> 3. **Trocar o PyMuPDF por `pikepdf` (MPL-2.0) + `pdfminer.six` (MIT).**
>    Tecnicamente pior: perde-se o `apply_redactions`, o `scrub` e o acesso a
>    bounding box por caractere, que são exatamente os pilares desta fase.
>    Custo de reescrita alto e risco de redação menos confiável.
>
> **Isto não bloqueia a Fase 0** (uso interno, sem distribuição), mas precisa
> estar decidido antes da primeira entrega a cliente. Ver
> [`02-requisitos.md`](02-requisitos.md), RN-04.

### 2.3 Ferramentas de host

| Ferramenta | Onde | Necessária para |
|---|---|---|
| Docker Desktop | host Windows | construir e rodar o container |
| WSL2 | host Windows | backend do Docker Desktop |
| Git | host | versionamento |
| `make` (opcional) | host Linux/WSL | atalhos; no Windows há `run.ps1` equivalente |

Nada mais é instalado no host — nem Python, nem modelos, nem bibliotecas.

---

## 3. Modelos de NER

Três configurações, comparadas pelo harness de avaliação. Todas gravadas na
imagem durante o build e usadas offline.

| Config | Modelo | Tamanho aprox. | Licença | Domínio de treino |
|---|---|---|---|---|
| `spacy` | `pt_core_news_lg` 3.8.0 | ~570 MB | **CC BY-SA 4.0** | UD Bosque + WikiNER |
| `bert-lenerbr` | `pierreguillou/ner-bert-base-cased-pt-lenerbr` | ~430 MB | **não declarada** | LeNER-Br (jurídico) |
| `bertimbau-harem` | `marquesafonso/bertimbau-large-ner-selective` | ~1,3 GB | MIT | HAREM selective (geral) |

Rótulos por modelo:

- `pt_core_news_lg`: `PER`, `ORG`, `LOC`, `MISC`
- `lenerbr`: `PESSOA`, `ORGANIZACAO`, `LOCAL`, `TEMPO`, `LEGISLACAO`, `JURISPRUDENCIA`
- `bertimbau-harem`: `PESSOA`, `ORGANIZACAO`, `LOCAL`, `TEMPO`, `VALOR`

O mapeamento para o vocabulário do Presidio está em `config._LABEL_MAP_PT`.
`LEGISLACAO`, `JURISPRUDENCIA` e `VALOR` são descartados: não são dado pessoal.

> **Risco médio — o checkpoint LeNER-Br não declara licença.**
> O card do `pierreguillou/ner-bert-base-cased-pt-lenerbr` não traz campo de
> licença. Sem declaração expressa não há concessão de direitos de uso
> comercial. O modelo é o mais promissor para petições e contratos (o autor
> reporta F1 0,8926 no conjunto de teste do LeNER-Br), então vale resolver em
> vez de descartar: contatar o autor pedindo declaração expressa, ou refazer o
> fine-tuning sobre o LeNER-Br a partir do BERTimbau (MIT), o que produz um
> checkpoint com procedência limpa e ainda permite treinar no domínio do
> cliente. **Decidir antes de qualquer entrega comercial.**

> **Atenção — `pt_core_news_lg` é CC BY-SA 4.0.**
> Compartilhamento pela mesma licença. Distribuir o modelo dentro da imagem
> exige atribuição; adaptá-lo (fine-tuning) obrigaria a redistribuir a
> adaptação sob CC BY-SA 4.0. Como o spaCy aqui é usado sobretudo para
> tokenização e lematização, e como configuração de NER ele é apenas a
> baseline, o impacto tende a ser pequeno — mas a atribuição é obrigatória.

> **Nota sobre um erro do documento de ideia original.**
> `neuralmind/bert-base-portuguese-cased` (o "BERTimbau" citado) é um modelo de
> linguagem **sem cabeça de NER**. Não pode ser usado diretamente para
> reconhecimento de entidades; exigiria fine-tuning. Os dois checkpoints acima
> já vêm ajustados.

---

## 4. Artefatos de código

### 4.1 Núcleo (`src/anonimizador/`)

| Arquivo | Linhas ~ | Responsabilidade | Dependências pesadas |
|---|---|---|---|
| `validators.py` | 210 | dígitos verificadores (mod-11, mod-97-10), lista de DDD | nenhuma |
| `fakes.py` | 160 | geradores sintéticos com checksum válido | nenhuma |
| `spans.py` | 130 | modelo de span, resolução de sobreposição, desambiguação por âncora | nenhuma |
| `config.py` | 150 | entidades, limiares, configs de NER, precedência, âncoras de desambiguação | nenhuma |
| `recognizers/` | 400 | 12 reconhecedores Presidio, um por identificador | presidio |
| `ner.py` | 220 | NlpEngine PT e reconhecedor transformer com janelamento | presidio, transformers |
| `pipeline.py` | 95 | montagem do `AnalyzerEngine` | presidio |
| `layout.py` | 170 | ponte offset de caractere → retângulo | PyMuPDF |
| `pdf_redactor.py` | 170 | redação, saneamento, save não-incremental | PyMuPDF |
| `verifier.py` | 220 | verificação em 10 vetores | PyMuPDF, pdfplumber |
| `politica.py` | 170 | perfil de política serializável, operador por entidade | nenhuma |
| `cli.py` | 250 | ponto de entrada único do container | todas |

Os quatro primeiros, mais `politica.py`, não importam nada além da stdlib. Foi deliberado: é a parte
que decide *o que prevalece* e precisa ser testável sem carregar 2 GB de modelo.

### 4.2 Avaliação (`eval/`)

| Arquivo | Responsabilidade |
|---|---|
| `generate_corpus.py` | gera texto + gabarito e **depois** renderiza o PDF; 5 gêneros, 3 páginas, com tabelas e seções de duas colunas |
| `align.py` | projeta o gabarito no texto extraído (difflib + fallback) |
| `metrics.py` | F1 estrito, F1 relaxado, cobertura de caracteres |
| `run_eval.py` | roda as 3 configs, mede latência, separa gate de vazamento e diagnóstico de resíduo, gera `report.md` |

### 4.3 Testes (`tests/`)

| Arquivo | Cobre | Precisa de modelo |
|---|---|---|
| `test_validators.py` | checksums, valores públicos conhecidos, ida-e-volta, mutação | não |
| `test_pipeline.py` | resolução de sobreposição, determinismo | não |
| `test_align.py` | projeção de gabarito, ocorrências repetidas | não |
| `test_metrics.py` | as três métricas discordando nos casos certos | não |
| `test_layout.py` | alinhamento dos vetores, retângulo cobre o valor certo | não (só PDF) |
| `test_redaction.py` | redação nos 10 vetores + controle negativo | não (só PDF) |
| `test_desambiguacao.py` | âncora vencendo a precedência, e os empates em que ela não decide | não |
| `test_corpus_layout.py` | offsets do gabarito em tabela, colunas e multipágina | não (só PDF) |
| `test_politica.py` | perfil serializável; operador não implementado falha alto | não |
| `test_recognizers.py` | reconhecedores no AnalyzerEngine real | **sim** (`slow`) |

### 4.4 Infraestrutura

| Arquivo | Papel |
|---|---|
| `docker/Dockerfile` | imagem única; modelos gravados no build; usuário não-root |
| `docker-compose.yml` | serviços com `network_mode: none` |
| `docker-compose.gpu.yml` | override com torch CUDA e `gpus: all` |
| `Makefile` / `run.ps1` | mesmos alvos, para Linux/WSL e para Windows |
| `requirements.txt` | versões fixadas (torch fica no Dockerfile, por causa do índice) |

---

## 5. Entidades cobertas

| Entidade | Detecção | Checksum | Faixa |
|---|---|---|---|
| `CPF` | regex + mod-11 | sim | **com gate** (F1 estrito ≥ 0,95) |
| `CNPJ` | regex + mod-11 | sim | **com gate** (F1 estrito ≥ 0,95) |
| `PERSON` | NER | não | **com gate** (F1 relaxado ≥ 0,80) |
| `PROCESSO_CNJ` | regex + mod-97-10 (ISO 7064) | sim | medida |
| `CNS` | regex + soma ponderada mod-11 | sim | medida |
| `PIS_PASEP` | regex + mod-11 | sim | medida |
| `TITULO_ELEITOR` | regex + mod-11 + código de UF | sim | medida |
| `CNH` | regex + mod-11 (variante) + contexto obrigatório | parcial | medida |
| `RG` | regex + contexto; DV só no formato SP | parcial | medida |
| `CEP` | regex + contexto | não | medida |
| `TELEFONE` | regex + validação de DDD e de prefixo | parcial | medida |
| `EMAIL` | regex | não | medida |
| `ENDERECO` | regex de logradouro | não | best-effort |
| `ORGANIZATION`, `LOCATION`, `DATE_TIME` | NER | não | best-effort, **não tarjadas** |

Por que `RG` e `CEP` não têm gate: não existe checksum nacional uniforme. Cada
SSP estadual tem seu próprio formato, e o CEP não tem dígito verificador —
validá-lo exigiria a base de faixas dos Correios, que não é livremente
redistribuível e desatualizaria dentro de um container offline.

---

## 6. Corpus de avaliação

| Propriedade | Valor |
|---|---|
| Documentos | 50 (configurável) |
| Gêneros | contrato, petição judicial, prontuário, RH, ofício administrativo |
| Origem | 100% sintético, semente fixa `20260829` |
| Gabarito | exato por construção — gerado junto com o texto, não anotado depois |
| Identificadores | checksum válido, sem vínculo com pessoa real |

Nenhum documento real foi usado. Ver [`02-requisitos.md`](02-requisitos.md),
RS-01.

---

## 7. Estado de verificação

Distinção que importa: **o que foi executado** e **o que apenas foi escrito**.

### Verificado, com execução real

- Checksums de CPF e CNPJ contra valores públicos de teste conhecidos.
- CPF, CNPJ, CNS, PIS, CNH, título de eleitor e processo CNJ por ida-e-volta
  gerador↔validador, 2.000 amostras cada, 100% válidas.
- Robustez: mutação de um dígito reprova em 93%–100% dos casos, por tipo.
- 14 testes de lógica pura (spans, alinhamento, métricas) — todos passando.
- Existência e rótulos dos três modelos de NER, e existência de todas as
  versões fixadas no PyPI com artefato Linux.

### Escrito, ainda não executado

Tudo que depende do container: extração de PDF, mapeamento offset→retângulo,
redação, os 10 vetores de verificação, os reconhecedores dentro do Presidio, o
NER, o corpus e o harness de avaliação.

**Consequência prática:** os números dos decision gates ainda não existem. A
primeira execução do `eval` provavelmente vai expor defeitos de integração —
3.500 linhas nunca executadas em conjunto não funcionam de primeira.

### Fora do escopo de verificação deste projeto

As citações normativas e os benchmarks do documento de ideia original
(Decreto 12.572/2025, IN GSI 8/2025, Lei 15.352/2026, o preprint
Brazilian-PHI). **Não foram conferidos.** Não bloqueiam a Fase 0, que é
puramente técnica e local, mas não devem ser tratados como confirmados em
material comercial sem checagem das fontes primárias.

---

## 8. O que não existe ainda

Fora do escopo da Fase 0, por decisão registrada no goal:

cofre de reversibilidade, criptografia do mapa token→valor, HashiCorp Vault,
copiloto LLM local (Ollama), OCR de PDF escaneado, interface web, autenticação,
multi-tenancy, trilha de auditoria, precificação.

O caminho de cada um até o produto está em
[`04-implantacao.md`](04-implantacao.md).
