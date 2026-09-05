# 05 — Política de uso de LLM

Onde um modelo de linguagem entra no produto, exatamente o que ele faz em cada
ponto, e exatamente a que dados ele tem acesso. Este documento é normativo: um
uso de LLM que não esteja listado aqui não está autorizado.

Nada descrito aqui está implementado. A Fase 0 não tem LLM nenhuma. O
documento existe agora porque a decisão de arquitetura precisa vir antes da
interface — é ela que define o que a tela oferece e o que o pipeline expõe.

---

## 1. A restrição, formulada corretamente

A formulação intuitiva — *"a LLM não pode ter acesso a dados sensíveis"* — não
se sustenta como está escrita, e vale entender por quê antes de adotá-la.

O pipeline **já** faz dois modelos lerem cada byte de PII de todo documento:
`pt_core_news_lg` e o checkpoint BERT de NER. Se o critério fosse "nenhum
modelo vê dado sensível", a Fase 0 inteira já teria violado a regra.

O que separa os dois casos não é o acesso. São três propriedades:

| | NER (spaCy / BERT) | LLM generativa |
|---|---|---|
| Forma da saída | rótulo + offset | texto livre |
| Pode reproduzir a PII na saída? | não, estruturalmente | sim |
| Deixa rastro entre chamadas? | não | prompt e resposta, e o log de ambos |

O risco de uma LLM não é ela *conhecer* o dado. É o dado **propagar** para
artefatos novos — uma explicação, um resumo, uma trilha de auditoria, um log de
prompt. Cada um desses vira uma cópia de dado pessoal fora do PDF que o
pipeline acabou de sanear, com retenção própria e sem verificação.

Daí as três regras que este documento impõe:

**R1 — Local e sem rede.** A LLM roda via Ollama, no mesmo container, sob
`network_mode: none`. É o mesmo mecanismo que já prova a soberania do resto do
sistema: não é uma promessa de configuração, é uma ausência de interface de
rede.

**R2 — A LLM nunca recebe valor de PII, e nunca escreve um.** Ela opera sobre
*metadados* — tipos, contagens, gêneros documentais, pedidos do usuário — não
sobre valores. Com R2 valendo, os logs nascem limpos por construção, e não por
uma política de saneamento que alguém precisa lembrar de aplicar.

**R3 — A LLM propõe, o humano decide.** Nenhuma saída de LLM altera um
documento sem aprovação explícita. A responsabilidade pelo tratamento é do
controlador; um modelo não pode assumi-la.

> R2 é mais forte do que o estritamente necessário. Uma LLM local num container
> sem rede seria, em rigor, o mesmo perímetro de confiança do spaCy. Adotamos a
> regra mais forte porque ela é **verificável por inspeção do código que monta
> o prompt**, enquanto "a LLM viu, mas não vazou" só seria verificável por
> auditoria de logs — e auditoria de log é controle que falha em silêncio.

---

## 2. Onde a LLM entra

Cinco pontos autorizados. Para cada um: o que ela faz, o que recebe, o que
devolve, e o que acontece se ela errar.

### 2.1 Tradutor de intenção → perfil de política

**Atividade.** O usuário descreve em português o que precisa (*"vou publicar
esta sentença no Diário Oficial; as partes precisam continuar identificáveis,
mas endereço e documentos não podem sair"*). A LLM devolve um
`PerfilPolitica` preenchido: operador por entidade e threshold.

**Acesso a dados.** Só o texto que o usuário escreveu e a lista de entidades
suportadas. **Nenhum acesso ao documento.**

**Saída.** JSON validado por `politica.validar_perfil`. Perfil malformado é
recusado antes de tocar em qualquer arquivo.

**Se errar.** O perfil aparece na tela, campo a campo, para aprovação (R3).
O erro é visível antes de produzir efeito.

**Por que vale a pena.** É o que evita obrigar o usuário a configurar dezesseis
entidades numa tela para anonimizar um documento.

### 2.2 Consultor de risco de reidentificação

**Atividade.** Dado o inventário agregado do documento, apontar risco que a
detecção por entidade não enxerga — o caso clássico sendo a combinação de
quase-identificadores: CEP, data de nascimento e diagnóstico raro reidentificam
uma pessoa sem que o nome apareça em lugar nenhum.

**Acesso a dados.** Apenas o inventário: `{PERSON: 2, CEP: 1, DATE_TIME: 3,
CNS: 1}`, mais o gênero documental. **Nenhum valor, nenhum trecho de texto.**

**Saída.** Alertas em linguagem natural e, opcionalmente, sugestão de endurecer
o perfil.

**Se errar.** Alerta falso custa atenção do revisor; alerta ausente devolve o
sistema ao comportamento que ele já tem hoje. Nenhum dos dois altera o PDF.

**Por que vale a pena.** É provavelmente o uso de maior valor por unidade de
risco. Raciocínio de k-anonimato sobre metadados é exatamente o tipo de erro
que nenhuma camada de NER pega, porque cada campo isolado parece inofensivo.

### 2.3 Redator do relatório de conformidade

**Atividade.** Transformar contagens e a política aplicada em texto de
justificativa para o processo administrativo.

**Acesso a dados.** Contagens por tipo, perfil aplicado, resultado da
verificação. **Nenhum valor.**

**Se errar.** Texto ruim, revisado por quem assina.

### 2.4 Gerador de corpus sintético e de casos adversariais

**Atividade.** Escrever novos gêneros documentais e casos difíceis para o
`generate_corpus.py`.

**Acesso a dados.** Nenhum. A saída é dado sintético por definição.

**Restrição.** Vale para nomes o mesmo cuidado da seção 3: o texto gerado
precisa passar pelos geradores com checksum, não inventar identificadores.

### 2.5 Explicador de métricas

**Atividade.** Traduzir o `report.md` para quem decide e não é técnico.

**Acesso a dados.** O relatório de métricas, que é agregado. **Nenhum valor.**

### 2.6 Análise do documento pseudonimizado

> Acrescentado em 2026-09-05, quando o operador de token (`pseudonimo.py`)
> e a saída de texto passaram a existir. **Ainda não há envio implementado** —
> esta seção autoriza o uso e fixa suas condições antes de o código existir,
> que é a ordem que este documento exige.

**Atividade.** O usuário faz perguntas sobre o próprio documento — resumir,
localizar, classificar, explicar o andamento — e a LLM responde com base no
texto pseudonimizado.

**Acesso a dados.** O documento **inteiro**, em texto, com cada valor
detectado já substituído por token (`[P-7F3A]`, `[CPF-2C81]`). É o único ponto
desta lista que vê o corpo do documento, e por isso ele precisa de análise
própria em vez de herdar a dos outros cinco.

**Por que isso não viola R2.** R2 diz que a LLM nunca recebe valor de PII. A
substituição por token garante isso **por construção**, e não por promessa: o
artefato só existe depois de `verify_texto` confirmar as duas metades —
nenhum valor original sobreviveu, e nenhum token se perdeu. Um texto que
falhe qualquer uma das duas não é gerado, não fica em disco e não pode ser
baixado.

Vale registrar que este ponto é **mais forte** que o texto original de R2 em
um aspecto e mais fraco em outro. Mais forte: aqui há verificação automática
do que a LLM recebe, o que nenhum dos outros cinco pontos tem. Mais fraco: os
outros cinco veem metadados agregados, e este vê a estrutura narrativa
completa do documento.

**Saída.** Texto livre, em resposta ao usuário. Ela pode conter tokens — e
deve, porque é assim que a resposta fica rastreável ao documento. Ela **não**
pode conter valor original, e não tem como conter: o modelo nunca viu um.

**Se errar.** Uma análise errada é uma análise errada — o documento não é
alterado, e R3 continua valendo integralmente: nenhuma saída de LLM altera
PDF, texto ou span sem aprovação humana explícita.

**O que esta autorização não cobre, e precisa de decisão separada:**

1. **Para onde o texto vai.** R1 exige LLM local sob `network_mode: none`. A
   decisão de 2026-09-05 é usar **LLM externa** (ver `goal-fase-3.md` §2), o
   que é uma exceção explícita a R1 e traz junto: serviço de egress isolado
   sem acesso ao original, consentimento por documento, retenção acertada com
   o provedor, e registro do que foi enviado. Nada disso está implementado.

2. **O que o gate não prova.** `verify_texto` prova que os valores *que
   decidimos substituir* não sobreviveram. Não prova que tudo que era dado
   pessoal foi detectado. Os dois furos medidos continuam: `PERSON` escapa em
   cerca de 1 documento a cada 50, e identificador indireto por contexto
   (§3.2) não é detectado de forma alguma — e nenhum token o resolve, porque
   não há o que substituir. Com envio externo, esses furos deixam de ser
   defeito local e viram incidente com terceiro.

---

## 3. Onde a LLM **não** entra

### 3.1 Pseudonimização — proibido, e não por causa de exposição

Gerar o pseudônimo é a tarefa que mais parece caber a uma LLM e menos cabe. A
pseudonimização tem quatro requisitos, e a geração por modelo viola todos:

1. **Determinismo.** A mesma pessoa precisa virar o mesmo token na página 1 e
   na página 80, e no processo inteiro, não só num documento. Amostragem de
   modelo não dá essa garantia.
2. **Reversibilidade sob chave.** O cofre da Fase 2 é um mapa cifrado. Isso é
   criptografia, não geração.
3. **Ausência de colisão.** Duas pessoas distintas não podem receber o mesmo
   token, e nada na geração impede isso.
4. **Não reintroduzir dado pessoal.** Peça a um modelo um nome brasileiro
   plausível e ele devolve o nome de uma pessoa real. Substituir a PII de
   alguém pela PII de outro alguém é o pior resultado possível — e nada no
   sistema detectaria.

`Faker` com semente e HMAC sob chave atende os quatro, é auditável e roda em
microssegundos. A única fresta onde uma LLM ajudaria — escolher substituto
coerente de tipo, para o texto não ficar absurdo — sai mais barato com pools
tipados.

### 3.2 Detecção — proibido nesta arquitetura, com custo conhecido

É honesto registrar que **o lugar onde a LLM agregaria mais valor bruto é
justamente o que R2 bloqueia**. O que ela pegaria e o pipeline atual nunca vai
pegar são os identificadores indiretos por contexto: *"o único servidor cego da
repartição"*, *"o filho mais velho do prefeito de Ouro Preto"*. Não há regex
nem NER que resolva isso; é compreensão de texto.

O custo dessa decisão precisa ficar explícito, porque as métricas não o
mostram: a cobertura de caracteres do `report.md` mede o quanto cobrimos das
entidades **que estão no gabarito**, e o gabarito também não contém
identificadores indiretos. Um número alto ali não é evidência de ausência desse
risco — é silêncio sobre ele.

Isso é uma limitação assumida do produto, não uma lacuna esquecida. Se o
cliente exigir cobertura de identificador indireto, a decisão a rediscutir é
R2, e a rediscussão é sobre perímetro de confiança, não sobre modelo.

### 3.3 Aplicação silenciosa de qualquer decisão

Nenhuma saída de LLM altera documento sem aprovação humana explícita (R3).
Vale inclusive para o caminho fácil de violar: aplicar automaticamente um
perfil "óbvio" em processamento de lote.

---

## 4. Resumo do acesso a dados

| Ponto | Vê o documento? | Vê valores de PII? | Vê metadados? | Altera o PDF? |
|---|---|---|---|---|
| 2.1 Perfil a partir da intenção | não | não | lista de entidades | não |
| 2.2 Risco de reidentificação | não | não | contagens por tipo | não |
| 2.3 Relatório de conformidade | não | não | contagens e política | não |
| 2.4 Corpus sintético | não | não | não | não |
| 2.5 Explicador de métricas | não | não | métricas agregadas | não |
| 2.6 Análise do documento pseudonimizado | **sim**, em texto, com token no lugar de cada valor | não — garantido por `verify_texto`, não por promessa | o corpo do documento | não (R3) |
| 3.1 Pseudonimização | — | **proibido** | — | — |
| 3.2 Detecção | **proibido** | **proibido** | — | — |

Nenhuma linha da tabela tem "sim" na coluna de valores de PII. Se uma
funcionalidade futura exigir esse "sim", ela não é uma extensão deste
documento — é uma revisão de R2, com decisão registrada.

---

## 5. Como isso se verifica

R1 se verifica sozinho: o container não tem interface de rede, e
`make offline-proof` falha se alguma etapa precisar de egress.

R2 se verifica por inspeção do montador de prompt. A regra de implementação é
que **a função que monta o prompt não recebe o texto do documento como
parâmetro** — ela recebe o inventário. Com essa assinatura, passar PII para a
LLM deixa de ser um erro de disciplina e passa a ser um erro de tipo, visível
em revisão de código e testável.

R3 se verifica na interface: toda proposta de LLM entra na tela como sugestão
pendente de aprovação, nunca como estado aplicado.
