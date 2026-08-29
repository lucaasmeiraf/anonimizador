"""Harness de avaliação da Fase 0.

Roda o corpus inteiro em cada configuração de NER, mede detecção e latência,
executa a redação + verificação, avalia os decision gates do goal e escreve
``report.md``.

O relatório é o entregável da fase. Ele não diz "funcionou": diz qual
configuração passou em qual gate, com que latência e com que risco residual —
que é o que permite decidir a Fase 1 sem chutar.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parent))

from align import alinhar  # noqa: E402
from metrics import Contagem, Resultado, acumular, tabela_markdown  # noqa: E402

from anonimizador import config  # noqa: E402
from anonimizador.layout import build_text_map  # noqa: E402
from anonimizador.pdf_redactor import redact_document  # noqa: E402
from anonimizador.pipeline import DetectionPipeline  # noqa: E402
from anonimizador.spans import spans_para_redigir  # noqa: E402
from anonimizador.verifier import verify  # noqa: E402

GATE_ESTRUTURADO = 0.95
GATE_PERSON = 0.80
ENTIDADES_GATE_ESTRITO = ["CPF", "CNPJ"]


@dataclass
class ResultadoConfig:
    nome: str
    descricao: str
    resultado: Resultado
    erros: list[str] = field(default_factory=list)


def carregar_corpus(pasta: Path) -> list[dict]:
    indice = json.loads((pasta / "index.json").read_text(encoding="utf-8"))
    docs = []
    for item in indice["documentos"]:
        meta = json.loads((pasta / f"{item['doc_id']}.json").read_text(encoding="utf-8"))
        meta["caminho_pdf"] = pasta / meta["pdf"]
        docs.append(meta)
    return docs


def avaliar_config(
    nome: str,
    docs: list[dict],
    pasta_saida: Path,
    redigir: bool,
) -> tuple[ResultadoConfig, list[dict]]:
    cfg = config.NER_CONFIGS[nome]
    print(f"\n=== configuração de NER: {nome} — {cfg.descricao}", flush=True)

    pasta_saida.mkdir(parents=True, exist_ok=True)

    pipeline = DetectionPipeline(ner_config=nome)
    res = Resultado()
    erros: list[str] = []
    verificacoes: list[dict] = []

    for i, meta in enumerate(docs, 1):
        doc = fitz.open(str(meta["caminho_pdf"]))
        try:
            tm = build_text_map(doc)
            spans, dt = pipeline.analyze_timed(tm.text)

            alinhamento = alinhar(meta["source_text"], tm.text, meta["gold"])
            res.defeitos_corpus += len(alinhamento.defeitos)
            acumular(res, alinhamento.gold, spans)

            res.docs += 1
            res.paginas += doc.page_count
            res.segundos += dt

            if redigir:
                saida = pasta_saida / f"{meta['doc_id']}.redigido.pdf"
                rr = redact_document(doc, tm, spans_para_redigir(spans), saida)
                relatorio = verify(saida, rr.valores)
                verificacoes.append(
                    {
                        "doc_id": meta["doc_id"],
                        "spans": rr.spans_redigidos,
                        "retangulos": rr.retangulos,
                        "sem_retangulo": rr.spans_sem_retangulo,
                        "ok": relatorio.ok,
                        "leaks": [str(x) for x in relatorio.leaks],
                    }
                )
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{meta['doc_id']}: {type(exc).__name__}: {exc}")
        finally:
            doc.close()

        if i % 10 == 0:
            print(f"  {i}/{len(docs)} documentos", flush=True)

    return ResultadoConfig(nome, cfg.descricao, res, erros), verificacoes


def _gate(valor: float, alvo: float) -> str:
    return f"{valor:.3f} {'✅' if valor >= alvo else '❌'} (alvo {alvo:.2f})"


def montar_relatorio(
    resultados: list[ResultadoConfig],
    verificacoes: dict[str, list[dict]],
    corpus: dict,
    duracao: float,
) -> str:
    L: list[str] = []
    a = L.append

    a("# Fase 0 — Relatório de Avaliação")
    a("")
    a(f"Gerado em {time.strftime('%Y-%m-%d %H:%M:%S')} · duração total {duracao:.1f}s")
    a("")
    a("## Corpus")
    a("")
    a(f"- documentos: **{corpus['n']}** (semente {corpus['semente']}, reprodutível)")
    a(f"- entidades no gabarito: **{corpus['entidades_total']}**")
    a(f"- por gênero: {corpus['generos']}")
    a("")
    a("> Corpus 100% sintético. Identificadores com checksum válido, sem vínculo com")
    a("> pessoa real. Nenhum documento real foi usado nesta fase.")
    a("")

    # ---- decision gates --------------------------------------------------
    a("## Decision gates")
    a("")
    a("| Configuração de NER | CPF (F1 estrito) | CNPJ (F1 estrito) | PERSON (F1 relaxado) | PERSON (F1 estrito) |")
    a("|---|---|---|---|---|")
    for rc in resultados:
        e, r = rc.resultado.estrito, rc.resultado.relaxado
        cpf = e.get("CPF", Contagem()).f1
        cnpj = e.get("CNPJ", Contagem()).f1
        pes_rel = r.get("PERSON", Contagem()).f1
        pes_est = e.get("PERSON", Contagem()).f1
        a(f"| `{rc.nome}` | {_gate(cpf, GATE_ESTRUTURADO)} | {_gate(cnpj, GATE_ESTRUTURADO)} "
          f"| {_gate(pes_rel, GATE_PERSON)} | {pes_est:.3f} |")
    a("")

    # ---- risco residual e latência --------------------------------------
    a("## Cobertura e latência")
    a("")
    a("Cobertura em caracteres é agnóstica de tipo: mede a fração dos caracteres de")
    a("PII do gabarito que ficou sob **alguma** tarja. É o indicador de risco de")
    a("vazamento — errar o rótulo não vaza, deixar de tarjar vaza.")
    a("")
    a("| Configuração | Cobertura de chars | s/página | s/documento | Docs | Erros |")
    a("|---|---:|---:|---:|---:|---:|")
    for rc in resultados:
        r = rc.resultado
        a(f"| `{rc.nome}` | {r.cobertura_chars:.3f} | {r.seg_por_pagina:.3f} | "
          f"{r.seg_por_doc:.3f} | {r.docs} | {len(rc.erros)} |")
    a("")

    # ---- verificação pós-redação ----------------------------------------
    a("## Verificação pós-redação")
    a("")
    a("Dez vetores checados por documento: texto (PyMuPDF e pdfplumber), anotações,")
    a("AcroForm, anexos, sumário, metadados, XMP, streams descomprimidos e bytes")
    a("brutos. Um único vazamento reprova a fase.")
    a("")
    a("| Configuração | Documentos | Sem vazamento | Spans sem retângulo |")
    a("|---|---:|---:|---:|")
    for rc in resultados:
        v = verificacoes.get(rc.nome, [])
        ok = sum(1 for x in v if x["ok"])
        sem_rect = sum(len(x["sem_retangulo"]) for x in v)
        marca = "✅" if v and ok == len(v) else ("❌" if v else "—")
        a(f"| `{rc.nome}` | {len(v)} | {ok}/{len(v)} {marca} | {sem_rect} |")
    a("")
    for rc in resultados:
        falhos = [x for x in verificacoes.get(rc.nome, []) if not x["ok"]]
        if falhos:
            a(f"**Vazamentos em `{rc.nome}`:**")
            a("")
            for x in falhos[:20]:
                a(f"- `{x['doc_id']}`: " + "; ".join(x["leaks"][:5]))
            a("")

    # ---- detalhamento ----------------------------------------------------
    a("## Detalhamento por entidade")
    a("")
    for rc in resultados:
        a(f"### `{rc.nome}` — {rc.descricao}")
        a("")
        a(tabela_markdown(rc.resultado.estrito, "Estrito (tipo + fronteiras exatas)"))
        a("")
        a(tabela_markdown(rc.resultado.relaxado, "Relaxado (mesmo tipo, sobreposição > 0)"))
        a("")
        if rc.resultado.defeitos_corpus:
            a(f"> {rc.resultado.defeitos_corpus} spans do gabarito não puderam ser")
            a("> projetados no texto extraído e foram excluídos das métricas")
            a("> (defeito de corpus, não erro do detector).")
            a("")
        if rc.erros:
            a("**Erros de execução:**")
            a("")
            for e in rc.erros[:10]:
                a(f"- {e}")
            a("")

    # ---- recomendação ----------------------------------------------------
    a("## Recomendação para a Fase 1")
    a("")
    melhor = max(
        resultados,
        key=lambda rc: rc.resultado.relaxado.get("PERSON", Contagem()).f1,
    )
    f1p = melhor.resultado.relaxado.get("PERSON", Contagem()).f1
    a(f"Melhor `PERSON` (F1 relaxado): **`{melhor.nome}`** com {f1p:.3f}.")
    a("")
    if f1p >= GATE_PERSON:
        a(f"O gate de PERSON foi atingido por `{melhor.nome}`. Levar essa configuração")
        a("para a Fase 1 e concentrar o esforço na camada de revisão humana.")
    else:
        a("**Nenhuma configuração atingiu o gate de PERSON (0,80).** Isso é um")
        a("resultado de decisão, não uma falha do PoC: indica que a Fase 1 precisa de")
        a("fine-tuning próprio sobre documentos do domínio do cliente, e que a revisão")
        a("humana antes de aplicar as tarjas deixa de ser desejável e passa a ser")
        a("obrigatória.")
    a("")
    a("As entidades com checksum são o alicerce: elas não dependem de modelo, não")
    a("degradam com o domínio do documento e não têm custo de latência relevante.")
    a("")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description="Avaliação da Fase 0")
    ap.add_argument("--datasets", default="eval/datasets", type=Path)
    ap.add_argument("--report", default="eval/report.md", type=Path)
    ap.add_argument("--out", default="out", type=Path)
    ap.add_argument("--ner", nargs="*", default=None,
                    help="configurações a avaliar (padrão: todas)")
    ap.add_argument("--sem-redacao", action="store_true",
                    help="pula redação e verificação (só mede detecção)")
    args = ap.parse_args()

    if not (args.datasets / "index.json").exists():
        raise SystemExit(
            f"corpus não encontrado em {args.datasets}. Rode o alvo `corpus` primeiro."
        )

    docs = carregar_corpus(args.datasets)
    corpus = json.loads((args.datasets / "index.json").read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)

    nomes = args.ner or list(config.NER_CONFIGS)
    t0 = time.perf_counter()
    resultados, verificacoes = [], {}
    for nome in nomes:
        rc, v = avaliar_config(nome, docs, args.out / nome, not args.sem_redacao)
        resultados.append(rc)
        verificacoes[nome] = v
    duracao = time.perf_counter() - t0

    relatorio = montar_relatorio(resultados, verificacoes, corpus, duracao)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(relatorio, encoding="utf-8")

    print(f"\nrelatório escrito em {args.report}\n")
    print(relatorio.split("## Cobertura")[0])


if __name__ == "__main__":
    main()
