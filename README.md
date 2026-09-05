# Anonimizador

**Remove dados pessoais de documentos PDF — de verdade, e sem que o documento
saia da sua máquina.**

Você envia um PDF, a ferramenta marca o que identificou como dado pessoal,
você confere e corrige a proposta na tela, e só então o arquivo protegido é
gerado. O processamento é inteiramente local: o serviço que lê o seu documento
roda sem interface de rede.

> Há **um** recurso opcional que usa a internet — a análise por IA, que envia
> o *texto já protegido* (nunca o PDF, nunca o original) a um modelo externo.
> Ele só funciona se você configurar uma chave de API, e está descrito com os
> riscos [mais abaixo](#análise-por-ia--opcional-e-o-que-ela-custa). Desligado,
> nada sai da máquina em nenhum momento.

---

## O problema que ele resolve

Um órgão público precisa publicar um processo. Um escritório precisa mandar um
contrato para a outra parte. Um hospital precisa compartilhar um prontuário
para pesquisa. Em todos os casos o documento precisa sair, e o dado pessoal
não pode ir junto.

O jeito comum de fazer isso falha de duas maneiras, e as duas custam caro:

**Tarjar à mão.** Alguém abre o PDF e desenha retângulos pretos por cima dos
nomes. O resultado *parece* protegido, mas o texto continua dentro do arquivo,
embaixo do retângulo — e volta com um simples copiar e colar. É a origem de
praticamente todo vazamento público de documento "tarjado" que virou notícia.

**Mandar para um serviço na nuvem.** Resolve o problema técnico e cria outro:
o documento com os dados sensíveis foi entregue a um terceiro, muitas vezes
fora do país, **antes** de ser protegido.

Esta ferramenta não faz nenhum dos dois. A proteção acontece na sua máquina, e
o que eventualmente sai — se você ligar a análise por IA — é o texto depois de
protegido e conferido, nunca antes.

---

## As três garantias

### 1. A tarja apaga o texto, não o esconde

Quando um trecho é tarjado, ele é **removido do arquivo**. Não é uma imagem
por cima, não é uma cifra, não é ocultação. O texto deixa de existir no PDF.

E não basta tirar da página: o mesmo dado costuma estar guardado em paralelo
em lugares que ninguém olha — nas propriedades do arquivo, em anexos, em
comentários, em campos de formulário, no sumário, em versões antigas que o PDF
carrega junto. Todos esses lugares são limpos.

> Consequência que vale entender antes de decidir: **não existe como
> desfazer.** Não há chave, não há cópia guardada, não há mapa. Se você
> precisa poder voltar ao original, guarde o original — a ferramenta nunca
> altera o arquivo que você envia, ela escreve um arquivo novo.

### 2. O documento não sai da sua máquina

Não é uma promessa de configuração — é uma ausência de capacidade. A parte do
sistema que lê o seu documento roda **sem interface de rede**: mesmo que
alguém quisesse enviar o arquivo para fora, não existe caminho por onde.

Isso é verificável, e não apenas afirmado. Um comando (`ui-proof`) tenta
alcançar a internet de dentro do serviço que processa documentos e **falha o
teste** se conseguir.

> **Uma exceção, e ela é sua para ligar ou não.** Existe um recurso opcional de
> análise por IA, em que o **texto com código** — nunca o PDF, nunca o
> original — é enviado a um modelo externo. Ele vive num componente separado,
> que não tem acesso ao seu documento original e não faz nada além de repassar
> o texto. Se você não configurar uma chave de API, ele não faz nada.
>
> Quando você usa esse recurso, a garantia acima muda de natureza para aquele
> texto: sai de "não existe caminho para fora" para "o que sai já passou por
> duas conferências". Leia a seção sobre isso antes de decidir — a diferença é
> real e está descrita sem maquiagem.

### 3. Nada é entregue sem conferência independente

Depois de gerar o arquivo protegido, uma segunda etapa **reabre o resultado do
zero** e procura cada valor que deveria ter sido removido, em dez lugares
diferentes do arquivo — inclusive na leitura crua dos bytes, e usando uma
biblioteca de leitura diferente da que fez a remoção.

Se qualquer valor sobrevive em qualquer um desses dez lugares, **não existe
botão de download.** O arquivo reprovado é apagado, e a tela explica o que
sobreviveu e onde.

---

## Como funciona, na prática

```
   1. Enviar          2. Revisar             3. Aprovar        4. Baixar
   ──────────         ──────────             ─────────         ────────
   Você envia    →    Original e proposta →  Você assina   →   Só sai se a
   o PDF              lado a lado.           embaixo           conferência
                      Você liga e desliga                      aprovar
                      cada tarja
```

**A revisão humana é o centro do produto, não um detalhe.** A detecção
automática erra nos dois sentidos, e a ferramenta é desenhada em torno de qual
erro é mais fácil de consertar:

- Sobrou uma tarja onde não precisava → você **vê** e desliga com um clique.
- Faltou uma tarja → você precisa notar uma **ausência**, o que é bem mais
  difícil.

Por isso a configuração escolhida prefere errar para o lado de marcar demais.
Medido no conjunto de testes: ela encontra **92,5%** dos nomes de pessoa, ao
custo de que cerca de um terço do que ela marca não precisava ser marcado —
e é exatamente isso que a tela existe para você corrigir.

Se algo passou batido, você pode selecionar o trecho na tela e tarjar só
aquela ocorrência, ou digitar um valor e tarjar todas as ocorrências dele no
documento.

### Duas saídas, para dois usos diferentes

A tarja é perfeita para publicar e péssima para analisar, e a razão é a mesma:
ela apaga o texto de verdade. Num PDF tarjado não há como saber se o servidor
citado no parágrafo 3 é o mesmo do parágrafo 9 — as tarjas são todas iguais.
Para publicar no Diário Oficial isso não é problema. Para pedir a alguém, ou a
uma ferramenta, que analise o documento, é: perde-se o fio da narrativa.

Por isso a ferramenta produz dois arquivos a partir da mesma revisão:

| | **PDF tarjado** | **Texto com código** |
|---|---|---|
| O que aparece no lugar do nome | nada — o texto foi removido | `[P-7F3A]` |
| Serve para | publicar, responder LAI, arquivar | analisar, resumir, submeter a uma IA |
| Dá para seguir o mesmo ator no documento? | não | sim |
| É reversível? | **não** | **não** |

O código é sorteado, não calculado a partir do nome, e o mapa que os liga é
descartado assim que o arquivo fica pronto. **Não existe chave, não guardamos
nada, e nem nós conseguimos voltar ao original** — o mesmo código representa
outra pessoa em outro documento. É o que mantém as duas saídas no mesmo
patamar de proteção; a diferença entre elas é de legibilidade, não de
segurança.

Os dois arquivos passam por conferência antes de serem liberados. A do texto
confere duas coisas: que nenhum valor original sobreviveu, e que nenhum código
se perdeu no caminho — porque um arquivo em que o nome sumiu mas o código não
entrou pareceria correto e não seria.

### Análise por IA — opcional, e o que ela custa

Você pode pedir que um modelo de linguagem analise o documento: resumir,
localizar, explicar o andamento. **O que é enviado é o texto com código**, e é
por isso que o código existe — um PDF tarjado chega ao modelo como
`O servidor ⏎ compareceu`, sem nem indicar que havia alguém ali, e é assim que
se produz uma análise inventada.

Como ligar:

```
cd anonimizador-poc
cp .env.example .env      # cole sua chave do OpenRouter em OPENROUTER_API_KEY
make ui-llm
```

Sem chave, o recurso simplesmente não funciona — não há envio silencioso.

**Antes de enviar, três travas correm nesta ordem:** o texto precisa ter
passado pela conferência; a detecção roda **de novo** sobre o texto de saída,
com critério mais rigoroso, e qualquer coisa encontrada **cancela o envio**; e
o envio é sempre uma ação por documento, nunca uma configuração que fica
ligada. Cada envio é registrado — quando, para onde, qual modelo, quantos
caracteres. O conteúdo não é registrado.

**E o que isso custa, dito sem maquiagem.** Nenhuma dessas travas prova que
*tudo* que era dado pessoal foi encontrado — elas provam que o que a ferramenta
decidiu remover não sobreviveu. A detecção tem dois furos medidos: um nome
escapa em cerca de 1 documento a cada 50, e identificador indireto por contexto
(*"o único servidor cego da repartição"*) não é detectado de forma alguma, e
nenhum código o resolve, porque não há o que substituir.

Sem envio externo, um nome que escapou é um defeito que fica na sua máquina e
você corrige na próxima revisão. **Com envio externo, o mesmo defeito vira
incidente com terceiro**: o dado saiu, pode ter sido registrado ou usado em
treino, e apagar depois não desfaz o envio.

Por isso, duas recomendações concretas: revise antes de enviar, e configure a
retenção na sua conta do provedor (`openrouter.ai/settings/privacy`) — alguns
provedores treinam com o que recebem, e isso é decisão sua, não deste
software.

### O que ele identifica sozinho

| | |
|---|---|
| **Identificadores** | CPF, CNPJ, RG, CNH, PIS/PASEP, título de eleitor, cartão do SUS, processo judicial (CNJ) |
| **Contato** | telefone, e-mail, CEP, endereço |
| **Pessoas e entidades** | nome de pessoa, organização, local, data |

Os identificadores numéricos são conferidos pelo dígito verificador — um CPF
válido é reconhecido com certeza matemática, não por parecer um CPF. Números
com dígito errado (comum em minuta, formulário preenchido à mão ou documento
digitalizado) também são apontados, mas marcados como suspeita, não como
certeza — e a tela diz qual é qual.

Nome de órgão, cidade e data começam **preservados**, não tarjados. Um ato
administrativo sem o órgão e sem a data perde o sentido de ser publicado. Você
pode mudar isso por documento.

---

## O que ele **não** faz

Esta lista é parte da ferramenta, não uma ressalva escondida no rodapé.

| Limitação | O que significa |
|---|---|
| **Não lê documento digitalizado** | Se o PDF é uma foto ou uma digitalização sem texto embutido, não há texto para remover. A ferramenta recusa o arquivo em vez de mostrar uma tela vazia que pareceria "nada encontrado". |
| **Invalida assinatura digital** | Alterar o arquivo quebra a assinatura — é matemático, não tem contorno. Documento de órgão público costuma vir assinado. *Ainda não testado com documento assinado real.* |
| **Remove todos os links** | Inclusive os inofensivos. |
| **Apaga o sumário inteiro** | Não só as entradas que continham dado pessoal. |
| **Zera as propriedades do arquivo** | Autor, título, data de criação, programa que gerou. |
| **Não desfaz** | Ver a primeira garantia. O que devolve o original é o original. |
| **Não altera o layout** | Página, fontes e diagramação ficam idênticas. Isso é intencional. |

---

## Anonimização e LGPD: a distinção que costuma ser vendida errado

A LGPD trata dois casos de forma diferente, e a diferença muda a obrigação
legal:

- **Dado anonimizado** deixa de ser dado pessoal e sai do alcance da lei — mas
  **só enquanto o processo não puder ser revertido**.
- **Dado pseudonimizado** (substituído por um código que alguém consegue
  desfazer) **continua sendo dado pessoal**, com todas as obrigações que isso
  traz.

**As duas saídas desta ferramenta são irreversíveis** — a tarja porque apaga o
texto, e o texto com código porque o código é sorteado e o mapa é descartado.
Nenhuma das duas guarda chave, então as duas ficam no caso mais forte. A
irreversibilidade parece uma limitação e é justamente o que dá valor ao
resultado.

Um modo reversível sob chave chegou a ser desenhado, para o caso em que
alguém autorizado precisasse voltar ao original. **Ele foi descartado**, e a
razão vale ser dita: quem tem o documento original já pode "voltar atrás"
guardando-o com o controle de acesso que ele merece — e essa solução não
custa nada em obrigação legal, enquanto guardar uma chave devolveria o
arquivo de saída para dentro do alcance da LGPD.

> Uma ressalva honesta: "sair do alcance da lei" vale enquanto a
> reidentificação não for viável por esforços razoáveis. A orientação da ANPD
> é baseada em risco, e não existe técnica com eficácia plena — nem esta.

> A leitura jurídica do seu caso concreto é de quem responde por ela na sua
> organização. O que a ferramenta faz é descrever com precisão o que ela fez
> com o arquivo, para que essa decisão seja tomada sobre fato, e não sobre
> suposição.

### E a Lei de Acesso à Informação

Em documento público as duas leis puxam para lados opostos: a LGPD empurra
para tarjar, a LAI empurra para preservar, porque publicidade é a regra.

**Tarjar demais não é o lado seguro — é a outra falha.** Um documento tarjado
além da conta perde valor probatório e pode descumprir a LAI tanto quanto o
contrário descumpre a LGPD. É por isso que a ferramenta preserva órgão, local
e data por padrão, e por isso a decisão final é sempre de uma pessoa.

---

## Começando

**Único pré-requisito: Docker.** Nada é instalado na máquina — nem Python, nem
os modelos de inteligência artificial. Tudo vive dentro do container.

```powershell
cd anonimizador-poc
.\run.ps1 build      # única etapa que usa internet: baixa a imagem
.\run.ps1 ui         # abre em http://127.0.0.1:8000
```

Em Linux, macOS ou WSL, use `make build`, `make ui` — os alvos são os mesmos.

O modelo leva cerca de 30 segundos para carregar na primeira subida.

```powershell
.\run.ps1 ui-proof   # prova que a interface responde E que não há saída para a internet
.\run.ps1 test       # 217 testes
```

---

## Por dentro

```
  PDF ──► extração de texto com a posição exata de cada caractere
           │
           ├─► reconhecedores por padrão + dígito verificador  (CPF, CNPJ, ...)
           ├─► modelo de linguagem local para nomes            (bert-lenerbr)
           └─► reforço por contexto (palavras-âncora ao redor)
           │
           ▼
       resolução de conflitos ──► REVISÃO HUMANA ──► remoção + saneamento
       (checksum vence                                      │
        estatística)                                        ▼
                                            conferência independente, 10 vetores
                                                            │
                                          aprovou? ──► download   reprovou? ──► apagado
```

A peça de maior risco técnico é a primeira: traduzir "o caractere número 1.043
do texto" para "este retângulo, nesta página". Uma tarja deslocada por um
caractere é um vazamento. A tradução é feita percorrendo o documento uma única
vez e construindo texto e coordenadas em paralelo — sem buscar a string na
página, que é o caminho intuitivo e o que erra quando a mesma palavra aparece
cinco vezes.

Detalhes técnicos, decisões e o porquê de cada uma:
[`anonimizador-poc/README.md`](anonimizador-poc/README.md).

---

## Estado do projeto

Isto **não é um produto acabado.** É um sistema em construção, com cada fase
documentada e medida antes de a seguinte começar.

| Fase | O que respondeu | Estado |
|---|---|---|
| **0** — Detecção e redação | "a stack local aguenta, e com que qualidade?" | ✅ concluída, com números |
| **1** — Interface de revisão | "uma pessoa consegue confiar e assinar embaixo?" | 🔶 quase concluída — falta medir o gate de usabilidade com pessoas reais |
| **2A** — Código no lugar do nome | "dá para o documento continuar legível sem expor ninguém?" | ✅ concluída — saída de texto, sem chave e sem cofre |
| **2B** — Reversibilidade sob chave | "dá para desfazer, com controle?" | ⛔ encerrada — guardar o original resolve, sem custo legal |
| **3** — Perímetro de rede | "vale abrir a rede para análise por IA?" | 🔶 decidida e construída — falta a tela e a retenção no provedor |

**Antes de qualquer entrega comercial**, duas pendências de licenciamento
precisam ser resolvidas: a biblioteca de PDF (AGPL ou licença comercial) e o
modelo de linguagem jurídico (licença não declarada). As duas estão descritas
em [`anonimizador-poc/docs/02-requisitos.md`](anonimizador-poc/docs/02-requisitos.md),
RN-04 e RN-05.

Todos os testes e medições usam **exclusivamente documentos sintéticos**.
Nenhum documento real entra no ambiente de desenvolvimento.

---

## Documentação

| Para quem | Onde |
|---|---|
| **Cliente e decisor** | este arquivo |
| Quem instala e opera | [`docs/04-implantacao.md`](anonimizador-poc/docs/04-implantacao.md) |
| Quem calibra para um caso de uso | [`docs/03-configuracao.md`](anonimizador-poc/docs/03-configuracao.md) |
| Quem valida escopo ou monta proposta | [`docs/02-requisitos.md`](anonimizador-poc/docs/02-requisitos.md) |
| Quem decide arquitetura | [`docs/06-resultados-fase-0.md`](anonimizador-poc/docs/06-resultados-fase-0.md) e os `goal-fase-*.md` |
| Quem escreve código | [`CLAUDE.md`](CLAUDE.md) — invariantes e regras de mudança |
