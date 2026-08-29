# /goal — Fase 0: Prova de Conceito (Detecção + Redação Local de PII PT-BR)

> **Revisão 2** — corrigido após análise técnica. Mudanças em relação à v1:
> ambiente containerizado obrigatório; BERTimbau movido para dentro do escopo;
> adicionada a camada de mapeamento texto→coordenadas do PDF (que estava ausente
> e é o item de maior risco); redação verdadeira expandida além do content stream;
> definição formal das métricas; corpus sintético multi-domínio; prova de offline
> por isolamento de rede do container.

## Objetivo
Validar, em ambiente **100% local e sem rede (sem enviar nenhum conteúdo para APIs ou modelos externos)**, que é possível:
1. Detectar dados pessoais e sensíveis (LGPD) em PDFs de texto em português-BR, em múltiplos gêneros documentais;
2. Aplicar **redação verdadeira** no PDF (remoção física do texto e de todos os seus vetores paralelos, não retângulo por cima);
3. Medir a qualidade da detecção com números reprodutíveis (precisão/recall/F1 por entidade) para decidir a arquitetura das próximas fases.

Esta fase **não** entrega produto vendável nem interface final. Ela responde à pergunta: *"a stack local aguenta, com que qualidade, e qual configuração de NER devemos levar para a Fase 1?"*.

## Perguntas que esta fase precisa responder (decision gates)
- Regex + dígito verificador (mod-11) resolve **CPF e CNPJ** com F1 estrito >= 0,95? *(esperado: sim)*
- Regex + contexto resolve **RG, CEP, telefone, e-mail** e os identificadores estendidos com recall aceitável? *(medir, não prometer — RG e CEP não têm checksum nacional uniforme)*
- Qual das três configurações de NER entrega **PERSON com F1 relaxado >= 0,80**: `spaCy pt_core_news_lg`, `BERTimbau/LeNER-Br` ou `BERTimbau-large/HAREM`? *(a v1 deste goal deixava o BERTimbau como contingência; agora ele é avaliado de saída, para não gerar retrabalho na Fase 1)*
- O mapeamento **offset de caractere → retângulo na página** é confiável o suficiente para que a redação acerte a região certa em documentos com colunas, tabelas e quebras de linha?
- A redação sobrevive à verificação: re-extração do PDF final, anotações, campos de formulário, anexos, sumário, metadados, XMP **e varredura de bytes brutos** não encontram nenhuma PII tarjada?
- A latência em **CPU** é aceitável para documentos de dezenas/centenas de páginas? E quanto a GPU melhora?

## Escopo

**Dentro da Fase 0:**
- Entrada: PDF com **texto selecionável** (digital). OCR/imagem fica fora.
- Gêneros documentais cobertos pelo corpus sintético: **contrato**, **petição/processo judicial**, **prontuário médico**, **RH/ficha funcional**, **ofício administrativo público**.
- Entidades-alvo, em três faixas:
  - **Com gate:** `CPF`, `CNPJ` (checksum mod-11), `PERSON` (NER).
  - **Medidas, sem meta rígida:** `RG`, `CEP`, `TELEFONE`, `EMAIL`, `CNS`, `PIS_PASEP`, `PROCESSO_CNJ` (mod-97-10), `CNH`, `TITULO_ELEITOR`.
  - **Best-effort, apenas reportadas:** `ENDERECO`, `ORG`, `LOC`, `DATA`.
- Detecção em pipeline de camadas: **(1)** regex + checksum -> **(2)** NER local (spaCy e/ou transformer) -> **(3)** contexto (palavras-âncora tipo "CPF nº", "portador do RG") -> **(4)** desduplicação e resolução de spans sobrepostos.
- **Mapeamento texto→layout**: índice caractere→bounding box construído a partir de `page.get_text("rawdict")`, para converter spans detectados em retângulos de redação. **Não usar `page.search_for()`** — falha com texto fragmentado em spans, hifenização, ligaduras e ocorrências repetidas.
- Redação real no PDF + **saneamento completo** + **verificação automática pós-redação**.
- Harness de avaliação reprodutível que roda sobre o corpus e produz métricas por tipo de entidade e por configuração de NER.

**Fora da Fase 0 (fases seguintes):**
- Cofre de reversibilidade / pseudonimização reversível (Fase 2).
- Copiloto LLM local via Ollama (Fase 3).
- OCR de PDF escaneado (implementação futura — deixar só o "gancho" na arquitetura).
- Interface web, login, planos, hospedagem de produção.

## Ambiente: containerizado, obrigatório

Todo o desenvolvimento, execução e avaliação acontecem **dentro de um container Docker**. Nada é instalado no host. Motivos: isolamento de segurança ao manipular documentos, reprodutibilidade das métricas, e caminho direto para escalar a automação depois.

- Imagem base `python:3.12-slim`. **Python 3.14 não serve**: o PyMuPDF ainda não publica wheels cp314 (spaCy e torch já publicam — o bloqueio é especificamente o PyMuPDF).
- **Modelos são baixados na etapa de build** (spaCy `pt_core_news_lg`, os checkpoints de NER) e ficam gravados na imagem.
- **Em tempo de execução o container roda com `network_mode: none`.** Isso não é um teste opcional: é a prova executável da restrição de soberania. Se qualquer biblioteca tentar chamar um serviço externo com o conteúdo do documento, a execução falha em vez de vazar. `HF_HUB_OFFLINE=1` e `TRANSFORMERS_OFFLINE=1` reforçam.
- Serviço opcional com GPU (override de compose) para medir o ganho de latência do transformer — a máquina de desenvolvimento tem RTX 4060 8 GB.
- Volumes montados: `eval/`, `out/` e `data/` para entrada/saída; o código entra por bind mount em desenvolvimento e é copiado na imagem para execução limpa.

> Restrição inviolável: nenhuma biblioteca/etapa pode chamar serviço externo com o conteúdo do documento. O isolamento de rede do container **prova** isso, em vez de apenas afirmá-lo.

## Stack técnica (tudo local, tudo open-source)
- **Python 3.12** (no container)
- **presidio-analyzer** e **presidio-anonymizer** (Microsoft, MIT) — registro de reconhecedores, enriquecimento por contexto e operadores de anonimização
- **spaCy** + **`pt_core_news_lg`** — tokenização/lematização (necessária ao enriquecedor de contexto do Presidio) e primeira configuração de NER
- **transformers** + **torch** — segunda e terceira configurações de NER:
  - `pierreguillou/ner-bert-base-cased-pt-lenerbr` (BERT PT-BR ajustado em LeNER-Br, domínio jurídico; rótulos PESSOA/ORGANIZACAO/LOCAL/TEMPO/LEGISLACAO/JURISPRUDENCIA)
  - `marquesafonso/bertimbau-large-ner-selective` (BERTimbau-large ajustado em HAREM selective; rótulos PESSOA/ORGANIZACAO/LOCAL/TEMPO/VALOR)
  - *Nota corrigida:* `neuralmind/bert-base-portuguese-cased` — o checkpoint citado no documento de ideia — é um modelo de linguagem **sem cabeça de NER**. Usá-lo exigiria fine-tuning próprio, o que está fora do escopo da Fase 0. Os dois checkpoints acima já vêm ajustados para NER.
- **PyMuPDF (fitz)** — extração com layout, `apply_redactions()`, `scrub()` e saneamento
- **pdfplumber** — extração independente para checagem cruzada na verificação
- **Faker (pt_BR)** + geradores de identificadores com checksum válido — corpus sintético
- **pytest** — testes automatizados e harness de métricas

## Estrutura de projeto
```
anonimizador-poc/
├── docker/
│   └── Dockerfile              # python:3.12-slim + modelos baked-in
├── docker-compose.yml          # serviços com network_mode: none
├── docker-compose.gpu.yml      # override opcional com GPU
├── Makefile                    # build / shell / test / corpus / eval / demo
├── requirements.txt
├── pyproject.toml
├── README.md
├── src/anonimizador/
│   ├── config.py               # entidades ativas, thresholds, deny/allow-list
│   ├── validators.py           # mod-11, mod-97-10, validadores puros (sem I/O)
│   ├── recognizers/            # reconhecedores customizados PT-BR
│   │   ├── cpf.py  cnpj.py  rg.py  cep.py  telefone.py  email.py
│   │   ├── cns.py  pis.py  cnj.py  cnh.py  titulo_eleitor.py
│   │   └── registry.py         # monta o RecognizerRegistry do Presidio
│   ├── ner.py                  # spaCy e transformer como EntityRecognizer do Presidio
│   ├── layout.py               # ponte offset de caractere -> retângulo (rawdict)
│   ├── pipeline.py             # orquestra camadas + desduplicação de spans
│   ├── pdf_redactor.py         # apply_redactions + scrub + save não-incremental
│   ├── verifier.py             # re-extração multi-vetor + varredura de bytes
│   └── cli.py                  # analyze / redact / verify / corpus / eval
├── eval/
│   ├── generate_corpus.py      # gera texto+gabarito e renderiza o PDF
│   ├── align.py                # projeta gabarito no texto extraído (difflib)
│   ├── metrics.py              # estrito, relaxado, char-level, latência
│   ├── run_eval.py             # roda as 3 configs de NER e compara
│   ├── datasets/               # PDFs sintéticos + gabarito (gerado)
│   └── report.md               # saída das métricas (gerado)
└── tests/
```

## Tarefas / entregáveis

**Bloco 0 — Container e fundação**
- [ ] `Dockerfile` com Python 3.12, dependências e **modelos gravados na imagem**.
- [ ] `docker-compose.yml` com `network_mode: none` no serviço de execução; override de GPU separado.
- [ ] `Makefile` com os alvos de ciclo de vida; nada roda fora do container.
- [ ] Alvo `make offline-proof`: roda o pipeline completo sem rede e falha se qualquer etapa exigir egress.

**Bloco 1 — Reconhecedores estruturados**
- [ ] `validators.py`: mod-11 (CPF, CNPJ, CNS, PIS, CNH, título de eleitor) e mod-97-10 (numeração CNJ), como funções puras testáveis.
- [ ] Reconhecedor de **CPF** e **CNPJ** (regex + checksum), rejeitando dígitos repetidos e respeitando fronteiras de token.
- [ ] Reconhecedores de **RG, CEP, telefone, e-mail** (regex + palavras-âncora). Telefone valida o DDD contra a lista finita de DDDs válidos.
- [ ] Reconhecedores estendidos: **CNS, PIS/PASEP, processo CNJ, CNH, título de eleitor**.
- [ ] Testes unitários por reconhecedor: válidos, inválidos, falsos positivos plausíveis (números de nota fiscal, matrícula, sequências dentro de outros números).
- [ ] Registrar todos no `AnalyzerEngine` do Presidio com `supported_language="pt"`.

**Bloco 2 — NER e pipeline**
- [ ] `ner.py`: spaCy PT como NER (mapeando `PER`→`PERSON`) e um `EntityRecognizer` customizado que encapsula o pipeline de token-classification do transformer, com janelamento para documentos longos.
- [ ] As três configurações de NER selecionáveis por configuração, para comparação no eval.
- [ ] `pipeline.py`: camadas (regex+checksum → NER → contexto → resolução de sobreposição), com política explícita de precedência: checksum vence NER em caso de conflito.

**Bloco 3 — Layout, redação e verificação**
- [ ] `layout.py`: percorre `rawdict` (blocos → linhas → spans → caracteres) construindo o texto **e** o vetor de bounding boxes alinhado por índice; converte `(início, fim)` em retângulos agrupados por linha. Este é o item de maior risco técnico da fase.
- [ ] `pdf_redactor.py`: `add_redact_annot` → `apply_redactions` → `clean_contents` → `scrub` (metadados, XMP, anotações, campos de formulário, anexos, JavaScript, links, miniaturas) → `save(garbage=4, deflate=True)` **sem incremental save**.
- [ ] `verifier.py`: reabre o PDF final e falha se qualquer valor tarjado aparecer em: texto das páginas, anotações, widgets/AcroForm, anexos embutidos, sumário/outline, metadados, XMP **ou nos bytes brutos do arquivo**. Checagem cruzada com pdfplumber.

**Bloco 4 — Corpus, avaliação e decisão**
- [ ] `generate_corpus.py`: 50 documentos sintéticos distribuídos nos 5 gêneros, com identificadores de checksum válido, **garantindo que nenhum valor de PII seja quebrado entre linhas**. Emite o PDF e o gabarito em JSON.
- [ ] `align.py`: projeta o gabarito do texto-fonte no texto extraído do PDF (difflib), com fallback por busca do valor e contagem de defeitos de corpus.
- [ ] `metrics.py`: F1 estrito (fronteiras e tipo exatos), F1 relaxado (mesmo tipo, sobreposição > 0), cobertura em nível de caractere e **recall agnóstico de tipo** (a métrica que representa risco real de vazamento).
- [ ] `run_eval.py`: roda as 3 configurações de NER, mede latência por página em CPU (e GPU se disponível), gera `report.md`.
- [ ] Documentar a conclusão: qual configuração de NER vai para a Fase 1 e por quê.

## Dados de teste (importante para segurança)
- Nesta fase, usar **exclusivamente dados sintéticos ou fictícios** — identificadores gerados com checksum válido mas sem vínculo com pessoa real, nomes e documentos-modelo inventados. **Nunca** usar documento real sigiloso de cliente no PoC, e muito menos numa KVM de demonstração.
- Se o cliente puder fornecer documentos reais para validação, isso é uma etapa separada, feita **na máquina/ambiente controlado dele**, não no ambiente de dev/demo.
- O diretório `data/` do container é montado como volume e fica no `.gitignore` — nenhum documento entra no repositório.

## Definição das métricas (sem isso os gates não significam nada)
- **F1 estrito**: um acerto exige tipo idêntico **e** fronteiras de caractere idênticas às do gabarito.
- **F1 relaxado**: um acerto exige tipo idêntico e sobreposição de pelo menos um caractere. É a métrica justa para `PERSON`, onde títulos e conectivos ("Dr.", "da", "Jr.") deslocam legitimamente as fronteiras.
- **Recall agnóstico de tipo, em caracteres**: fração dos caracteres de PII do gabarito cobertos por *qualquer* span detectado. É a métrica que corresponde ao risco de vazamento — errar o rótulo mas tarjar o trecho não vaza nada; deixar de tarjar, sim.
- Gates de CPF/CNPJ usam **estrito**. O gate de PERSON usa **relaxado**, com o estrito reportado ao lado.

## Critérios de aceite (o que "pronto" significa)
- CPF/CNPJ com **F1 estrito >= 0,95**. *(Se < 0,95, revisar regex/checksum antes de avançar.)*
- PERSON com **F1 relaxado >= 0,80** em pelo menos uma das três configurações de NER. *(Se nenhuma atingir, isso é um resultado de decisão — não uma falha do PoC — e indica fine-tuning próprio na Fase 1.)*
- Demais entidades com recall medido e documentado (sem meta rígida — servem para calibrar contexto).
- Recall agnóstico de tipo reportado, com o número tratado como o indicador honesto de risco residual.
- Verificação pós-redação passando em 100% dos documentos (zero PII tarjada vazando no PDF final, em nenhum dos vetores checados).
- Pipeline rodando **comprovadamente offline** — `make offline-proof` verde, com o container sem interface de rede.
- `report.md` com as métricas, as latências e uma recomendação explícita para a Fase 1.

## Ambiente de execução
- **Desenvolvimento:** container Docker na máquina local, sem rede em tempo de execução.
- **Demonstração (depois do PoC):** mesma imagem numa KVM na Hostinger, **somente com dados sintéticos** — adequado para mostrar a ferramenta funcionando, **não** para dados reais/sigilosos.
- **Produção (cliente final):** mesma imagem, on-premise no cliente **ou** OCI região Brasil, conforme o perfil do órgão. A escolha do container desde a Fase 0 é justamente o que torna esse trajeto sem retrabalho.

## Nota de soberania a confirmar (não bloqueia a Fase 0)
"RDS" é o nome do serviço gerenciado da AWS (Amazon RDS), inclusive na variante "RDS for Oracle" — mas isso é banco Oracle rodando em infraestrutura da Amazon, ou seja, jurisdição estrangeira. Para soberania real, o equivalente no mundo Oracle é o Oracle Base Database / Autonomous Database **na OCI, região Brasil**. Confirmar esse termo com o cliente antes da fase de produção. A Fase 0 é toda local e não depende dessa decisão.

## Fora de escopo desta fase — não implementar agora
Cofre reversível, criptografia de mapa token->valor, HashiCorp Vault, copiloto Ollama, OCR, UI web, autenticação, precificação. Tudo isso vem depois; misturar aqui atrasa a validação técnica que é o único objetivo da Fase 0.
