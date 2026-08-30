"""Diagnóstico dos vazamentos de PERSON: falta de detecção ou rótulo errado?

O ``report.md`` diz *quantos* documentos vazaram e *quais* nomes. Não diz
**por quê**, e as duas causas possíveis têm conserto completamente diferente:

* **não detectado** — nenhum span cobre o nome. É limite do modelo. Conserto:
  trocar de checkpoint, fine-tuning, ou unir duas configurações.
* **rótulo errado** — o nome *foi* detectado, mas como ``LOCATION`` ou
  ``ORGANIZATION``, que ``ENTIDADES_REDIGIDAS`` preserva de propósito. Não é
  limite do modelo: é interação entre erro de classificação e política de
  preservação. Conserto: reconhecedor de contexto (``Sr.``, ``Sra.``,
  ``portador(a) do``), que é barato e determinístico.

A seção 6 do ``06-resultados-fase-0.md`` levantou a segunda hipótese a partir
de um caso só (``Casa Grande``). Este script mede em quantos ela vale.

Critério de vazamento usado aqui: uma entidade ``PERSON`` do gabarito com
**cobertura zero** por spans que a política manda tarjar. Cobertura zero é o
que faz o valor sobreviver inteiro no PDF e ser encontrado pelo ``verifier`` —
se qualquer pedaço fosse tarjado, a string contígua não sobreviveria.

    python eval/diagnostico_person.py --datasets eval/datasets
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parent))

from align import GoldSpan, alinhar  # noqa: E402

from anonimizador import config  # noqa: E402
from anonimizador.layout import build_text_map  # noqa: E402
from anonimizador.pipeline import DetectionPipeline  # noqa: E402
from anonimizador.spans import Span, spans_para_redigir  # noqa: E402

# Classificações possíveis de um PERSON do gabarito.
COBERTO = "coberto"
PARCIAL = "coberto em parte"
ROTULO_ERRADO = "vazou — rótulo errado"
NAO_DETECTADO = "vazou — nenhum span"

ORDEM = (COBERTO, PARCIAL, ROTULO_ERRADO, NAO_DETECTADO)

# Tratamentos que o gerador de corpus prefixa ao nome. Aparecem no `value` do
# gabarito, então um detector que marca só o nome deixa o título descoberto —
# e isso nao expoe ninguem.
TITULOS = {"sr", "sra", "dr", "dra", "srta", "exmo", "exma"}


def _chars_cobertos(gold: GoldSpan, spans: list[Span]) -> set[int]:
    """Quais caracteres do gabarito caem dentro de algum span."""
    coberto: set[int] = set()
    for s in spans:
        ini, fim = max(s.start, gold.start), min(s.end, gold.end)
        if ini < fim:
            coberto.update(range(ini, fim))
    return coberto


def descoberto(gold: GoldSpan, spans: list[Span], texto: str) -> str:
    """O trecho do gabarito que ficou **sem** tarja, como texto.

    Distingue os dois tipos de cobertura parcial, que tem gravidade oposta:
    sobrar so um titulo ("Sr.", "Dra.") e artefato de fronteira do gabarito e
    nao vaza nada; sobrar um sobrenome e vazamento parcial de verdade.
    """
    cobertos = _chars_cobertos(gold, spans)
    faltando = [i for i in range(gold.start, gold.end) if i not in cobertos]
    if not faltando:
        return ""
    return "".join(texto[i] for i in faltando).strip()


def _rotulos_sobrepostos(gold: GoldSpan, spans: list[Span]) -> list[str]:
    """Rótulos de *todos* os spans detectados que tocam o gabarito."""
    return sorted(
        {s.entity for s in spans if s.start < gold.end and gold.start < s.end}
    )


def classificar(
    gold: GoldSpan, todos: list[Span], redigidos: list[Span]
) -> tuple[str, list[str]]:
    """Devolve (classificação, rótulos que o detector deu ao trecho)."""
    cobertos = len(_chars_cobertos(gold, redigidos))
    rotulos = _rotulos_sobrepostos(gold, todos)

    if cobertos >= (gold.end - gold.start):
        return COBERTO, rotulos
    if cobertos > 0:
        # Cobertura parcial não vaza a string inteira, mas vaza um pedaço —
        # é diagnóstico de fronteira, não de classe.
        return PARCIAL, rotulos
    # Cobertura zero: o valor sobrevive. A causa é o que interessa.
    if rotulos:
        return ROTULO_ERRADO, rotulos
    return NAO_DETECTADO, rotulos


def carregar_corpus(pasta: Path) -> list[dict]:
    indice = json.loads((pasta / "index.json").read_text(encoding="utf-8"))
    docs = []
    for item in indice["documentos"]:
        meta = json.loads(
            (pasta / f"{item['doc_id']}.json").read_text(encoding="utf-8")
        )
        meta["caminho_pdf"] = pasta / meta["pdf"]
        docs.append(meta)
    return docs


def diagnosticar(nome: str, docs: list[dict]) -> dict:
    cfg = config.NER_CONFIGS[nome]
    print(f"\n=== {nome} — {cfg.descricao}", flush=True)

    pipeline = DetectionPipeline(ner_config=nome)
    classes: Counter[str] = Counter()
    rotulos_do_vazamento: Counter[str] = Counter()
    casos: list[dict] = []
    parciais: list[dict] = []
    docs_que_vazam: set[str] = set()

    for i, meta in enumerate(docs, 1):
        doc = fitz.open(str(meta["caminho_pdf"]))
        try:
            tm = build_text_map(doc)
            todos = pipeline.analyze(tm.text)
            redigidos = spans_para_redigir(todos)
            alinhamento = alinhar(meta["source_text"], tm.text, meta["gold"])

            for gold in alinhamento.gold:
                if gold.label != "PERSON":
                    continue
                classe, rotulos = classificar(gold, todos, redigidos)
                classes[classe] += 1
                if classe == PARCIAL:
                    parciais.append(
                        {
                            "doc_id": meta["doc_id"],
                            "valor": gold.value,
                            "sobra": descoberto(gold, redigidos, tm.text),
                        }
                    )
                if classe in (ROTULO_ERRADO, NAO_DETECTADO):
                    docs_que_vazam.add(meta["doc_id"])
                    chave = "+".join(rotulos) if rotulos else "(nenhum)"
                    rotulos_do_vazamento[chave] += 1
                    casos.append(
                        {
                            "doc_id": meta["doc_id"],
                            "valor": gold.value,
                            "classe": classe,
                            "rotulos": chave,
                        }
                    )
        finally:
            doc.close()
        print(f"  [{i:>3}/{len(docs)}] {meta['doc_id']}", flush=True)

    return {
        "nome": nome,
        "descricao": cfg.descricao,
        "classes": classes,
        "rotulos": rotulos_do_vazamento,
        "casos": casos,
        "parciais": parciais,
        "docs_que_vazam": sorted(docs_que_vazam),
        "total_docs": len(docs),
    }


def relatorio(resultados: list[dict]) -> str:
    linhas: list[str] = []
    a = linhas.append

    a("# Diagnóstico dos vazamentos de PERSON")
    a("")
    a("Gerado por `eval/diagnostico_person.py`. Responde a uma pergunta só:")
    a("quando um nome vaza, o detector **não o viu** ou o viu e deu o")
    a("**rótulo errado**? A distinção decide o conserto.")
    a("")
    a("Um `PERSON` do gabarito conta como vazado quando tem **cobertura zero**")
    a("por spans que a política manda tarjar — é a condição que faz o valor")
    a("sobreviver inteiro e ser achado pelo `verifier`.")
    a("")

    a("## Classificação de todos os `PERSON` do gabarito")
    a("")
    a("| Configuração | " + " | ".join(ORDEM) + " |")
    a("|---" + "|---:" * len(ORDEM) + "|")
    for r in resultados:
        celulas = [str(r["classes"].get(c, 0)) for c in ORDEM]
        a(f"| `{r['nome']}` | " + " | ".join(celulas) + " |")
    a("")

    a("## Causa dos vazamentos")
    a("")
    for r in resultados:
        total = sum(r["rotulos"].values())
        a(f"### `{r['nome']}`")
        a("")
        if not total:
            a("Nenhum vazamento de `PERSON`.")
            a("")
            continue
        a(
            f"{total} entidades vazadas em "
            f"{len(r['docs_que_vazam'])}/{r['total_docs']} documentos."
        )
        a("")
        a("| Rótulo que o detector deu ao trecho | Casos | % |")
        a("|---|---:|---:|")
        for rotulo, n in r["rotulos"].most_common():
            a(f"| `{rotulo}` | {n} | {100 * n / total:.0f}% |")
        a("")
        a("Casos:")
        a("")
        por_doc: dict[str, list[str]] = defaultdict(list)
        for c in r["casos"]:
            por_doc[c["doc_id"]].append(f"{c['valor']!r} → `{c['rotulos']}`")
        for doc_id in sorted(por_doc):
            a(f"- `{doc_id}`: " + "; ".join(por_doc[doc_id]))
        a("")

    a("## Cobertura parcial: o que sobrou sem tarja")
    a("")
    a("Cobertura parcial não faz o valor inteiro sobreviver, então não é")
    a("vazamento pelo critério acima. Mas *o que* sobrou decide a gravidade:")
    a("um título (`Sr.`, `Dra.`) é artefato de fronteira do gabarito e não")
    a("expõe nada; um sobrenome descoberto é exposição parcial de verdade.")
    a("")
    for r in resultados:
        parciais = r["parciais"]
        a(f"### `{r['nome']}`")
        a("")
        if not parciais:
            a("Nenhuma cobertura parcial.")
            a("")
            continue
        titulos = Counter()
        for c in parciais:
            titulos[c["sobra"]] += 1
        so_titulo = sum(
            n for s, n in titulos.items() if s.rstrip(".").lower() in TITULOS
        )
        a(f"{len(parciais)} casos. **{so_titulo}** deixaram só um título")
        a(f"descoberto ({100 * so_titulo / len(parciais):.0f}%); ")
        a(f"**{len(parciais) - so_titulo}** deixaram outra coisa.")
        a("")
        a("| Trecho que ficou sem tarja | Casos |")
        a("|---|---:|")
        for sobra, n in titulos.most_common(15):
            marca = " (título)" if sobra.rstrip(".").lower() in TITULOS else ""
            a(f"| `{sobra}`{marca} | {n} |")
        a("")

    a("## Como ler")
    a("")
    a("`(nenhum)` significa que o modelo não produziu span algum sobre o nome:")
    a("limite de detecção, que só se resolve trocando ou combinando modelo.")
    a("")
    a("Qualquer outro rótulo — `LOCATION`, `ORGANIZATION` — significa que o")
    a("trecho **foi detectado** e a política o preservou de propósito. Esse é")
    a("o caso que um reconhecedor de contexto resolve sem trocar de modelo.")
    a("")
    return "\n".join(linhas)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--datasets", default="eval/datasets")
    p.add_argument("--out", default="eval/diagnostico-person.md")
    p.add_argument(
        "--ner",
        action="append",
        help="configuração de NER (repetível). Padrão: os dois transformers.",
    )
    p.add_argument("--limit", type=int, default=0, help="só os N primeiros docs")
    args = p.parse_args()

    nomes = args.ner or ["bert-lenerbr", "bertimbau-harem"]
    docs = carregar_corpus(Path(args.datasets))
    if args.limit:
        docs = docs[: args.limit]

    resultados = [diagnosticar(nome, docs) for nome in nomes]

    texto = relatorio(resultados)
    Path(args.out).write_text(texto, encoding="utf-8")
    print("\n" + texto)
    print(f"\nrelatório escrito em {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
