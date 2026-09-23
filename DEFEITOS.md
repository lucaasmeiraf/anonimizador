# Defeitos abertos

Defeito **aberto** é o que já foi observado e ainda não foi corrigido. Quando
fechar, sai daqui e a explicação vai para o comentário do código ou para o
`goal-` da fase — este arquivo não é histórico, é lista de trabalho.

Limitação conhecida e aceita **não** entra aqui: essa vai para a tabela "O que
ele não faz" do `README.md`, que é onde o cliente lê. A diferença é intenção —
o que está abaixo ninguém decidiu que ficaria assim.

A lista dos fechados fica logo abaixo e é curta de propósito: serve para não
reabrir a mesma investigação, e some quando deixar de ser útil. Quem quiser a
história completa tem o `git log`, que é onde ela mora.

---

## Nenhum defeito aberto

---

## Defeitos fechados

Fechados em 2026-09-23, os três relatados pelo usuário no modo "Código no
lugar", que nunca tinha sido usado de ponta a ponta pela tela:

- **O NER devolvia a mesma palavra em pedaços.** "Eloah" como `El` + `oa`,
  uma data como `20` `/` `12`… — 1.393 pares colados de `DATE_TIME` e 386 de
  `PERSON` no corpus. Em tarja não se via; em código cada pedaço ganhava o
  seu, e caixas de 2,8pt reprovavam o documento. Ver
  `TransformersNerRecognizer._colar_fragmentos` e
  `tests/test_ner_fragmentos.py`.
- **Desmarcar a classe não desligava o trecho ligado à mão.** A caixa passava
  por `aplicar_perfil`, que só zera exceções de classe cuja regra mudou — e
  desmarcar uma classe em `manter` não muda nada. Ver
  `Sessao.alternar_entidade` e `tests/test_caixa_de_classe.py`.
- **Modo código reprovava quase todo documento, sem saída na tela.** CEP e
  data nunca comportam token, e a escolha de tarja por classe que o modo
  misto pressupunha não existia na interface. Resolvido por decisão do
  usuário (não cabe → tarja naquele trecho, dito na tela e no relatório);
  ver A4 no `goal-fase-2.md`. Junto: a prévia passou a desenhar o código em
  vez de tarja preta.

Fechados em 2026-09-17:

- **D-01, a tarja comia o texto das linhas vizinhas.** Causa: entrelinha mais
  apertada que a caixa do caractere fazia as fileiras se sobreporem, e
  `apply_redactions` remove todo caractere que **encosta** no retângulo. A
  correção e a medição que a sustenta estão em `layout.recortar_entre_fileiras`.

- **D-02, desmarcar a classe não desligava os trechos apontados à mão.** Causa:
  a caixa de `MANUAL` era desabilitada na tela, e `MANUAL` não é entidade de
  política — o caminho do perfil seria recusado, com razão. A explicação está
  em `Sessao.alternar_manuais` e em `tests/test_manuais_em_lote.py`.

- **D-03, `make test-all` vermelho.** Eram três coisas, não uma: dois testes
  velhos (telefone e CPF) e um defeito de detecção real — CNH e PIS ganhavam
  score 1,0 por checksum sozinho, apesar de terem a forma de um CPF. O efeito
  visível era rótulo errado: um CPF de DV inválido aparecia como `PIS_PASEP`.
  Ver `ChecksumRecognizer.analyze` e `tests/test_recognizers.py`.

  **O que ficou sem resolver:** que a suíte lenta possa ficar vermelha por
  meses sem ninguém ver. `make test` desmarca `slow` de propósito — carregar
  1 GB de pesos a cada execução tornaria o ciclo inviável —, mas alguma coisa
  precisa rodar `test-all` de tempos em tempos e reclamar. Enquanto não
  houver, isto se repete.

- **A tarja do trecho manual não sumia ao ser desligada.** Relatado pelo
  usuário. Especificidade de CSS: `.tarja.desligada` e `.tarja.manual` empatam,
  e `.manual` vencia por vir depois. Travado por teste em
  `tests/test_web_estaticos.py`.
