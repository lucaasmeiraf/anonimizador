"""Instrumento do gate de usabilidade: um revisor acha a tarja que faltou?

É a única pergunta da Fase 1 que não se responde com software, e é a que
sustenta todo o resto. D1 escolheu o `bert-lenerbr` — precisão 0.685 — com o
argumento de que falso positivo é barato (o revisor vê a tarja sobrando e
descarta) e falso negativo é caro (o revisor precisa notar uma **ausência**).
A segunda metade do argumento é uma afirmação sobre comportamento humano, e
nunca foi medida. Se ela for falsa, a tela é decorativa e o vazamento residual
chega ao documento publicado com a assinatura de alguém que acreditou ter
revisado.

Este script **não mede** — ele prepara a medição e apura o resultado. Quem
mede são pessoas, e é por isso que o instrumento existe: sem gabarito guardado
e sem cegamento, o que sobra é impressão.

## As duas metades

    python eval/gate_usabilidade.py --preparar --n 4
    python eval/gate_usabilidade.py --apurar eval/gate-usabilidade/registro.csv

## Por que o vazamento é plantado assim

Não é plantado: é **colhido**. O script gera documentos candidatos com o mesmo
gerador do corpus, roda o pipeline real, e fica só com os documentos em que um
`PERSON` do gabarito tem cobertura zero — ou seja, em que o modelo que
embarcamos de fato erra. Nada é simulado, nenhum caminho de produção é
alterado, e o que o revisor vê na tela é exatamente o que qualquer usuário
veria com aquele documento.

A alternativa — suprimir um span na aplicação para "criar" a falha — teria
exigido um gancho de teste no caminho do gate, que é justamente onde este
sistema não pode ter gancho nenhum.

## Cegamento

Os PDFs saem com nome neutro (`documento-01.pdf`) e **sem** o `.json` do
gabarito ao lado. O gabarito vai para um arquivo separado, fora da pasta que o
participante abre. Um participante que descubra que existe exatamente uma
tarja faltante já está contaminado: ele passa a procurar, e procurar é
justamente o que queremos saber se ele faz por conta.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import statistics
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parent))

from align import alinhar  # noqa: E402
from diagnostico_person import NAO_DETECTADO, ROTULO_ERRADO, classificar  # noqa: E402
from generate_corpus import gerar_corpus  # noqa: E402

from anonimizador import config  # noqa: E402
from anonimizador.layout import build_text_map  # noqa: E402
from anonimizador.pipeline import DetectionPipeline  # noqa: E402
from anonimizador.spans import spans_para_redigir  # noqa: E402

VAZOU = (ROTULO_ERRADO, NAO_DETECTADO)

COLUNAS_REGISTRO = (
    "participante",
    "documento",
    "achou",
    "segundos",
    "falsos_alarmes",
    "observacao",
)

NOME_GABARITO = "gabarito-NAO-ABRIR-ANTES.json"


# --------------------------------------------------------------------------
# Preparação
# --------------------------------------------------------------------------
def colher(pasta_candidatos: Path, ner: str) -> list[dict]:
    """Documentos em que o modelo real deixa **exatamente um** nome sem tarja.

    Exatamente um, e não "pelo menos um", por uma razão de medição: com dois
    alvos, "achou" deixa de ser binário e a taxa passa a depender de qual dos
    dois a pessoa encontrou primeiro. Com um alvo, achou ou não achou.
    """
    indice = json.loads((pasta_candidatos / "index.json").read_text(encoding="utf-8"))
    pipeline = DetectionPipeline(ner_config=ner)
    colhidos: list[dict] = []

    for i, item in enumerate(indice["documentos"], 1):
        doc_id = item["doc_id"]
        meta = json.loads(
            (pasta_candidatos / f"{doc_id}.json").read_text(encoding="utf-8")
        )
        caminho = pasta_candidatos / meta["pdf"]

        doc = fitz.open(str(caminho))
        try:
            tm = build_text_map(doc)
            paginas = doc.page_count
        finally:
            doc.close()

        todos = pipeline.analyze(tm.text)
        redigidos = spans_para_redigir(todos)
        alinhamento = alinhar(meta["source_text"], tm.text, meta["gold"])

        vazados = []
        for gold in alinhamento.gold:
            if gold.label != "PERSON":
                continue
            classe, rotulos = classificar(gold, todos, redigidos)
            if classe in VAZOU:
                vazados.append(
                    {
                        "valor": gold.value,
                        "classe": classe,
                        "rotulo_dado": "+".join(rotulos) if rotulos else "(nenhum)",
                        "pagina": tm.page_of(gold.start) + 1,
                    }
                )

        if len(vazados) == 1:
            colhidos.append(
                {
                    "origem": doc_id,
                    "genero": meta["genero"],
                    "caminho": caminho,
                    "paginas": paginas,
                    "tarjas_propostas": len(redigidos),
                    "vazamento": vazados[0],
                }
            )
        print(
            f"  {i}/{len(indice['documentos'])} candidatos, "
            f"{len(colhidos)} aproveitáveis",
            end="\r",
            flush=True,
        )

    print()
    return colhidos


def preparar(destino: Path, n: int, candidatos: int, semente: int, ner: str) -> int:
    destino.mkdir(parents=True, exist_ok=True)
    pasta_docs = destino / "documentos"
    pasta_docs.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        pasta_candidatos = Path(tmp)
        print(f"gerando {candidatos} candidatos (semente {semente})...", flush=True)
        gerar_corpus(pasta_candidatos, candidatos, semente)
        print(f"rodando o pipeline real ({ner}) para colher os que vazam...", flush=True)
        colhidos = colher(pasta_candidatos, ner)

        escolhidos = colhidos[:n]
        gabarito = []
        for k, item in enumerate(escolhidos, 1):
            nome_neutro = f"documento-{k:02d}.pdf"
            shutil.copy2(item["caminho"], pasta_docs / nome_neutro)
            gabarito.append(
                {
                    "documento": nome_neutro,
                    "origem": item["origem"],
                    "genero": item["genero"],
                    "paginas": item["paginas"],
                    "tarjas_propostas": item["tarjas_propostas"],
                    "nome_sem_tarja": item["vazamento"]["valor"],
                    "pagina_do_vazamento": item["vazamento"]["pagina"],
                    "classe": item["vazamento"]["classe"],
                    "rotulo_que_o_detector_deu": item["vazamento"]["rotulo_dado"],
                }
            )

    (destino / NOME_GABARITO).write_text(
        json.dumps(
            {
                "ner": ner,
                "semente": semente,
                "candidatos_gerados": candidatos,
                "aproveitaveis": len(colhidos),
                "documentos": gabarito,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    caminho_csv = destino / "registro.csv"
    if caminho_csv.exists():
        print(f"registro.csv já existe, preservado: {caminho_csv}")
    else:
        with caminho_csv.open("w", encoding="utf-8", newline="") as fh:
            escritor = csv.writer(fh)
            escritor.writerow(COLUNAS_REGISTRO)
        print(f"registro em branco escrito em {caminho_csv}")

    print()
    print(f"  candidatos gerados      : {candidatos}")
    print(f"  com exatamente 1 vazamento: {len(colhidos)}")
    print(f"  separados para a sessão  : {len(escolhidos)}")
    print(f"  documentos em            : {pasta_docs}")
    print(f"  gabarito em              : {destino / NOME_GABARITO}")

    if len(escolhidos) < n:
        # Falhar alto: uma sessão com menos documentos que o planejado produz
        # um número que ninguém consegue interpretar depois.
        print()
        print(
            f"  ATENÇÃO: pedidos {n}, obtidos {len(escolhidos)}. "
            f"Aumente --candidatos ou troque --seed."
        )
        return 1
    return 0


# --------------------------------------------------------------------------
# Apuração
# --------------------------------------------------------------------------
def _sim(valor: str) -> bool:
    return valor.strip().lower() in {"sim", "s", "1", "true", "x"}


def apurar(linhas: list[dict]) -> dict:
    """Resume o registro preenchido. Lógica pura, para poder ser testada."""
    validas = [l for l in linhas if (l.get("participante") or "").strip()]
    if not validas:
        return {"sessoes": 0}

    achou = [l for l in validas if _sim(l.get("achou", ""))]
    tempos = []
    for l in achou:
        try:
            tempos.append(float(str(l.get("segundos", "")).replace(",", ".")))
        except ValueError:
            pass

    falsos = 0
    for l in validas:
        try:
            falsos += int(str(l.get("falsos_alarmes", "0") or 0))
        except ValueError:
            pass

    por_documento: dict[str, dict] = {}
    for l in validas:
        d = por_documento.setdefault(
            (l.get("documento") or "?").strip(), {"tentativas": 0, "achou": 0}
        )
        d["tentativas"] += 1
        d["achou"] += 1 if _sim(l.get("achou", "")) else 0

    participantes = {(l.get("participante") or "").strip() for l in validas}

    return {
        "sessoes": len(validas),
        "participantes": len(participantes),
        "achou": len(achou),
        "taxa": len(achou) / len(validas),
        "mediana_segundos": statistics.median(tempos) if tempos else None,
        "falsos_alarmes": falsos,
        "por_documento": por_documento,
    }


def formatar(resumo: dict) -> str:
    if not resumo.get("sessoes"):
        return "Nenhuma sessão registrada ainda."

    linhas = [
        "# Gate de usabilidade — resultado",
        "",
        f"- sessões: **{resumo['sessoes']}** ({resumo['participantes']} participantes)",
        f"- achou a tarja faltante: **{resumo['achou']}/{resumo['sessoes']}** "
        f"({resumo['taxa']:.0%})",
    ]
    if resumo["mediana_segundos"] is not None:
        linhas.append(
            f"- tempo mediano até achar: **{resumo['mediana_segundos']:.0f} s**"
        )
    linhas.append(f"- falsos alarmes somados: {resumo['falsos_alarmes']}")
    linhas += ["", "| Documento | Achou / Tentativas |", "|---|---:|"]
    for doc, d in sorted(resumo["por_documento"].items()):
        linhas.append(f"| `{doc}` | {d['achou']}/{d['tentativas']} |")

    linhas += [
        "",
        "## Como ler",
        "",
        "A taxa é a resposta do gate. Ela não tem um limiar objetivo definido "
        "em lugar nenhum — quem decide o que é aceitável é quem responde pelo "
        "produto. O que este número faz é tirar a pergunta do campo da opinião.",
        "",
        "Taxa alta sustenta **D1**: a revisão humana pega o que o modelo "
        "deixou passar, e trocar precisão por recall foi a escolha certa.",
        "",
        "Taxa baixa **não** significa que D1 esteja errada — significa que a "
        "interface ainda não entrega o que D1 pressupõe. O conserto seria de "
        "interface (o que ajuda alguém a notar uma ausência?), não de modelo.",
    ]
    return "\n".join(linhas)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preparar", action="store_true", help="monta a sessão")
    ap.add_argument("--apurar", type=Path, help="lê o registro.csv preenchido")
    ap.add_argument("--out", default=Path("eval/gate-usabilidade"), type=Path)
    ap.add_argument("--n", default=4, type=int, help="documentos para a sessão")
    # A taxa de aproveitamento é baixa **porque o modelo é bom**: medido, cerca
    # de 1 documento em 50 tem um `PERSON` com cobertura zero. Não há como
    # apressar isso sem fabricar a falha, que é justamente o que este
    # instrumento não faz. 300 candidatos rendem ~6 documentos e levam uns 20
    # minutos de CPU — é uma preparação de uma vez só, não parte do ciclo.
    ap.add_argument("--candidatos", default=300, type=int)
    ap.add_argument("--seed", default=20260901, type=int)
    ap.add_argument("--ner", default=config.NER_PADRAO)
    args = ap.parse_args()

    if args.apurar:
        with args.apurar.open(encoding="utf-8", newline="") as fh:
            linhas = list(csv.DictReader(fh))
        print(formatar(apurar(linhas)))
        return 0

    if args.preparar:
        return preparar(args.out, args.n, args.candidatos, args.seed, args.ner)

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
