# 04 — Implantação: passo a passo

Do zero até o pipeline rodando, e daí até o ambiente do cliente.

Três partes:

- **A. Máquina de desenvolvimento** — preparar o host (uma vez).
- **B. Executar e validar a Fase 0** — obter os números dos decision gates.
- **C. Implantar no cliente** — inclusive em ambiente sem internet.

E, no fim, a lista honesta do que ainda **não** é produto.

---

# A. Máquina de desenvolvimento

## Onde os comandos rodam: dentro ou fora do container?

Esta é a dúvida mais natural do desenho, e a resposta é direta:

> **`wsl --install` e `winget install` rodam FORA do container, no PowerShell
> do Windows, como Administrador.**

O motivo é que não existe container ainda. O Docker é *o que cria* containers —
instalá-lo dentro de um seria como pedir a chave do carro que está trancado
dentro do carro. O WSL2 é o motor que o Docker Desktop usa no Windows, então
vem antes dele.

A regra "tudo roda no container" começa a valer **depois** desses dois
comandos. Divisão definitiva:

| Roda no host (fora) | Roda dentro do container |
|---|---|
| `wsl --install` | tudo em Python |
| `winget install Docker.DockerDesktop` | `pytest` |
| `git clone`, `git commit` | geração de corpus |
| `docker compose build` | detecção, redação, verificação |
| `docker compose run ...` | avaliação e relatório |

Os comandos `docker` rodam no host, mas o que eles executam roda dentro. Nunca
será necessário instalar Python, spaCy, torch ou PyMuPDF no Windows.

## Passo 1 — WSL2

No **PowerShell como Administrador**:

```powershell
wsl --install
```

Reinicie a máquina. Depois:

```powershell
wsl --status
```

Deve reportar WSL 2 como versão padrão.

## Passo 2 — Docker Desktop

Ainda no host:

```powershell
winget install -e --id Docker.DockerDesktop
```

Abra o Docker Desktop uma vez para ele finalizar a configuração. Confirme:

```powershell
docker info
docker compose version
```

Se `docker info` responder com a versão do servidor, o host está pronto. **É a
última coisa instalada no Windows.**

## Passo 3 — Obter o projeto

```powershell
cd C:\Users\<voce>\Desktop\Altus\Projetos\Anonimizador
git status
```

O repositório já está inicializado, com o commit da Fase 0.

---

# B. Executar e validar a Fase 0

## Passo 4 — Construir a imagem

```powershell
cd anonimizador-poc
.\run.ps1 build
```

O que acontece, nesta ordem: instala o Python 3.12 e as dependências, baixa o
`pt_core_news_lg` e os dois checkpoints de NER, **e só então** liga
`HF_HUB_OFFLINE=1`. É a única etapa da vida do sistema que usa rede.

Espere 10–25 minutos na primeira vez e cerca de 4 GB de imagem. Builds
seguintes reaproveitam as camadas e são rápidos, desde que `requirements.txt`
não mude.

Se falhar por timeout de download, repita — as camadas já concluídas são
reaproveitadas.

## Passo 5 — Testes rápidos

```powershell
.\run.ps1 test
```

Roda tudo que não precisa carregar modelo: checksums, resolução de
sobreposição, alinhamento de gabarito, métricas, layout e redação. Deve levar
menos de um minuto.

**Se algo falhar aqui, pare.** São os fundamentos; nada acima deles vai fazer
sentido.

## Passo 6 — Testes completos

```powershell
.\run.ps1 test-all
```

Inclui os marcados `slow`, que instanciam o Presidio com o spaCy e exercitam os
reconhecedores no motor real.

## Passo 7 — Gerar o corpus

```powershell
.\run.ps1 corpus
```

Produz 50 PDFs sintéticos e seus gabaritos em `eval/datasets/`, distribuídos
pelos cinco gêneros. Semente fixa: dois runs geram exatamente os mesmos
documentos.

Confira um deles a olho nu antes de confiar nas métricas — vale abrir
`eval/datasets/contrato-000.pdf` e ver se parece um contrato.

## Passo 8 — Avaliação

```powershell
.\run.ps1 eval
```

Roda as três configurações de NER sobre os 50 documentos, mede detecção e
latência, redige, verifica nos 10 vetores e escreve `eval/report.md`.

Em CPU, conte com algo entre 20 e 60 minutos — o `bertimbau-harem` é um modelo
large. Para iterar rápido durante ajustes:

```powershell
.\run.ps1 eval-fast     # só spaCy
```

Com GPU:

```powershell
.\run.ps1 gpu-build
.\run.ps1 gpu-eval
```

### Como ler o `report.md`

| Seção | O que decidir |
|---|---|
| Decision gates | CPF e CNPJ passaram de 0,95? PERSON passou de 0,80 em alguma config? |
| Cobertura e latência | a cobertura de caracteres é o risco residual real; a latência dimensiona o hardware |
| Verificação pós-redação | **qualquer** vazamento reprova a fase, sem discussão |
| Detalhamento | onde estão os falsos positivos, por entidade |
| Recomendação | qual configuração levar para a Fase 1 |

**Expectativa registrada antes da primeira execução:** CPF e CNPJ passam com
folga; `spacy` fica bem abaixo de 0,80 em PERSON; `bert-lenerbr` deve liderar
em petição e contrato e sofrer em prontuário e RH. Se a primeira execução
contradisser isso, a suspeita deve recair primeiro sobre bug de integração, não
sobre os modelos.

## Passo 9 — Prova de offline

```powershell
.\run.ps1 offline-proof
```

Gera um corpus mínimo, carrega os modelos, **sabota o módulo `socket`** e só
então processa os documentos. Qualquer tentativa de conexão vira exceção. Somado
ao `network_mode: none` do compose, são duas provas independentes.

Guarde a saída: é o artefato que demonstra a restrição de soberania para um
cliente ou auditor.

## Passo 10 — Demonstração com um documento

```powershell
.\run.ps1 demo
```

Ou, com um documento seu (coloque-o em `.\data\`):

```powershell
docker compose run --rm cli redact --in /app/data/meu.pdf --out /app/out/meu.redigido.pdf
```

Saída esperada: contagem de entidades detectadas e redigidas, resultado do
saneamento, e o veredicto da verificação.

> **A saída da verificação imprime os valores vazados quando encontra algum.**
> É intencional — sem isso o diagnóstico seria impossível. Em produção, essa
> saída precisa ir para um canal de auditoria restrito, nunca para log de
> aplicação. Ver [`02-requisitos.md`](02-requisitos.md), RS-04.

**Nesta fase, use apenas documentos sintéticos.** Documento real de cliente é
etapa separada, no ambiente controlado dele.

---

## Passo 10b — Abrir a interface no navegador

O `redact` acima é a linha de comando. A **tela de revisão** — onde uma pessoa
confere o que a máquina propôs e assina embaixo — é outro caminho, e é o
produto de verdade.

### 1. Subir

Na pasta `anonimizador-poc`:

```powershell
.un.ps1 ui          # Windows
make ui               # Linux, macOS, WSL
```

O comando **não** abre o navegador sozinho, e **não** devolve o prompt
imediatamente: ele sobe dois containers e fica de pé. Na primeira subida são
cerca de 30 segundos carregando ~1 GB de pesos do NER — a tela só responde
depois disso.

Pronto quando isto devolver `{"ok":true,...}`:

```powershell
curl http://127.0.0.1:8000/api/saude
```

### 2. Abrir

Digite no navegador:

```
http://127.0.0.1:8000
```

Não é `localhost:8000` por acaso — é o mesmo endereço, mas o `ui-proxy`
publica em `127.0.0.1` de propósito: a interface só é alcançável **desta
máquina**. Não existe autenticação ainda (Fase 4), e é esse endereço que faz
as vezes dela.

### 3. Usar

1. **Arraste um PDF** para a área central, ou clique para escolher. Só PDF com
   texto — digitalização sem OCR é recusada com explicação, porque uma tela
   vazia faria você concluir que o documento está limpo.
2. **Escolha o que fica no lugar do dado** — primeiro bloco da barra lateral
   direita:
   - **Tarja preta**: o valor some e o espaço fica coberto.
   - **Código no lugar** (`[P-7F3A]`): o valor some e um código ocupa o lugar,
     preservando que havia um ator, de que tipo, e que é o mesmo ator dos
     outros trechos. É o formato para mandar a uma análise automatizada.

   Nos dois casos o valor é removido do arquivo, sem chave e sem volta.
3. **Revise.** Clique numa tarja para desligá-la; digite ou selecione um
   trecho que faltou; ligue e desligue classes inteiras na lista.
4. **Aprove.** O PDF só é gerado nesse momento, e só é liberado para download
   se passar na verificação — 10 vetores, ou 11 quando há código.

> **Valor curto não comporta código.** `[CEP-2C81]` ocupa 48,0pt e um CEP
> deixa 43,0pt de espaço; `[DATA-9E44]` ocupa 53,0pt contra 45,0pt de
> `12/03/2026`. Em modo código, deixe `CEP` e `DATE_TIME` em tarja na lista —
> a tela avisa. Sem isso o documento é **reprovado inteiro** na aprovação, de
> propósito: a alternativa seria entregar a linha deformada em silêncio.

### 4. Derrubar

```powershell
.un.ps1 ui-down     # ou:  docker compose down
```

### Quando não abre

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `failed to connect to the docker API` | Docker Desktop não está rodando | abra o Docker Desktop e espere ficar verde |
| Navegador diz "recusou a conexão" | ainda carregando o modelo | espere o `/api/saude` responder |
| `port is already allocated` | outra coisa na 8000 | `docker compose down` e suba de novo |
| A tela abre mas parece a versão antiga | cache do navegador | recarregue; os estáticos são carimbados com a data de modificação, então isso não deveria acontecer — se acontecer, é defeito |

---

# C. Implantação no cliente

## Passo 11 — Levantamento prévio

Antes de qualquer instalação, responda com o cliente as perguntas da seção 7 de
[`02-requisitos.md`](02-requisitos.md). Duas mudam a arquitetura inteira:

- **Os PDFs têm texto selecionável ou são digitalizados?** Se forem
  digitalizados, o produto **não funciona** hoje — falta OCR. Descobrir isso na
  implantação é tarde demais.
- **Qual a classificação dos dados?** Ultrassecreto não pode ir para nuvem
  nenhuma; sigiloso e reservado têm exigências de infraestrutura próprias.

## Passo 12 — Resolver as pendências que bloqueiam entrega

Duas travas jurídicas, ambas em [`02-requisitos.md`](02-requisitos.md):

- **RN-04 — PyMuPDF é AGPL-3.0 ou licença comercial da Artifex.** Distribuir o
  produto a um cliente dispara a obrigação. Ou se compra a licença comercial,
  ou se distribui o produto sob AGPL, ou se troca a biblioteca. **Decidir antes
  da proposta comercial**, porque a licença comercial é custo recorrente que
  precisa estar no preço.
- **RN-05 — o checkpoint `ner-bert-base-cased-pt-lenerbr` não declara
  licença.** Sem declaração não há concessão de uso. Ou se obtém do autor uma
  declaração expressa, ou se refaz o fine-tuning a partir do BERTimbau (MIT).

Nenhuma das duas impede desenvolvimento. As duas impedem entrega.

## Passo 13 — Validação com documentos reais, no ambiente do cliente

Não traga documentos do cliente para a sua máquina. Leve a ferramenta até eles.

1. Instale Docker no ambiente do cliente (passos 1 e 2, ou o equivalente Linux).
2. Transfira a imagem (passo 14, se não houver internet).
3. Rode `analyze` sobre uma amostra representativa — 20 a 50 documentos que
   cubram os tipos que eles realmente processam.
4. **Alguém do cliente** revisa a saída e aponta o que ficou de fora. Só quem
   conhece o documento sabe o que é sensível nele.
5. Ajuste as palavras-âncora conforme [`03-configuracao.md`](03-configuracao.md),
   seção 4.1.
6. Repita até o cliente aceitar a taxa de erro **por escrito**, com o número
   medido, não com uma impressão.

O passo 6 é o que protege os dois lados. Sem número acordado, qualquer falso
negativo futuro vira disputa.

## Passo 14 — Ambiente sem internet (air-gap)

Construa a imagem numa máquina com rede, exporte, transporte, importe:

```powershell
# máquina com rede
docker compose build
docker save anonimizador-poc:fase0 -o anonimizador-fase0.tar

# transporte físico do .tar (~4 GB)

# máquina do cliente, sem rede
docker load -i anonimizador-fase0.tar
```

Copie junto o `docker-compose.yml`, o `run.ps1` (ou o `Makefile`) e a pasta
`docs/`. Não é preciso copiar `src/` se você remover os bind mounts do compose —
o código já está dentro da imagem. Manter os bind mounts é útil em
homologação, para ajustar reconhecedores sem rebuild.

Confirme a integridade após a carga:

```powershell
docker compose run --rm offline-proof
```

## Passo 14b — Comandos do dia a dia

Referência rápida. Todos rodam de `anonimizador-poc/`; no Windows sem `make`,
troque por `.\run.ps1 <alvo>`.

| Comando | O que faz | Precisa de rede? |
|---|---|---|
| `make build` | constrói a imagem | **sim** — única etapa |
| `make ui` | interface em `127.0.0.1:8000` | não |
| `make ui-llm` | interface **+** serviço de análise por LLM | o `analise`, sim |
| `make ui-down` | derruba tudo | não |
| `make ui-proof` | a porta responde **e** o `ui` não tem egress | não |
| `make llm-proof` | o `ui` segue sem egress; o `analise` não vê documento | o `analise`, sim |
| `make offline-proof` | o pipeline roda sem interface de rede | não |
| `make test` | 296 testes rápidos | não |
| `make test-all` | inclui os 9 marcados `slow` (carregam modelo) | não |
| `make eval` | avaliação nas 3 configurações de NER (~5,5 min) | não |
| `make diagnostico` | por que `PERSON` vaza | não |
| `make corpus` | regenera os 50 PDFs sintéticos | não |

Pela CLI, um documento por vez:

```bash
docker compose run --rm cli redact        --in /app/data/x.pdf --out /app/out/x.pdf
docker compose run --rm cli pseudonimizar --in /app/data/x.pdf --out /app/out/x.txt
docker compose run --rm cli analyze       --in /app/data/x.pdf
```

Nos dois primeiros, **se a verificação reprovar, nada é escrito** e o código de
saída é 1. Não existe arquivo reprovado em disco, por desenho.

### A chave do OpenRouter

```bash
cp .env.example .env     # cole a chave em OPENROUTER_API_KEY
make ui-llm
```

O `.env` é ignorado pelo git **e** pelo Docker. A chave é lida apenas pelo
serviço `analise`; o `ui`, que processa o documento, não a recebe.

### Armadilha: mexeu no código, reinicie o `ui`

O compose monta `./src` no container, mas isso **não** recarrega o processo em
execução. O `uvicorn` sobe sem `--reload`, e há dois níveis de cache:

1. os módulos são importados uma vez, na subida;
2. o `DetectionPipeline` é construído uma vez e guardado em `_pipeline` — e
   cada `ChecksumRecognizer` copia sua lista de âncoras **no momento da
   construção**.

Consequência prática, e ela já custou uma sessão inteira de depuração em
2026-09-05: depois de editar um reconhecedor, `docker compose exec ui python -c
"..."` mostra o código **novo** (é um processo novo) enquanto a interface
continua servindo o **antigo**. Os dois discordam, e o teste parece falhar sem
motivo.

```bash
docker compose restart ui
docker compose logs -f ui     # espere "pipeline pronto" (~30 s)
```

Regra: **mexeu em `src/`, reinicie o `ui` antes de testar pela interface.** Os
alvos `make test` e `make eval` não sofrem disso — sobem processo novo a cada
execução.

---

## Passo 15 — Operação

Estrutura mínima no ambiente do cliente:

```
/opt/anonimizador/
├── docker-compose.yml
├── data/     <- entrada  (política de retenção do cliente)
├── out/      <- saída
└── docs/
```

Processar um lote:

```bash
for f in data/*.pdf; do
  docker compose run --rm cli redact --in "/app/$f" --out "/app/out/$(basename "$f")"
done
```

O container não tem estado: os documentos podem ser processados em paralelo
por múltiplas instâncias, limitado por CPU e RAM. O dimensionamento sai da
latência medida no passo 8.

Três disciplinas operacionais que valem mais do que parecem:

1. **Descarte de `data/`** conforme a política do cliente. Documento processado
   que fica no volume é risco acumulado, não conveniência.
2. **A verificação nunca é opcional.** Se ela reprovar, o documento de saída não
   deve ser entregue — mesmo que "pareça" correto.
3. **Revisão humana** enquanto o gate de PERSON não estiver satisfeito com
   folga no domínio do cliente.

---

# O que ainda não é produto

Sendo direto: **o que existe hoje é um pipeline de linha de comando validado
por métricas, não um produto.** Vender o que está aqui como produto final seria
prometer o que não existe. O que falta, em ordem de dependência:

> Atualizado em 2026-09-05. Três linhas desta tabela mudaram de estado, e uma
> saiu: o **cofre de reversibilidade** foi encerrado, não adiado. Guardar o
> original com controle de acesso resolve "voltar atrás" sem nenhum custo
> jurídico, enquanto guardar uma chave devolveria o arquivo de saída para
> dentro do alcance da LGPD. Ver `goal-fase-2.md` §5, Bloco B0.

| Falta | Fase | Por que importa |
|---|---|---|
| ~~Interface de revisão humana~~ | 1 | ✅ existe; falta medir o gate de usabilidade com pessoas |
| Processamento em lote com fila e retomada | 1 | hoje é um documento por invocação |
| ~~Cofre de reversibilidade~~ | — | ⛔ **encerrado**; guardar o original resolve, sem custo jurídico |
| **Autenticação e controle de acesso** | — | **não existe nenhum**. Ver abaixo: é o que bloqueia mais de uma pessoa usar |
| Trilha de auditoria do documento | 4 | existe para envio externo; falta para upload, revisão e download |
| OCR de PDF escaneado | futuro | grande parte do acervo público é digitalizada |
| ~~Copiloto de configuração~~ | 3 | ✅ análise por LLM externa existe; falta tela |
| Assessment de risco de reidentificação documentado | 4 | a ANPD pode exigir em fiscalização |
| Empacotamento, instalador, atualização | 4 | hoje a implantação é manual |

## Caminho recomendado até a primeira venda

1. **Fechar a Fase 0** — rodar o eval, corrigir os defeitos de integração,
   registrar os números.
2. **Resolver RN-04 e RN-05** — as duas travas jurídicas. Podem ser feitas em
   paralelo ao desenvolvimento, mas não depois da proposta.
3. **Fase 1: revisão humana e lote.** É o que transforma o pipeline em
   ferramenta operável.
4. **Piloto com um cliente**, com documentos reais no ambiente dele e taxa de
   erro acordada por escrito.
5. **Fase 2: cofre.** É o diferencial, e é também o item de maior risco de
   prazo do projeto inteiro — reserve folga.

Antes do passo 4, o material comercial precisa estar alinhado com RN-01 e
RN-02: pseudonimização reversível **não** tira o dado do escopo da LGPD.
Prometer isso é erro jurídico, e é o tipo de erro que um cliente institucional
detecta na primeira reunião técnica.
