# 03 — Configuração

Todos os pontos de ajuste do sistema, onde ficam, o que fazem e o que acontece
se forem mexidos. Referência para quem for calibrar a ferramenta para um
cliente específico.

---

## 1. Mapa dos lugares de configuração

| Onde | O que controla | Muda com que frequência |
|---|---|---|
| Variáveis de ambiente | escolha de NER, dispositivo, limiar | por execução |
| `src/anonimizador/config.py` | entidades, precedência, limiares padrão | por cliente |
| `src/anonimizador/recognizers/*.py` | regex e palavras-âncora | por domínio documental |
| `docker/Dockerfile` | versões, modelos gravados na imagem | raramente |
| `docker-compose.yml` | volumes, isolamento de rede | por ambiente |
| `docker-compose.gpu.yml` | uso de GPU | por hardware |

---

## 2. Variáveis de ambiente

Aplicadas sem rebuild. As três primeiras são as que se usa no dia a dia.

| Variável | Padrão | Valores | Efeito |
|---|---|---|---|
| `ANON_NER` | `bert-lenerbr` | `spacy`, `bert-lenerbr`, `bertimbau-harem` | configuração de NER padrão |
| `ANON_DEVICE` | `cpu` | `cpu`, `cuda` | dispositivo do transformer |
| `ANON_SCORE_THRESHOLD` | `0.35` | `0.0`–`1.0` | limiar mínimo de confiança |
| `HF_HUB_OFFLINE` | `1` | `0`, `1` | impede o Hugging Face de tentar rede |
| `TRANSFORMERS_OFFLINE` | `1` | `0`, `1` | idem |
| `HF_HOME` | `/opt/models/hf` | caminho | onde os modelos ficam na imagem |
| `PYTHONPATH` | `/app/src` | caminho | resolução do pacote |

Uso:

```powershell
docker compose run --rm -e ANON_NER=spacy -e ANON_SCORE_THRESHOLD=0.5 `
    cli analyze --in /app/data/doc.pdf
```

> **Não altere `HF_HUB_OFFLINE` nem `TRANSFORMERS_OFFLINE` em produção.** Elas
> são a segunda linha de defesa da restrição de soberania — a primeira é o
> `network_mode: none`. Só faz sentido desligá-las durante o build.

---

## 3. `config.py` — o arquivo que se ajusta por cliente

### 3.1 Faixas de entidade

```python
ENTIDADES_COM_GATE   = ("CPF", "CNPJ", "PERSON")
ENTIDADES_MEDIDAS    = ("RG", "CEP", "TELEFONE", "EMAIL", "CNS",
                        "PIS_PASEP", "PROCESSO_CNJ", "CNH", "TITULO_ELEITOR")
ENTIDADES_BEST_EFFORT = ("ENDERECO", "ORGANIZATION", "LOCATION", "DATE_TIME")
```

Estas três tuplas definem o que é **medido**. A quarta define o que é
**tarjado**:

```python
ENTIDADES_REDIGIDAS = ENTIDADES_COM_GATE + ENTIDADES_MEDIDAS + ("ENDERECO",)
```

`ORGANIZATION`, `LOCATION` e `DATE_TIME` são medidas mas **não tarjadas** por
padrão. A razão é prática: em documento público, o nome do órgão e a data do
ato costumam ser exatamente o que precisa continuar legível. Tarjá-los deixaria
o documento inútil.

**Quando mudar:** documentos de saúde e RH frequentemente precisam da data de
nascimento tarjada — nesse caso, acrescente `DATE_TIME` a `ENTIDADES_REDIGIDAS`
e aceite que datas de assinatura e de vigência também serão cobertas. Não há
como separar as duas sem um classificador de papel semântico, que está fora do
escopo da Fase 0.

### 3.2 Limiar de score

```python
SCORE_THRESHOLD = 0.35
```

O valor 0,35 não é arbitrário. Ele fica:

- **abaixo** de 1,0, o score de tudo que teve checksum confirmado;
- **abaixo** de 0,4, o piso que o enriquecedor de contexto do Presidio aplica
  quando encontra uma palavra-âncora;
- **acima** de 0,2 e 0,25, os scores nus de CNH e RG.

O efeito é que padrões numéricos crus sem nenhuma âncora textual são
descartados, e são justamente eles a principal fonte de falso positivo.

| Se você... | Aumente para ~0,5 | Diminua para ~0,2 |
|---|---|---|
| efeito | menos falso positivo, mais falso negativo | mais cobertura, muito mais ruído |
| quando | documento com muita numeração administrativa | revisão humana obrigatória e o custo do vazamento é altíssimo |

> Mexer no limiar invalida a comparação com execuções anteriores. Sempre
> registre o valor usado junto com as métricas.

### 3.3 Precedência entre entidades

```python
PRECEDENCIA = (
    "CPF", "CNPJ", "PROCESSO_CNJ", "CNS", "PIS_PASEP", "TITULO_ELEITOR",
    "CNH", "RG", "CEP", "EMAIL", "TELEFONE",
    "PERSON", "ENDERECO", "ORGANIZATION", "LOCATION", "DATE_TIME",
)
```

Quando dois reconhecedores disputam o mesmo trecho, vence quem estiver mais à
esquerda. A ordem não é estética: **entidades com checksum vêm primeiro**
porque um dígito verificador que fecha é evidência matemática, e um span de NER
é evidência estatística. Um CPF dentro de um trecho que o NER marcou como
`PERSON` deve ser tarjado como CPF.

Critério de desempate completo, em `spans.resolver_sobreposicoes`: precedência
→ span mais longo → score maior → posição. As duas últimas garantem
determinismo.

### 3.4 Configurações de NER

```python
NER_CONFIGS = {
    "spacy":           pt_core_news_lg,
    "bert-lenerbr":    pierreguillou/ner-bert-base-cased-pt-lenerbr,
    "bertimbau-harem": marquesafonso/bertimbau-large-ner-selective,
}
```

Acrescentar uma quarta configuração exige três passos: entrada no dicionário,
`RUN` de download no `Dockerfile`, e rebuild. O `label_map` traduz os rótulos
do modelo para o vocabulário do Presidio; rótulos não mapeados são
silenciosamente descartados — é assim que `LEGISLACAO`, `JURISPRUDENCIA` e
`VALOR` ficam de fora, por não serem dado pessoal.

---

## 4. Reconhecedores — o ajuste mais frequente por cliente

Cada arquivo em `recognizers/` tem a mesma estrutura: `PATTERNS`, `CONTEXT`,
`build()`.

```python
PATTERNS = [
    Pattern("CPF mascarado", r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", 0.6),
    Pattern("CPF cru",       r"(?<!\d)\d{11}(?!\d)",           0.3),
]
CONTEXT = ["cpf", "cadastro de pessoa física", "portador do cpf", ...]
```

### 4.1 Palavras-âncora

`CONTEXT` é onde se calibra para o vocabulário do cliente. O Presidio compara
os **lemas** do spaCy, então "portador" cobre "portadora" e "portadores".

Exemplo real: um tribunal que escreve "inscrito no Cadastro de Pessoas Físicas
sob o nº" em vez de "CPF nº" precisa dessa expressão em `CONTEXT` para que o
CPF cru (score 0,3) suba acima do limiar. Sem isso, só o CPF mascarado é
detectado.

**Como descobrir quais âncoras faltam:** rode `analyze` num documento do
cliente com `ANON_SCORE_THRESHOLD=0.1` e compare com a execução no limiar
padrão. O que aparece só no limiar baixo é candidato a âncora nova.

### 4.2 Scores dos padrões

| Faixa | Significado | Exemplos |
|---|---|---|
| 0,7–0,8 | formato rígido, quase sem ambiguidade | CNPJ mascarado, processo CNJ, e-mail |
| 0,5–0,6 | formato com máscara reconhecível | CPF mascarado, telefone com DDD, CEP |
| 0,3–0,4 | forma crua, precisa de checksum ou contexto | CPF cru, CNPJ cru |
| 0,1–0,25 | ambíguo por natureza, **exige** contexto | CNH, RG cru, CEP cru |

A CNH é o caso mais delicado: 11 dígitos, forma idêntica à do CPF. O score 0,2
a deixa deliberadamente abaixo do limiar, e ela só aparece quando há âncora
("habilitação", "Detran", "condutor"). Sem essa disciplina, todo CPF do
documento viraria também um falso positivo de CNH.

### 4.3 Acrescentar um reconhecedor

1. Crie `recognizers/matricula.py` no molde dos existentes.
2. Se houver dígito verificador, ponha a função em `validators.py` e passe-a
   para o `ChecksumRecognizer`; se não houver, passe `None`.
3. Registre o módulo em `recognizers/__init__.py`, tupla `MODULOS`.
4. Acrescente a entidade em `config.ENTIDADES_MEDIDAS` e em
   `config.PRECEDENCIA`, na posição certa (com checksum, junto dos outros
   com checksum).
5. Se ela deve ser tarjada, confirme que entra em `ENTIDADES_REDIGIDAS`.
6. Escreva o teste em `tests/`, com casos válidos, inválidos **e falsos
   positivos plausíveis**.

O passo 6 não é opcional. Um reconhecedor sem teste de falso positivo é um
gerador de ruído esperando para acontecer.

---

## 5. Configuração do container

### 5.1 Argumentos de build

| Argumento | Padrão | Para quê |
|---|---|---|
| `TORCH_INDEX` | `https://download.pytorch.org/whl/cpu` | índice do torch; troque por `.../cu124` para GPU |
| `TORCH_VERSION` | `2.9.1` | versão do torch |

```powershell
docker build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124 `
             -f docker/Dockerfile -t anonimizador-poc:fase0-gpu .
```

A diferença de tamanho é relevante: torch CPU tem ~200 MB; torch CUDA passa de
2,5 GB. Por isso o padrão é CPU e a GPU é override explícito.

### 5.2 Isolamento de rede

```yaml
x-base: &base
  network_mode: none
```

Todos os serviços de execução herdam isso. **É a garantia central de soberania
do projeto** e não deve ser removida. Se um serviço precisar de rede algum dia
(uma API HTTP, por exemplo), crie um serviço separado com rede e mantenha o de
processamento isolado — nunca relaxe este.

Para conferir:

```powershell
docker compose run --rm dev python -c "import socket; socket.create_connection(('1.1.1.1',53),2)"
# esperado: falha imediata de resolução ou de rota
```

### 5.3 Volumes

| Host | Container | Modo | Conteúdo |
|---|---|---|---|
| `./src` | `/app/src` | leitura | código — bind mount permite editar sem rebuild |
| `./eval` | `/app/eval` | escrita | corpus e relatório |
| `./tests` | `/app/tests` | leitura | testes |
| `./data` | `/app/data` | escrita | **documentos de entrada** |
| `./out` | `/app/out` | escrita | documentos redigidos |

`./data` e `./out` estão no `.gitignore`. Em produção, monte-os em
armazenamento com a política de retenção do cliente — nunca deixe documento
processado acumulando no volume por padrão.

### 5.4 GPU

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml build eval
docker compose -f docker-compose.yml -f docker-compose.gpu.yml run --rm eval
```

Requer Docker Desktop com backend WSL2 e driver NVIDIA no host. O
`network_mode: none` continua valendo — GPU e isolamento de rede são
independentes.

---

## 6. Parâmetros internos que raramente se mexe

Documentados porque, quando o problema aparece, é aqui que ele está.

### `ner.TransformersNerRecognizer`

| Parâmetro | Padrão | O que faz |
|---|---|---|
| `janela` | 1200 | tamanho da janela em caracteres |
| `sobreposicao` | 200 | sobreposição entre janelas |
| `score_minimo` | 0.5 | corte de confiança do próprio modelo |

Os checkpoints são BERT, com teto de 512 tokens. Sem janelamento, o pipeline do
Hugging Face **trunca** — e a partir da página 2 nada seria detectado, um
vazamento silencioso. A sobreposição de 200 caracteres garante que uma entidade
na fronteira apareça inteira na janela seguinte.

**Sintoma de janela pequena demais:** entidades longas cortadas ao meio.
**Sintoma de sobreposição pequena demais:** entidades sumindo em posições
regulares ao longo do documento.

### `layout`

| Constante | Padrão | O que faz |
|---|---|---|
| `_LIMIAR_ESPACO` | 1.0 pt | distância a partir da qual se assume espaço não codificado entre spans |
| `_TOLERANCIA_LINHA` | 2.0 pt | tolerância vertical para considerar dois caracteres na mesma linha |

**Sintoma de `_LIMIAR_ESPACO` alto demais:** palavras coladas no texto
extraído, quebrando regex com `\b`.
**Sintoma de `_TOLERANCIA_LINHA` baixa demais:** um retângulo por caractere em
vez de um por linha — tarja visualmente picotada.

### `verifier`

| Constante | Padrão | O que faz |
|---|---|---|
| `TAMANHO_MINIMO` | 5 | valores mais curtos não são verificados |

Valores curtos colidem por acaso com bytes de estrutura do PDF e tornariam a
verificação ruidosa a ponto de ser inútil.

### `generate_corpus`

| Constante | Padrão | O que faz |
|---|---|---|
| `LARGURA_LINHA` | 92 | caracteres por linha, **quebrando só entre segmentos** |
| `FONTE` / `CORPO` | `helv` / 9 | fonte base-14, sem arquivo externo |
| semente | 20260829 | reprodutibilidade do corpus |

A quebra nunca ocorre dentro de um segmento rotulado. Se ocorresse, o valor
atravessaria a linha, o reconhecedor não teria como acertá-lo, e o eval estaria
medindo o gerador em vez do detector.

---

## 7. Perfis sugeridos

Ponto de partida para calibrar por cliente. Todos precisam ser validados com
documentos reais do cliente antes de ir a produção.

### Máxima cobertura — dado sensível, revisão humana obrigatória

```
ANON_SCORE_THRESHOLD=0.20
ANON_NER=bertimbau-harem
ENTIDADES_REDIGIDAS += DATE_TIME, ORGANIZATION, LOCATION
```

Assume-se que um humano revisa antes de aplicar. Muito falso positivo é
aceitável; falso negativo, não.

### Equilibrado — documento jurídico e administrativo

```
ANON_SCORE_THRESHOLD=0.35
ANON_NER=bert-lenerbr
```

O padrão do projeto.

### Alta precisão — lote grande, revisão por amostragem

```
ANON_SCORE_THRESHOLD=0.50
ANON_NER=bert-lenerbr
```

Menos ruído, mais risco de falso negativo. **Só é defensável se os documentos
não contiverem dado sensível** ou se houver revisão por amostragem com critério
estatístico definido.
