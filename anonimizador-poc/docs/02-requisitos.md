# 02 — Requisitos

Requisitos do produto, com o estado de cada um. Nasceu no marco zero e foi
**revisto em 2026-09-24**, na avaliação para homologação (`HOMOLOGACAO.md`,
na raiz): os estados abaixo são os daquela data, e os números citados vêm do
`eval/report.md` de 2026-09-23. A coluna **Estado** distingue:

- **Atendido** — implementado e verificado.
- **Implementado** — código escrito, verificação pendente.
- **Parcial** — parte entregue; o que falta está dito na linha.
- **Pendente** — previsto, ainda não feito.
- **Descartado** — decidido que não será feito; a razão está na linha.

Identificadores: `RF` funcional, `RNF` não-funcional, `RS` segurança,
`RN` normativo/jurídico, `RO` operacional.

---

## 1. Requisitos funcionais

| ID | Requisito | Fase | Estado |
|---|---|---|---|
| RF-01 | Detectar identificadores estruturados PT-BR (CPF, CNPJ, CNS, PIS/PASEP, processo CNJ, título de eleitor, CNH, RG, CEP, telefone, e-mail) em PDF de texto | 0 | **Atendido** — CPF e CNPJ com F1 estrito 1,000 nas três configurações; demais medidos no `report.md` |
| RF-02 | Validar por dígito verificador todo identificador que tenha um, descartando o candidato reprovado | 0 | **Atendido** |
| RF-03 | Detectar nomes de pessoas, organizações e locais por NER local em português | 0 | **Atendido** — `bert-lenerbr`: PERSON F1 relaxado 0,979, recall 0,999; 49/50 documentos sem vazamento (corpus sintético) |
| RF-04 | Usar palavras-âncora de contexto para elevar a confiança de padrões ambíguos | 0 | **Atendido** — inclusive como desempate obrigatório para CNH e PIS (`forma_ambigua`) |
| RF-05 | Resolver spans sobrepostos com política explícita e determinística | 0 | **Atendido** |
| RF-06 | Converter offsets de caractere em retângulos na página, corretamente inclusive quando o valor cruza quebra de linha | 0 | **Atendido parcialmente** — 0 spans sem retângulo em 50 documentos com tabela, duas colunas e 3 páginas; o caso *valor cruzando quebra de linha* continua sem exercício no corpus (ver `06`, seção 5) |
| RF-07 | Aplicar redação verdadeira: remover o texto do content stream, não cobri-lo | 0 | **Atendido** — nenhum vazamento atribuível à redação; os vazamentos residuais são falhas de detecção de `PERSON` |
| RF-08 | Sanear metadados, XMP, anotações, campos AcroForm, anexos, sumário, miniaturas e objetos órfãos | 0 | **Atendido** — 10 vetores verificados por documento em 150 execuções de redação |
| RF-09 | Verificar o arquivo final em múltiplos vetores e **reprovar** se qualquer valor tarjado sobreviver | 0 | **Atendido** — 10 vetores no PDF (11 com token), 2 no texto; é o gate de download na UI e na CLI |
| RF-10 | Gerar corpus sintético multi-gênero com gabarito exato | 0 | **Atendido** — 50 documentos, 5 gêneros, 2.546 entidades; falta o campo de chave PIX (RN-09) |
| RF-11 | Produzir métricas por entidade (F1 estrito, F1 relaxado, cobertura de caracteres) e latência | 0 | **Atendido** — só em modo tarja; o modo código não é medido (`PROXIMOS-PASSOS.md`, item 5) |
| RF-12 | Comparar múltiplas configurações de NER num mesmo relatório | 0 | **Atendido** |
| RF-13 | Interface de revisão humana: o operador confirma ou ajusta as tarjas antes de aplicar | 1 | **Atendido** — `make ui`; o gate de usabilidade com pessoas reais **nunca foi medido** (`goal-fase-1.md`, Bloco 3) |
| RF-14 | Pseudonimização reversível com cofre de mapa token→valor | 2 | **Descartado** em 2026-09-05 — guardar o original resolve "voltar atrás" sem devolver a saída ao escopo da LGPD (`goal-fase-2.md` §5, B0) |
| RF-15 | Modo de anonimização irreversível, sem cofre | 2 | **Atendido** — tarja, e token sorteado por documento, com o mapa descartado (Fase 2A) |
| RF-16 | OCR de PDF escaneado | futuro | Pendente — PDF sem texto é recusado; página digitalizada dentro de PDF com texto é apontada na revisão |
| RF-17 | Copiloto de configuração com LLM local, sem acesso ao conteúdo do documento | 3 | Pendente — não iniciado (`goal-fase-3.md`, Bloco 2). A LLM que existe é a **externa**, para análise do texto com código (§2.6 de [`05-politica-llm.md`](05-politica-llm.md)) |
| RF-19 | Perfil de política de anonimização serializável: operador por entidade, carregável de JSON e validado antes de tocar em documento | 1 | **Atendido** (`politica.PerfilPolitica`) — `tarja`, `pseudonimo` e `manter` implementados; `mascara` continua recusado por `validar_perfil` |
| RF-20 | Seleção do tipo de anonimização pelo usuário, por entidade | 1 | **Parcial** — a tela escolhe tarja ou código **por documento** e liga/desliga cada classe; o operador por entidade existe no perfil, mas a tela não o oferece. Onde o código não cabe, aquele trecho vai em tarja automaticamente |
| RF-18 | Processamento em lote com fila | 1 | Pendente — a CLI processa um documento por chamada |
| RF-21 | Saída de texto com código, verificada, para análise por LLM | 2A | **Atendido** — `verify_texto`, `GET /download/texto` |
| RF-22 | Análise do texto com código por LLM externa, com consentimento por documento | 3 | **Parcial** — funciona, envio real verificado em 2026-09-23; retenção no provedor e parecer jurídico pendentes (`PROXIMOS-PASSOS.md`, itens 2 e 3) |

### RF-13 não é um enfeite

A camada de revisão humana é o que separa a ferramenta de um risco. Nenhuma
detecção de nome próprio em texto livre chega a 100%, e a consequência de um
falso negativo é um vazamento. **O produto não deve oferecer modo totalmente
automático sem revisão** para documentos com dado sensível — e o material
comercial não deve prometer isso.

---

## 2. Requisitos não-funcionais

| ID | Requisito | Critério | Estado |
|---|---|---|---|
| RNF-01 | Todo processamento roda localmente | zero chamadas de rede em execução | **Atendido** — única exceção é o envio opcional do texto com código pelo serviço `analise`, que não vê o original (CLAUDE.md, invariante 6) |
| RNF-02 | Execução comprovadamente offline | container sem interface de rede; `ui` em rede `internal: true` | **Atendido** — `prova_rede` (TCP, DNS e subprocesso bloqueados) conferida em 2026-09-24 |
| RNF-03 | Ambiente reprodutível | versões fixadas, imagem única, corpus semeado | **Atendido** |
| RNF-04 | Determinismo | mesma entrada produz exatamente a mesma saída | **Atendido** (lógica de spans) |
| RNF-05 | Latência aceitável em CPU | a medir no eval; sem meta rígida na Fase 0 | **Medido** — 0,044 s/página (spaCy) e ~0,54 s/página (transformers) no eval; na UI, ~0,7 s/página com renderização e montagem da sessão |
| RNF-06 | Suporte opcional a GPU | override de compose com torch CUDA | Implementado |
| RNF-07 | Portabilidade | mesma imagem em dev, homologação e produção | Implementado |
| RNF-08 | Documentos de dezenas a centenas de páginas | janelamento do NER já previsto | **Medido** em 2026-09-24 com 102 páginas sintéticas: detecção 69–74 s, pré-verificação 47 s, aprovação 45 s, 3,1 GB de memória no `ui`. Funciona; é lento, e cada rodada de correção custa uma pré-verificação |
| RNF-09 | Observabilidade | log estruturado, contadores por etapa | Parcial |
| RNF-10 | Escalabilidade horizontal | container sem estado; paralelizável por documento | **Parcial** — a CLI é sem estado e paralelizável; a UI **não**: sessão na memória do processo e modelo carregado por processo (`07-modelo-de-produto.md` §3). Escalar a UI hoje é máquina maior |
| RNF-11 | Um documento em processamento não bloqueia os outros usuários | a interface responde enquanto outro documento é detectado | **Atendido** em 2026-09-24 — antes, 60 s sem resposta durante a detecção de 102 páginas; depois, 0,47 s no pior caso. Detecções são serializadas (uma por vez). `tests/test_envio_nao_trava.py` |

---

## 3. Requisitos de segurança

| ID | Requisito | Estado |
|---|---|---|
| RS-01 | Na Fase 0, usar **exclusivamente** dados sintéticos; nunca documento real sigiloso | **Atendido** |
| RS-02 | Documentos de entrada e saída fora do controle de versão | **Atendido** (`.gitignore`) |
| RS-03 | Container roda como usuário não-root | **Atendido** — usuário `anon` (uid 1000) no `Dockerfile` |
| RS-04 | Nenhum conteúdo de documento em log | **Atendido** — logs registram id, contagem, entidade e posição; `tests/test_log_sem_pii.py` |
| RS-05 | Não persistir o texto original do documento | **Atendido** — o original só existe na pasta da sessão durante a revisão: TTL de 2 h, `DELETE` explícito e varredura de órfãs na subida (CLAUDE.md, invariante 9) |
| RS-06 | Validação com documentos reais ocorre no ambiente do cliente, nunca no de dev ou demonstração | Regra operacional |
| RS-07 | Cofre com criptografia envelope e chave sob controle do cliente | **Descartado** com o cofre (RF-14) |
| RS-10 | LLM roda local, no container sem rede | **Revogado para a análise de documento** pela decisão de 2026-09-05 (LLM externa, `goal-fase-3.md` §2). Continua valendo para um eventual copiloto local (RF-17). A revisão de R1 **por escrito** em [`05-politica-llm.md`](05-politica-llm.md) segue pendente (`goal-fase-3.md`, Bloco 0) |
| RS-11 | LLM nunca recebe nem escreve valor de PII; opera sobre metadados | **Atendido para o que é detectado** — a LLM recebe só texto com código, depois de `verify_texto` e de uma re-detecção com limiar mais baixo. Não cobre o que a detecção não acha (~1 documento em 50 com nome escapado; identificador indireto) — §2.6 de `05-politica-llm.md` |
| RS-12 | Nenhuma saída de LLM altera documento sem aprovação humana explícita | **Atendido** — a análise devolve texto para leitura; nada volta para o documento |
| RS-08 | Controle de acesso por papel para a operação de reversão | **Descartado** com o cofre (RF-14). O controle de acesso ao **documento** é RS-14 |
| RS-09 | Trilha de auditoria de cada operação de anonimização e reversão | **Parcial** — existe só para envio externo, e em memória (`Sessao.envios`); upload, revisão, aprovação e download pendentes (`goal-fase-4.md`, Bloco 4) |
| RS-13 | Imagem sem credenciais, tokens ou segredos embutidos | **Atendido** — `.dockerignore` tira `.env` e `out/` da imagem; `make llm-proof` confere. *Era um segundo `RS-10` até 2026-09-24; renumerado.* |
| RS-14 | Autenticação e posse de documento: só o dono alcança a sessão | **Pendente** — não há login. A interface só escuta em `127.0.0.1`, e é isso que a protege hoje. **Bloqueia homologação por várias pessoas num servidor compartilhado** (`goal-fase-4.md`, Blocos 2 e 3) |
| RS-15 | TLS fora de `localhost` | **Pendente** — entra junto com RS-14 (`goal-fase-4.md` §5) |

### Sobre RS-04

O `verifier.py` reporta o valor vazado quando encontra um — é o único ponto em
que um valor sensível aparece em saída, e é intencional: sem isso o
diagnóstico seria impossível. Em produção, essa saída deve ir para um canal de
auditoria restrito, nunca para log de aplicação. Está em
[`04-implantacao.md`](04-implantacao.md), passo 9.

---

## 4. Requisitos normativos e jurídicos

| ID | Requisito | Estado |
|---|---|---|
| RN-01 | Distinguir explicitamente anonimização de pseudonimização em produto e material comercial | Regra de produto |
| RN-02 | Não prometer que dado pseudonimizado "sai do escopo da LGPD" | Regra de produto |
| RN-03 | Documentar o assessment de risco de reidentificação | Pendente (Fase 4) |
| RN-04 | **Resolver o licenciamento do PyMuPDF antes da primeira entrega comercial** | **Pendente — bloqueia entrega** |
| RN-05 | Resolver a licença do checkpoint de NER LeNER-Br, ou substituí-lo | **Pendente — bloqueia entrega** |
| RN-06 | Atribuição do `pt_core_news_lg` (CC BY-SA 4.0) na documentação do produto | Pendente |
| RN-07 | Conferir as citações normativas do documento de ideia antes de usá-las em material comercial | **Não verificado** |
| RN-08 | Todo artefato entregável passa por verificação própria antes de ser servido — não só o PDF | Atendido (Fase 2A) |
| RN-09 | O corpus sintético precisa gerar campo de chave PIX | **Pendente — lacuna de medição** |

### RN-09 — o corpus não exercita a âncora de PIX

Em 2026-09-05 um documento real de teste reprovou a verificação: o mesmo CNPJ
aparecia mascarado sob a âncora `CNPJ:` e cru sob `Chave PIX:`, e só o primeiro
era detectado. O conserto foi acrescentar `chave pix` às âncoras de CPF e CNPJ.

O `make eval` mediu o custo e não achou nenhum: CPF e CNPJ seguem com F1
estrito 1.000 nas três configurações, então a âncora não introduziu falso
positivo em 50 documentos e 2.546 entidades.

**Mas ele também não mediu o ganho**, e isso precisa ficar escrito:
`generate_corpus.py` não emite campo de chave PIX, então o corpus não contém o
caso que o conserto resolve. A evidência do ganho é o documento real mais
`tests/test_chave_pix.py`, não a métrica.

Enquanto o gerador não emitir esse campo, uma regressão nessa âncora passaria
pelo eval sem aparecer. É a mesma classe de silêncio que o
`docs/05-politica-llm.md` §3.2 descreve para identificador indireto: número
alto não é evidência de ausência de risco quando o gabarito não contém o caso.

### RN-01 e RN-02, em uma frase

Pela LGPD, dado **anonimizado** (art. 5º, III; art. 12) sai do escopo da lei;
dado **pseudonimizado** (art. 13, §4º) continua sendo dado pessoal.
Prometer o contrário é erro jurídico com risco reputacional.

> **Atualização de 2026-09-05 — a palavra "pseudonimização" passou a ter dois
> sentidos neste projeto, e confundi-los é o erro que RN-01 existe para
> impedir.**
>
> O que a Fase 2A entregou é **token sem cofre**: o token é sorteado, não
> derivado do valor, e o mapa morre com o processamento. Não existe chave, não
> existe "informação adicional mantida separadamente", e o processo não é
> reversível — nem por nós. Pela definição da lei, essa saída é **dado
> anonimizado**, e sai do escopo, apesar de o nome do módulo ser
> `pseudonimo.py`.
>
> O que tornaria a saída dado pessoal é o **cofre** (Fase B, encerrada em
> 2026-09-05). Enquanto ele não existir, a ressalva de RN-02 não se aplica ao
> artefato de texto.
>
> Duas coisas continuam valendo, e são as que a tela precisa dizer:
> a saída sair do escopo depende de a reidentificação não ser viável por
> esforços razoáveis — não é garantia absoluta, e a orientação da ANPD é
> baseada em risco; e a detecção tem furos medidos (§ `docs/05-politica-llm.md`
> 2.6), então "não sobrou o que detectamos" nunca é "não sobrou nada".

### RN-08 — o gate vale por artefato, não por formato

A invariante do projeto é que nada é entregue sem verificação aprovada. Até a
Fase 1 havia um só entregável, o PDF, e o gate era `verify()`. A Fase 2A
acrescentou o texto pseudonimizado, e com ele `verify_texto()`, que confere
duas coisas: nenhum valor original sobreviveu, **e** nenhum token se perdeu.

A segunda metade não é simetria estética. Se o valor sai e o token não entra,
uma checagem que só procurasse o original diria "limpo" — porque o original de
fato sumiu — e o gate aprovaria um documento mutilado. Qualquer entregável
novo herda a mesma exigência: verificação própria, e nada servido sem ela.

### RN-04 e RN-05 bloqueiam entrega, não desenvolvimento

O PyMuPDF é AGPL-3.0 ou licença comercial da Artifex; o checkpoint LeNER-Br não
declara licença. Nenhum dos dois impede a Fase 0, que é uso interno sem
distribuição. Ambos precisam estar resolvidos antes de o produto chegar a um
cliente. Detalhes e alternativas em
[`01-inventario-marco-zero.md`](01-inventario-marco-zero.md), seções 2.2 e 3.

### RN-07 é uma dívida herdada

As referências normativas do documento de ideia (Decreto 12.572/2025, IN GSI
8/2025, Lei 15.352/2026, o preprint Brazilian-PHI e os números de mercado) não
foram verificadas contra fontes primárias. São o alicerce do argumento
comercial de soberania — vale conferir antes de levá-las a uma proposta.

---

## 5. Requisitos operacionais

| ID | Requisito | Estado |
|---|---|---|
| RO-01 | Nada instalado no host além do Docker | **Atendido** |
| RO-02 | Build é a única etapa com rede | Implementado |
| RO-03 | Implantação em ambiente air-gapped por transferência de imagem | Implementado (ver passo 10 da implantação) |
| RO-04 | Mesmos comandos em Windows, Linux e macOS | **Atendido** (`Makefile` + `run.ps1`) |
| RO-05 | Retenção e descarte de documentos processados | Pendente — política do cliente |
| RO-06 | Backup e recuperação | Pendente (relevante a partir da Fase 2, com o cofre) |

---

## 6. Critérios de aceite da Fase 0

Repetidos aqui do `goal-fase-0.md` para servirem de checklist de fechamento.

Conferidos em 2026-09-24 contra o `eval/report.md` de 2026-09-23.

- [x] CPF e CNPJ com F1 estrito ≥ 0,95 — 1,000 nas três configurações
- [x] PERSON com F1 relaxado ≥ 0,80 em pelo menos uma configuração de NER —
      `bert-lenerbr` 0,979, `bertimbau-harem` 0,904
- [x] Demais entidades com recall medido e documentado
- [x] Cobertura de caracteres agnóstica de tipo reportada — 0,981 no `bert-lenerbr`
- [ ] Verificação pós-redação passando em 100% dos documentos — **49/50** no
      `bert-lenerbr`. O que falha não é a redação: é `rh-028`, "Bento da Mata",
      nome que a detecção não marcou como pessoa (`PROXIMOS-PASSOS.md`, item 4).
      Nenhum valor que o sistema decidiu tarjar sobreviveu por defeito de
      redação.
- [x] Sem egress no container que processa documento — `prova_rede` no `ui`
      conferida em 2026-09-24. O alvo `make offline-proof` em si **não** foi
      rodado nesta revisão.
- [x] `report.md` com métricas, latências e recomendação explícita para a
      Fase 1 — recomendação `bert-lenerbr`, decisão D1 em `goal-fase-1.md`

---

## 7. Requisitos de ambiente do cliente (produção)

Levantamento a fazer com o cliente antes da implantação. Estas perguntas
mudam a arquitetura, então valem uma conversa antes da proposta.

| Tema | Pergunta |
|---|---|
| Classificação | Os documentos são sigilosos, reservados, secretos ou ultrassecretos? Dados ultrassecretos não podem ir para nuvem nenhuma |
| Local | On-premise, nuvem de governo, OCI região Brasil ou outro? |
| Air-gap | O ambiente tem acesso à internet, mesmo que restrito? |
| Volume | Documentos por dia, páginas por documento, pico |
| Hardware | CPU disponível, RAM, existe GPU? |
| Origem | Os PDFs têm texto selecionável ou são digitalizados? (o segundo caso exige OCR, que não existe ainda) |
| Reversão | O cliente precisa reverter a anonimização? Quem pode? Sob que controle? |
| Integração | Entrada por pasta monitorada, API, ou upload manual? |
| Retenção | Por quanto tempo os arquivos ficam no ambiente de processamento? |
| Homologação | Quem valida a qualidade da detecção nos documentos reais dele? |
