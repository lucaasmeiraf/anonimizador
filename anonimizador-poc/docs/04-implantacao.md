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
.\run.ps1 ui          # Windows
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

A barra do topo mostra as etapas — **Enviar → Revisar → Verificar →
Exportar** — e, na revisão, o botão principal, sempre visível.

1. **Enviar.** Escolha para que é o documento — *Publicar ou compartilhar*
   (tarja preta) ou *Enviar para análise por IA* (código no lugar do dado) —
   e clique em **Selecionar PDF**, arraste o arquivo para qualquer ponto da
   janela, ou cole com `Ctrl+V` (`Ctrl+O` abre o seletor). A escolha só define
   o formato inicial.
   - Digitalização sem texto é recusada com explicação, porque uma tela vazia
     faria você concluir que o documento está limpo. PDF com senha também é
     recusado; salve uma cópia sem a proteção.
   - PDF com algumas páginas digitalizadas segue para a revisão, com aviso de
     quais páginas não puderam ser analisadas.
   - "Como garantimos isso", abaixo do cartão, reúne os detalhes técnicos:
     modelo de detecção, camadas da verificação e o que muda no PDF.
2. **Revisar.** O documento aparece com cada dado marcado pela cor da
   categoria. Na barra acima dele: *Anonimizado*, *Original* ou *Comparar*
   (lado a lado), *Ver como ficará* (`P`) e zoom. No painel à direita:
   - **Detecções** — categorias em português, agrupadas, com a contagem
     "X de Y". Expanda uma categoria para ver os valores e as páginas; clique
     num valor para ir até ele. `J`/`K` (ou `↓`/`↑`) andam entre as
     ocorrências e `Espaço` liga ou desliga a que está em foco. O campo
     *Buscar ou adicionar termo* acha uma detecção ou anonimiza um termo em
     todo o documento.
   - **Ajustes** — o formato de substituição, tarja ou código. Nos dois casos
     o valor é removido do arquivo, sem chave e sem volta.

   Clique numa marcação para *Não anonimizar esta*, *Não anonimizar nenhuma
   igual* ou *Mudar categoria*. Selecione um trecho do documento para
   anonimizá-lo. O `?` no topo lista os atalhos.
3. **Verificar.** A cada alteração, a verificação que libera o arquivo roda de
   novo sobre a versão atual, e o selo no topo do painel diz se algum dado
   marcado ainda ficaria legível. Clique nele para ver onde, com *Ir para a
   página* e *Anonimizar todas*. Enquanto houver pendência, o botão principal
   vira "Revisar N pendências".
4. **Exportar.** Na aba *Exportar*: o checklist da verificação, o que você
   vai receber (PDF anonimizado, texto com códigos para IA, envio para
   análise por IA quando `make ui-llm` está no ar) e o que muda no PDF além
   dos dados. **Gerar e baixar** gera o arquivo do zero e só o libera se ele
   passar na verificação — 10 vetores, ou 11 quando há código.

> **Valor curto não comporta código.** `[CEP-2C81]` ocupa 48,0pt e um CEP
> deixa 43,0pt de espaço; `[DATA-9E44]` ocupa 53,0pt contra 45,0pt de
> `12/03/2026`. Desde 2026-09-23 esses trechos saem em **tarja preta** em vez
> de reprovar o documento, e a tela diz quantos são — por categoria, na aba
> *Ajustes* — antes de você exportar. O texto para IA usa código em todos.

### 4. Depois de alterar alguma coisa

**Na dúvida, um comando:**

```powershell
.\run.ps1 ui-recarregar     # make ui-recarregar
```

Ele recria os containers, espera a UI responder e **diz em que modo subiu**.
Custa os ~30 s do modelo carregando, e não exige decidir nada.

A regra, para quando você quiser economizar esse tempo:

| O que você mudou | O que precisa |
|---|---|
| `CSS`, `JS`, `HTML` | **nada** — recarregue a página. Os estáticos levam carimbo de versão pela data de modificação, então o cache não atrapalha |
| `.env` ou `docker-compose.yml` | `.\run.ps1 ui` já basta: a configuração resolvida mudou, e o compose recria sozinho |
| Código Python | **recriar** — o uvicorn carrega os módulos na subida e não roda em modo reload |
| Migração de banco | `.\run.ps1 ui-recarregar`, e aplique a migração antes |

> **Por que o serviço não roda em `--reload`.** Ele carrega ~1 GB de pesos do
> NER na subida, e o reload os recarregaria a cada arquivo salvo. O
> `ui-recarregar` explícito é mais rápido na prática que um reload que dispara
> sozinho a cada `Ctrl+S`.

### 5. Ligar o login

O padrão é **modo local**: a porta sai em `127.0.0.1` e o perímetro é o
endereço. Para exigir identificação:

```powershell
# 1. crie o usuario ANTES de ligar, ou voce se tranca do lado de fora
.\run.ps1 usuario -Email voce@exemplo.org -Inquilino "Seu Orgao"
#    anote a senha: ela aparece uma vez e vale para um login so

# 2. no .env
#    ANON_EXIGIR_LOGIN=1

# 3. recarregue
.\run.ps1 ui-recarregar
```

A saída do passo 3 confirma: `modo: COM LOGIN`. O primeiro acesso cai direto
na tela de troca de senha.

Para voltar ao modo local, tire o `1` do `.env` e recarregue.

### 6. Derrubar

```powershell
.\run.ps1 ui-down     # ou:  docker compose down
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

# C2. Mostrar o sistema sem hospedar

O caminho mais rápido para alguém **fora da sua rede** usar o sistema não é um
VPS: é um túnel temporário a partir da sua própria máquina.

```powershell
.\run.ps1 tunel          # make tunel
```

O `cloudflared` abre uma conexão **de dentro para fora** e devolve uma URL
`trycloudflare.com` aleatória. Nenhuma porta é aberta no seu roteador,
nenhuma conta é necessária, e a URL morre quando você fecha o terminal.

Instale uma vez:

```powershell
winget install --id Cloudflare.cloudflared
```

## A trava, e por que ela existe

O alvo **recusa rodar em modo local**. Sem login, publicar aquela URL deixaria
qualquer pessoa subir documento, e quem tivesse um `doc_id` abriria o
documento de outra. A recusa é o que impede a pressa de virar vazamento.

Antes de usar o túnel, portanto:

```powershell
.\run.ps1 usuario -Email voce@exemplo.org -Inquilino "Seu Orgao"
# ANON_EXIGIR_LOGIN=1 no .env
.\run.ps1 ui-recarregar
```

## Administrar acessos pela tela

Quem é `dono` do inquilino vê um botão de engrenagem no topo. Lá dentro:

- **a lista de quem tem acesso**, com papel, último acesso e se a pessoa já
  trocou a senha do primeiro login;
- **criar acesso** — e-mail mais papel (`operador` ou `dono`);
- **nova senha** para alguém, em dois toques no botão (o segundo rótulo diz
  a consequência: as sessões daquela pessoa caem);
- **desativar e reativar**.

### Três regras que a tela não pode afrouxar

**Não existe autocadastro.** Ninguém cria a própria conta — o dono cria e
entrega por fora. A tabela `solicitacao` existe no esquema para o dia em que
houver convite, e continua sem rota. `tests/test_usuarios.py` percorre
`app.routes` e falha se alguma rota de cadastro aparecer.

**Quem cria não escolhe a senha.** Ela é sorteada, aparece **uma vez** e vale
para um login só. Não é comodidade: senha escolhida por quem provisiona é
fraca e reaproveitada, e — o que decide — faria o administrador saber a senha
com que a pessoa vai trabalhar. É o que separa *administrar acesso* de *poder
entrar como a outra pessoa*.

**O dono não alcança outro inquilino, nem cria `plataforma`, nem se
desativa.** Os três são recusados no servidor, não só escondidos na tela.

> Esconder o botão para quem não é dono é cortesia; a trava é o **403** do
> servidor. `usuarios.py` decide, `app.py` traduz em código de status.

## Verificado em 2026-11-04

O túnel rápido foi aberto e testado de fora, da internet:

```
GET /api/saude      -> 200   TLS válido (certificado da Cloudflare)
GET /               -> 200   a tela de entrada abre
GET /api/eu         -> 401   exige sessão
GET /api/doc/<id>   -> 401   protegido
GET /api/usuarios   -> 401   administração protegida
```

E o fluxo inteiro de administração, pela URL pública: login do dono → troca
obrigatória → criar operador → senha de 24 caracteres devolvida uma vez →
lista mostrando quem tem acesso.

### Atualizar sem derrubar o túnel

`{ps} ui-recarregar` recria **apenas o `ui`**. O `ui-proxy` fica de pé de
propósito: é ele que segura a porta publicada, e recriá-lo derrubaria um
túnel apontado para `127.0.0.1:8000` — a URL que você já mandou para alguém.

O proxy resolve `ui` por DNS a cada conexão, então acha o container novo
sozinho. Só as requisições em voo se perdem. Verificado em 2026-11-04: o
túnel sobreviveu ao reload e serviu a rota nova em seguida.

A trava de login vale do lado de fora exatamente como vale em `127.0.0.1` —
que é o que se precisava saber antes de mandar a URL para alguém.

## URL fixa: o túnel nomeado

O túnel rápido sorteia a URL e **ela muda toda vez que você reinicia**. Para
um endereço estável, no seu domínio, é o túnel **nomeado** — e ele traz junto
duas coisas que o rápido não tem.

Exige conta na Cloudflare (gratuita) e o DNS do domínio apontado para lá.

```bash
cloudflared tunnel login                       # abre o navegador, uma vez
cloudflared tunnel create anonimizador
cloudflared tunnel route dns anonimizador anonimizador.seudominio.com.br
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: anonimizador
credentials-file: /caminho/para/<id-do-tunel>.json
ingress:
  - hostname: anonimizador.seudominio.com.br
    service: http://127.0.0.1:8000
    originRequest:
      # A deteccao de um documento longo passa de um minuto: o padrao
      # derrubaria a conexao no meio.
      connectTimeout: 30s
      noTLSVerify: false
  - service: http_status:404
```

```bash
cloudflared tunnel run anonimizador
```

### E aqui está o ganho que não é o nome bonito

Com túnel nomeado você pode pôr o **Cloudflare Access** na frente — uma
trava por e-mail, antes de a requisição sequer chegar à aplicação. Isso
resolve, sem VPS e sem custo, as duas pendências que o `DEFEITOS.md` D-04
deixa abertas:

| Pendência do D-04 | Resolvida por |
|---|---|
| Sem TLS | certificado da Cloudflare, automático |
| Sem limite por IP | limite na borda, antes de alcançar o `ui-proxy` |

Some também o problema de o `forward.py` apenas *degradar* sob pressão: o
tráfego hostil para na borda da Cloudflare e nunca chega à sua máquina.

**Isto torna o túnel nomeado uma alternativa séria ao VPS**, não só um
atalho de demonstração — para um cliente só, com você hospedando na sua
infraestrutura. O que ele **não** resolve continua igual: a trilha (Bloco 4)
e a RN-04, no Passo D7.

## Quando usar cada caminho

| | Túnel rápido | Túnel nomeado | VPS (Parte D) |
|---|---|---|---|
| Esforço | minutos | ~1 hora | meio dia |
| URL | aleatória, some ao fechar | **seu domínio**, fixa | seu domínio, fixa |
| Sua máquina ligada | sim | sim | não |
| TLS | sim (Cloudflare) | sim (Cloudflare) | você configura (D6) |
| Limite por IP | não | **sim**, com Access | você configura (D6) |
| Serve para | demonstrar, com você por perto | um cliente, você hospedando | vários, independente de você |

Para **apresentar a um cliente**, o túnel costuma ser melhor: a pessoa usa de
verdade, no navegador dela, e você revoga fechando o terminal. Some também a
questão da AGPL do Passo D7, porque não há serviço público oferecido a
terceiros de forma duradoura — mas isso é leitura, não parecer (RN-07).

---

# D. Hospedar num VPS

Escrito em 2026-11-03 para um VPS da Hostinger, mas vale para qualquer
servidor com Docker.

> **Antes de tudo, o que muda de natureza.** Até aqui o perímetro de
> segurança era o endereço: a porta sai em `127.0.0.1` e só quem está na
> máquina alcança. Num VPS isso deixa de valer, e três coisas que eram
> opcionais passam a ser obrigatórias: **login**, **TLS** e **proxy reverso**.
> O `HOMOLOGACAO.md` §4 ainda lista "servidor compartilhado na rede" como
> *não — ainda não*, e os passos abaixo cobrem o que falta do lado técnico.
> O que eles **não** cobrem está no Passo D7.

## Clonar não basta

A pergunta natural é se basta `git clone`. Não basta, e o motivo é a imagem:

| O que o repositório tem | O que ele **não** tem |
|---|---|
| código, compose, migrações, documentação | a imagem Docker (~4 GB) |
| `.env.example` | o `.env` (ignorado pelo git, com as senhas) |
| | os modelos de NER, que são **assados na imagem** |

A imagem carrega torch CPU, o spaCy `pt_core_news_lg` e dois checkpoints BERT
— é o único momento do sistema com rede, e é por isso que o pipeline roda
offline depois. Construí-la é obrigatório, no VPS ou fora dele.

## O caminho curto: um script

Os passos D2 a D5 estão num script idempotente — rodar duas vezes não
estraga nada:

```bash
scp -r anonimizador-poc usuario@vps:~/      # ou git clone no VPS
ssh usuario@vps
cd anonimizador-poc && bash provisionar-vps.sh
```

Ele confere a máquina, instala o Docker, cria o `.env` com senha de banco
sorteada, constrói a imagem, aplica as migrações, pergunta o primeiro
usuário, liga o login e sobe tudo com `restart: unless-stopped`. Termina
rodando a prova de perímetro.

**Ele para antes do D6** — proxy reverso e TLS —, que depende do seu domínio.
E não abre porta no firewall nem publica em `0.0.0.0`: a porta continua em
`127.0.0.1`, de propósito.

Os passos abaixo explicam o que o script faz e por quê. Leia-os se algo
falhar, ou se preferir fazer à mão.

## Passo D1 — Dimensionar a máquina

Números **medidos**, não estimados:

| | |
|---|---|
| Imagem construída | ~4 GB |
| `ui` em repouso | ~1,5 GB de RAM (modelo carregado na subida) |
| `ui` com documento de 102 páginas | **3,1 GB** |
| Detecção, 102 páginas | 69–74 s |

Com isso: **8 GB de RAM e 2 vCPU** é o mínimo confortável, e **40 GB de
disco** depois da imagem. Com 4 GB a máquina sobrevive a documento pequeno e
morre por OOM num grande — e o modo de falha é o container reiniciando no
meio de uma revisão.

## Passo D2 — Instalar o Docker no VPS

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # saia e entre de novo para valer
docker compose version
```

## Passo D3 — Levar o código e a imagem

```bash
git clone https://github.com/lucaasmeiraf/anonimizador.git
cd anonimizador/anonimizador-poc
```

E então **construir**:

```bash
docker compose build        # única etapa com rede; demora
```

> **Se o VPS for de 1 ou 2 vCPU, construa na sua máquina e transporte.**
> Compilar e baixar tudo num VPS fraco leva muito tempo e pode estourar o
> disco durante a build. O caminho já está no Passo 14:
>
> ```bash
> # na sua máquina
> docker compose build
> docker save anonimizador-poc:fase0 | gzip > anonimizador.tar.gz
> scp anonimizador.tar.gz usuario@vps:~
>
> # no VPS
> gunzip -c anonimizador.tar.gz | docker load
> ```

## Passo D4 — Criar o `.env`

Ele **não** vem no clone, de propósito: carrega senhas.

```bash
cp .env.example .env
nano .env
```

Mínimo para um VPS:

```
POSTGRES_PASSWORD=<senha longa e aleatória>
ANON_EXIGIR_LOGIN=1
```

`ANON_EXIGIR_LOGIN=1` é o que faz toda rota de documento exigir sessão. Sem
ele o sistema sobe em modo local — **aberto** — e a porta estaria publicada.

## Passo D5 — Banco, usuário e subida

Na ordem, e a ordem importa: criar o usuário **antes** de exigir login, ou
você se tranca do lado de fora.

```bash
docker compose up -d postgres
docker compose run --rm cli-db upgrade head

# a senha aparece UMA vez; anote
make usuario EMAIL=voce@exemplo.org INQUILINO="Seu Orgao"

docker compose -f docker-compose.yml -f docker-compose.vps.yml up -d ui ui-proxy
```

A sobreposição `docker-compose.vps.yml` acrescenta `restart: unless-stopped`
aos serviços de longa duração. Sem ela, **um reboot do VPS derruba o sistema
e ele não volta** — o compose principal não tem política de restart nenhuma,
porque em máquina de desenvolvimento isso seria intrometido.

Confirme o modo:

```bash
docker compose exec -T ui python -m anonimizador.web.modo
#   modo: COM LOGIN  (ANON_EXIGIR_LOGIN=1)
```

## Passo D6 — Proxy reverso e TLS, no host

**A porta continua em `127.0.0.1:8000`.** Não a exponha em `0.0.0.0`: seria
pôr a aplicação na internet sem TLS e sem limite por IP.

Quem fica de frente é um proxy reverso **no host** — não um container. Assim
o perímetro do compose fica intacto: continuam existindo exatamente dois
componentes com saída de rede (invariante 6), e o terminador de TLS é
infraestrutura do host.

Com Caddy, que resolve o certificado sozinho:

```bash
sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```
anonimizador.seudominio.com.br {
    # Limite por IP: e o que o `forward.py` NAO faz, e esta dito em D-04.
    rate_limit {
        zone entrada {
            key    {remote_host}
            events 60
            window 1m
        }
    }

    # O upload e grande; o padrao do Caddy nao e.
    request_body {
        max_size 55MB
    }

    reverse_proxy 127.0.0.1:8000 {
        # A deteccao de um documento longo leva mais de um minuto.
        transport http {
            response_header_timeout 300s
            read_timeout 300s
        }
    }
}
```

```bash
sudo systemctl reload caddy
```

E feche tudo menos SSH e HTTPS:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 443/tcp
sudo ufw enable
```

> O `rate_limit` do Caddy exige um build com o módulo correspondente. Se o
> seu não tiver, use nginx com `limit_req`, ou aceite que o limite por IP não
> existe — e então leia D-04 outra vez antes de deixar a URL pública.

## Passo D7 — Confirmar o perímetro no VPS

As provas valem no servidor como valem na sua máquina, e é lá que importa:

```bash
docker compose exec -T ui python -m anonimizador.web.prova_rede
# APROVADO — nenhum caminho de saída, subprocesso incluído.
```

## O que isto **não** resolve

Dito aqui porque hospedar não transforma o sistema em produto:

1. **Posse por documento não existe.** Com login, qualquer usuário
   autenticado alcança qualquer `doc_id`. É o Bloco 3 da Fase 4
   (`sessao_dono`), e sem ele não coloque dois clientes no mesmo servidor.
2. **Não há trilha.** Quem subiu, aprovou e baixou o quê não fica registrado
   (Bloco 4).
3. **Sem backup do `pgdata`** e sem rotina de atualização.
4. **O original em claro vive no disco do VPS** durante a revisão, em
   `./out`, com TTL e varredura de órfãs. Num VPS, "o disco" é de outra
   pessoa — avalie criptografia de disco com quem contratou.
5. **RN-04, e aqui ela muda de forma.** O PyMuPDF é AGPL-3.0. Enquanto o uso
   era interno, a pendência era sobre *distribuir*. Oferecer o sistema como
   serviço acessível pela rede é o caso que a cláusula de uso em rede da AGPL
   existe para alcançar, e a leitura corrente é que ela obriga a oferecer o
   código correspondente a quem usa o serviço. **Isto é leitura de memória,
   não parecer** — RN-07 — e precisa de confirmação de quem assina
   juridicamente **antes** de a URL ficar pública para terceiros. Para
   demonstração sua, com documento sintético, a conversa é outra.

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
