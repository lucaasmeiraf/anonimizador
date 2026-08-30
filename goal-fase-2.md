# /goal — Fase 2: Reversibilidade sob chave

> Responde a uma pergunta feita em 2026-08-30: *"consigo desanonimizar na
> minha máquina um documento que a ferramenta anonimizou?"*
>
> Resposta curta: **com o que existe hoje, não — e isso é intencional.** Com o
> que esta fase propõe, sim, sob chave, e com um custo jurídico que precisa
> ser decidido antes de uma linha de código.

---

## 1. Por que hoje é impossível, e por que isso não é um defeito

O único operador implementado é `tarja`, e ele faz **redação verdadeira**:

| Etapa | O que acontece com o texto |
|---|---|
| `apply_redactions()` | sai do content stream |
| `clean_contents()` | o stream é reescrito, sem restos do operador de texto |
| `scrub()` | metadados, XMP, anexos, anotações, formulários, miniaturas |
| `save(garbage=4, incremental=False)` | a revisão anterior **não** é anexada; objetos órfãos são coletados |

Não é cifra. Não é ocultação. É **remoção**. Não existe chave que reverta, não
existe mapa guardado, não existe cópia do valor em lugar nenhum do arquivo —
e o `verifier` confere exatamente isso em dez vetores antes de liberar o
download.

> Reverter o PDF anonimizado é tão possível quanto recuperar um arquivo de um
> disco que foi sobrescrito com zeros. A informação não está escondida: ela
> não está lá.

**O que devolve o original é o original.** A ferramenta nunca modifica o
arquivo de entrada — ela escreve um arquivo novo. Se o objetivo é "voltar
atrás", a resposta operacional é guardar o original, com o controle de acesso
que ele merece.

E isso é a característica que dá valor ao produto hoje: é o que permite dizer
que o documento de saída **não é dado pessoal** (ver seção 3).

---

## 2. O que a Fase 2 propõe

Um segundo operador, `pseudonimo`, ao lado de `tarja` — nunca no lugar dele.

Em vez de apagar, substitui por um token estável e reversível **sob chave**:

```
  Mariana Aparecida Souza  ->  [PESSOA-7F3A]
  529.982.247-25           ->  [CPF-2C81]
```

E um **cofre**: um mapa token → valor, cifrado, guardado **fora do PDF**. Com
a chave, um comando local reconstrói o documento original. Sem a chave, o
token não diz nada.

O vocabulário já existe. `politica.py` declara `PSEUDONIMO` e `MASCARA` desde
a Fase 0, e `validar_perfil` os **recusa** justamente para impedir o pior modo
de falha: o usuário pedir pseudônimo, o executor não aplicar nada, e o
relatório afirmar que o documento foi anonimizado.

### Os quatro requisitos, e por que uma LLM não serve

Já registrados em `docs/05-politica-llm.md`, seção 3.1, e repetidos aqui
porque são o critério de aceite:

1. **Determinismo.** A mesma pessoa vira o mesmo token na página 1 e na
   página 80, e no processo inteiro. Amostragem de modelo não dá essa
   garantia.
2. **Reversibilidade sob chave.** O cofre é um mapa cifrado. Isso é
   criptografia, não geração.
3. **Ausência de colisão.** Duas pessoas distintas não podem receber o mesmo
   token.
4. **Não reintroduzir dado pessoal.** Peça a um modelo um nome brasileiro
   plausível e ele devolve o nome de uma pessoa real. Substituir a PII de
   alguém pela de outro alguém é o pior resultado possível, e nada no sistema
   detectaria.

`HMAC` sob chave + pools tipados atendem os quatro, são auditáveis e rodam em
microssegundos.

### O obstáculo técnico que a Fase 0 não resolveu

`tarja` só precisa **apagar** e desenhar um retângulo. `pseudonimo` precisa
**escrever texto de volta no PDF**, e isso é substancialmente mais difícil:

- o token quase nunca tem a largura do valor original — o texto ao redor
  precisa ser reposicionado, ou o token precisa caber na caixa;
- a fonte original pode estar embutida como subconjunto, sem os glifos
  necessários para os caracteres do token;
- reflow em documento de várias colunas quebra o layout, e a promessa atual é
  que **a estrutura do original não muda**.

Nenhum desses está resolvido, e é por isso que a Fase 0 travou o operador em
vez de entregá-lo pela metade.

---

## 3. A decisão que precisa vir antes do código

Esta é a parte que não é técnica, e é a mais importante.

### Documento reversível não é documento anonimizado

Sob a LGPD (Lei 13.709/2018), anonimização e pseudonimização são coisas
diferentes, com consequências diferentes:

- **Dado anonimizado** não é dado pessoal, e sai do escopo da lei — mas essa
  saída vale enquanto o processo **não puder ser revertido** com meios
  próprios ou esforços razoáveis.
- **Dado pseudonimizado** continua sendo dado pessoal. Continua exigindo base
  legal, continua sujeito a direitos do titular, continua exigindo controles
  de segurança, continua sendo comunicável em caso de incidente.

> **Confirme a leitura jurídica com quem assina.** A substância acima é o
> entendimento corrente, mas a citação de artigo por número é de memória e o
> enquadramento do caso concreto é decisão do encarregado/jurídico do cliente,
> não deste documento.

Em termos práticos: **hoje o produto entrega um arquivo que sai do escopo da
LGPD. Ligar `pseudonimo` devolve o arquivo para dentro do escopo.** Isso pode
ser exatamente o que um cliente precisa — ou pode destruir a razão pela qual
ele comprou a ferramenta.

### O cofre concentra o risco

Com `tarja`, comprometer o arquivo de saída não expõe ninguém, porque não há
nada nele. Com `pseudonimo`, o valor de segurança do sistema inteiro se
desloca para o cofre: quem tem a chave reidentifica **todo mundo, em todos os
documentos, de uma vez**.

Isso não é argumento contra fazer — é a definição do que precisa ser
protegido, e muda o que a Fase 2 tem de entregar: gestão de chave, controle
de acesso, trilha de auditoria de cada reversão, e política de retenção do
cofre. O cofre é o produto tanto quanto o PDF.

### Quando cada um faz sentido

| Situação | Operador |
|---|---|
| Publicar no Diário Oficial, responder LAI, divulgar decisão | `tarja` |
| Compartilhar com terceiro que não pode reidentificar | `tarja` |
| Treinar modelo, gerar estatística, análise interna | `tarja` |
| Fluxo interno onde alguém autorizado precisa voltar ao original | `pseudonimo` |
| Documento que circula entre setores e volta para o dono do processo | `pseudonimo` |

**Recomendação: `tarja` continua o padrão.** `pseudonimo` é opção explícita
por documento, com a consequência jurídica dita na tela no momento da
escolha — não escondida numa configuração.

---

## 4. Perguntas que esta fase precisa responder

- O cliente precisa mesmo de reversibilidade, ou precisa de **guardar o
  original com controle de acesso**? As duas resolvem "voltar atrás", e a
  segunda não tem custo jurídico nenhum.
- Quem pode reverter, e como isso é registrado? Sem trilha de auditoria da
  reversão, o cofre é um backdoor sem dono.
- Onde a chave vive? Arquivo local, HSM, Vault, senha do operador? Cada
  resposta muda o modelo de ameaça inteiro.
- O token pode ocupar o espaço do valor original **sem reflow**? Se não, a
  promessa de "a estrutura não muda" precisa ser reescrita.
- Retenção: por quanto tempo o cofre existe? Um cofre eterno é um risco
  eterno.

---

## 5. Tarefas / entregáveis

**Bloco 0 — Decisão, antes de qualquer código**
- [ ] Confirmar com o jurídico do cliente o enquadramento de dado
      pseudonimizado, por escrito.
- [ ] Decidir se reversibilidade é requisito real ou se guardar o original
      resolve.
- [ ] Definir custódia da chave e política de retenção do cofre.

**Bloco 1 — Cofre**
- [ ] `cofre.py`: mapa token → valor, cifrado em repouso, com HMAC sob chave
      para o token ser determinístico e sem colisão.
- [ ] Trilha de auditoria: quem reverteu, o quê, quando.
- [ ] Testes: determinismo entre execuções, ausência de colisão, recusa de
      reversão sem chave válida.

**Bloco 2 — Escrita de texto no PDF**
- [ ] Reposicionamento ou ajuste do token à caixa original, sem reflow.
- [ ] Tratamento de fonte embutida sem os glifos necessários.
- [ ] Critério de falha explícito: se o token não couber sem quebrar o
      layout, **falhar** em vez de entregar documento deformado.

**Bloco 3 — Habilitar o operador**
- [ ] Remover `PSEUDONIMO` de `OPERADORES_NAO_IMPLEMENTADOS` só depois que os
      Blocos 1 e 2 estiverem verdes.
- [ ] Na interface: consequência jurídica dita no momento da escolha.
- [ ] `verifier` adaptado — com `pseudonimo` o valor original **não deve**
      estar no PDF, mas o token deve; é uma verificação diferente.

**Bloco 4 — Reversão**
- [ ] Comando local `desanonimizar --in doc.pdf --cofre x.vault --chave ...`.
- [ ] Roda sem rede, como todo o resto.

---

## 6. Critérios de aceite

- Nenhum operador não implementado é oferecido pela interface.
- Token determinístico entre execuções e entre documentos, sem colisão.
- Reversão só com a chave; falha alto e claro sem ela.
- Toda reversão registrada em trilha de auditoria.
- O documento pseudonimizado **não contém** o valor original em nenhum dos
  dez vetores do `verifier`.
- A tela diz, no momento da escolha, que o documento continua sendo dado
  pessoal.
- `tarja` continua sendo o padrão, e continua produzindo documento
  irreversível.

---

## 7. Fora de escopo

Reverter documento produzido pelas Fases 0 e 1. Não há como: aqueles arquivos
foram gerados com `tarja`, o texto não existe neles, e nenhum cofre foi
criado. Qualquer promessa em contrário seria falsa.
