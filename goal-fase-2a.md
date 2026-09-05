# /goal — Fase 2A: token intradocumento e saída de texto

> Recorte executável da Fase A do `goal-fase-2.md`: os itens **A2** (operador
> de pseudônimo sem cofre) e **A9** (saída de texto pseudonimizado).
>
> Existe como documento próprio porque a Fase A foi dividida por dificuldade
> depois da medição do A1, e esta metade tem uma propriedade que a outra não
> tem: **ela não escreve nada dentro do PDF**. É substituição de string em
> offset conhecido. Nenhuma das arestas caras da Fase 2 aparece aqui.

---

## 0. O que decidiu este recorte

Três decisões tomadas em 2026-09-05, nesta ordem:

1. **Fase B encerrada por ora.** O caso de uso é pseudonimizar para análise
   por LLM, e o original fica com quem o enviou — então "voltar atrás" já está
   resolvido pelo controle de acesso ao original. Sem cofre, sem chave, sem
   custo jurídico novo. Registrado em `goal-fase-2.md` §5, Bloco B0.

2. **O A1 mediu, e o veredito foi "serve, com uma condição".** A geometria do
   token sai exata; o que quebra é a ordem do content stream. Metade dos
   extratores testados lê errado, e o padrão diverge entre bibliotecas. A
   conclusão que importa aqui: **entregar só o PDF não garante a ordem**,
   porque a ordem passa a depender de uma escolha de quem consome o arquivo.

3. **A LLM será externa, não local.** O produto não mira cliente com infra de
   GPU. Isso reativa integralmente a análise de `goal-fase-3.md` §2 — mas
   **não afeta este documento**: A2 e A9 produzem o texto, não o enviam. O
   envio, e a decisão de perímetro que ele carrega, continuam na Fase 3.

### A restrição que o usuário impôs, e que organiza o plano inteiro

> *"Pode seguir com A2 e A9 se isso não influenciar de forma alguma o
> funcionamento atual do sistema, prejudicando o sistema."*

Isso não é um pedido de cuidado genérico; é um requisito de projeto com
consequência concreta. Traduzido: **tudo aqui é adição pura.** Nenhum caminho
existente muda de comportamento. A §5 lista, arquivo por arquivo, o que é
tocado e o que não é, e a §6 transforma isso em critério verificável.

---

## 1. O que A2 e A9 são, e por que são um só trabalho

**A2 decide o conteúdo.** Qual valor vira qual token, e a garantia de que o
mesmo valor vira o mesmo token em todas as ocorrências do documento.

**A9 decide o destino.** Escreve o resultado como texto puro, montado a partir
de `TextMap.text` e dos offsets dos spans.

A2 sem A9 não tem onde escrever. A9 sem A2 não tem o que escrever. Separá-los
em entregas distintas só produziria uma metade inútil, então são um recorte só.

### Por que o texto, e não o PDF

O documento pseudonimizado existe para ser analisado por um modelo de
linguagem. **Um LLM não consome PDF — consome texto.** Entregar PDF para que
alguém depois reextraia texto adiciona no meio do caminho exatamente o passo
que o A1 mostrou ser frágil.

O pipeline já tem a resposta certa em mãos: `TextMap.text` mais os offsets dos
spans dão a substituição exata, **na ordem correta por construção**, sem
passar pelo content stream e sem depender de qual biblioteca o cliente usa.

E o contraste com a tarja é o argumento central do recorte:

| O que a LLM recebe | Com `tarja` | Com token |
|---|---|---|
| Texto | `O servidor  compareceu` | `O servidor [P-7F3A] compareceu` |
| Sabe que havia um ator ali? | **não** | sim |
| Sabe o tipo (pessoa, não CNPJ)? | não | sim |
| Sabe que é o mesmo do §9? | não | sim |
| Margem para alucinar | alta | baixa |

A tarja não apaga só o nome: apaga o *ator*. É por isso que o token importa
aqui e não importava quando o entregável era um PDF para publicar.

---

## 2. As decisões de projeto que não são óbvias

### 2.1 O token não pode ser hash do valor — e essa é a armadilha principal

A implementação intuitiva é `sha256(valor)[:4]`. **Ela é reversível por força
bruta e reintroduz o risco que a Fase A existe para evitar.**

O espaço de nomes brasileiros plausíveis é pequeno o bastante para enumerar.
Quem tem o documento pseudonimizado e uma lista de candidatos confirma cada um
por tentativa — sem chave, sem cofre, sem nada que o sistema pudesse controlar.
O mesmo vale, e pior, para CPF: 11 dígitos com dígito verificador dão um
espaço percorrível.

Isso não é hipótese distante: é o modo de falha padrão de pseudonimização por
hash, e ele transformaria uma saída que deveria ser irreversível numa saída
reidentificável — exatamente a diferença jurídica que a Fase 2 inteira existe
para preservar.

**Decisão: o token é sorteado, não derivado.** Um valor aleatório por
documento, de um `random.SystemRandom`, guardado num mapa em memória. Sem
relação matemática com o valor original, portanto irreversível por
construção — inclusive por nós. É o que sustenta a afirmação de que a saída
não é dado pessoal.

> A alternativa equivalente é HMAC com chave efêmera sorteada por documento e
> descartada no fim. Dá a mesma garantia e é mais código. Sorteio direto é
> preferido pela regra da correção mínima.

### 2.2 Colisão precisa ser impedida, não improvável

Com 4 dígitos hexadecimais são 65.536 tokens possíveis. Num documento com 50
entidades distintas, a probabilidade de duas receberem o mesmo token é

    1 − exp(−50² / (2 × 65.536)) ≈ 1,9%

Cerca de **1 documento em 50** — a mesma ordem de grandeza do vazamento de
`PERSON` já conhecido, e igualmente inaceitável em silêncio. Duas pessoas
distintas com o mesmo token fazem a LLM fundir dois atores num só, que é um
erro de análise pior que a ausência do nome.

**Decisão: sortear rejeitando repetido.** O conjunto de tokens já emitidos no
documento é conhecido; sortear de novo enquanto houver colisão custa nada e
leva a probabilidade a **zero**, não a "baixa". Testar isso explicitamente.

### 2.3 O tipo tem de sobreviver ao token (A3)

`[P-7F3A]` para pessoa, `[CPF-2C81]` para CPF. Quem lê — humano ou modelo —
precisa saber que ali havia uma pessoa e não um CNPJ, senão o token vira ruído
opaco e a legibilidade que motivou tudo se perde pela metade.

O prefixo sai de um mapa explícito entidade → sigla, em `config.py`. Entidade
sem sigla declarada **falha alto**, em vez de cair num prefixo genérico: um
prefixo genérico silencioso é como uma entidade nova entra no sistema sem
ninguém decidir seu tratamento.

### 2.4 Determinismo é intradocumento, e isso é escolha, não limitação

O mesmo nome vira o mesmo token da página 1 à página 80 **do mesmo documento**.
Em outro documento, o mesmo nome vira outro token.

Isso é deliberado e está na §0 do `goal-fase-2.md`: token determinístico
*entre* documentos cria capacidade de vínculo — quem tiver dois documentos sabe
que a mesma pessoa aparece nos dois, **sem ter chave nenhuma**. Dependendo do
contexto isso já é reidentificação por meios razoáveis.

O mapa vive em memória e morre com o processamento. **Nenhum mapa em disco, em
nenhum momento** — é critério de aceite, não detalhe.

### 2.5 O gate precisa existir para o texto, e ele ainda não existe

A invariante 2 é clara: nada é entregue sem `verify().ok`. Hoje `verify()`
recebe o caminho de um PDF e roda dez vetores sobre ele. O texto
pseudonimizado é um artefato novo, e se ele puder sair sem passar por um gate,
o sistema ganhou exatamente a rota que o CLAUDE.md proíbe.

**Decisão: `verify_texto(texto, valores)`**, no mesmo `verifier.py`,
reaproveitando `_normalizar`, `_variantes` e `_procurar` — que é onde mora a
inteligência real da verificação (as variantes com e sem pontuação, o
casamento tolerante a acento). Dos dez vetores só um se aplica a uma string; os
outros nove descrevem estruturas de PDF que não existem aqui. O relatório tem
de dizer isso explicitamente, com o nome do vetor executado, para ninguém ler
"verificado" e supor dez.

Duas coisas que este gate **não** prova, e que precisam estar ditas na tela
quando a Fase 3 chegar:

- que tudo que era dado pessoal foi detectado — ele só prova que o que
  decidimos substituir não sobreviveu;
- que o token está presente onde deveria (isso é o A5, e vale aqui: token
  ausente com valor removido passaria como "limpo").

### 2.6 `politica.py` não é tocado — e a razão importa

A tentação é liberar `PSEUDONIMO` em `OPERADORES_IMPLEMENTADOS` agora. **Não.**

A invariante 5 existe para impedir que o usuário peça pseudônimo, o executor
não aplique nada, e o relatório afirme que aplicou. Liberar o operador com
apenas metade do executor pronto — texto sim, PDF não — recria exatamente esse
buraco: um perfil com `pseudonimo` passaria em `validar_perfil` e produziria um
PDF tarjado, sem token nenhum, sem ninguém ser avisado.

**Decisão: a substituição por token é uma propriedade da *saída de texto*, não
um operador de política.** Os spans selecionados são os mesmos, escolhidos pela
mesma política; o que muda é o que preenche o buraco em cada artefato — retângulo
preto no PDF, token no texto. Com esse enquadramento, `validar_perfil` continua
recusando `pseudonimo` como hoje, a invariante 5 fica intacta, e A7 continua
onde está: depois de A3–A8, quando existir de fato um escritor de token no PDF.

---

## 3. O que o usuário vê

Nada, por enquanto — e isso é intencional.

Este recorte entrega a capacidade e o gate, não a tela. A tela é onde as
afirmações jurídicas aparecem, e elas dependem de decisões da Fase 3 que ainda
não foram tomadas (para onde o texto vai, com que aviso, com quantos cliques).
Colocar tela agora seria fixar uma promessa antes de a decisão que a sustenta
existir.

O acesso nesta fase é pela CLI e pela API, com o gate valendo nos dois.

---

## 4. Tarefas

**Bloco 1 — o token (A2, A3)**
- [x] `pseudonimo.py`: alocador de token por documento. Sorteio com
      `SystemRandom`, rejeição de colisão, mapa `valor → token` em memória.
- [x] Mapa entidade → sigla em `config.py`. Entidade sem sigla declarada
      levanta erro, não cai em genérico.
- [x] Testes: mesmo valor → mesmo token no documento; valores distintos →
      tokens distintos **sempre** (forçar o caminho de colisão com um espaço
      de token reduzido, para o teste ser determinístico); documentos
      diferentes → tokens diferentes; nenhum arquivo criado.

**Bloco 2 — a saída de texto (A9)**
- [x] Função que recebe `TextMap.text` + spans ativos + alocador e devolve o
      texto com os tokens nas posições. Substituição de trás para frente, para
      os offsets não se moverem.
- [x] Teste de ordem: o análogo textual do A1 — token entre as mesmas âncoras
      que cercavam o valor. Aqui tem de passar por construção; se falhar, o
      erro é de offset e é grave.
- [x] Teste com spans adjacentes e com o documento inteiro do corpus.

**Bloco 3 — o gate (A5, para texto)**
- [x] `verify_texto(texto, valores)` em `verifier.py`, reaproveitando
      `_variantes` e `_procurar`.
- [x] O relatório nomeia o vetor executado e **não** insinua os dez.
- [x] Verificar também **presença do token**: valor removido e token ausente
      reprova. É a aresta 1 da sondagem, no caminho de texto.
- [x] Teste do caminho de falha: texto com valor sobrevivente reprova, e o
      artefato não fica disponível.

**Bloco 4 — acesso, sem tela**
- [x] Método na `Sessao` que produz o texto e guarda o relatório, espelhando
      a estrutura de `aprovar()` — inclusive apagar o artefato quando reprova.
- [x] `_invalidar` passa a apagar também o texto gerado (invariante 3: edição
      invalida aprovação **e** apaga o que foi gerado).
- [x] Rota de download do texto atrás do gate, no mesmo padrão do
      `GET /download`. Nenhum atalho, nenhuma rota de debug.
- [x] Subcomando na CLI, sem valor de PII no stdout.

**Bloco 5 — registro**
- [x] `docs/05-politica-llm.md`: seção 2.6, "análise de documento
      pseudonimizado por LLM", com a mesma tabela de acesso a dados das
      outras cinco. Sem isso o uso não está autorizado, pela regra do próprio
      documento.
- [x] `docs/02-requisitos.md`: requisito de que o texto pseudonimizado é
      artefato sujeito ao gate, como o PDF.
- [x] `README.md`: o segundo artefato na descrição do que a ferramenta produz,
      **com a ressalva da irreversibilidade** (RN-01).

---

## 5. Raio de alcance — o que é tocado e o que não é

A restrição da §0 exige que isto seja explícito.

| Arquivo | O que acontece |
|---|---|
| `pseudonimo.py` | **novo** |
| `config.py` | **adição**: mapa entidade → sigla. Nada existente muda |
| `verifier.py` | **adição**: `verify_texto`. `verify` intocada |
| `web/sessao.py` | **adição**: método novo; `_invalidar` ganha uma linha |
| `web/app.py` | **adição**: uma rota, atrás do gate |
| `cli.py` | **adição**: um subcomando |
| `docs/*`, `README.md` | documentação |

E o que **não** é tocado, porque tocar aqui seria mudar o comportamento atual:

- `pdf_redactor.py` — o PDF continua saindo exatamente como sai hoje;
- `politica.py` — `validar_perfil` continua recusando `pseudonimo` (§2.6);
- `spans.py`, `layout.py`, `pipeline.py` — a detecção não muda em nada;
- `verify()`, `aprovar()`, `pode_baixar` no caminho do PDF;
- `web/static/*` — nenhuma tela nesta fase.

Como `spans.py`, `layout.py` e `pdf_redactor.py` ficam intocados, o gatilho de
`make eval` do CLAUDE.md não se aplica. **Rodar mesmo assim uma vez**, para ter
o número de antes e depois registrado e não depender desse raciocínio.

---

## 6. Critérios de aceite

**Não prejudicar o que existe** — o requisito da §0, em forma verificável:

- Os 235 testes atuais continuam verdes, sem edição de nenhum deles. Um teste
  existente que precisasse mudar seria prova de que o comportamento atual
  mudou.
- `make eval` dá o mesmo número de antes.
- `make ui-proof` e `make offline-proof` continuam verdes. Nada aqui abre rede.
- O PDF produzido é o mesmo de antes desta fase, comparado por **impressão
  digital de conteúdo** (`eval/impressao_pdf.py`): texto extraído, páginas,
  retângulos, saneamento e resultado da verificação.

  > **Correção de 2026-09-05.** A primeira redação deste critério dizia "byte
  > a byte", e ela é impossível de cumprir — medido: a saída do PyMuPDF não é
  > byte-determinística nem para o mesmo código rodado duas vezes, porque o
  > `/ID` do trailer varia por execução. Comparar bytes acusaria "mudou"
  > sempre, o que é ruído e não sinal. A impressão de conteúdo mede o que o
  > critério queria dizer.

**O token**

- Mesmo valor → mesmo token, em todas as ocorrências do documento.
- Valores distintos → tokens distintos, **sempre**, com o caminho de colisão
  exercitado por teste e não deixado à probabilidade.
- Documentos diferentes → tokens diferentes para o mesmo valor.
- O token não é derivado do valor. Não há função que, dada a saída, reduza o
  espaço de busca do original.
- O tipo sobrevive no token.
- Ao fim do processamento **não existe mapa em disco** — verificado por teste
  que inspeciona a pasta da sessão.

**O texto**

- Os tokens aparecem nas posições dos valores originais. Ordem correta por
  construção.
- Nenhum valor original sobrevive no texto, conferido por `verify_texto`.
- Todo token está presente; valor removido com token ausente **reprova**.
- Nenhum artefato de texto é servido sem `verify_texto().ok`, e o caminho de
  falha é testado.
- Qualquer edição na sessão invalida a aprovação e apaga o texto gerado.
- Nenhum valor de PII em log, em mensagem de erro ou em resposta de API.

---

## 7. Fora de escopo

- **Escrever token dentro do PDF** (A3–A8). O PDF continua com `tarja`.
- **Enviar o texto para qualquer LLM.** Este recorte produz o artefato; quem
  envia, para onde, e com que aviso é `goal-fase-3.md` §2 — e é lá que a
  decisão de perímetro acontece, agora sabendo que a LLM será externa.
- **Tela.** Ver §3.
- **Cofre e reversibilidade.** Encerrados na §0.
- **Determinismo entre documentos.** Requer chave, e chave é cofre.

---

## 8. O que continua verdadeiro e não pode ser esquecido

A decisão de LLM externa foi tomada, mas os números que a tornam delicada não
mudaram, e estão medidos em `goal-fase-3.md` §2:

- `bert-lenerbr` deixa passar um `PERSON` em cerca de **1 documento a cada
  50**;
- **identificador indireto por contexto** (*"o único servidor cego da
  repartição"*) não é detectado de forma alguma, e nenhum token resolve —
  não há o que substituir;
- a cobertura alta do `report.md` é **silêncio** sobre esse segundo risco, não
  garantia contra ele.

O token melhora a análise e não piora a proteção. Mas ele **não** reduz nenhum
dos dois números acima, e a tela da Fase 3 não pode sugerir que reduz.
