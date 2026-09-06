# /goal — Fase 4: identidade, inquilino e trilha

> Responde à pergunta que hoje não tem resposta nenhuma: **quem é você, e o
> que você pode ver?**
>
> Hoje o sistema não tem autenticação. Nenhuma. `pegar_sessao(doc_id)` procura
> o id e devolve a sessão — quem tiver o link tem o documento, e qualquer
> visitante faz upload. A única proteção é o `ui-proxy` publicar em
> `127.0.0.1:8000`, ou seja: **funciona porque só quem está na máquina
> alcança.** No instante em que outra pessoa acessa, não há nada.

---

## 0. A decisão de desenho que organiza tudo

**Autenticação e inquilino entram juntos, numa única passada.**

Não é preciosismo. "Login" e "isolamento entre clientes" são coisas
diferentes, e a segunda é transversal: sessão em memória, arquivo em disco,
linha no banco, trilha de auditoria e configuração de agente. Um documento da
empresa A não pode ser alcançável pela empresa B em **nenhuma** dessas
camadas.

Isolamento retrofitado é, notoriamente, o que vaza — porque basta **uma**
consulta sem filtro de inquilino para furar tudo, e essa consulta é sempre
adicionada meses depois por alguém que não sabia da regra.

Isso também desatrela esta fase da decisão comercial em aberto
(`docs/07-modelo-de-produto.md` §2): o plano pessoa física é simplesmente um
inquilino de um usuário, sem trilha. Nada aqui precisa esperar aquela escolha.

---

## 1. A invariante nova, e ela é a razão desta fase existir

> **O banco guarda identidade e trilha. O documento e seus valores ficam em
> disco, com TTL.**

`SpanUI.valor` carrega o valor da PII em texto — é o que a tela mostra e o que
alimenta a verificação. Hoje isso vive na memória do processo e morre com a
sessão.

Quando um banco entra, a tentação natural é *"persistir a sessão no Postgres
para poder escalar"*. **Isso transformaria o banco num arquivo de dados
pessoais**, com backup, réplica, WAL e retenção própria, fora dos dez vetores
que o `verifier` confere e sem TTL nenhum. Quebra a invariante 9 do
`CLAUDE.md` de forma direta, e é a brecha mais fácil de abrir porque tudo
continuaria funcionando perfeitamente.

| Vai para o banco | Fica em disco, com TTL |
|---|---|
| usuário, hash de senha, papel | o PDF original |
| inquilino, e a quem pertence cada sessão | o texto extraído |
| trilha: quem subiu, revisou, aprovou, baixou, enviou | os valores dos spans |
| contagens e metadados de auditoria | o PDF redigido e o texto pseudonimizado |

Se um dia for preciso rodar várias réplicas, a resposta é **volume
compartilhado ou afinidade de sessão** — nunca PII no banco. Fica dito aqui
para que a próxima pessoa não precise redescobrir.

---

## 2. Modelo de ameaça — contra o que isto defende

Explicitar evita construir a defesa errada.

| Ameaça | Hoje | Depois |
|---|---|---|
| Curioso na mesma rede acessa a interface | **entra e usa** | precisa de credencial |
| Alguém descobre um `doc_id` | **vê o documento** | precisa ser o dono |
| Usuário da empresa A vê documento da empresa B | não existe conceito de empresa | negado em toda camada |
| Senha capturada na rede | trafega em claro fora de `localhost` | TLS obrigatório |
| Força bruta de senha | ilimitada | limitada por tentativa |
| Vazamento do banco expõe senhas | — | hash lento; senha não é recuperável |
| Vazamento do banco expõe documentos | — | **não há documento no banco** (§1) |
| Auditor precisa saber quem fez o quê | impossível | trilha por ação |

**Fora do modelo**, e dito para não gerar falsa sensação de cobertura:
administrador da máquina hospedeira lê o disco e a memória; quem tem acesso
físico ao servidor tem tudo. Este desenho não defende contra isso, e nenhum
desenho de aplicação defende.

---

## 3. Decisões antes do código

- [ ] **Provedor de identidade.** Usuário e senha próprios, ou federar (OIDC /
      Entra ID / Google)? Cliente institucional quase sempre exige federação,
      e implementá-la depois muda o modelo de sessão. Resposta afeta o §5.
- [ ] **Quem cria inquilino e usuário.** Auto-cadastro, convite, ou provisão
      manual pelo operador? Para venda a empresa, convite é o mais provável;
      auto-cadastro exige verificação de e-mail e abre superfície.
- [ ] **Papéis.** O mínimo honesto é dois: quem **revisa** e quem **aprova**.
      Separá-los é o que dá sentido à trilha — se a mesma pessoa faz tudo, a
      trilha registra, mas não controla nada.
- [ ] **Retenção da trilha.** Por quanto tempo? Trilha eterna é risco eterno,
      e ela contém metadado de documento (nome do arquivo, contagens).
- [ ] **Onde o banco vive.** Container agora (decidido). Nuvem depois muda a
      prova de rede — ver §7.

---

## 4. O que vai para o banco

Portável de propósito: **SQLAlchemy, sem tipo exclusivo do Postgres**
(`JSONB`, arrays, `SERIAL`). O cliente pode acabar num banco Oracle, e
descobrir isso depois de escrever SQL específico é caro. Chave primária como
UUID gerado pela aplicação, não sequência do banco.

```
inquilino    id, nome, criado_em, ativo
usuario      id, inquilino_id, email, senha_hash, papel, ativo,
             criado_em, ultimo_acesso
sessao_dono  doc_id, inquilino_id, usuario_id, criado_em
             -- só a POSSE. O conteúdo da sessão não entra aqui.
trilha       id, inquilino_id, usuario_id, doc_id, acao, quando,
             detalhe_json_curto
             -- acao: upload | revisao | aprovacao | download |
             --       pseudonimizar | envio_externo | remocao
login_falho  email, ip, quando        -- para o limite de tentativa
```

**`trilha.detalhe` nunca carrega valor de PII.** Contagem, entidade, vetor,
modelo — nunca o texto. É a mesma regra da invariante 4, e o mesmo raciocínio
do `SpanSemRetangulo`: quem investiga tem o documento em mãos; o valor não
acrescenta nada e cria uma cópia com retenção própria.

**Nome do arquivo é metadado sensível.** `processo-fulano-de-tal.pdf` carrega
um nome. Decidir: guardar, truncar, ou substituir por identificador. Não é
detalhe — é o campo mais fácil de vazar PII para dentro do banco sem perceber.

---

## 5. Mecânica, e o que não é negociável

- **Hash de senha lento**: Argon2id, ou bcrypt. Nunca SHA-256 — é rápido
  demais, e velocidade é exatamente o que não se quer aqui.
- **TLS obrigatório** fora de `localhost`. Hoje tudo é HTTP em `127.0.0.1`, o
  que é seguro justamente porque não sai da máquina. Senha em HTTP claro num
  ambiente com mais de uma pessoa é inaceitável, e isso entra **junto** com a
  autenticação, não depois.
- **Cookie de sessão** `HttpOnly`, `Secure`, `SameSite=Lax`, com expiração.
  Proteção CSRF nas rotas que alteram estado.
- **Limite de tentativa** no login. Sem ele o hash lento perde o efeito.
- **`doc_id` deixa de ser autorização.** Hoje é `secrets.token_urlsafe(9)` —
  quem tem o link tem o documento. Continua sendo imprevisível, o que é bom,
  mas passa a ser **identificador**, não credencial. A autorização vem de
  `sessao_dono`.
- **Toda rota de documento verifica posse**, sem exceção. A verificação mora
  em `pegar_sessao`, um lugar só — não espalhada por rota, que é como uma
  acaba esquecida.
- **A varredura de órfãs e o TTL continuam valendo.** Autenticação não
  substitui o descarte: documento em claro que fica é risco acumulado, com ou
  sem dono.

---

## 6. Tarefas

**Bloco 1 — banco e infraestrutura**
- [ ] Serviço `postgres` no compose, rede `interna`, **sem egress**, com
      volume nomeado e senha vinda do `.env`.
- [ ] Verificar a licença do driver **antes** de adicioná-lo ao
      `requirements.txt`. Já há duas pendências de licença bloqueando entrega;
      não criar uma terceira por descuido.
- [ ] Migrações versionadas. Esquema que muda sem histórico é o que impede
      atualizar a instalação de um cliente.
- [ ] O `ui` sobe **sem o banco no ar**? Decidir: falhar alto na subida é
      preferível a servir sem autenticação por engano.

**Bloco 2 — identidade**
- [ ] `auth.py`: hash, verificação, criação de sessão de login, limite de
      tentativa.
- [ ] Rotas de login, logout e troca de senha.
- [ ] Dependência do FastAPI que resolve o usuário atual e **falha fechado**:
      sem sessão válida, 401 — nunca "segue como anônimo".

**Bloco 3 — inquilino e posse**
- [ ] `sessao_dono` gravado na criação do documento.
- [ ] `pegar_sessao` passa a exigir posse. **Um lugar só.**
- [ ] Toda consulta ao banco filtra por inquilino. Sem exceção, e com teste
      que percorre as rotas procurando a que esqueceu.

**Bloco 4 — trilha**
- [ ] Registro por ação, com a regra do §4 (sem valor de PII).
- [ ] Rota de leitura da trilha, restrita ao próprio inquilino.
- [ ] A trilha de envio externo, que hoje vive em `Sessao.envios` na memória,
      migra para cá — ela é auditoria, e auditoria em memória some no restart.

**Bloco 5 — interface**
- [ ] Tela de login, e o estado "não autenticado" em toda a interface.
- [ ] A tela de revisão vira também a tela de auditoria do documento.

---

## 7. Consequência para a prova de rede

O `postgres` fica na rede `interna`, sem egress. **A promessa continua
intacta**: `make ui-proof` e `make llm-proof` seguem valendo sem alteração, e o
`ui` continua sem rota para fora.

Isso é um argumento forte a favor do banco em container, e não só
conveniência: **hoje o único componente que o `ui` alcança está dentro do
perímetro.** Um banco gerenciado na nuvem exigiria que o `ui` alcançasse a
rede, e a garantia mudaria de *"não existe interface de rede"* para *"existe
rota só para o banco, na rede privada, e nenhuma para a internet"* — ainda
verificável, mas mais fraca, e o material comercial teria de dizer a versão
nova. Quando essa hora chegar, é decisão consciente, não efeito colateral.

---

## 8. Critérios de aceite

**Isolamento**
- Usuário do inquilino A recebe 404 — não 403 — em documento do inquilino B.
  404 não confirma a existência do documento.
- Existe teste que percorre **todas** as rotas de documento e falha se alguma
  não exigir posse. É o teste que impede a rota nova esquecida.
- Nenhuma consulta ao banco sem filtro de inquilino.

**A invariante do §1**
- Teste que inspeciona o banco depois de um fluxo completo e falha se
  qualquer valor de PII do documento aparecer em qualquer tabela.
- Teste que confirma que o conteúdo da sessão continua em disco, com TTL.

**Autenticação**
- Sem sessão válida, toda rota de documento responde 401. Testado rota a rota.
- Senha não é recuperável do banco: só hash, com algoritmo lento.
- Tentativas de login são limitadas, e o limite é testado.
- Logout invalida a sessão de fato — não só apaga o cookie do navegador.

**O que não pode regredir**
- `make ui-proof`, `make llm-proof` e `make offline-proof` continuam verdes.
- Os 296 testes atuais continuam passando.
- O caminho do PDF continua idêntico por `eval/impressao_pdf.py`.
- `make eval` dá o mesmo número.

---

## 9. Fora de escopo

Cobrança, cota e medição de uso — dependem da decisão de hospedagem
(`docs/07` §2) e não bloqueiam nada aqui. Federação de identidade, se a
resposta do §3 for "senha própria por enquanto". Escala horizontal. Agentes
configuráveis por contratante, que são Fase 3 e têm o risco de prompt
registrado em `docs/07` §5.
