# Avaliação de Viabilidade e Escopo de Projeto: Ferramenta de Anonimização/Pseudonimização de PDFs com Conformidade LGPD e Soberania de Dados

## TL;DR
- **O projeto é tecnicamente viável e comercialmente promissor.** Existe uma pilha de software open-source madura que roda 100% localmente (Microsoft Presidio + spaCy/BERTimbau + PyMuPDF + HashiCorp Vault), e a restrição de soberania — nenhum conteúdo enviado a IA no exterior — é um diferencial real de mercado, não um obstáculo. O caminho crítico não é a detecção, é a governança do cofre de reversibilidade e a validação em documentos reais.
- **O modelo escolhido (pseudonimização reversível "com condições") é juridicamente sólido, mas mantém o dado sob a LGPD.** Pela LGPD, dado pseudonimizado continua sendo dado pessoal (art. 13, §4º); só a anonimização irreversível (art. 5º, III e art. 12) tira o dado do escopo da lei. A ferramenta deve oferecer os dois modos e deixar essa distinção explícita ao usuário — é o principal risco de posicionamento jurídico.
- **A soberania de dados deixou de ser diferencial "nice-to-have" e virou requisito regulatório para o setor público.** O Decreto nº 12.572/2025 e a IN GSI nº 8/2025 exigem infraestrutura nacional, dedicada e certificada (ISO 27001/27017/27018/27701/22237) para dados classificados do governo — o que favorece um produto on-premise/soberano e desqualifica concorrentes que dependem de nuvem estrangeira.

## Key Findings

1. **Stack local viável e comprovado cientificamente.** O benchmark acadêmico *Brazilian-PHI* (preprint 2026, Igor Eduardo, DOI 10.21203/rs.3.rs-10757966/v1) mostrou que reconhecedores customizados do Microsoft Presidio com validação de dígito verificador (mod-11) atingem macro-F1 = 1,000 em sete tipos de PII brasileiros (CPF, CRM, CNS, CNPJ, RG, CEP, telefone), contra 0,270 do Presidio padrão e 0,989 do LLM Llama 3.3 70B — com latência de ~9,9 microssegundos por nota vs. 801 ms do LLM (diferença de ~80.000×). Isso valida a tese central do projeto: **não é preciso um LLM externo para detecção de PII de alta qualidade em português; regex+checksum+NER local supera o LLM e é milhares de vezes mais rápido.** (Ressalva: o autor declara conflito de interesse por ser fundador de empresa que usa os reconhecedores avaliados, e o corpus é sintético — os números devem ser confirmados em documentos reais do cliente.)

2. **Presidio suporta nativamente pseudonimização reversível.** A documentação oficial do Presidio traz um fluxo de "pseudonymization" com mapeamento entidade→token e um `DeanonymizeEngine` para reverter (via `InstanceCounterDeanonymizer`). Presidio é MIT-licensed, gratuito, extensível com reconhecedores customizados (regex, deny-list, checksum) e roda offline. É a espinha dorsal técnica recomendada.

3. **Redação verdadeira de PDF é resolvida com PyMuPDF.** O método `apply_redactions()` do PyMuPDF (fitz) remove fisicamente o texto do content stream — não apenas cobre com retângulo preto — evitando o problema clássico de "fake redaction" (caso da Comissão Europeia/AstraZeneca em 2021 e do caso Manafort). Essencial para conformidade real.

4. **Existe concorrência nacional, mas com brechas exploráveis.** MavenDoc (maven.com.br) já anonimiza PDFs/planilhas/áudios com IA "treinada para o contexto brasileiro", OCR, revisão visual e cálculo de k-anonimato. O TJPA lançou (2025) um "Anonimizador" próprio conforme a Resolução CNJ nº 615. Privacy Tools (desde 2019), Tee Global (desde 2022) e outras cobrem governança LGPD, mas não o nicho específico de "anonimização documental on-premise com cofre reversível e zero-cloud-estrangeira".

5. **A ANPD ainda NÃO publicou o guia definitivo de anonimização.** A minuta do "Guia de Anonimização e Pseudonimização para a Proteção de Dados Pessoais" entrou em consulta pública em 30/01/2024 (contribuições encerradas em março de 2024), mas, conforme o próprio relatório de acompanhamento da Agenda Regulatória 2025-2026 da ANPD, "a versão final encontra-se no Conselho Diretor para aprovação" — e foi reencaminhada à Coordenação-Geral de Normatização (CGN) para adequações após informações supervenientes. Isso significa incerteza regulatória, mas também uma janela de oportunidade para se posicionar como "conforme às melhores práticas" antes da consolidação normativa.

6. **A demanda de mercado é real e crescente**, impulsionada pelo enrijecimento da ANPD (transformada em agência reguladora, com multas de até 2% do faturamento limitadas a R$ 50 milhões por infração) e pela exigência de soberania no setor público.

## Details

### 1. Ferramentas e bibliotecas (processamento local)

**Microsoft Presidio (recomendado como núcleo).** Framework open-source (MIT) da Microsoft com três componentes: `presidio-analyzer` (detecção via NER + regex + checksum + context), `presidio-anonymizer` (operadores de mascaramento, substituição, hash, criptografia) e image-redactor (via Tesseract OCR, para o futuro). Suporta spaCy 3+, Stanza, transformers e Flair como backends de NLP. Reconhecedores padrão são calibrados para EUA (~20 entidades), então CPF/CNPJ/RG exigem reconhecedores customizados — o que é rotina (poucas linhas de código, com validação de dígito verificador). Suporta reversibilidade: o `entity_mapping` guardado pelo cliente permite deanonymization.

**spaCy — modelos para português.** Há três pipelines PT (`pt_core_news_sm/md/lg`), otimizados para CPU, treinados em Universal Dependencies + WikiNER. A acurácia de NER do spaCy pronto em texto genérico é limitada: conforme Canário & Duarte, "Taggus" (arXiv:2508.03358, 2025), "Taggus significantly outperforms the off-the-shelf Spacy's NER model for Portuguese both in Precision and F1-Score, with an average of 93.9% and 94.1% against 29.4% and 43.4%, respectively." Conclusão: **spaCy sozinho não basta para nomes de pessoas em contratos; combinar com regras de contexto e/ou um modelo transformer melhora muito.**

**BERTimbau e modelos transformer PT-BR.** Conforme Souza, Nogueira & Lotufo, "Portuguese Named Entity Recognition using BERT-CRF" (arXiv:1909.10649; BRACIS 2020), o BERTimbau-Large (BERT-CRF) obtém Precisão/Revocação/F1 de 83,38/81,17/82,26 no HAREM I (cenário total), "improving the state-of-the-art... outperforming Multilingual BERT". Roda localmente (com GPU modesta ou CPU com latência maior). É a opção para elevar a detecção de PERSON/ORG/LOC em texto livre, onde regex não alcança.

**Detecção estruturada PT-BR (CPF/CNPJ/RG/CEP).** Regex + validação de dígito verificador (mod-11 para CPF/CNPJ) é determinística, rápida e language-agnostic. É o que dá o F1=1,0 do benchmark Brazilian-PHI e elimina falsos positivos — algo que o LLM não consegue fazer (não valida checksum matemático).

**Redação de PDF.** PyMuPDF/fitz (`apply_redactions()`) para remoção real; pdfplumber para extração/posicionamento de texto. Atenção: limpar metadados também (autor, histórico). Verificação obrigatória pós-redação (extrair texto do arquivo final para confirmar remoção).

**Anonimização estatística/tabular (complementar).** ARX (Java, open-source, Apache 2.0) — k-anonimato, l-diversidade, t-closeness, δ-presence, (ε,δ)-differential privacy, generalização, supressão, microagregação; usado no mundo real em saúde (ex.: Registro de Câncer da Noruega, 5M+ registros). Amnesia (OpenAIRE) — k-anonimato e km-anonimato. Estes se aplicam a dados tabulares, não a texto de contrato; úteis se o produto expandir para planilhas.

**Cofre/gestão de chaves.** HashiCorp Vault com transit engine e Transform (tokenização, FPE, masking). A tokenização do Vault usa AES256-GCM96, chaves derivadas de token+root key, rotação automática, e permite modos em que o plaintext só é recuperável com o token distribuído. Envelope encryption (DEK local + CMK/master no KMS) é o padrão.

**Faker** — geração de dados fake realistas para substituir PII (pseudônimos plausíveis) e para dados sintéticos de teste.

**Referências comerciais mundiais.** Private AI (Toronto; detecção/redação de PII em texto não-estruturado, 50+ tipos, 50+ idiomas, deploy on-prem/air-gapped); Skyflow (data privacy vault, tokenização, data residency regional); Tonic.ai (dados sintéticos); Nightfall, BigID, Immuta, Privitar (adquirida pela Informatica), Gretel, Mostly AI. **Nenhum desses tem região/data residency no Brasil como padrão nem processamento soberano garantido** — a maioria é SaaS em nuvem estrangeira, o que os desqualifica para o cliente-alvo (governo/dados sigilosos).

### 2. Anonimização vs. pseudonimização — o que dizem a LGPD e a ANPD

**Definições legais (Lei 13.709/2018):**
- *Dado anonimizado* (art. 5º, III): "dado relativo a titular que não possa ser identificado, considerando a utilização de meios técnicos razoáveis e disponíveis na ocasião de seu tratamento". Art. 12: dado anonimizado **não é dado pessoal** e sai do escopo da LGPD — salvo se o processo for reversível ou exigir esforço não razoável.
- *Pseudonimização* (art. 13, §4º): "tratamento por meio do qual um dado perde a possibilidade de associação, direta ou indireta, a um indivíduo, senão pelo uso de informação adicional mantida separadamente pelo controlador em ambiente controlado e seguro". **Continua sendo dado pessoal e sob a LGPD.**
- *Dado pessoal sensível* (art. 5º, II): origem racial/étnica, convicção religiosa, opinião política, filiação sindical/religiosa/filosófica/política, saúde, vida sexual, dado genético ou biométrico vinculado a pessoa natural.

**Implicação direta para o projeto:** o modelo escolhido (reversível com chave) é **pseudonimização**, não anonimização. O dado permanece protegido pela LGPD; isso é aceitável e comum, mas o produto NÃO deve prometer "sair do escopo da LGPD". Recomenda-se oferecer também um modo de anonimização irreversível (supressão/hash sem cofre) para os casos em que o cliente queira efetivamente desidentificar.

**Orientação da ANPD.** A ANPD abriu consulta pública (30/01/2024) da minuta do "Guia de Anonimização e Pseudonimização para a Proteção de Dados Pessoais", com estudo preliminar, estudo de casos e dois estudos técnicos (risco/computacional e jurídico). Pontos-chave da minuta: (a) não existe técnica de anonimização com eficácia plena; adota-se **modelo baseado em risco** de reidentificação, avaliando meios e esforços razoavelmente acessíveis; (b) o processo de anonimização é, ele próprio, um tratamento de dados (atrai a LGPD durante a execução); (c) o processo deve ser **documentado** (a ANPD pode exigir o assessment de risco em fiscalização); (d) a proteção das chaves e algoritmos de pseudonimização é essencial. **O guia definitivo ainda não foi publicado** — a versão final está no Conselho Diretor para aprovação e foi devolvida à CGN para ajustes (relatório de balanço da Agenda Regulatória 2025-2026 da ANPD). A minuta também referencia guias internacionais (ex.: o "Guidance on Anonymisation and Pseudonymisation" da Data Protection Commission irlandesa, 2019).

**Técnicas e aplicabilidade:**
- Texto de contrato (não-estruturado): masking/supressão, tokenização, criptografia reversível, substituição por pseudônimos (Faker). k-anonimato/l-diversidade/t-closeness/differential privacy **não se aplicam bem a texto livre** — são para dados tabulares/estatísticos.
- Dados tabulares (futuro): k-anonimato, l-diversidade, t-closeness, generalização, supressão, differential privacy (via ARX/Amnesia).

### 3. Detecção de PII em português sem IA externa

Totalmente viável. Arquitetura recomendada em camadas: (1) regex + checksum para identificadores estruturados (CPF, CNPJ, RG, CEP, telefone, e-mail, cartão) — precisão altíssima; (2) NER local (spaCy `pt_core_news_lg` e/ou BERTimbau via transformers) para PERSON/ORG/LOC/datas; (3) reconhecedores customizados de contexto (deny-list, palavras-âncora como "CPF nº", "portador do RG"); (4) camada de revisão humana (o usuário confirma/ajusta as tarjas antes de aplicar). Roda em CPU; BERTimbau se beneficia de GPU modesta mas funciona em CPU com latência maior. O benchmark Brazilian-PHI confirma precisão de ponta com essa abordagem.

### 4. Arquitetura de reversibilidade segura (cofre)

Padrão recomendado:
- **Tokenização**: cada valor real (ex.: "João da Silva", CPF X) → token opaco (ex.: `<PESSOA_1>`); o mapa token→valor real é o único elo.
- **Criptografia do mapa**: AES-256-GCM; envelope encryption — DEK gerada/criptografada localmente, CMK/master fica em KMS ou Vault transit engine (nunca em claro no banco).
- **Gestão de chaves**: HashiCorp Vault (transit/transform), rotação automática de chaves, `min_decryption_version` para invalidar chaves comprometidas, unseal ceremony com Shamir/GPG. Opcionalmente HSM/FIPS-validado para a master key.
- **Controle de acesso à reversão**: só quem anonimizou (ou detentor autorizado da chave) reverte; políticas por papel, trilha de auditoria de cada operação de encode/decode, autenticação forte.
- **Minimização de persistência**: o texto real do contrato não é persistido; apenas o mapa token→valor criptografado (o "cofre") é armazenado — alinhado à preferência do cliente de não guardar dados sensíveis em claro.

### 5. Soberania de dados e hospedagem no Brasil

**Quadro regulatório do setor público (endureceu em 2025):**
- **Decreto nº 12.572/2025** — governança de dados e requisitos de segurança para processamento na administração pública; consolida o conceito de "nuvem de governo" e de soberania de dados.
- **IN GSI nº 8/2025** (altera a IN nº 5/2021) — autoriza nuvem para dados sigilosos (reservado/secreto) SÓ se: provedor estabelecido no Brasil, certificações ABNT NBR ISO/IEC 27001, 27017, 27018, 27701 e 22237, todos os servidores em território nacional, infraestrutura física dedicada (sem compartilhamento), alta disponibilidade, habilitação/auditoria pelo GSI. **Proíbe replicação/backup no exterior.** Dados **ultrassecretos** não podem ir para nuvem nenhuma.
- **Nuvem de Governo (Serpro/Dataprev)** — catálogos lançados em 2025; 11+ órgãos federais migrados; meta de 20% da administração federal em nuvem de governo.
- **Portaria SGD/MGI nº 5.950/2023** — modelo obrigatório de contratação de nuvem/software para órgãos do SISP (obrigatório desde 30/04/2024).

**Opções de hospedagem no Brasil:**
- **Oracle Cloud (OCI)** — duas regiões no Brasil (São Paulo e Vinhedo); oferece Autonomous Database e Exadata; tem oferta Sovereign Cloud e Dedicated Region Cloud@Customer (DRCC — primeiro caso no Brasil: Dataprev). Dados ficam em solo nacional; ressalva: o contrato master segue direito americano (mesmo dilema de AWS/Azure/GCP), relevante para setores críticos. Oracle publica certificações ISO 27001 e SOC 2.
- **AWS São Paulo, Azure Brasil Sul, Google Cloud São Paulo** — regiões locais, mas jurisdição estrangeira (exposição ao Cloud Act americano é o argumento central dos provedores nacionais).
- **Magalu Cloud** — provedor nacional (data centers em São Paulo e Fortaleza), forte narrativa de soberania ("o dado fica aqui, podemos abrir o código-fonte"); em negociação com o governo para a nuvem soberana, mas ainda não fechado; críticos apontam que localização geográfica ≠ soberania plena (infraestrutura/governança/cadeia tecnológica ainda dependem de bases estrangeiras).
- **Hostinger (KVM)** para dev/homologação — aceitável para ambiente sem dados reais; NÃO adequado para produção com dados sigilosos de governo (não atende às exigências de infraestrutura dedicada/certificação do GSI).

**Recomendação de soberania:** dev/homologação em Hostinger KVM (dados sintéticos apenas); produção on-premise no cliente OU em OCI região Brasil/Magalu/Nuvem de Governo, conforme o perfil do órgão. Para dados classificados de governo, o alvo é infraestrutura habilitada pelo GSI.

### 6. Viabilidade de mercado

**Dor real e crescente.** A ANPD virou agência reguladora com poderes ampliados (Lei 15.352/2026), publicou o Painel da Fiscalização (nov/2025) e o Mapa de Temas Prioritários 2026-2027 (foco em direitos dos titulares, crianças, IA, saúde e **poder público**). As sanções previstas incluem, conforme o art. 52, II da LGPD, "multa simples, de até 2% (dois por cento) do faturamento da pessoa jurídica de direito privado, grupo ou conglomerado no Brasil no seu último exercício, excluídos os tributos, limitada, no total, a R$ 50.000.000,00 (cinquenta milhões de reais) por infração", além de multas diárias por descumprimento de medidas cautelares (Deliberação CD-10/2025). Historicamente as multas pecuniárias foram baixas: conforme a Turivius ("Multas LGPD 2026"), "até o início de 2026, a ANPD aplicou multa pecuniária em um único caso, no total de R$ 14.400, contra uma microempresa [Telekall Infoservice]" — em grande parte porque a maioria dos sancionados foi o setor público, que não paga. Mas o enforcement está acelerando — em junho de 2026 a ANPD abriu 19 novos processos sancionadores num único mês.

**Tamanho de mercado.** Conforme a ResearchAndMarkets ("Brazil RegTech Business and Investment Opportunities Databook", atualização Q3 2024), "the regtech industry in Brazil is expected to grow by 35.3% on annual basis to reach US$270.36 million in 2024... recording a CAGR of 22.1% during 2024-2029", partindo de US$199,79 milhões em 2023 para uma projeção de US$732,95 milhões até 2029. (Atenção: são projeções — outras casas, como a IMARC Group, apresentam números materialmente diferentes; o "35,3%" é o crescimento de um único ano 2023→2024, não a taxa de longo prazo.) O ecossistema privacy-tech nacional é jovem mas ativo (PrivacyTools desde 2019, Tee Global desde 2022). O setor financeiro lidera a demanda, seguido de jurídico, saúde, manufatura e varejo.

**Diferenciação competitiva possível:**
- **Processamento 100% local + zero-cloud-estrangeira** — nenhum grande player global oferece isso como padrão; é exatamente o que o setor público brasileiro passou a exigir.
- **Cofre de reversibilidade com chave sob controle do cliente** — poucas ferramentas nacionais oferecem pseudonimização reversível segura.
- **Copiloto de configuração com LLM local (Ollama)** — assistente conversacional que NUNCA vê o conteúdo do contrato, apenas ajuda a configurar regras/reconhecedores; preserva a soberania.
- **Foco documental (PDF) + validação de checksum PT-BR** — nicho subatendido vs. plataformas genéricas de governança LGPD.

Concorrentes diretos a monitorar: MavenDoc (o mais próximo), soluções internas de tribunais (TJPA), e eventuais entrantes.

### 7. LLM local para o copiloto (Ollama)

Viável e recomendado. Ollama (wrapper sobre llama.cpp) roda modelos quantizados (GGUF) localmente. Modelos 7B-8B (Llama 3.1, Mistral) rodam com ~6 GB de VRAM (GPU) ou CPU-only com 8-16 GB RAM (6-15 tokens/s em CPU moderna). Q4_K_M é o "sweet spot" (95%+ da qualidade, ~4× menos memória). **Papel do LLM: exclusivamente copiloto de configuração** (ajudar o usuário a criar reconhecedores, explicar categorias LGPD, sugerir políticas) — nunca processar o conteúdo real do contrato. Assim a restrição de soberania é respeitada mesmo usando IA generativa, pois tudo roda on-premise e o LLM não recebe PII.

## Recommendations

**Fase 0 — Validação (semanas 1-3):**
- Montar PoC com Presidio + reconhecedores CPF/CNPJ/RG/CEP (regex+mod-11) + spaCy `pt_core_news_lg` + PyMuPDF `apply_redactions()`.
- Testar em 20-50 contratos reais anonimizados/sintéticos; medir precisão/recall por tipo de entidade.
- **Benchmark de decisão:** se o F1 de identificadores estruturados < 0,95, revisar regex/checksum; se o F1 de nomes (PERSON) < 0,80, adicionar BERTimbau.

**Fase 1 — Núcleo de detecção e redação (meses 1-2):**
- Camada de detecção em pipeline (regex+checksum → NER → contexto → revisão humana).
- Redação real de PDF + limpeza de metadados + verificação pós-redação automática.
- UI de revisão visual (usuário confirma tarjas antes de aplicar) — crítico para confiança e para o requisito de "campos que a empresa marca como sensíveis".

**Fase 2 — Cofre de reversibilidade (meses 2-4):**
- Integrar HashiCorp Vault (transit/transform), AES-256-GCM, envelope encryption.
- Controle de acesso por papel + trilha de auditoria completa de encode/decode.
- Modo duplo: pseudonimização reversível (com cofre) e anonimização irreversível (supressão/hash sem cofre).
- **Não persistir** o texto original; apenas o mapa criptografado.

**Fase 3 — Copiloto local e soberania (meses 4-5):**
- Ollama on-premise com modelo 7B-8B para o copiloto de configuração (guardrails para nunca receber conteúdo do documento).
- Empacotamento para deploy on-premise/air-gapped (Docker); dev/homologação em Hostinger KVM (dados sintéticos), produção em OCI Brasil/Magalu/on-premise do cliente.

**Fase 4 — Conformidade, testes e go-to-market (mês 6):**
- Documentar o assessment de risco de reidentificação (a ANPD pode exigir).
- Preparar material que deixe explícita a distinção anonimização vs. pseudonimização (evitar prometer "saída do escopo da LGPD" para dado reversível).
- Buscar certificação/aderência às normas ISO exigidas pelo GSI se o alvo for governo.
- Piloto com um órgão público ou empresa com dados sigilosos.

**Benchmarks que mudam a estratégia:**
- Se a ANPD publicar o guia definitivo → realinhar as técnicas e a documentação de risco imediatamente.
- Se a detecção de nomes em CPU ficar lenta demais para o volume do cliente → GPU modesta ou modelo quantizado.
- Se surgir concorrente com o mesmo posicionamento soberano → acelerar diferenciação no cofre e no nicho documental.

## Caveats

- **A minuta do guia da ANPD ainda não é norma.** A versão final está no Conselho Diretor e foi devolvida à CGN para ajustes; há risco de que traga requisitos técnicos específicos que exijam adaptações. Monitorar a Plataforma Participa+Brasil e as publicações da ANPD.
- **Pseudonimização ≠ anonimização juridicamente.** Prometer que o dado "sai da LGPD" quando ele é reversível é erro jurídico e risco reputacional. O produto deve ser preciso nessa comunicação.
- **Acurácia de NER para nomes em português é o ponto fraco técnico.** Regex resolve identificadores estruturados, mas nomes/endereços em texto livre exigem NER de qualidade + revisão humana. Nunca prometer 100% automático sem revisão.
- **O benchmark F1=1,0 é de corpus sintético e com conflito de interesse declarado.** Validar com documentos reais do cliente antes de fazer qualquer promessa de acurácia.
- **"Redação verdadeira" exige disciplina.** Cobrir com retângulo não basta; é preciso remover do content stream e limpar metadados, com verificação. Falhas aqui são vazamentos graves.
- **Soberania "geográfica" não é soberania plena.** OCI/AWS/Azure no Brasil ainda seguem jurisdição estrangeira (Cloud Act). Para o cliente-alvo mais sensível (governo, dados sigilosos), on-premise ou nuvem de governo/soberana é o mais defensável.
- **Números de mercado variam por fonte** e são projeções (verbos "expected", "forecast") — tratar como estimativas, não fatos consolidados; citar sempre a fonte específica.
- **Cronograma de 6 meses é factível com Claude Code**, mas o cofre de reversibilidade e a validação em documentos reais são os itens de maior risco de prazo. Reservar folga para segurança e testes.