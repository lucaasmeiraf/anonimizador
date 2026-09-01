# Gate de usabilidade — roteiro da sessão

> A pergunta: **um revisor encontra a tarja que faltou?**
>
> Ela sustenta D1. A escolha do `bert-lenerbr` (precisão 0.685) foi feita com
> o argumento de que falso positivo é barato e falso negativo é caro *porque o
> humano corrige o primeiro e caça o segundo*. A segunda metade nunca foi
> medida. Este roteiro mede.

---

## Antes: preparar

```
make gate-usabilidade          # ou: .\run.ps1 gate-usabilidade
```

Gera 300 documentos candidatos, roda o pipeline real e separa os que de fato
vazam um nome. **Leva uns 20 minutos de CPU**, uma vez só.

O aproveitamento é baixo — cerca de 1 documento em 50 — e isso não é defeito
do instrumento: é a medida de quão bom o `bert-lenerbr` é. Não há como
apressar sem fabricar a falha, e fabricar a falha é exatamente o que este
instrumento não faz, porque aí o que a pessoa veria na tela não seria o que
um usuário veria. Se o comando avisar que obteve menos documentos do que o
pedido, aumente `--candidatos`.

Produz:

```
eval/gate-usabilidade/
  documentos/documento-01.pdf ...   <- o que o participante abre
  gabarito-NAO-ABRIR-ANTES.json     <- onde está a tarja faltante
  registro.csv                      <- planilha em branco
```

**Não abra o gabarito na frente de ninguém que vá participar.** E não deixe a
pasta `eval/gate-usabilidade` visível na tela compartilhada.

---

## Quem participa

**3 a 5 pessoas**, e nenhuma delas pode ser você nem quem escreveu o código.
Não é formalidade: quem sabe que existe uma tarja faltante procura por ela, e
o que queremos medir é justamente se a pessoa procura sem saber.

O perfil ideal é quem faria essa revisão no trabalho real — alguém de
jurídico, de protocolo, de RH. Não precisa entender de anonimização; precisa
entender de documento.

---

## O que dizer

Leia isto, literalmente:

> "Esta ferramenta marca automaticamente os dados pessoais de um documento
> para que ele possa ser publicado. A marcação nem sempre está certa. Sua
> tarefa é revisar a proposta e deixá-la do jeito que você assinaria embaixo.
> Quando terminar, me avise. Pode pensar em voz alta se quiser."

Depois: abra `http://127.0.0.1:8000`, envie um dos documentos, e saia do
caminho.

## O que **não** dizer

- ❌ "Veja se está faltando alguma tarja."
- ❌ "Tem um erro nesse documento."
- ❌ "Repare nas tabelas."
- ❌ Qualquer coisa que indique que existe **um** alvo, ou onde ele está.

Dizer qualquer uma dessas frases invalida a sessão. Se escapar, anote na
coluna `observacao` e descarte a linha.

## Durante

- **Não ajude.** Silêncio é dado. Se a pessoa perguntar "está certo assim?",
  devolva: "o que você acha?".
- **Cronometre** do momento em que o documento aparece na tela até a pessoa
  dizer que terminou.
- Anote quantas vezes ela marcou como faltante algo que **não** era o alvo —
  são os falsos alarmes, e eles importam tanto quanto o acerto: uma tela que
  faz a pessoa desconfiar de tudo não é uma tela que funciona.

## Depois de cada documento

Só então, e só se a pessoa não achou, você pode mostrar onde estava. Registre
antes de contar — a reação contamina a memória do que aconteceu.

---

## Registro

Preencha `registro.csv`, uma linha por documento por participante:

| coluna | o que é |
|---|---|
| `participante` | identificador anônimo (`P1`, `P2`) — **nunca o nome** |
| `documento` | `documento-01.pdf` |
| `achou` | `sim` / `nao` |
| `segundos` | tempo até achar; se não achou, o tempo total gasto |
| `falsos_alarmes` | quantos trechos ela apontou que não eram o alvo |
| `observacao` | o que chamou atenção; frases ditas em voz alta |

Identificador anônimo não é burocracia: este arquivo fica no repositório, e
nome de pessoa num arquivo versionado é exatamente o que a ferramenta existe
para evitar.

---

## Apurar

```
make gate-usabilidade-apurar    # ou: .\run.ps1 gate-usabilidade-apurar
```

Sai a taxa de acerto, o tempo mediano e a contagem por documento.

**Não existe limiar objetivo definido em lugar nenhum**, e é deliberado: quem
decide o que é aceitável é quem responde pelo produto. O que o número faz é
tirar a pergunta do campo da opinião.

- **Taxa alta** sustenta D1: a revisão humana pega o que o modelo deixou
  passar, e trocar precisão por recall foi a escolha certa.
- **Taxa baixa** não derruba D1 — mostra que a interface ainda não entrega o
  que D1 pressupõe. O conserto seria de interface (o que ajuda alguém a notar
  uma *ausência*?), não de modelo. Trocar para um modelo de precisão maior
  pioraria o problema: menos tarjas propostas, mais nomes descobertos.

Seja qual for o resultado, ele vai para `goal-fase-1.md` com a data e o número
de participantes. Um gate medido com 3 pessoas é um gate medido com 3 pessoas,
e o registro precisa dizer isso.
