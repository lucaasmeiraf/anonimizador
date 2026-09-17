# Defeitos abertos

Defeito **aberto** é o que já foi observado e ainda não foi corrigido. Quando
fechar, sai daqui e a explicação vai para o comentário do código ou para o
`goal-` da fase — este arquivo não é histórico, é lista de trabalho.

Limitação conhecida e aceita **não** entra aqui: essa vai para a tabela "O que
ele não faz" do `README.md`, que é onde o cliente lê. A diferença é intenção —
o que está abaixo ninguém decidiu que ficaria assim.

---

## D-03 — `make test-all` está vermelho, e faz tempo

**Gravidade: média.** Nada de errado chega ao documento; o que está quebrado é
a rede de proteção. Dois testes marcados `slow` falham, e como `make test` os
desmarca, a suíte rápida fica verde e ninguém repara.

Achado em 2026-09-17, e **pré-existente**: falham igual em `0cc322d`, o commit
que era HEAD no começo da sessão.

```
FAILED tests/test_recognizers.py::test_ddd_invalido_derruba_telefone
FAILED tests/test_recognizers.py::test_cnh_sem_ancora_nao_dispara
```

### O que acontece

```
test_ddd_invalido_derruba_telefone:
  assert not [s for s in pipe.analyze(texto) if s.entity == "TELEFONE"]
  -> Span(start=20, end=35, entity='TELEFONE', score=0.6, nota='checksum_invalido')
```

O teste exige que `(00) 98765-4321` **não** seja detectado. O código detecta,
com score baixo e `nota='checksum_invalido'`.

### Hipótese, com evidência mas sem confirmação

`git log -S"checksum_invalido"` aponta um commit só:

```
8701910 fix: identificador com checksum invalido deixa de ser invisivel
```

É exatamente a nota que aparece na falha. A leitura provável é que a decisão
mudou ali — de **descartar** o identificador com dígito verificador inválido
para **sinalizar como suspeita** —, e que estes dois testes ficaram afirmando
o comportamento antigo. O `CLAUDE.md` §5 registra essa decisão como
deliberada, e com a medição que a motivou: `validate_result` devolvendo
`False` apagava CPF com DV inválido.

Se a leitura estiver certa, **os testes é que estão velhos**, não o código, e o
conserto é atualizá-los para exigir o comportamento novo — detectado, com
score baixo e marcado. Não foi confirmado executando no commit anterior a
`8701910`; a evidência acima é circunstancial.

### O que fazer junto

Que a suíte lenta possa ficar vermelha por meses sem ninguém ver é o defeito
por trás do defeito. `make test` desmarca `slow` de propósito — carregar 1 GB
de pesos a cada execução tornaria o ciclo inviável —, mas alguma coisa precisa
rodar `test-all` de tempos em tempos e reclamar.

---

## Defeitos fechados

Os dois que estavam aqui foram fechados em 2026-09-17:

- **D-01, a tarja comia o texto das linhas vizinhas.** Causa: entrelinha mais
  apertada que a caixa do caractere fazia as fileiras se sobreporem, e
  `apply_redactions` remove todo caractere que **encosta** no retângulo. A
  correção e a medição que a sustenta estão em `layout.recortar_entre_fileiras`.

- **D-02, desmarcar a classe não desligava os trechos apontados à mão.** Causa:
  a caixa de `MANUAL` era desabilitada na tela, e `MANUAL` não é entidade de
  política — o caminho do perfil seria recusado, com razão. A explicação está
  em `Sessao.alternar_manuais` e em `tests/test_manuais_em_lote.py`.
