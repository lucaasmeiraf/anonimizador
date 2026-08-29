# Anonimizador — PoC Fase 0

Detecção e **redação verdadeira** de dados pessoais (LGPD) em PDFs de texto em
português-BR, rodando **100% local, dentro de um container, sem rede**.

Esta é a Fase 0: uma prova de conceito com veredicto numérico, não um produto.
O escopo, os decision gates e os critérios de aceite estão em
[`../goal-fase-0.md`](../goal-fase-0.md).

---

## Pré-requisito único

**Docker Desktop.** Nada é instalado no host — nem Python, nem modelos.
No Windows, o Docker Desktop precisa do backend WSL2:

```powershell
wsl --install            # requer terminal como Administrador + reinício
winget install -e --id Docker.DockerDesktop
```

Depois de reiniciar, confirme com `docker info`.

## Uso

```powershell
.\run.ps1 build           # constrói a imagem (única etapa com rede)
.\run.ps1 test            # testes rápidos, sem carregar modelos
.\run.ps1 corpus          # gera 50 PDFs sintéticos + gabarito
.\run.ps1 eval            # avaliação nas 3 configurações de NER -> eval/report.md
.\run.ps1 offline-proof   # prova que o pipeline roda sem rede
```

Em Linux/macOS/WSL, `make build`, `make eval` etc. — os alvos são os mesmos.

Redigir um documento específico:

```powershell
docker compose run --rm cli redact --in /app/data/meu.pdf --out /app/out/meu.redigido.pdf
```

`./data` e `./out` são montados no container. **`./data` está no `.gitignore`** —
nenhum documento entra no repositório.

---

## Como funciona

```
PDF ──► layout.py ──► texto + caixa de cada caractere
                          │
                          ▼
              ┌───────────────────────┐
              │ 1. regex + checksum   │  CPF, CNPJ, CNS, PIS, CNJ, CNH, título
              │ 2. NER local          │  PERSON, ORG, LOCAL, DATE
              │ 3. contexto (lemas)   │  "CPF nº", "portador do RG"
              │ 4. resolve overlaps   │  checksum vence NER
              └───────────────────────┘
                          │  spans (offsets de caractere)
                          ▼
        layout.rects_for() ──► retângulos na página
                          │
                          ▼
     pdf_redactor ──► apply_redactions + clean_contents + scrub + save não-incremental
                          │
                          ▼
     verifier ──► 10 vetores re-checados; qualquer sobra REPROVA
```

### As quatro decisões que sustentam o desenho

**Checksum antes de modelo.** CPF, CNPJ, CNS, PIS, processo CNJ e título de
eleitor têm dígito verificador. Um acerto de checksum é evidência matemática,
não estatística: não degrada com o domínio do documento, não custa latência e
não depende de treinamento. Por isso a precedência em `config.PRECEDENCIA`
sempre coloca checksum acima de NER.

**O mapeamento offset→retângulo é feito uma vez, não por busca.**
`page.search_for()` seria o caminho óbvio e é uma armadilha: o texto do PDF é
fatiado em spans por mudança de fonte, a hifenização e o kerning fazem a
string extraída divergir da desenhada, e ocorrências repetidas voltam sem
identidade. `layout.py` percorre o `rawdict` uma única vez construindo o texto
**e** o vetor de caixas indexado pelo mesmo offset. Qualquer span vira
retângulo por consulta direta. Ver a discussão completa no cabeçalho do
módulo.

**Redação é mais do que o content stream.** Remover o texto da página e parar
aí é o erro que produziu os vazamentos públicos famosos de documentos
"tarjados". O mesmo dado costuma existir em metadados, XMP, anotações, campos
AcroForm, anexos, sumário, miniaturas e em objetos órfãos de revisões
incrementais. `pdf_redactor.py` limpa todos; `verifier.py` confere de forma
independente, incluindo os streams descomprimidos e os bytes brutos do
arquivo.

**Offline é provado, não afirmado.** Os modelos são gravados na imagem durante
o build — o único momento com rede. Em execução, o compose usa
`network_mode: none` e o comando `offline-proof` ainda sabota o módulo
`socket` in-process, de modo que qualquer tentativa de egress vira exceção em
vez de vazamento silencioso.

---

## Documentação

| Documento | Conteúdo |
|---|---|
| [`docs/01-inventario-marco-zero.md`](docs/01-inventario-marco-zero.md) | dependências, versões, licenças, modelos, estado de verificação |
| [`docs/02-requisitos.md`](docs/02-requisitos.md) | requisitos e critérios de aceite |
| [`docs/03-configuracao.md`](docs/03-configuracao.md) | todos os pontos de ajuste |
| [`docs/04-implantacao.md`](docs/04-implantacao.md) | passo a passo, do host ao ambiente do cliente |

## Estrutura

| Caminho | O que é |
|---|---|
| `src/anonimizador/validators.py` | dígitos verificadores (mod-11, mod-97-10) — funções puras |
| `src/anonimizador/fakes.py` | geradores sintéticos com checksum válido |
| `src/anonimizador/recognizers/` | um reconhecedor Presidio por tipo de identificador |
| `src/anonimizador/ner.py` | spaCy e transformer como reconhecedores; janelamento |
| `src/anonimizador/spans.py` | modelo de span e resolução de sobreposição (lógica pura) |
| `src/anonimizador/layout.py` | ponte offset de caractere → retângulo |
| `src/anonimizador/pipeline.py` | montagem do AnalyzerEngine |
| `src/anonimizador/pdf_redactor.py` | redação + saneamento |
| `src/anonimizador/verifier.py` | verificação em 10 vetores |
| `eval/generate_corpus.py` | corpus sintético + gabarito exato |
| `eval/align.py` | projeta o gabarito no texto extraído |
| `eval/metrics.py` | F1 estrito, F1 relaxado, cobertura de caracteres |
| `eval/run_eval.py` | harness e geração do `report.md` |

## Configurações de NER comparadas

| Nome | Modelo | Domínio |
|---|---|---|
| `spacy` | `pt_core_news_lg` | genérico — baseline |
| `bert-lenerbr` | `pierreguillou/ner-bert-base-cased-pt-lenerbr` | jurídico (LeNER-Br) |
| `bertimbau-harem` | `marquesafonso/bertimbau-large-ner-selective` | geral (HAREM selective) |

`ANON_NER` troca a configuração padrão; `ANON_DEVICE=cuda` usa GPU.

> `neuralmind/bert-base-portuguese-cased`, citado no documento de ideia
> original, é um modelo de linguagem **sem cabeça de NER** — usá-lo exigiria
> fine-tuning próprio, o que está fora do escopo desta fase. Os dois
> checkpoints acima já vêm ajustados para reconhecimento de entidades.

---

## Dados

Corpus **100% sintético**, semeado e reprodutível, em cinco gêneros: contrato,
petição judicial, prontuário, ficha de RH e ofício administrativo. Os
identificadores têm checksum válido — sem isso não exercitariam os
reconhecedores — mas nenhum tem vínculo com pessoa real.

**Nunca** use documento real sigiloso neste PoC, e muito menos numa VM de
demonstração. Validação com documentos reais é uma etapa separada, no ambiente
controlado do cliente.
