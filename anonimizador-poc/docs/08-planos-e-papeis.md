# 08 — Planos de assinatura e papéis de acesso

Registra a decisão de produto de **2026-11-05** sobre os dois planos de
assinatura e sobre quem, dentro de cada um, vê o quê. Complementa o
[`07-modelo-de-produto.md`](07-modelo-de-produto.md), que já separava "pessoa
física" e "empresa". Este documento fixa o recorte de funcionalidade de cada
plano e mede a distância até ele.

**Só documentação.** Nada aqui está implementado além do que a coluna "hoje"
diz. A ordem de implementação está no §7.

---

## 1. A decisão, na formulação do dono do produto

> *"Teremos dois tipos de assinatura para esse produto, a primeira será o
> acesso individual e o segundo será para empresas. O acesso individual terá o
> que o sistema oferece a um usuário hoje: ANONIMIZAR, mas a opção de 'Enviar
> para a IA' que estamos desenvolvendo será disponibilizada APENAS para
> empresas, pois deixaremos configurado um chatbox onde ao anonimizar eu tenho
> a possibilidade de enviar diretamente para a LLM que a empresa paga (token de
> alguma API, como OpenRouter ou demais — OpenAI, Gemini, Claude etc.), já o
> usuário individual só vai conseguir gerar um PDF anonimizado da forma que ele
> configurou na tela existente."*

> *"SOMENTE admin pode ter acesso à engrenagem que permite adicionar usuários e
> visualizar os existentes; usuários comuns não podem ver essa opção, portanto
> o admin precisa ter uma opção de definir também a role (já existe a de dono,
> que deve ser o mesmo que admin)."*

Respostas às perguntas em aberto, no mesmo dia:

> 1. *"Pode sim, tanto tarjar ou código."* (Individual usa os dois modos.)
> 2. *"Todo usuário que for cadastrado na lista de acessos da empresa poderá
>    enviar para a IA o documento após anonimizar."*
> 3. *"A criação da empresa será feita, inicialmente, pelo admin, mas em breve
>    faremos a página de contratação da ferramenta [...] o pagamento sendo
>    confirmado pelo checkout, é gerado um acesso para o responsável pela
>    empresa e ele poderá cadastrar alguns usuários [...] iremos definir um
>    valor para a quantidade de usuários [...] conforme for aumentando mais caro
>    será, e ele vai precisar criar o cadastro de cada um (ou apagar o cadastro
>    de algum usuário e criar outro no lugar). Será criada automaticamente após
>    checkout."*
> 4. *"Nada impede de incluirmos essa opção [trocar a própria senha] em
>    configurações, lembrando que cada configuração varia dependendo da role."*

---

## 2. Os dois planos

| | **Individual** | **Empresa** |
|---|---|---|
| Quem | uma pessoa | um órgão ou escritório, com vários usuários |
| Usuários por inquilino | 1 | até o limite contratado (§4) |
| Anonimizar PDF (detectar, revisar, aprovar, baixar) | **sim** | **sim** |
| Modo tarja **e** modo código (pseudônimo) | **sim, os dois** | **sim, os dois** |
| Baixar o texto pseudonimizado | **sim** | **sim** |
| Enviar para a IA (chat sobre o documento pseudonimizado) | **não** | **sim, todo usuário cadastrado** |
| De quem é a chave da API da LLM | — | **da empresa** (ela paga o provedor) |
| Provedores de LLM | — | OpenRouter hoje; OpenAI, Gemini, Claude etc. como objetivo |
| Administrar acessos | não se aplica | **só o admin** |
| Trilha de auditoria | não (`07`, §1) | sim (`07`, §1) |

A regra que decide o recorte: **o plano Individual entrega arquivos; o envio
direto a um terceiro, feito pelo sistema, é do plano Empresa**, onde existe um
contratante que escolhe o provedor e paga por ele.

### Consequência de o Individual baixar o texto pseudonimizado

O texto pseudonimizado existe para ser levado a uma IA. No plano Individual o
usuário pode baixá-lo e colá-lo onde quiser — e aí o envio acontece **fora do
sistema**, sem a re-detecção que o serviço `analise` faz antes de mandar
qualquer byte (`05-politica-llm.md` §2.6). O texto em si continua protegido
pela mesma trava de qualquer download (`verify_texto`, invariante 2), mas a
segunda checagem só existe no caminho da Empresa.

Isso não impede a decisão; obriga a tela a dizer a verdade no momento do
download: texto pseudonimizado **continua sendo dado pessoal** (LGPD art. 13,
§4º — de memória, ver §9), e quem o leva a uma IA é quem responde por esse
envio. A tela de hoje já distingue os dois modos na escolha; o aviso no
download do texto é o que precisa existir.

---

## 3. Papéis e configurações

**"Admin" é o papel `dono` que já existe.** Não se cria papel novo: na tela,
`dono` passa a aparecer como "Administrador" e `operador` como "Usuário". O
nome interno continua igual, porque mudá-lo exigiria migração de banco sem
ganho nenhum.

### A engrenagem passa a ser "Configurações", e o conteúdo varia por papel

A resposta 4 revisa a frase *"usuários comuns não podem ver essa opção"*:
o que o usuário comum não pode ver é a **administração de acessos**, não a
engrenagem inteira. A engrenagem vira a tela de Configurações para todos, e
cada papel vê as seções que lhe cabem:

| Seção de Configurações | Usuário (`operador`) | Administrador (`dono`) | Individual |
|---|---|---|---|
| Minha conta — trocar a própria senha | sim | sim | sim |
| Acessos — listar, criar, definir papel, redefinir senha, desativar | **não** | sim | não se aplica |
| Chave da IA — cadastrar, trocar, ver os últimos 4 caracteres | **não** | sim | não se aplica |
| Plano — plano atual, limite de usuários e quantos estão em uso | **não** | sim | **sim**, o próprio plano |

A regra de quem vê o quê **mora no servidor**: cada seção é uma rota que
responde 403 ao papel errado. A tela esconder a seção é conforto, não trava —
é o mesmo desenho que já existe hoje para a administração de acessos.

### O que já existe hoje (conferido no código em 2026-11-05)

- A engrenagem só aparece para `dono` (`app.js`, `mostrarAcoesDeConta`), e o
  servidor recusa com **403** qualquer chamada de administração vinda de
  `operador` (`usuarios._exigir_dono`).
- Ao **criar** um usuário, o admin já escolhe o papel (`#novo-papel`), e o
  servidor só aceita `operador` e `dono` (`usuarios.PAPEIS_ATRIBUIVEIS`).
- Listar, redefinir senha e ativar/desativar já são só do `dono` e só dentro
  do próprio inquilino.
- Trocar a própria senha **só existe no primeiro acesso**. A rota
  (`POST /api/senha`) serve para qualquer usuário logado; falta a tela.

### O que falta

1. **Mudar o papel de quem já existe.** Hoje o papel só é escolhido na
   criação. Duas travas:
   - o admin **não** pode rebaixar a si mesmo, nem desativar a si mesmo, se
     for o último admin ativo do inquilino — senão ninguém mais administra a
     empresa e só nós conseguimos destrancar;
   - a mudança derruba as sessões do alvo, como a troca de senha já faz, para
     que o papel novo valha na próxima requisição e não só no próximo login.
2. **Renomear na tela**: "Dono" → "Administrador", "Operador" → "Usuário".
3. **Configurações para todos**, com a seção "Minha conta" (§ acima).

---

## 4. Contratação, limite de usuários e criação da empresa

### Fase inicial: criação manual

Até a página de contratação existir, a empresa e o seu primeiro
administrador são criados **por nós**, pela linha de comando que já existe
(`criar-usuario --inquilino ... --papel dono`). "O admin" na resposta 3 foi
lido como o administrador da plataforma (papel `plataforma`), e não o da
empresa — o admin da empresa não tem como criar a empresa em que ele próprio
entra. **Confirmar esta leitura.**

### Fase seguinte: contratação com checkout

Fluxo pretendido:

1. A pessoa escolhe o plano (Individual ou Empresa e, na Empresa, a faixa de
   usuários) e paga.
2. O checkout confirma o pagamento.
3. O sistema cria, **automaticamente**: o inquilino, com o plano e o limite de
   usuários; e o primeiro usuário, como `dono`, com senha temporária de um
   login só — o mesmo mecanismo de hoje.
4. O responsável entra, troca a senha (primeiro acesso), e cadastra os
   usuários da empresa até o limite.

**Limite de usuários.** O preço cresce com a quantidade de usuários; o valor
de cada faixa ainda não foi definido. A regra técnica:

- o limite é um campo do inquilino, e quem o conta é o **servidor**, na
  criação de usuário — criar além do limite responde erro com a mensagem
  "limite do plano atingido", não falha silenciosa;
- para pôr outra pessoa no lugar, o admin **desativa** um cadastro e cria
  outro; desativado não conta no limite (§8, decisão 1).

**Mudança de plano** — de Individual para Empresa, ou de faixa — mantém a
conta e fica registrada em histórico próprio (§8, decisão 3).

**Onde o checkout entra no desenho de rede.** A confirmação de pagamento
chega de fora (webhook do provedor de pagamento) e, conforme o provedor,
exige consultar a API dele. Isso é rede, e a invariante 6 diz que só dois
componentes têm saída — o `ui-proxy` e o `analise` — e que não se cria um
terceiro. O caminho coerente é o checkout e a página de contratação viverem
**fora** do perímetro do documento (outro serviço ou plataforma), e a
criação do inquilino chegar ao sistema por uma rota de provisionamento
autenticada, sem que o `ui` ganhe egress. É decisão de arquitetura a tomar
antes de escolher o provedor de pagamento.

---

## 5. "Enviar para a IA" no plano Empresa

### O que existe hoje

- O envio é feito pelo serviço `analise` (`web/analise.py`), que fala só com o
  **OpenRouter**.
- A chave é **uma só, do servidor**: `OPENROUTER_API_KEY` no `.env`, e só o
  `analise` a recebe. O `ui` nunca vê a chave (invariante 6).
- É uma pergunta e uma resposta por vez, sobre o texto pseudonimizado.
- Qualquer usuário logado, de qualquer inquilino, vê a opção, desde que o
  serviço `analise` esteja no ar. **Não existe hoje noção de plano** no banco
  (`Inquilino` não tem campo de plano).

### O que a decisão pede, e o que cada parte implica

**a) Só para o plano Empresa, e para todo usuário dela.** Sem permissão por
usuário: estar cadastrado na empresa basta. A checagem é do **plano do
inquilino**, feita no servidor, na rota de análise — não só na tela.

**b) A chave é da empresa.** Isso muda onde a chave mora, e é a parte que
mexe no perímetro:

- Hoje a chave está num arquivo, lida por um serviço sem banco. Com uma chave
  por empresa, ela fica guardada por inquilino, e o `analise` a recebe por
  requisição.
- **A chave não pode passar a morar no `ui`.** O motivo de o `analise`
  existir separado é que quem tem rede não tem a árvore de dependências, e
  quem tem a árvore não tem a chave. O caminho coerente é guardar a chave
  **cifrada** no banco, com a chave de cifra só no `analise`. O `ui` repassa
  o blob cifrado sem conseguir abri-lo.
- Só o admin cadastra ou troca a chave (§3). Depois de salva, a tela mostra
  só os últimos 4 caracteres; a chave nunca volta inteira ao navegador e
  nunca vai para log (invariante 4 vale para segredo tanto quanto para PII).
- Empresa sem chave cadastrada: a opção aparece desabilitada, dizendo que o
  administrador precisa cadastrar a chave — não some sem explicação.

**c) Vários provedores.** Dois caminhos:

- **Só OpenRouter**, que já dá acesso aos modelos de OpenAI, Google e
  Anthropic. É o menor e não muda nada no `analise`.
- **Provedor direto**: cada um é um adaptador novo **dentro do `analise`**,
  com o próprio destino de rede. Continua dentro da regra de não criar um
  terceiro componente com rede, mas cada provedor é um destino a mais para
  listar e provar no `make llm-proof`.

**d) Chatbox.** Uma conversa com várias perguntas sobre o mesmo documento. O
histórico contém o texto pseudonimizado e as respostas, e **texto
pseudonimizado continua sendo dado pessoal**. Portanto o histórico segue a
regra do documento: vive na pasta da sessão, com o mesmo TTL, e some junto
com ela. Não vai para o banco.

**e) Mudança de política a registrar em `05-politica-llm.md` §2.6** quando
isto for implementado: hoje o texto trata a LLM externa como decisão do
produto, com a nossa conta. Com chave da empresa, **a empresa escolhe e
contrata o provedor**, e a retenção de dados no provedor passa a ser
configuração da conta dela. A tela de cadastro da chave precisa dizer isso.

---

## 6. Gatilho jurídico (CLAUDE.md §6)

1. **Muda o que sai do escopo da LGPD?** Não para o PDF tarjado, que segue
   irreversível. O modo código e o texto pseudonimizado **não** saem do
   escopo, nos dois planos — isso já era verdade e continua.
2. **Remove algo que a LAI exige público?** Não. Nada muda no que é tarjado.
3. **A tela continua dizendo a verdade?** Precisa de três ajustes quando for
   implementado:
   - para o plano Individual, a tela inicial não pode prometer "enviar para
     uma IA" pelo sistema. A opção de modo continua (códigos no lugar dos
     dados), mas o texto deve falar em **gerar** o arquivo pseudonimizado,
     não em enviá-lo;
   - no download do texto pseudonimizado, dizer que ele continua sendo dado
     pessoal (§2);
   - no plano Empresa, a tela do envio diz que o texto vai para o provedor
     **contratado pela empresa**, sob as regras da conta dela.
4. **Precisa de confirmação jurídica?** Sim:
   - a responsabilidade pelo envio feito com a chave e a conta da empresa
     (entendimento de memória: a empresa é a controladora e escolhe o
     operador);
   - o termo de uso do plano Individual sobre o texto pseudonimizado levado
     pelo próprio usuário a um terceiro;
   - **RN-04 (AGPL do PyMuPDF)** continua bloqueando a oferta como serviço
     acessível pela rede, nos dois planos — e a contratação com checkout é
     exatamente essa oferta.

---

## 7. Ordem sugerida de implementação

1. **Papéis e Configurações por papel** (§3): renomear, trocar papel com a
   trava do último admin, "Minha conta" com troca de senha para todos.
   Independente do resto.
2. **Plano e limite no `Inquilino`** (`individual` / `empresa`, limite de
   usuários), com migração. Inquilinos existentes nascem `empresa`, para não
   tirar de ninguém o que já usa. A criação e a reativação de usuário passam
   a respeitar o limite, e toda mudança de plano grava uma linha no
   histórico de plano (§8, decisão 3).
3. **Bloquear "Enviar para a IA" no servidor para o Individual**, e ajustar os
   textos da tela (§6.3).
4. **Chave por empresa**, cifrada, aberta só pelo `analise` (§5b).
5. **Chatbox** (§5d).
6. **Contratação com checkout** (§4), depois de decidir onde ela vive na rede
   e de resolver a RN-04.
7. **Provedores diretos**, se o OpenRouter não bastar (§5c).

---

## 8. Decisões de 2026-11-05 e perguntas em aberto

### Decididas

1. **Liberar vaga é desativar, não apagar.** (*"O que achar melhor."*)
   Usuário desativado **não conta** no limite do plano, não entra, e o
   cadastro permanece para a trilha de auditoria — apagar levaria junto o
   "quem" das ações dele. Reativar um desativado volta a ocupar vaga, e por
   isso a reativação também respeita o limite: com o plano cheio, o servidor
   recusa com "limite do plano atingido". O e-mail de um desativado continua
   reservado; para reaproveitar a vaga com outra pessoa, cria-se um cadastro
   novo com outro e-mail.
2. **O plano Individual vê o próprio plano** nas Configurações (seção
   "Plano", §3). Para o Individual, a seção mostra o plano e a situação da
   assinatura; não há limite de usuários a mostrar.
3. **Mudança de plano mantém a conta.** Uma conta Individual que contrata o
   plano Empresa continua sendo o mesmo inquilino e o mesmo usuário: o plano
   do inquilino é atualizado, o limite de usuários passa a valer, e esse
   usuário vira o `dono` (administrador) da empresa. Vale o mesmo para subir
   ou descer de faixa de usuários dentro do plano Empresa.

   **A troca fica registrada**, numa tabela própria de histórico de plano —
   uma linha por mudança, nunca sobrescrita:

   | Campo | Conteúdo |
   |---|---|
   | inquilino | id |
   | quando | data e hora |
   | de → para | plano e limite anteriores e novos |
   | origem | `checkout` (com o id da transação do provedor de pagamento) ou `manual` (com o id de quem da plataforma fez) |

   Sem nome, e-mail ou dado de pagamento além do id da transação — a regra
   da invariante 4 vale aqui. O campo de plano no `Inquilino` diz o estado
   atual; o histórico diz como se chegou nele, e é o que responde a uma
   contestação de cobrança.

   **Rebaixamento** (Empresa → Individual, ou faixa menor de usuários) não
   desativa ninguém sozinho: o servidor só aceita a mudança se o número de
   usuários ativos couber no novo limite, e caso contrário diz ao admin
   quantos precisa desativar antes. Escolher quem perde o acesso é decisão
   da empresa, não do sistema.

### Ainda em aberto

1. **"Admin" na criação inicial da empresa é o administrador da plataforma
   (nós)?** É a leitura do §4.
2. **Limite de uso por documentos** (cota, `07` §2) continua sem decisão, e
   depende de quem hospeda.
3. **Valor de cada faixa de usuários**: a definir.

---

## 9. Ressalvas

- Citações de artigo de lei neste documento são **de memória** (RN-07) e
  precisam de confirmação de quem assina juridicamente antes de ir para
  tela, contrato ou material comercial.
- O que está descrito como "existe hoje" foi conferido no código em
  2026-11-05. Nenhuma das mudanças do §7 foi implementada.
