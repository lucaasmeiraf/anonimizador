# Defeitos abertos

Defeito **aberto** é o que já foi observado e ainda não foi corrigido. Quando
fechar, sai daqui e a explicação vai para o comentário do código ou para o
`goal-` da fase — este arquivo não é histórico, é lista de trabalho.

Limitação conhecida e aceita **não** entra aqui: essa vai para a tabela "O que
ele não faz" do `README.md`, que é onde o cliente lê. A diferença é intenção —
o que está abaixo ninguém decidiu que ficaria assim.

A lista dos fechados fica no fim e é curta de propósito: serve para não
reabrir a mesma investigação, e some quando deixar de ser útil. Quem quiser a
história completa tem o `git log`, que é onde ela mora.

---

## D-04 — Exposição pública: falta defesa de perímetro

**Gravidade: alta no dia em que a porta sair de `127.0.0.1`. Nenhuma antes
disso.** Achado em 2026-11-03, avaliando a hipótese de hospedar num VPS.

Hoje a segurança do perímetro é o endereço: o `ui-proxy` publica em
`127.0.0.1:8000`, então só quem está na máquina alcança. Tudo abaixo é o que
falta para a porta poder ser pública — e **nada disso substitui a Fase 4**,
que é quem resolve *quem é você*.

### Corrigido em parte

`forward.py` abria **três threads por conexão** (uma que atende, duas que
bombeiam), sem teto e sem timeout nenhum. Bastavam conexões TCP ociosas — sem
falar HTTP, sem credencial — para esgotar threads e o serviço parar de
responder.

Ganhou teto de conexões (`ANON_PROXY_MAX_CONEXOES`, 64) e espera pelo
primeiro byte (`ANON_PROXY_ESPERA_INICIAL`, 15 s). Só o primeiro byte é
cronometrado: depois dele o silêncio é legítimo, porque a detecção de um
documento de 102 páginas leva 74 s com o cliente calado esperando a resposta.
`tests/test_forward_recursos.py` trava os quatro comportamentos.

**O limite, dito porque a correção não resolve o problema:** com 64 vagas e
15 s de espera, um atacante que sustente ~4 conexões por segundo mantém o
teto cheio. O que a correção compra é **degradar previsivelmente** em vez de
morrer — não imunidade. Limite por IP é o que falta, e ele não mora aqui.

### Aberto

1. **Nenhum limite de taxa, em lugar nenhum.** Nem por IP, nem por sessão,
   nem no upload. Um documento de 102 páginas consumiu 3,1 GB; alguns PDFs de
   50 MB em paralelo derrubam o container por memória. O `MAX_BYTES` limita
   cada requisição e nada limita o conjunto.

2. **Nenhum cabeçalho de segurança.** Sem CSP, `X-Frame-Options`,
   `X-Content-Type-Options` nem `Referrer-Policy`. XSS hoje está barrado por
   construção — conferido em 2026-11-03: todo dado vindo do documento entra no
   DOM por `textContent`, e os `innerHTML` com conteúdo usam `escapar()`. CSP
   é a defesa que sobrevive ao erro futuro de alguém, não a atual.

3. **Sem TLS.** Hoje é HTTP em `127.0.0.1`, que é seguro justamente por não
   sair da máquina.

### Onde isso se resolve

Limite por IP, timeout de requisição, tamanho de corpo e TLS são trabalho de
**proxy reverso na frente** (nginx, Caddy), não de código Python. Enfiar isso
no `forward.py` contraria a razão de ele existir: o único processo com saída
de rede é pequeno o bastante para ser lido inteiro numa sentada, e sem árvore
de dependências.

A decisão que falta antes de hospedar está em `HOMOLOGACAO.md` §4: o cenário
"servidor compartilhado na rede" continua na tabela **"Não — ainda não"**,
bloqueado por login, posse de documento e TLS — Fase 4, Blocos 2 e 3.

---


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
