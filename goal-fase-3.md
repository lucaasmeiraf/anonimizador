# /goal — Fase 3: O perímetro de rede

> Registra duas ideias levantadas em 2026-08-30, e a razão de estarem no mesmo
> documento: **as duas pedem para abrir a rede**, que é a restrição em que
> todo o resto do sistema se apoia.
>
> Nada aqui está implementado nem decidido. O documento existe para que a
> decisão seja tomada com o custo à vista.

---

## 0. A restrição que as duas ideias tocam

`docs/05-politica-llm.md` impõe três regras, e a primeira é a que está em
jogo:

> **R1 — Local e sem rede.** A LLM roda via Ollama, no mesmo container, sob
> `network_mode: none`. Não é uma promessa de configuração, é uma ausência de
> interface de rede.

A Fase 1 endureceu isso: o serviço que lê documento vive numa rede
`internal: true`, sem rota para fora, e `make ui-proof` **falha** se algum
caminho de egress abrir. É a característica que permite dizer ao cliente que
o documento não sai da máquina — e dizer isso de forma verificável, não
afirmativa.

As duas propostas abaixo pedem exceções a R1. Cada uma é defensável. Nenhuma
é gratuita, e as duas juntas mudam o que o produto pode prometer.

---

## 1. Conexões — puxar documento da nuvem

### A ideia

Na tela inicial, ao lado do envio de arquivo, uma seção **Conexões**: conectar
Google Drive, OneDrive/SharePoint e afins — possivelmente via servidores MCP —
para escolher documentos direto da nuvem em vez de baixar e reenviar à mão.

### Por que faz sentido

O fluxo real de quem trabalha com documento de órgão público raramente começa
no disco local. Obrigar a baixar, achar na pasta de downloads e reenviar é
atrito puro, e atrito é o que faz uma ferramenta de conformidade ser
contornada.

### O que muda no perímetro

| | Hoje | Com conexões |
|---|---|---|
| Documento chega por | upload do navegador | rede, de servidor de terceiro |
| Credenciais guardadas | nenhuma | token OAuth, renovável |
| Egress necessário | nenhum | autenticação + download |
| Superfície de ataque | o arquivo enviado | o arquivo + o provedor + o token |

O ponto mais delicado não é o download em si — é que **o token de acesso à
nuvem do cliente passa a viver dentro do produto**. Um token do Drive
corporativo costuma alcançar muito mais do que os documentos que o usuário
pretendia anonimizar.

### O desenho que preserva a garantia

A Fase 1 já resolveu um problema estruturalmente idêntico, e a solução se
aplica igual: **isolar o que tem rede do que lê documento.**

```
  conector (tem rede)  --grava arquivo-->  volume  <--lê--  ui (sem rede)
```

- Um serviço `conectores`, separado, na rede externa. Fala com Drive/Graph/MCP,
  baixa o arquivo, grava no volume da sessão.
- O `ui` continua em `internal: true`, sem rota para fora. Ele lê do volume e
  nunca sabe que a nuvem existe.
- `make ui-proof` continua valendo sem alteração: o serviço que processa
  documento segue sem egress.

Isso mantém a propriedade que interessa — **a pilha de ML e o conteúdo do
documento continuam sem rede** — e concentra o risco num componente pequeno,
que só faz transferência.

### Perguntas em aberto

- MCP é a camada certa, ou SDKs diretos? MCP dá uniformidade; SDK dá controle
  sobre escopo de token. Não avaliado.
- Escopo mínimo de OAuth por provedor: dá para pedir só leitura de arquivo
  selecionado, ou o provedor obriga escopo amplo?
- Onde o token é guardado, e por quanto tempo?
- O cliente **quer** isso? Para um órgão com política de dados rígida, uma
  ferramenta que se conecta ao Drive pode ser exatamente o que a área de
  segurança proíbe.

---

## 2. Análise do documento anonimizado por LLM externa

### A ideia

Depois de uma anonimização bem-sucedida — verificação aprovada, zero
vazamento —, permitir que o usuário converse sobre o documento num chatbox,
com o texto anonimizado enviado a um modelo via **OpenRouter**, que o usuário
já paga. Assim qualquer modelo pode ser usado, sem hardware local.

### O raciocínio está certo, e é importante reconhecer isso

Se o documento está **de fato** anonimizado, ele não é dado pessoal. Enviá-lo
a um terceiro não é transferência de dado pessoal, e a restrição de soberania
não se aplica. O argumento é sólido — e é exatamente o que a LGPD permite ao
tirar dado anonimizado do escopo.

O problema não é o raciocínio. É a palavra **"de fato"**.

### O que o sistema sabe, e o que ele não sabe

O `verify()` prova uma coisa só, com muito rigor: **os valores que decidimos
tarjar não sobrevivem no arquivo.** Ele não prova, e não pode provar, que
tudo que era dado pessoal foi detectado.

Três lacunas medidas, não hipotéticas:

| Lacuna | Evidência |
|---|---|
| Nome de pessoa não tarjado | `bert-lenerbr` vaza em 1 de 50 documentos do corpus (`report.md`) |
| Identificador indireto por contexto | Fora do gabarito. `05-politica-llm.md` §3.2: a cobertura de caracteres é **silenciosa** sobre isso, não tranquilizadora |
| Rótulo errado com política de preservação | Todos os 15 vazamentos do corpus (`diagnostico-person.md`) |

O caso do identificador indireto é o que mais preocupa aqui, porque nenhuma
tarja o resolve: *"o único servidor cego da repartição"*, *"o filho mais velho
do prefeito de Ouro Preto"*. O texto sai do pipeline sem nenhuma marca, e uma
LLM é justamente boa em reconstruir a identidade a partir disso.

> **A consequência precisa ficar dita.** Sem envio externo, um nome não
> detectado é um defeito que fica na máquina do cliente e é corrigido na
> próxima revisão. Com envio externo, o mesmo defeito vira **incidente com
> terceiro** — o dado saiu, pode ter sido registrado, cacheado ou usado em
> treino, e nenhuma correção posterior o traz de volta. Apagar depois não
> desfaz o envio.

Com 1 em 50 documentos vazando um nome, enviar automaticamente significa
aceitar que, a cada 50 documentos, um nome real vai para um provedor externo.

### As opções, com o que cada uma custa

**(a) LLM local, via Ollama — R1 preservada.**
É o que `05-politica-llm.md` já autoriza. Sem egress, sem revisão de política,
sem risco novo. O cliente tem RTX 4060 8 GB, o que comporta modelos de 7-8B
com folga e 14B quantizado. Para resumir, perguntar sobre e classificar um
documento, isso é suficiente. Não é o estado da arte, e não precisa ser.

**(b) OpenRouter — revisão explícita de R1.**
Dá acesso a modelos que nenhum hardware local alcança. Exige:
- serviço separado com egress, nos moldes do `ui-proxy`, sem acesso ao
  original — só ao texto anonimizado e verificado;
- gate adicional antes do envio: **re-rodar a detecção sobre o texto
  anonimizado**, com limiar mais estrito, e recusar o envio se qualquer coisa
  for encontrada. É barato e pega o caso "sobrou uma ocorrência";
- consentimento explícito **por documento**, não uma configuração ligada uma
  vez e esquecida;
- configuração de retenção no OpenRouter — provedores têm políticas
  diferentes, e alguns treinam com o que recebem. Isso precisa ser fixado e
  verificado, não presumido;
- registro de o quê foi enviado, para quem e quando.

E, mesmo com tudo isso, o gate extra **não resolve identificador indireto**.
Nenhuma verificação automática resolve, porque não há o que procurar.

**(c) Híbrido — recomendação.**
Local por padrão, para todo uso corriqueiro. OpenRouter como opção explícita,
por documento, com o aviso dizendo o que o sistema sabe e o que não sabe. O
usuário decide com a informação correta em vez de com a palavra
"anonimizado".

> **Decisão de 2026-09-05: (b), não (c).** A LLM será externa desde o início.
> Razão dada: o produto não mira cliente com capacidade de investir em infra
> de GPU, e exigir Ollama local excluiria o público-alvo.
>
> A decisão é defensável e é do usuário. O que ela **não** faz é tornar
> desnecessária a lista de exigências de (b) — ela as torna obrigatórias, e
> todas continuam pendentes: serviço com egress isolado nos moldes do
> `ui-proxy` e sem acesso ao original; re-detecção sobre o texto antes do
> envio, com limiar mais estrito; consentimento por documento e não por
> configuração; retenção fixada e verificada junto ao provedor; registro do
> que foi enviado, para quem e quando.
>
> E a frase que o produto pode dizer ao cliente muda de natureza: sai de "o
> documento não sai da sua máquina" — verificável por ausência de interface
> de rede — para "o documento sai, mas pseudonimizado" — que é uma promessa
> sobre a *qualidade da detecção*, e a detecção tem os dois furos medidos
> acima. Isso precisa estar no material comercial antes de existir na tela.

### O que não pode acontecer

A tela **não pode** dizer "documento anonimizado, seguro para enviar". O que
ela pode dizer honestamente é:

> Nenhum dos 47 valores detectados sobreviveu no arquivo, conferido em 10
> vetores. Isso não garante que tudo que era dado pessoal foi detectado —
> nomes escapam em cerca de 1 a cada 50 documentos, e identificadores
> indiretos por contexto não são detectados de forma alguma. Enviar a um
> serviço externo é irreversível.

### Acréscimo de 2026-09-05 — a inversão do fluxo, e o pseudônimo no meio

Duas coisas que esta seção não previa, levantadas depois da medição do A1.

**1. O que a LLM recebe deve ser pseudonimizado, não tarjado.** Esta seção
inteira fala em "texto anonimizado", subentendendo tarja. Mas tarja não
apaga só o nome: apaga o *ator*. A LLM recebe `O servidor ⏎ compareceu`, sem
saber que havia alguém ali, sem saber se é a mesma pessoa do parágrafo
seguinte — que é convite a alucinação exatamente onde a análise precisa ser
confiável.

Com token (`[P-7F3A]`), o modelo sabe que existe um ator, sabe o tipo, e sabe
que é o mesmo nos dois parágrafos. **A Fase A da Fase 2 é pré-requisito desta
seção**, não um trabalho paralelo — e o item A9 (saída de texto
pseudonimizado, ordem correta por construção) existe por causa deste caso de
uso, não do PDF.

**2. A inversão do fluxo.** Hoje a revisão é o caminho obrigatório e o
resultado é o PDF. A proposta é trocar a ordem:

| | Hoje | Proposta |
|---|---|---|
| Tela principal | revisão lado a lado | chatbox: envia documento, pergunta |
| Revisão de tarjas | obrigatória, sempre | um clique de distância, opcional |
| Tela de revisão vira | o produto | a **auditoria** — como provar o que foi feito |
| Entregável | PDF tarjado | resposta da LLM; PDF quando o caso for publicar |

O ganho é real: atrito é o que faz ferramenta de conformidade ser contornada,
e o fluxo atual cobra revisão completa mesmo de quem só quer perguntar algo
ao documento.

**A trava a preservar, e ela é barata.** A invariante exige *autorização
humana* antes de liberar, não revisão de cada tarja. Um resumo do inventário
com um botão — "12 pessoas, 3 CPFs, 2 e-mails encontrados; enviar?" — mais um
link discreto para a tela de revisão satisfaz a invariante e continua sendo um
clique. O que não pode existir é o caminho de zero clique **com LLM externa**,
porque ali o envio é irreversível e o 1-em-50 vira incidente com terceiro.

Com LLM local a conta muda: nada sai da máquina, o envio não é publicação, e
o automático passa a ser defensável. É mais um argumento para a recomendação
(c) desta seção — local por padrão.

**3. Consequência para `docs/05-politica-llm.md`.** O documento é normativo e
diz que uso não listado não está autorizado. Ele lista cinco pontos, e nenhum
é "a LLM analisa o documento pseudonimizado inteiro". Não é violação de R2 —
o A2 garante por construção que não há valor de PII no que a LLM recebe —
mas é ponto **novo**, e precisa virar uma seção 2.6 com a mesma análise de
acesso a dados que as outras têm, antes de existir em código.

---

## 2.9 Implementado em 2026-09-05 — o que existe e o que ainda não

A opção (b) foi construída. O desenho segue o precedente do `ui-proxy`: **o
componente com egress é o pequeno**, e o que processa documento continua sem
rota para fora.

```
   navegador          ui-proxy          ui                  analise         OpenRouter
   (host)      →      copia bytes  →    interna, SEM rede   interna+externa  →  internet
                                        deteccao, redacao,  so ./src montado
                                        verificacao,        + tmpfs em /app/out
                                        gate de pre-envio   guarda a chave
```

**O que ficou pronto**

- `web/analise.py` — o serviço de egress. Biblioteca padrão apenas
  (`http.server`, `urllib`): sem torch, sem transformers, sem PyMuPDF. Não vê
  o original, não detecta, não guarda estado, não registra conteúdo.
- **Gate de pré-envio** (`Sessao.conferir_antes_do_envio`): a detecção roda
  **de novo** sobre o texto já pseudonimizado, com limiar 0.20 em vez de 0.35.
  O limiar é mais baixo porque a conta se inverte antes de um envio externo —
  falso positivo custa recusar um envio seguro; falso negativo custa um nome
  real num terceiro, sem desfazer. Achou algo que a política mandava
  substituir → **nada sai**, e a resposta traz entidade e posição, nunca o
  valor.
- **Consentimento por documento**, estruturalmente: é uma chamada explícita
  por documento. Não existe configuração global que ligue isso e seja
  esquecida.
- **Trilha de auditoria** (`Sessao.registrar_envio`): quando, para onde, qual
  modelo, quantos caracteres e tokens. Metadado apenas — nunca o que foi
  enviado nem o que voltou. Não é apagada por `_invalidar`: o envio aconteceu,
  e editar o documento depois não o desfaz.
- **A chave vive só no serviço `analise`.** O `ui` não a recebe.
- `make llm-proof` — três metades: o `ui` continua sem egress, o `analise` não
  alcança documento em claro, e o `analise` tem a saída que precisa.

**Um buraco que a prova encontrou, e que era anterior a esta fase**

Na primeira execução o `llm-proof` reprovou. O `docker-compose.yml` monta só
`./src` no serviço `analise`, mas o `Dockerfile` faz `COPY . /app` e **não
havia `.dockerignore`** — então `out/`, onde o original em claro vive durante a
revisão, era assado na imagem no momento do build.

Estava vazio, e não houve vazamento. Mas um build feito com uma sessão em
revisão teria copiado o PDF original para dentro de uma imagem, com retenção
própria, sem TTL e sem verificação — violação direta da invariante 9. E a mesma
falha assaria o `.env` com a chave da API.

Corrigido em duas camadas: `.dockerignore` e `tmpfs` sobre `/app/out` no
serviço com egress. `web/prova_isolamento.py` impede que as duas apodreçam em
silêncio.

**O que continua pendente, e bloqueia uso com documento real**

- [ ] **Retenção no OpenRouter.** É configuração da conta do cliente
      (`openrouter.ai/settings/privacy`), não deste repositório. Provedores
      têm políticas diferentes e alguns treinam com o que recebem. Precisa ser
      fixada e verificada, não presumida.
- [ ] **Tela.** Hoje o acesso é por API. O aviso do que o sistema sabe e do
      que não sabe precisa aparecer no momento da escolha.
- [ ] **Os dois furos de detecção continuam.** `PERSON` escapa em ~1 documento
      a cada 50; identificador indireto por contexto não é detectado de forma
      alguma, e nenhum token o resolve. O gate de pré-envio **não** os cobre:
      ele acha o que o detector acha, e o problema é justamente o que ele não
      acha. Com envio externo isso deixa de ser defeito local e vira incidente
      com terceiro.

---

## 3. Como as duas se relacionam

Não são a mesma decisão, e têm gravidades diferentes:

- **Conexões** move *para dentro* documento que ainda não foi anonimizado. O
  risco é de credencial e de superfície, e o desenho de isolamento da Fase 1
  o contém bem.
- **Análise externa** move *para fora* documento que acreditamos estar
  anonimizado. O risco é de exposição irreversível, e nenhum desenho de
  isolamento o contém — porque a exposição é o objetivo da funcionalidade.

Se for para fazer uma, **conexões é a de menor risco** e a de maior ganho
imediato de uso.

---

## 4. Tarefas / entregáveis

**Bloco 0 — Decisão de política** *(bloqueia o resto)*
- [ ] Revisar R1 por escrito em `docs/05-politica-llm.md`, com a decisão e a
      justificativa, ou registrar que R1 se mantém e a ideia (b) fica fora.
- [ ] Confirmar com o cliente se conexão a nuvem corporativa é permitida pela
      política de segurança dele.

**Bloco 1 — Conexões**
- [ ] Serviço `conectores` em rede externa, sem acesso à rede interna a não
      ser pelo volume da sessão.
- [ ] `make ui-proof` estendido: provar que o `ui` continua sem egress mesmo
      com o conector no ar.
- [ ] Avaliar MCP contra SDK direto, decidir com evidência.
- [ ] Escopo OAuth mínimo por provedor; guarda e expiração de token.
- [ ] Seção "Conexões" na tela inicial, ao lado do envio de arquivo.

**Bloco 2 — Copiloto local (autorizado hoje)**
- [ ] Ollama no compose, sem rede, conforme R1.
- [ ] Chatbox sobre o documento **anonimizado e verificado**.
- [ ] Medir latência com o transformer de NER disputando a mesma CPU.

**Bloco 3 — Análise externa** *(só se o Bloco 0 aprovar)*
- [ ] Serviço de egress separado, sem acesso ao original.
- [ ] Gate pré-envio: re-detecção sobre o texto anonimizado, limiar estrito,
      recusa se achar qualquer coisa.
- [ ] Consentimento por documento, com o texto honesto da seção 2.
- [ ] Retenção zero configurada e **verificada** no OpenRouter.
- [ ] Registro de envio: o quê, para quem, quando.

---

## 5. Critérios de aceite

- `make ui-proof` continua verde: o serviço que processa documento segue sem
  egress, com conector e com copiloto no ar.
- Nenhum documento sai da máquina sem ação explícita do usuário **para aquele
  documento**.
- A interface nunca afirma que o documento é seguro para envio externo; ela
  informa o que foi verificado e o que não foi.
- Token de nuvem com escopo mínimo, expiração e guarda documentados.
- Se o Bloco 0 não aprovar a revisão de R1, o Bloco 3 não existe — e isso
  fica registrado como decisão, não como pendência.

---

## 6. O que não sabemos

Registrado para não virar suposição de que está avaliado:

- Nenhum servidor MCP de Drive/Graph foi testado neste projeto.
- Nenhum modelo local foi escolhido nem medido para a tarefa de conversar
  sobre documento em português.
- Latência do copiloto local disputando CPU com o NER: não medida.
- Políticas de retenção dos provedores por trás do OpenRouter: não levantadas.
- Se Ollama funciona sob `network_mode: none` falando por `localhost`: é
  plausível, **não testado**.
