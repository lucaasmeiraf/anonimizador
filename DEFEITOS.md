# Defeitos abertos

Defeito **aberto** é o que já foi observado e ainda não foi corrigido. Quando
fechar, sai daqui e a explicação vai para o comentário do código ou para o
`goal-` da fase — este arquivo não é histórico, é lista de trabalho.

Limitação conhecida e aceita **não** entra aqui: essa vai para a tabela "O que
ele não faz" do `README.md`, que é onde o cliente lê. A diferença é intenção —
o que está abaixo ninguém decidiu que ficaria assim.

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
