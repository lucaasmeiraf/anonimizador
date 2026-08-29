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

| Falta | Fase | Por que importa |
|---|---|---|
| Interface de revisão humana | 1 | sem ela, não há como oferecer garantia sobre nomes em texto livre |
| Processamento em lote com fila e retomada | 1 | hoje é um documento por invocação |
| Cofre de reversibilidade | 2 | é o diferencial competitivo central do projeto |
| Controle de acesso e trilha de auditoria | 2 | exigência de qualquer cliente institucional |
| OCR de PDF escaneado | futuro | grande parte do acervo público é digitalizada |
| Copiloto de configuração (Ollama local) | 3 | reduz o custo de calibrar por cliente |
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
