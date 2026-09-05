# CLAUDE.md — como trabalhar neste repositório

Ferramenta de **anonimização de documentos PDF** em português-BR, 100% local,
para órgãos públicos e escritórios que lidam com dado pessoal sob LGPD.
Detecta PII (regex + checksum + NER), propõe tarjas, um humano revisa e
aprova, e só então o PDF redigido é produzido, verificado e liberado.

Este arquivo é a instrução permanente. Se algo aqui conflitar com um pedido
pontual, diga isso em voz alta antes de executar — não escolha em silêncio.

---

## 1. A natureza do erro aqui

Quase todo software falha devolvendo erro. Este falha **devolvendo um arquivo
que parece pronto**. Os três modos de falha que importam:

| Falha | Como aparece | Por que é grave |
|---|---|---|
| **Vazamento** | PDF sai com dado pessoal recuperável | O usuário publicou. Não há desfazer. |
| **Falso silêncio** | A tela diz "anonimizado" e nada foi aplicado | Pior que erro: destrói a confiança no gate |
| **Tarja no lugar errado** | Cobre texto inocente, deixa o CPF à mostra | Ninguém percebe até alguém ler o PDF |

Consequência prática para qualquer mudança: **falhar alto e cedo é sempre
preferível a degradar em silêncio**. Um `raise` visível é aceitável; um
caminho que segue adiante sem aplicar o que prometeu, nunca.

---

## 2. Invariantes — não quebrar sem decisão explícita do usuário

Estas não são preferências de estilo. Cada uma existe porque a ausência dela
já produziu, ou produziria, um dos três modos de falha acima.

1. **Redação é remoção, não cobertura.** `apply_redactions` + `clean_contents`
   + `_sanear` + `save(garbage=4, incremental=False)`. Nunca desenhar
   retângulo por cima e chamar isso de tarja.
2. **Nada é baixado sem verificação aprovada, e isso vale por artefato.** O
   PDF passa por `verify()` (`Sessao.pode_baixar`, `GET /download`); o texto
   pseudonimizado passa por `verify_texto()` (`Sessao.pode_baixar_texto`,
   `GET /download/texto`). Entregável novo exige gate novo — não herda o de
   outro formato. Não criar nenhuma rota, atalho de debug ou export que sirva
   arquivo sem passar pelo seu.
3. **Qualquer edição invalida a aprovação** (`Sessao._invalidar`) e apaga o PDF
   já gerado. Sem isso o usuário baixa algo diferente do que aprovou.
4. **Nenhum valor de PII em log.** Registrar id de span, contagem, entidade,
   tipo de objeto PDF — nunca o texto. Um log é uma cópia do dado fora do
   arquivo saneado, com retenção própria e sem verificação.
5. **Operador declarado ≠ operador implementado.** `validar_perfil` recusa
   `pseudonimo` e `mascara` (`OPERADORES_IMPLEMENTADOS`). Não relaxar essa
   trava sem o executor correspondente existir e ser testado.

   Continua valendo **apesar de** `pseudonimo.py` existir: o token é escrito
   no artefato de *texto*, não dentro do PDF. Liberar o operador agora deixaria
   um perfil pedir pseudônimo e receber um PDF tarjado, sem aviso — que é
   exatamente o buraco que esta invariante existe para tapar. A trava sai
   quando A3–A8 (`goal-fase-2.md`) entregarem o escritor de token no PDF.

   Corolário: **substituição por token é propriedade da saída, não operador de
   política.** Os spans são os mesmos e a política é a mesma; muda só o que
   preenche o buraco em cada artefato.
6. **O perímetro de rede é a promessa central do produto.** Serviços de lote
   rodam em `network_mode: none`; o `ui` vive em rede `internal: true`; o
   `ui-proxy` é o único com egress e **não processa documento** — só copia
   bytes. Não adicionar dependência que precise de rede em runtime, nem
   chamada externa em nenhum caminho de documento.
7. **Offset é a verdade; o servidor confere, não adivinha.**
   `Sessao._conferir_intervalo` valida o intervalo do cliente contra o texto
   reivindicado (JS conta UTF-16, Python conta code points). Não achar →
   recusar, nunca chutar.
8. **Evidência de checksum vence evidência estatística** (`config.PRECEDENCIA`)
   e a origem da decisão fica marcada em `recognition_metadata["checksum"]`.
   Score não separa certeza de palpite; a marca separa.
9. **O original em claro só existe durante a revisão.** TTL, `DELETE`
   explícito, varredura de órfãs na subida. Não persistir documento fora da
   pasta da sessão.
10. **Detecção é determinística.** `resolver_sobreposicoes` ordena por
    critérios fixos. Duas execuções sobre o mesmo corpus dão o mesmo número —
    então variação de métrica é sempre variação de código, nunca ruído.
11. **Apenas dados sintéticos** em dev, teste, corpus e demo. Nenhum documento
    real de cliente entra no repositório ou no ambiente de desenvolvimento.

---

## 3. Onde cada mudança entra

O sistema tem camadas com fronteiras deliberadas. Colocar lógica na camada
errada é a principal forma de introduzir bug aqui.

| Camada | Arquivo | Responsabilidade | O que **não** pode morar aqui |
|---|---|---|---|
| Configuração | `config.py` | entidades ativas, limiar, precedência, âncoras | lógica |
| Detecção estruturada | `recognizers/*` | regex + checksum + âncora | política de tarja |
| NER | `ner.py` | carregar modelo, mapear rótulos | regra de negócio |
| Orquestração | `pipeline.py` | ordem das camadas, resolução | HTTP, disco |
| Lógica pura de span | `spans.py` | precedência, desambiguação, filtro | Presidio, torch |
| Geometria | `layout.py` | offset ↔ retângulo | decisão sobre o que tarjar |
| Redação | `pdf_redactor.py` | remover e sanear | decisão sobre o que tarjar |
| Pseudônimo | `pseudonimo.py` | token e substituição em texto | PDF, disco, política |
| Verificação | `verifier.py` | 10 vetores no PDF, 2 no texto | qualquer confiança no redator |
| Política | `politica.py` | operador por entidade, validação | execução |
| Estado + travas | `web/sessao.py` | **todas** as regras da UI | transporte |
| Transporte | `web/app.py` | HTTP, códigos de status | regra de decisão |
| Interface | `web/static/*` | desenho e interação | regra que afete o PDF |

Duas consequências que valem repetir:

- **`app.py` é só transporte.** Se uma decisão sobre o que é tarjado aparecer
  numa rota, ela está no lugar errado — vai para `sessao.py`, onde é testável
  sem subir servidor.
- **O que o navegador desenha nunca influencia o PDF.** O preview é imagem +
  retângulos; o entregável vem de `redact_document` + `verify` sobre a lista
  de spans ativos. Não "otimizar" isso reaproveitando estado do front-end.

### Raio de alcance por tipo de mudança

- Mexeu em `spans.py`, `layout.py` ou `pdf_redactor.py` → **rode o eval**. Um
  caractere de deslocamento é um vazamento, e o teste unitário não pega.
- Mexeu em qualquer coisa que possa alcançar o caminho do PDF → confira com
  `eval/impressao_pdf.py`, que compara a saída por conteúdo observável (texto
  extraído, retângulos, saneamento, verificação). **Não comparar bytes**: a
  saída do PyMuPDF não é byte-determinística entre execuções — o `/ID` do
  trailer varia — e um diff de bytes acusaria mudança sempre.
- Adicionar entidade nova exige, tudo junto, sob pena de lacuna silenciosa:
  `config.ENTIDADES_ATIVAS` + `config.PRECEDENCIA` + `config.SIGLAS_TOKEN` +
  `recognizers/__init__.MODULOS` + `perfil_padrao()` + testes + gerador de
  corpus. A sigla não é opcional: `AlocadorDeToken` levanta erro para entidade
  sem sigla, e `test_toda_entidade_ativa_tem_sigla` fecha a lacuna.
- Mexeu na política padrão (`ENTIDADES_REDIGIDAS`, `perfil_padrao`) → é
  mudança **jurídica**, não técnica. Ver seção 6.
- Mexeu em `web/static/*` → o carimbo de versão em `raiz()` já invalida o
  cache; não reintroduzir referência sem `?v=`.

---

## 4. Como executar

**Tudo roda dentro do Docker. Nada de Python no host** — é requisito do
projeto (RO-01), não conveniência.

```
make build          # única etapa com rede
make test           # rápido, sem carregar modelo
make test-all       # inclui os marcados slow
make eval           # avaliação nas 3 configurações de NER (~5 min CPU)
make diagnostico    # por que PERSON vaza: não detectado ou rótulo errado
make ui             # interface em http://127.0.0.1:8000
make ui-proof       # a porta responde E o ui não tem egress
make offline-proof  # o pipeline roda sem rede
```

No Windows sem `make`: `./run.ps1 <alvo>`, que faz exatamente o mesmo.

Testes: `pytest` com `--strict-markers`, marcador `slow` para o que carrega
modelo, fixture `tmp_pdf` em `conftest.py` para montar PDF de teste. Nomes de
teste em português, como o resto do código.

---

## 5. Disciplina de implementação

- **Ler o comentário antes de mudar a linha.** Este código documenta *por que*
  cada decisão estranha existe, quase sempre com a medição que a motivou. Uma
  simplificação que ignora o comentário costuma reintroduzir o bug que ele
  descreve. Casos já vividos: `validate_result` devolvendo `False` apagava CPF
  com DV inválido; normalizar dígitos no `verifier` colidia em 2,6% e reprovava
  redação correta; chave booleana de span perdia autoridade quando a classe
  estava em `manter`; span sobreposto empilhava tarja impossível de desligar.
- **Não alargar heurística sem medir.** Qualquer afrouxamento de reconhecedor
  ou de verificador precisa de número do corpus nas duas direções (o que ganha,
  o que perde), não de intuição.
- **Preferir a correção mínima** que resolve a causa. Não refatorar de carona
  em cima de um conserto, não renomear o que não precisa mudar.
- **Escrever no idioma e no estilo do arquivo**: código e comentários em
  português, com a densidade explicativa que o resto do módulo tem.
- **Commits**: prefixo convencional em português e sem acento
  (`feat:`, `fix:`, `docs:`, `eval:`), assunto descrevendo o efeito observável,
  não o arquivo mexido. Só commitar quando o usuário pedir.
- **Honestidade sobre o que não foi verificado.** Se um número não foi medido
  nesta sessão, dizer isso. Se um teste não rodou, dizer isso. Preencher
  lacuna com suposição plausível é o comportamento mais caro possível aqui.

---

## 6. LGPD e LAI — conferir prática contra lei em toda mudança

O sistema opera sobre documento de órgão público. Duas leis puxam em direções
opostas, e **as duas são obrigatórias**:

- **LGPD (Lei 13.709/2018)** empurra para tarjar: dado pessoal exposto é risco.
- **LAI (Lei 12.527/2011)** empurra para preservar: publicidade é a regra,
  sigilo é a exceção. Um ato administrativo sem órgão, sem data e sem local
  perde o efeito de publicidade que justifica publicá-lo.

**Tarjar demais não é o lado seguro — é a outra falha jurídica.** É por isso
que `ORGANIZATION`, `LOCATION` e `DATE_TIME` nascem em `manter` no
`perfil_padrao()`, e por isso existe o perfil `publicacao-oficial`. Qualquer
proposta de "tarjar tudo por padrão" precisa enfrentar esse argumento, não
ignorá-lo.

### Distinções que o produto nunca pode borrar

| Conceito | Base | Efeito |
|---|---|---|
| Dado **anonimizado** | LGPD art. 5º, III e art. 12 | não é dado pessoal, sai do escopo — **enquanto o processo não for reversível** |
| Dado **pseudonimizado** | LGPD art. 13, §4º | **continua** dado pessoal: base legal, direitos do titular, dever de segurança e de comunicar incidente |
| Dado pessoal **sensível** | LGPD art. 5º, II | saúde, biometria, convicção, filiação — regime mais estrito |
| Informação **pessoal** em documento público | LAI art. 31 | acesso restrito, mas o resto do documento continua público |

Regras de produto derivadas (RN-01 e RN-02 em `docs/02-requisitos.md`):

- **Nunca escrever, na interface ou em material comercial, que a saída "sai do
  escopo da LGPD" sem a ressalva da irreversibilidade.** Hoje o operador
  `tarja` é remoção — a afirmação se sustenta. Quando a Fase 2 ligar
  `pseudonimo`, deixa de se sustentar para aquele arquivo, e a tela precisa
  dizer isso **no momento da escolha**, não numa configuração escondida.
- **O processo de anonimização é ele próprio um tratamento de dados** e precisa
  ser documentável. A orientação da ANPD é baseada em risco de reidentificação:
  não existe técnica com eficácia plena. Não prometer eficácia plena.
- **Citação de artigo por número é de memória** neste repositório (RN-07, dívida
  registrada). Ao levar qualquer citação para tela, documento comercial ou
  proposta, marcá-la como pendente de confirmação com quem assina
  juridicamente. O enquadramento do caso concreto é do encarregado/jurídico do
  cliente, nunca deste código.

### Gatilho de verificação

Antes de fechar qualquer mudança que altere **o que é tarjado por padrão**, o
texto mostrado ao usuário sobre proteção, ou a reversibilidade da saída,
responder explicitamente:

1. Isso muda o que sai do escopo da LGPD? (reversibilidade)
2. Isso remove algo que a LAI exige que permaneça público?
3. A tela continua dizendo a verdade sobre o que foi feito?
4. Alguma afirmação nova precisa de confirmação jurídica antes de existir?

### Pendências jurídicas que bloqueiam entrega comercial

`RN-04`: PyMuPDF é AGPL-3.0 ou licença comercial da Artifex. `RN-05`: o
checkpoint LeNER-Br não declara licença. Nenhum dos dois impede desenvolvimento
interno; os dois impedem entrega a cliente. Não introduzir dependência nova sem
verificar licença — a lista de pendências já é grande o bastante.

---

## 7. Antes de dizer que terminou

- [ ] `make test` verde (e `make test-all` se tocou em detecção).
- [ ] `make eval` rodado se mexeu em span, layout ou redator — com o número.
- [ ] Nenhum valor de PII em log novo, em mensagem de erro ou em resposta de API.
- [ ] Nenhum caminho novo que sirva arquivo sem `verify().ok`.
- [ ] Nenhuma chamada de rede nova em caminho de documento; `make ui-proof`
      continua verde se mexeu em rede ou compose.
- [ ] O que não foi verificado está dito explicitamente na resposta.
- [ ] Se a mudança tem consequência jurídica, ela está escrita — não implícita.

---

## 8. Mapa rápido

```
goal-fase-0.md .. goal-fase-3.md   escopo e decisões por fase (fase 1 em andamento)
goal-fase-2a.md                    recorte executável da Fase 2A: token + saída de texto
anonimizador-poc/
  src/anonimizador/                pipeline, reconhecedores, redator, verificador
    web/                           API, sessão, estáticos, prova de rede
  eval/                            corpus sintético, avaliação, diagnóstico
  docs/01..06                      inventário, requisitos, configuração,
                                   implantação, política de LLM, resultados F0
  tests/                           161 testes
```

`docs/02-requisitos.md` tem a tabela de requisitos normativos (RN-01..RN-07) e
operacionais. `docs/05-politica-llm.md` é normativo sobre onde uma LLM pode
entrar e a que dados ela tem acesso — consultar antes de propor qualquer uso de
modelo generativo.
