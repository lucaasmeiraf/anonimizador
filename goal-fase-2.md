# /goal — Fase 2: Reversibilidade sob chave

> Responde a uma pergunta feita em 2026-08-30: *"consigo desanonimizar na
> minha máquina um documento que a ferramenta anonimizou?"*
>
> Resposta curta: **com o que existe hoje, não — e isso é intencional.** Com o
> que esta fase propõe, sim, sob chave, e com um custo jurídico que precisa
> ser decidido antes de uma linha de código.

---

## 0. Revisão de 2026-09-01 — medida, e ela divide a fase em duas

> Motivada por uma pergunta: *"seria muito trabalhoso migrar de tarja para
> pseudonimização, para entrar na LGPD e na LAI?"*
>
> **Leia esta seção antes das outras.** Ela corrige duas coisas que o resto do
> documento assume e que a medição derrubou.

### A premissa que precisa ser corrigida

Pseudonimização **não** aproxima o produto da conformidade com a LGPD — ela
afasta. Hoje a tarja produz saída irreversível, que **sai do alcance da lei**.
Pseudonimizar devolve o arquivo para dentro do alcance: continua dado pessoal,
continua exigindo base legal, direitos do titular e comunicação de incidente.

Em LGPD, migrar de tarja para pseudônimo é **descer** de patamar.

### Mas o instinto está certo — pelo lado da LAI

Num documento com dez nomes tarjados, todas as tarjas são iguais. Não dá para
saber se o servidor do parágrafo 3 é o mesmo do parágrafo 9. O documento fica
protegido e **ilegível como narrativa**, e isso é perda de publicidade que a
LAI cobra.

Com token, `[P-7F3A]` aparece nas duas passagens: dá para seguir quem fez o quê
sem saber quem é.

### A separação que muda o plano inteiro

**O ganho de legibilidade vem do token. O custo jurídico vem do cofre. Os dois
são separáveis, e este documento os tratava como uma coisa só.**

| | Token **com** cofre | Token **sem** cofre |
|---|---|---|
| Documento legível, atores rastreáveis | ✅ | ✅ |
| Reverter ao original | ✅ | ❌ |
| Situação na LGPD | dado pessoal | **fora do alcance** |
| Ativo a proteger para sempre | o cofre | nenhum |

A linha divisória é exata: **se o mesmo nome precisa virar o mesmo token em
documentos diferentes**, é preciso guardar uma chave — e essa chave é a
"informação adicional mantida separadamente" do art. 13 §4º, o que torna a
saída dado pseudonimizado. Se a estabilidade do token só precisa valer *dentro
de um documento*, o mapa é gerado e descartado, e a saída continua irreversível.

> **Armadilha a decidir cedo.** Token determinístico *entre* documentos cria
> capacidade de vínculo: quem tiver dois documentos sabe que a mesma pessoa
> aparece nos dois, **sem ter a chave**. Dependendo do contexto isso já é
> reidentificação por meios razoáveis. É mais um motivo para começar com
> determinismo apenas intradocumento.

### O obstáculo técnico é menor do que a seção 2 afirma — medido

A seção "O obstáculo técnico que a Fase 0 não resolveu" supõe que escrever
texto de volta no PDF é a parte cara. **Não é.** O PyMuPDF 1.28.2 suporta
nativamente:

```python
page.add_redact_annot(rect, text="[P-7F3A]", fontname="helv", fontsize=9)
```

Sondagem executada em 2026-09-01, em arquivos temporários, sem tocar no
projeto. Funcionou: originais removidos com o `verifier` **limpo nos dez
vetores**, tokens inseridos, e o mesmo nome virou o mesmo token em todas as
ocorrências.

**Três arestas apareceram, e duas são graves:**

```
[P-7F3A]                          caixa 42.2pt  token  35.5pt  cabe     -> ok
[PESSOA-7F3A]                     caixa 42.2pt  token  66.5pt  ESTOURA  -> desenha por cima do vizinho
[PESSOA-IDENTIFICADA-7F3A-2026]   caixa 42.2pt  token 155.0pt  ESTOURA  -> PERDIDO, em silêncio
```

1. **Token longo demais é descartado sem aviso.** O valor sai, nada entra, e o
   `verifier` atual diz "limpo" — porque o original realmente sumiu. É falso
   silêncio com o gate aprovando, que é a pior combinação possível aqui.
2. **Token que estoura a caixa escreve por cima do texto vizinho**, sem erro.
3. **A ordem de leitura quebra.** Os tokens entram anexados ao fim do fluxo de
   texto da página. Visualmente ficam no lugar; ao copiar e colar saem todos no
   fim. Para um caso de uso de transparência isso corrói justamente a
   legibilidade que motivou a mudança.

As três têm conserto conhecido: token curto, **medir antes de escrever** e
falhar alto quando não couber, e tratar a ordem de leitura como critério de
aceite verificável — não como detalhe de renderização.

### Recomendação

**Não substituir a tarja — acrescentar ao lado dela.** Tarja continua o padrão
e continua sendo a única coisa que produz saída fora do alcance da LGPD.
Trocar destruiria a garantia mais forte do produto.

Fazer a **Fase A** (token irreversível) primeiro. Ela entrega a legibilidade
que motivou o pedido, é mais barata, e **não abre nenhuma questão jurídica
nova**. A Fase B (cofre) só se a reversibilidade for requisito confirmado.

---

## 1. Por que hoje é impossível, e por que isso não é um defeito

O único operador implementado é `tarja`, e ele faz **redação verdadeira**:

| Etapa | O que acontece com o texto |
|---|---|
| `apply_redactions()` | sai do content stream |
| `clean_contents()` | o stream é reescrito, sem restos do operador de texto |
| `scrub()` | metadados, XMP, anexos, anotações, formulários, miniaturas |
| `save(garbage=4, incremental=False)` | a revisão anterior **não** é anexada; objetos órfãos são coletados |

Não é cifra. Não é ocultação. É **remoção**. Não existe chave que reverta, não
existe mapa guardado, não existe cópia do valor em lugar nenhum do arquivo —
e o `verifier` confere exatamente isso em dez vetores antes de liberar o
download.

> Reverter o PDF anonimizado é tão possível quanto recuperar um arquivo de um
> disco que foi sobrescrito com zeros. A informação não está escondida: ela
> não está lá.

**O que devolve o original é o original.** A ferramenta nunca modifica o
arquivo de entrada — ela escreve um arquivo novo. Se o objetivo é "voltar
atrás", a resposta operacional é guardar o original, com o controle de acesso
que ele merece.

E isso é a característica que dá valor ao produto hoje: é o que permite dizer
que o documento de saída **não é dado pessoal** (ver seção 3).

---

## 2. O que a Fase 2 propõe

Um segundo operador, `pseudonimo`, ao lado de `tarja` — nunca no lugar dele.

Em vez de apagar, substitui por um token estável e reversível **sob chave**:

```
  Mariana Aparecida Souza  ->  [PESSOA-7F3A]
  529.982.247-25           ->  [CPF-2C81]
```

E um **cofre**: um mapa token → valor, cifrado, guardado **fora do PDF**. Com
a chave, um comando local reconstrói o documento original. Sem a chave, o
token não diz nada.

O vocabulário já existe. `politica.py` declara `PSEUDONIMO` e `MASCARA` desde
a Fase 0, e `validar_perfil` os **recusa** justamente para impedir o pior modo
de falha: o usuário pedir pseudônimo, o executor não aplicar nada, e o
relatório afirmar que o documento foi anonimizado.

### Os quatro requisitos, e por que uma LLM não serve

Já registrados em `docs/05-politica-llm.md`, seção 3.1, e repetidos aqui
porque são o critério de aceite:

1. **Determinismo.** A mesma pessoa vira o mesmo token na página 1 e na
   página 80, e no processo inteiro. Amostragem de modelo não dá essa
   garantia.
2. **Reversibilidade sob chave.** O cofre é um mapa cifrado. Isso é
   criptografia, não geração.
3. **Ausência de colisão.** Duas pessoas distintas não podem receber o mesmo
   token.
4. **Não reintroduzir dado pessoal.** Peça a um modelo um nome brasileiro
   plausível e ele devolve o nome de uma pessoa real. Substituir a PII de
   alguém pela de outro alguém é o pior resultado possível, e nada no sistema
   detectaria.

`HMAC` sob chave + pools tipados atendem os quatro, são auditáveis e rodam em
microssegundos.

### O obstáculo técnico que a Fase 0 não resolveu

`tarja` só precisa **apagar** e desenhar um retângulo. `pseudonimo` precisa
**escrever texto de volta no PDF**, e isso é substancialmente mais difícil:

- o token quase nunca tem a largura do valor original — o texto ao redor
  precisa ser reposicionado, ou o token precisa caber na caixa;
- a fonte original pode estar embutida como subconjunto, sem os glifos
  necessários para os caracteres do token;
- reflow em documento de várias colunas quebra o layout, e a promessa atual é
  que **a estrutura do original não muda**.

Nenhum desses está resolvido, e é por isso que a Fase 0 travou o operador em
vez de entregá-lo pela metade.

---

## 3. A decisão que precisa vir antes do código

Esta é a parte que não é técnica, e é a mais importante.

### Documento reversível não é documento anonimizado

Sob a LGPD (Lei 13.709/2018), anonimização e pseudonimização são coisas
diferentes, com consequências diferentes:

- **Dado anonimizado** não é dado pessoal, e sai do escopo da lei — mas essa
  saída vale enquanto o processo **não puder ser revertido** com meios
  próprios ou esforços razoáveis.
- **Dado pseudonimizado** continua sendo dado pessoal. Continua exigindo base
  legal, continua sujeito a direitos do titular, continua exigindo controles
  de segurança, continua sendo comunicável em caso de incidente.

> **Confirme a leitura jurídica com quem assina.** A substância acima é o
> entendimento corrente, mas a citação de artigo por número é de memória e o
> enquadramento do caso concreto é decisão do encarregado/jurídico do cliente,
> não deste documento.

Em termos práticos: **hoje o produto entrega um arquivo que sai do escopo da
LGPD. Ligar `pseudonimo` devolve o arquivo para dentro do escopo.** Isso pode
ser exatamente o que um cliente precisa — ou pode destruir a razão pela qual
ele comprou a ferramenta.

### O cofre concentra o risco

Com `tarja`, comprometer o arquivo de saída não expõe ninguém, porque não há
nada nele. Com `pseudonimo`, o valor de segurança do sistema inteiro se
desloca para o cofre: quem tem a chave reidentifica **todo mundo, em todos os
documentos, de uma vez**.

Isso não é argumento contra fazer — é a definição do que precisa ser
protegido, e muda o que a Fase 2 tem de entregar: gestão de chave, controle
de acesso, trilha de auditoria de cada reversão, e política de retenção do
cofre. O cofre é o produto tanto quanto o PDF.

### Quando cada um faz sentido

| Situação | Operador |
|---|---|
| Publicar no Diário Oficial, responder LAI, divulgar decisão | `tarja` |
| Compartilhar com terceiro que não pode reidentificar | `tarja` |
| Treinar modelo, gerar estatística, análise interna | `tarja` |
| Fluxo interno onde alguém autorizado precisa voltar ao original | `pseudonimo` |
| Documento que circula entre setores e volta para o dono do processo | `pseudonimo` |

**Recomendação: `tarja` continua o padrão.** `pseudonimo` é opção explícita
por documento, com a consequência jurídica dita na tela no momento da
escolha — não escondida numa configuração.

---

## 4. Perguntas que esta fase precisa responder

- O cliente precisa mesmo de reversibilidade, ou precisa de **guardar o
  original com controle de acesso**? As duas resolvem "voltar atrás", e a
  segunda não tem custo jurídico nenhum.
- Quem pode reverter, e como isso é registrado? Sem trilha de auditoria da
  reversão, o cofre é um backdoor sem dono.
- Onde a chave vive? Arquivo local, HSM, Vault, senha do operador? Cada
  resposta muda o modelo de ameaça inteiro.
- O token pode ocupar o espaço do valor original **sem reflow**? Se não, a
  promessa de "a estrutura não muda" precisa ser reescrita.
- Retenção: por quanto tempo o cofre existe? Um cofre eterno é um risco
  eterno.

---

## 5. Tarefas / entregáveis

> Reestruturado pela revisão da seção 0. A ordem importa: a Fase A não depende
> de nenhuma decisão jurídica e pode começar imediatamente; a Fase B não pode
> começar sem as três decisões do Bloco B0.

### FASE A — token irreversível (legibilidade sem custo jurídico)

- [ ] **A1. Teste de ordem de leitura, primeiro.** Antes de qualquer operador:
      um teste que pseudonimiza um documento e afirma que o texto extraído traz
      os tokens **nas posições dos valores originais**, não no fim da página.
      É o item que decide se esta abordagem serve ou se é preciso outra forma
      de inserir texto — por isso vem antes, e não depois.
- [ ] **A2. Operador `pseudonimo` sem cofre.** Mapa valor → token em memória,
      descartado ao fim do documento. Determinismo **intradocumento**. Sem
      chave, sem custódia, sem retenção.
- [ ] **A3. Formato curto e tipado.** `[P-7F3A]`, `[CPF-2C81]`. O tipo precisa
      sobreviver ao token: quem lê o documento tem de saber que ali havia uma
      pessoa, não um CNPJ.
- [ ] **A4. Medir a largura antes de escrever.** Não coube na caixa →
      **falhar o documento**, alto e claro. Nunca entregar deformado, nunca
      entregar com token descartado. Cobre as arestas 1 e 2 da seção 0.
- [ ] **A5. `verifier` adaptado.** Hoje ele confere que o valor sumiu; passa a
      conferir também que **o token está presente**. Sem isso, o descarte
      silencioso da aresta 1 passa pelo gate.
- [ ] **A6. Interface.** Escolha por documento entre `tarja` e `pseudonimo`,
      com a diferença dita na tela no momento da escolha — não numa
      configuração escondida.
- [ ] **A7. Liberar em `politica.py`.** Remover `PSEUDONIMO` da recusa de
      `validar_perfil` **só** depois de A1 a A5 verdes.
- [ ] **A8. Fonte embutida sem os glifos do token.** Herdado do Bloco 2
      antigo, e ainda não medido: um PDF com subconjunto de fonte pode não ter
      os caracteres `[`, `-` ou os dígitos do token. Verificar antes de
      escrever; sem glifo, falhar como em A4.

### FASE B — cofre (reversibilidade, e o custo que vem junto)

**Bloco B0 — decisões, antes de qualquer código**
- [ ] Reversibilidade é requisito real, ou **guardar o original com controle de
      acesso** resolve? As duas resolvem "voltar atrás"; a segunda não tem
      custo jurídico nenhum. Responder isto pode encerrar a Fase B.
- [ ] Onde a chave vive, quem pode reverter, e por quanto tempo o cofre existe.
      Cofre eterno é risco eterno.
- [ ] Confirmação **por escrito** do jurídico do cliente de que a saída
      pseudonimizada volta a ser dado pessoal.

**Bloco B1 — cofre**
- [ ] `cofre.py`: mapa token → valor, cifrado em repouso, com HMAC sob chave
      para o token ser determinístico e sem colisão.
- [ ] Trilha de auditoria: quem reverteu, o quê, quando.
- [ ] Testes: determinismo entre execuções, ausência de colisão, recusa de
      reversão sem chave válida.
- [ ] Decidir explicitamente o escopo do determinismo — intradocumento ou entre
      documentos — com a armadilha de vínculo da seção 0 à vista.

**Bloco B2 — reversão**
- [ ] Comando local `desanonimizar --in doc.pdf --cofre x.vault --chave ...`.
- [ ] Roda sem rede, como todo o resto.

---

## 6. Critérios de aceite

Separados por fase pela revisão da seção 0. Dois critérios da lista original
**valem só para a Fase B** e seriam errados na Fase A — determinismo entre
documentos e o aviso de que o documento continua sendo dado pessoal.

### Valem para as duas fases

- Nenhum operador não implementado é oferecido pela interface.
- O documento pseudonimizado **não contém** o valor original em nenhum dos
  dez vetores do `verifier`.
- `tarja` continua sendo o padrão, e continua produzindo documento
  irreversível.

### Fase A — token irreversível

- **A ordem de leitura do texto extraído é preservada**: os tokens aparecem
  nas posições dos valores originais, não no fim da página. É o critério que
  decide a viabilidade da abordagem.
- O token do mesmo valor é idêntico dentro do documento, e **não há mapa
  algum em disco** ao fim do processamento.
- Todo token está presente no PDF final. Token que não coubesse na caixa
  **reprova o documento** — nunca sai descartado em silêncio nem sobreposto ao
  texto vizinho.
- O tipo da entidade sobrevive no token: quem lê sabe que ali havia uma
  pessoa, não um CNPJ.
- A tela diz, no momento da escolha, que a saída **não é reversível** — nem
  por nós.

### Fase B — cofre

- Token determinístico entre execuções e entre documentos, sem colisão.
- Reversão só com a chave; falha alto e claro sem ela.
- Toda reversão registrada em trilha de auditoria.
- A tela diz, no momento da escolha, que o documento **continua sendo dado
  pessoal** e volta ao alcance da LGPD.

---

## 7. Fora de escopo

Reverter documento produzido pelas Fases 0 e 1. Não há como: aqueles arquivos
foram gerados com `tarja`, o texto não existe neles, e nenhum cofre foi
criado. Qualquer promessa em contrário seria falsa.
