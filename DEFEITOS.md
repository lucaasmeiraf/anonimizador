# Defeitos abertos

Defeito **aberto** é o que já foi observado e ainda não foi corrigido. Quando
fechar, sai daqui e a explicação vai para o comentário do código ou para o
`goal-` da fase — este arquivo não é histórico, é lista de trabalho.

Limitação conhecida e aceita **não** entra aqui: essa vai para a tabela "O que
ele não faz" do `README.md`, que é onde o cliente lê. A diferença é intenção —
o que está abaixo ninguém decidiu que ficaria assim.

---

## D-01 — A tarja come texto das linhas vizinhas

**Gravidade: alta.** É o terceiro modo de falha da tabela do `CLAUDE.md` §1 —
tarja no lugar errado, cobrindo texto inocente — e tem consequência jurídica:
remove `ORGANIZATION`, que nasce em `manter` porque a LAI exige que o órgão do
ato continue legível.

Observado em 2026-09-16, no `documento_teste_anonimizacao_01_contrato_teste.pdf`.
Vale para os **dois** operadores; não tem relação com a entrega do token.

### O que acontece

```
original:  CONTRATANTE: Aurora Sistemas Administrativos Ltda., CNPJ nº 48.271.936/0001-40, com sede
saída:     CONTRA                                   istrativos Ltda., CNPJ nº [CNPJ-DC4E]     m sede
```

Sumiram, além da PII: `CONTRATANTE:`, `Aurora Sistemas Administrativos`, `com`,
`Bairro`, `Central,`, `Brasília/DF,`, `representada`, `por`, `telefone`,
`residente`, `ficticiamente`.

### Causa raiz, confirmada

A entrelinha do documento é mais apertada que a caixa do caractere: 12,00pt de
entrelinha contra 13,74pt de caixa. As fileiras se **sobrepõem em 1,82pt**.

```
CONTRATANTE: Aurora Sistemas…        y0=154,25  y1=168,07
fictícia na Avenida das Palmeiras…   y0=166,25  y1=179,99   <- invade 1,82pt
representada por Marina Duarte…      y0=178,25  y1=191,99   <- invade 1,82pt
```

O retângulo da tarja está **correto** — tem exatamente a caixa do valor. O que
o produz é `apply_redactions`, que remove todo caractere cuja caixa **encosta**
no retângulo. Como o retângulo tem a altura da caixa, ele alcança 1,8pt das
fileiras de cima e de baixo, no mesmo intervalo horizontal.

Por isso o diagnóstico demorou: spans corretos, retângulos corretos, valores
removidos e `verify` aprovando — e ainda assim texto inocente sumindo.

### Correção medida, não aplicada

Encolhendo o retângulo verticalmente, no mesmo documento:

| inset | valor removido | `Palmeiras`, na linha de cima |
|---|---|---|
| **0,0pt (hoje)** | sim | **destruído** |
| 1,0 a 6,0pt | sim | preservado |

A janela é larga porque o alvo continua interseccionando: a caixa dele ocupa a
altura inteira do retângulo.

### Por que a suíte não pega, e o que fazer antes de corrigir

| | invasão vertical entre fileiras |
|---|---|
| Corpus do eval | **0,00pt em 50 de 50** |
| PDFs dos testes (`tmp_pdf`) | 0,00pt — 13pt de espaçamento, caixa de 12,37 |
| Documento realista | **1,82pt** |

Não é um teste faltando: **nenhum documento do corpus consegue reproduzir o
caso**, porque o gerador usa entrelinha mais larga que a caixa. `make eval` dá
o mesmo número com ou sem a correção.

Ordem proposta:

1. **Corpus primeiro** — `eval/generate_corpus.py` passa a produzir também
   documentos de entrelinha apertada. Sem isso não há medição que signifique
   nada, nem regressão detectável depois.
2. **Depois o inset**, e sem constante mágica: recortar cada retângulo no
   **ponto médio entre a fileira dele e as adjacentes**. Adapta-se a qualquer
   entrelinha e é exato. Mora em `layout.rects_for`, que já tem as caixas.
3. **Aí sim** `make eval` e `eval/impressao_pdf.py`, que passam a significar
   algo para este caso.

> Mexer nisso é mexer na geometria da redação, que é o código mais crítico do
> projeto: um inset errado deixa PII descoberta, que é pior que o defeito
> atual. Daí a ordem acima, e daí não ter sido corrigido junto com o achado.

---

## D-02 — Desmarcar a classe não desliga os trechos marcados à mão

**Gravidade: alta.** O usuário desmarca a caixa da classe esperando limpar
tudo daquela classe, a tela não obedece, e não há outro caminho óbvio para
desfazer em lote.

Relatado pelo usuário em 2026-09-17.

### O que acontece

1. O usuário seleciona um trecho no documento e manda anonimizar; ele vira um
   trecho de origem `usuario`, e aparece na lista "O que será anonimizado".
2. Ele desmarca a caixa daquela classe, esperando desligar todas as seleções.
3. **Não desliga.**

### Hipótese, ainda não confirmada

`Sessao.aplicar_perfil` devolve ao padrão da classe apenas os spans que **não**
são do usuário:

```python
for s in self.spans.values():
    if s.entity in mudaram and s.origem != "usuario":
        s.ativo = None
```

E `operador_de` trata `MANUAL` à parte: trecho apontado à mão é sempre tratado,
com o operador padrão do documento. As duas regras juntas produzem exatamente
o sintoma — e as duas existem por um motivo: uma decisão explícita do usuário
sobre um trecho não pode ser revogada por uma caixa de classe.

Se a hipótese estiver certa, o defeito é de **interface**, não de regra: o
trecho manual não pertence à classe que a caixa governa, então a caixa não
deveria dar a impressão de governá-lo. As saídas possíveis, a decidir:

- o trecho manual não aparece na contagem daquela classe (ele já tem lista
  própria, "Trechos que você adicionou", com "apagar");
- ou a caixa passa a alcançá-lo, e aí some a garantia de que o apontamento
  explícito vence o padrão;
- ou a caixa alcança e a lista de manuais diz claramente que aquilo foi
  desligado em lote.

**Confirmar reproduzindo antes de escolher.** A hipótese acima foi levantada
lendo o código, não executando.
