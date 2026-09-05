# 02 — Requisitos

Requisitos do produto, com o estado de cada um no marco zero. A coluna
**Estado** distingue três situações:

- **Atendido** — implementado e verificado.
- **Implementado** — código escrito, verificação pendente do container.
- **Pendente** — fora do escopo da Fase 0, previsto para fase posterior.

Identificadores: `RF` funcional, `RNF` não-funcional, `RS` segurança,
`RN` normativo/jurídico, `RO` operacional.

---

## 1. Requisitos funcionais

| ID | Requisito | Fase | Estado |
|---|---|---|---|
| RF-01 | Detectar identificadores estruturados PT-BR (CPF, CNPJ, CNS, PIS/PASEP, processo CNJ, título de eleitor, CNH, RG, CEP, telefone, e-mail) em PDF de texto | 0 | Implementado |
| RF-02 | Validar por dígito verificador todo identificador que tenha um, descartando o candidato reprovado | 0 | **Atendido** |
| RF-03 | Detectar nomes de pessoas, organizações e locais por NER local em português | 0 | Implementado |
| RF-04 | Usar palavras-âncora de contexto para elevar a confiança de padrões ambíguos | 0 | Implementado |
| RF-05 | Resolver spans sobrepostos com política explícita e determinística | 0 | **Atendido** |
| RF-06 | Converter offsets de caractere em retângulos na página, corretamente inclusive quando o valor cruza quebra de linha | 0 | **Atendido parcialmente** — 0 spans sem retângulo em 50 documentos com tabela, duas colunas e 3 páginas; o caso *valor cruzando quebra de linha* continua sem exercício no corpus (ver `06`, seção 5) |
| RF-07 | Aplicar redação verdadeira: remover o texto do content stream, não cobri-lo | 0 | **Atendido** — nenhum vazamento atribuível à redação; os vazamentos residuais são falhas de detecção de `PERSON` |
| RF-08 | Sanear metadados, XMP, anotações, campos AcroForm, anexos, sumário, miniaturas e objetos órfãos | 0 | **Atendido** — 10 vetores verificados por documento em 150 execuções de redação |
| RF-09 | Verificar o arquivo final em múltiplos vetores e **reprovar** se qualquer valor tarjado sobreviver | 0 | Implementado |
| RF-10 | Gerar corpus sintético multi-gênero com gabarito exato | 0 | Implementado |
| RF-11 | Produzir métricas por entidade (F1 estrito, F1 relaxado, cobertura de caracteres) e latência | 0 | Implementado |
| RF-12 | Comparar múltiplas configurações de NER num mesmo relatório | 0 | Implementado |
| RF-13 | Interface de revisão humana: o operador confirma ou ajusta as tarjas antes de aplicar | 1 | Pendente |
| RF-14 | Pseudonimização reversível com cofre de mapa token→valor | 2 | Pendente |
| RF-15 | Modo de anonimização irreversível, sem cofre | 2 | Pendente |
| RF-16 | OCR de PDF escaneado | futuro | Pendente (gancho previsto na arquitetura) |
| RF-17 | Copiloto de configuração com LLM local, sem acesso ao conteúdo do documento | 3 | Pendente — escopo e limites de acesso fixados em [`05-politica-llm.md`](05-politica-llm.md) |
| RF-19 | Perfil de política de anonimização serializável: operador por entidade, carregável de JSON e validado antes de tocar em documento | 1 | **Atendido** (`politica.PerfilPolitica`) — apenas `tarja` e `manter` implementados; `pseudonimo` e `mascara` são recusados por `validar_perfil` |
| RF-20 | Seleção do tipo de anonimização pelo usuário, por entidade | 1 | Pendente — contrato pronto (RF-19), executor e tela pendentes |
| RF-18 | Processamento em lote com fila | 1 | Pendente |

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
| RNF-01 | Todo processamento roda localmente | zero chamadas de rede em execução | Implementado |
| RNF-02 | Execução comprovadamente offline | container sem interface de rede + sabotagem in-process do socket | Implementado |
| RNF-03 | Ambiente reprodutível | versões fixadas, imagem única, corpus semeado | **Atendido** |
| RNF-04 | Determinismo | mesma entrada produz exatamente a mesma saída | **Atendido** (lógica de spans) |
| RNF-05 | Latência aceitável em CPU | a medir no eval; sem meta rígida na Fase 0 | **Medido** — 0,044 s/página (spaCy) e ~0,53 s/página (transformers), em documentos de 3 páginas |
| RNF-06 | Suporte opcional a GPU | override de compose com torch CUDA | Implementado |
| RNF-07 | Portabilidade | mesma imagem em dev, homologação e produção | Implementado |
| RNF-08 | Documentos de dezenas a centenas de páginas | janelamento do NER já previsto | Implementado, **não verificado** — corpus tem 3 páginas; ver `06`, seção 5 |
| RNF-09 | Observabilidade | log estruturado, contadores por etapa | Parcial |
| RNF-10 | Escalabilidade horizontal | container sem estado; paralelizável por documento | Implementado por construção |

---

## 3. Requisitos de segurança

| ID | Requisito | Estado |
|---|---|---|
| RS-01 | Na Fase 0, usar **exclusivamente** dados sintéticos; nunca documento real sigiloso | **Atendido** |
| RS-02 | Documentos de entrada e saída fora do controle de versão | **Atendido** (`.gitignore`) |
| RS-03 | Container roda como usuário não-root | Implementado |
| RS-04 | Nenhum conteúdo de documento em log | Implementado (logs registram tipo e posição, não valor) |
| RS-05 | Não persistir o texto original do documento | Implementado (nada é gravado além do PDF de saída) |
| RS-06 | Validação com documentos reais ocorre no ambiente do cliente, nunca no de dev ou demonstração | Regra operacional |
| RS-07 | Cofre com criptografia envelope e chave sob controle do cliente | Pendente (Fase 2) |
| RS-10 | LLM roda local, no container sem rede | Pendente (Fase 3) — regra R1 de [`05-politica-llm.md`](05-politica-llm.md) |
| RS-11 | LLM nunca recebe nem escreve valor de PII; opera sobre metadados | Pendente (Fase 3) — regra R2; verificável pela assinatura do montador de prompt |
| RS-12 | Nenhuma saída de LLM altera documento sem aprovação humana explícita | Pendente (Fase 3) — regra R3 |
| RS-08 | Controle de acesso por papel para a operação de reversão | Pendente (Fase 2) |
| RS-09 | Trilha de auditoria de cada operação de anonimização e reversão | Pendente (Fase 2) |
| RS-10 | Imagem sem credenciais, tokens ou segredos embutidos | **Atendido** |

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

- [ ] CPF e CNPJ com F1 estrito ≥ 0,95
- [ ] PERSON com F1 relaxado ≥ 0,80 em pelo menos uma configuração de NER
- [ ] Demais entidades com recall medido e documentado
- [ ] Cobertura de caracteres agnóstica de tipo reportada
- [ ] Verificação pós-redação passando em 100% dos documentos
- [ ] `make offline-proof` verde, com container sem interface de rede
- [ ] `report.md` com métricas, latências e recomendação explícita para a Fase 1

Nenhum está marcado: dependem da primeira execução do harness dentro do
container.

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
