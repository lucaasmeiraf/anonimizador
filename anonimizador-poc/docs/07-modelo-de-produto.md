# 07 — Modelo de produto: os dois planos e o que cada um exige

Registra o objetivo comercial do projeto, declarado em 2026-09-05, e o que ele
implica tecnicamente. Existe porque a documentação até aqui descrevia **uma**
forma de entrega — ferramenta local, instalada pelo cliente — e o objetivo real
tem duas, com posturas jurídicas diferentes.

Este documento é honesto sobre o que ainda não existe. Ele não é material
comercial; é o que precisa estar resolvido antes de material comercial existir.

---

## 1. O objetivo, na formulação do dono do produto

> *"O que eu quero vender é a solução já com a estrutura necessária para
> escalabilidade e sustentabilidade para o cliente. Olha, a aplicação é essa e
> para mantê-la você deverá contratar isso e aquilo, a configuração será essa e
> eu posso realizá-la com um custo ou o seu profissional de TI segue a
> documentação e realiza todo o processo."*

Dois planos:

| | **Pessoa física** | **Empresa** |
|---|---|---|
| Cobrança | assinatura mensal, cota de documentos | contrato |
| Banco de dados | **só autenticação** | autenticação + auditoria |
| Trilha de auditoria | não | **sim** — o trajeto do documento |
| Análise por LLM | não | adicional opcional |
| Agentes configuráveis | não | adicional opcional, por contratante |

A separação é boa e vale ser dita: **o plano PF não precisa de banco para nada
além de saber quem é você.** Sem histórico, sem auditoria, sem retenção. Isso
preserva, para aquele plano, a garantia mais forte que o produto tem.

---

## 2. A pergunta que este documento existe para forçar: quem hospeda?

É a decisão de maior consequência do projeto inteiro, e ela ainda **não foi
tomada**. Tudo abaixo depende dela.

A promessa central hoje — verificável por `make ui-proof`, e escrita na
primeira linha do README — é *"o documento não sai da sua máquina"*. Ela vale
porque o software roda no Docker **do cliente**, numa rede sem rota para fora.

Uma assinatura mensal com cota de documentos sugere o oposto: que **nós**
hospedamos. E aí a promessa inverte.

### As duas leituras, e o que cada uma custa

**(a) PF auto-hospedado.** O cliente instala o Docker e roda na máquina dele.
A assinatura é uma **licença de uso**, não um serviço.

- A soberania continua intacta, e o argumento de venda continua o mesmo.
- **Mas medir "X documentos por mês" exige que a aplicação ligue para casa** —
  e isso é egress num produto cuja característica vendida é não ter egress.
  Ou se confia no contador do cliente (inaplicável), ou se aceita uma chamada
  de licenciamento, que precisa ser explicada e provada como não carregando
  conteúdo. É resolvível, mas é uma decisão, não um detalhe.
- Suporte é mais caro: cada cliente tem um ambiente diferente.

**(b) PF como serviço (SaaS).** Nós hospedamos, o cliente envia o PDF.

- Cobrança e cota ficam triviais.
- **A promessa se inverte por completo.** O documento com dado pessoal em
  claro sai da máquina do cliente e chega à nossa — que é exatamente o que o
  README hoje critica: *"Mandar para um serviço na nuvem... o documento com os
  dados sensíveis foi entregue a um terceiro, muitas vezes fora do país, antes
  de ser protegido."* Vender o plano PF como SaaS mantendo esse texto seria
  descrever o concorrente e ser ele.
- **Nós viramos operador de tratamento** perante a LGPD: contrato de
  tratamento com cada cliente, dever de segurança, dever de comunicar
  incidente, e responsabilidade solidária em certas hipóteses. Não é
  impeditivo — é um negócio diferente, com custo de conformidade próprio.

> **Nenhuma das duas é errada. O erro seria escolher por omissão** e descobrir
> a consequência depois de o material comercial estar impresso.

---

## 3. O que "escalável" exige, e ainda não existe

O objetivo é vender a solução *já com a estrutura para escalabilidade*.
Medido no código, hoje ela não existe — e isso é afirmação técnica, não
pessimismo:

| Obstáculo | Onde está | Por que impede escalar |
|---|---|---|
| Sessão em memória do processo | `Sessoes._itens`, um `dict` com `Lock` | duas réplicas não compartilham nada; a requisição que cair na réplica errada não acha a sessão |
| Modelo carregado por processo | `app.pipeline()`, ~1 GB, ~30 s na subida | cada réplica paga RAM e tempo de partida |
| Sem autenticação | não existe no `app.py` | qualquer um que alcance a porta envia e baixa documento |
| Sem multi-inquilino | não existe | não há a quem um documento pertence |

Hoje "escalar" significa **uma máquina maior**, não mais máquinas. Isso serve
para muitos clientes e é uma resposta legítima — desde que dita, e não
subentendida.

### A armadilha ao consertar isso

A solução óbvia para sessão compartilhada é guardá-la no banco. **Não pode.**
`SpanUI.valor` carrega o valor da PII em texto; persistir a sessão colocaria
dado pessoal no banco, com backup, réplica, WAL e retenção própria, fora dos
dez vetores que o verificador confere. Quebra a invariante 9.

A regra, que precisa virar invariante:

> **O banco guarda identidade e trilha. O documento e seus valores ficam em
> disco, com TTL.** Sessão compartilhada, quando precisar existir, sai de
> volume compartilhado ou de afinidade de sessão — nunca de PII no banco.

---

## 4. Multi-inquilino é maior que autenticação, e a ordem importa

"Login" e "isolamento entre clientes" são coisas diferentes, e a segunda é
transversal: sessão, arquivo em disco, linha no banco, trilha de auditoria e
configuração de agente. Um documento da empresa A não pode ser alcançável pela
empresa B em **nenhuma** dessas camadas.

Isolamento retrofitado é, notoriamente, o que vaza — porque basta uma consulta
sem filtro de inquilino para furar tudo. Se o plano empresa é destino real, o
inquilino entra **junto** com a autenticação, não depois.

---

## 5. Agentes por contratante — o risco específico

O plano empresa prevê "agentes configurados pela contratante": prompts próprios
para analisar os documentos anonimizados.

O prompt de sistema em `web/analise.py` instrui o modelo a **nunca inventar nem
adivinhar** o nome por trás de um token. É a única defesa contra o risco
específico de mandar documento pseudonimizado a um LLM: ele é bom em inferir
identidade a partir de contexto.

Um prompt configurável pelo cliente pode desfazer essa instrução — por
descuido ou de propósito. Portanto:

- o prompt do contratante **acrescenta**, nunca substitui;
- o prompt de sistema é a **última** palavra na montagem da mensagem, não a
  primeira;
- a instrução de não reidentificar não é configurável, em nenhum plano.

---

## 6. O que bloqueia a venda hoje, em ordem de urgência

Não são itens de engenharia, e nenhum deles fica mais barato adiando.

**1. RN-04 — licença do PyMuPDF.** É AGPL-3.0 ou licença comercial da Artifex.
Isto precisa ser resolvido **antes** da estrutura comercial, não depois, porque
a resposta muda o modelo de negócio:

- A cláusula de uso em rede da AGPL (§13) alcança software oferecido **como
  serviço**. Se o plano PF for SaaS com PyMuPDF sob AGPL, há obrigação de
  disponibilizar o código aos usuários — o que é incompatível com vender
  software fechado.
- A licença comercial da Artifex resolve, e tem custo, que entra na
  precificação.

Enquanto isso não estiver decidido, qualquer tabela de preço é chute.

**2. RN-05 — licença do checkpoint LeNER-Br.** Não declarada. Sem licença
declarada não há permissão de uso comercial presumida. Alternativas:
`bertimbau-harem` (que aliás mede melhor: F1 relaxado 0.862 contra 0.774) ou
treinar um próprio.

**3. O gate de usabilidade nunca foi medido.** A afirmação central do produto é
que uma pessoa revisa e corrige o que a máquina errou. Isso nunca foi testado
com ninguém além de quem escreveu o código. O instrumento está pronto
(`eval/gate_usabilidade.py`); faltam de 3 a 5 pessoas. **Vender a garantia
antes de medi-la é o risco comercial mais barato de eliminar** que existe neste
projeto.

**4. RN-07 — citações normativas não verificadas.** São o alicerce do argumento
de soberania e vieram de memória.

---

## 7. Sequência recomendada

Deliberadamente diferente da ordem intuitiva, e a razão está em cada linha.

1. **Decidir quem hospeda o plano PF** (§2). Gratuito, e todo o resto depende.
2. **Resolver RN-04** (§6.1). A resposta muda a precificação e pode impedir o
   modelo SaaS. Fazer isso depois de construir é descobrir tarde.
3. **Medir o gate de usabilidade.** Barato, e valida a promessa central.
4. **Autenticação + inquilino, juntos** (§4), com a regra do §3 travada por
   teste: nenhum valor de PII chega ao banco.
5. **Trilha de auditoria do documento** — upload, revisão, aprovação,
   download, envio externo. Só faz sentido depois de existir "quem".
6. **Cobrança e cota**, cuja forma depende inteiramente do passo 1.
7. **Escala horizontal**, se e quando um cliente exigir. Máquina maior atende
   muita gente, e é honesto dizer isso.

Os passos 1 a 3 não são de engenharia e podem correr em paralelo ao
desenvolvimento. Os passos 4 em diante são, e cada um fica mais caro se
construído antes dos três primeiros.
