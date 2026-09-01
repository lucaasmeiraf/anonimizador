"""CLI da Fase 0 — ponto de entrada único do container.

    python -m anonimizador.cli analyze  --in doc.pdf
    python -m anonimizador.cli redact   --in doc.pdf --out doc.redigido.pdf
    python -m anonimizador.cli corpus   --out eval/datasets --n 50
    python -m anonimizador.cli eval     --datasets eval/datasets
    python -m anonimizador.cli offline-proof
"""

from __future__ import annotations

import argparse
import logging
import runpy
import socket
import sys
from pathlib import Path

from . import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("anonimizador")

RAIZ = Path(__file__).resolve().parents[2]
DIR_EVAL = RAIZ / "eval"


def _preparar_eval_path() -> None:
    if str(DIR_EVAL) not in sys.path:
        sys.path.insert(0, str(DIR_EVAL))


# --------------------------------------------------------------------------
# analyze
# --------------------------------------------------------------------------
def cmd_analyze(args: argparse.Namespace) -> int:
    import fitz

    from .layout import build_text_map
    from .pipeline import DetectionPipeline

    pipeline = DetectionPipeline(ner_config=args.ner)
    doc = fitz.open(args.entrada)
    try:
        tm = build_text_map(doc)
        spans, dt = pipeline.analyze_timed(tm.text)
    finally:
        doc.close()

    print(f"\n{args.entrada}")
    print(f"  {len(tm.text)} caracteres, {doc.page_count} páginas, {dt:.2f}s\n")
    print(f"  {'ENTIDADE':<16} {'SCORE':>6}  {'POS':>12}  VALOR")
    print("  " + "-" * 78)
    for s in spans:
        rects = tm.rects_for(s.start, s.end)
        marca = "" if rects else "  <-- SEM RETÂNGULO"
        print(f"  {s.entity:<16} {s.score:>6.2f}  {s.start:>5}:{s.end:<6} "
              f"{s.text_of(tm.text)!r}{marca}")
    print(f"\n  total: {len(spans)} entidades\n")
    return 0


# --------------------------------------------------------------------------
# redact
# --------------------------------------------------------------------------
def cmd_redact(args: argparse.Namespace) -> int:
    import fitz

    from .layout import build_text_map
    from .pdf_redactor import redact_document
    from .pipeline import DetectionPipeline
    from .spans import spans_para_redigir
    from .verifier import verify

    pipeline = DetectionPipeline(ner_config=args.ner)
    doc = fitz.open(args.entrada)
    try:
        tm = build_text_map(doc)
        spans = pipeline.analyze(tm.text)
        alvo = spans_para_redigir(spans)
        Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
        res = redact_document(doc, tm, alvo, args.saida)
    finally:
        doc.close()

    print(f"\n  detectadas    : {len(spans)} entidades")
    print(f"  redigidas     : {res.spans_redigidos} ({res.retangulos} retângulos)")
    print(f"  saneamento    : {res.saneamento}")
    if res.spans_sem_retangulo:
        # Entidade e posição, não o texto: isto é sinal de bug de mapeamento,
        # e quem for investigar tem o documento de origem em mãos. Ver
        # `SpanSemRetangulo`.
        amostra = ", ".join(str(s) for s in res.spans_sem_retangulo[:5])
        print(f"  SEM RETÂNGULO : {len(res.spans_sem_retangulo)} -> {amostra}")

    relatorio = verify(args.saida, res.valores)
    print(f"\n  verificação   : {len(relatorio.vetores_executados)} vetores, "
          f"{relatorio.valores_checados} valores")
    if relatorio.ok:
        print("  RESULTADO     : nenhum vazamento detectado\n")
        return 0

    print(f"  RESULTADO     : {len(relatorio.leaks)} VAZAMENTO(S)\n")
    for leak in relatorio.leaks[:30]:
        print(f"    - {leak}")
    print()
    return 1


# --------------------------------------------------------------------------
# corpus / eval — delegam para os scripts em eval/
# --------------------------------------------------------------------------
def cmd_corpus(args: argparse.Namespace) -> int:
    _preparar_eval_path()
    sys.argv = ["generate_corpus.py", "--out", str(args.saida), "--n", str(args.n),
                "--seed", str(args.seed)]
    runpy.run_path(str(DIR_EVAL / "generate_corpus.py"), run_name="__main__")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    _preparar_eval_path()
    argv = ["run_eval.py", "--datasets", str(args.datasets), "--report", str(args.report),
            "--out", str(args.saida)]
    if args.ner:
        argv += ["--ner", *args.ner]
    if args.sem_redacao:
        argv.append("--sem-redacao")
    sys.argv = argv
    runpy.run_path(str(DIR_EVAL / "run_eval.py"), run_name="__main__")
    return 0


# --------------------------------------------------------------------------
# offline-proof
# --------------------------------------------------------------------------
class RedeBloqueada(RuntimeError):
    """Levantada quando alguma etapa tenta abrir conexão de rede."""


def _bloquear_rede() -> None:
    """Sabota o módulo ``socket`` para que qualquer egress falhe alto.

    O ``network_mode: none`` do compose já remove a interface, mas essa prova
    é *in-process* e independe do Docker: ela roda igual na máquina do
    desenvolvedor e demonstra que nenhuma biblioteca da pilha tenta falar com
    serviço externo enquanto processa o documento.
    """

    def negar(*_a, **_kw):
        raise RedeBloqueada("tentativa de conexão de rede durante o processamento")

    socket.socket.connect = negar             # type: ignore[assignment]
    socket.socket.connect_ex = negar          # type: ignore[assignment]
    socket.create_connection = negar          # type: ignore[assignment]
    socket.getaddrinfo = negar                # type: ignore[assignment]


def cmd_offline_proof(args: argparse.Namespace) -> int:
    import tempfile

    import fitz

    _preparar_eval_path()
    from generate_corpus import gerar_corpus  # type: ignore

    from .layout import build_text_map
    from .pdf_redactor import redact_document
    from .pipeline import DetectionPipeline
    from .spans import spans_para_redigir
    from .verifier import verify

    print("\n=== PROVA DE OPERAÇÃO OFFLINE ===\n")

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        print("1. gerando corpus mínimo (com rede ainda liberada)...")
        gerar_corpus(base / "ds", n=5, semente=1)

        print("2. carregando modelos (última etapa que poderia tocar a rede)...")
        pipeline = DetectionPipeline(ner_config=args.ner)
        pipeline.analyze("Aquecimento: CPF 529.982.247-25 de João da Silva.")

        print("3. BLOQUEANDO A REDE — qualquer conexão a partir daqui é erro fatal")
        _bloquear_rede()

        print("4. processando os documentos sem rede...\n")
        total_spans = vazamentos = 0
        for pdf in sorted((base / "ds").glob("*.pdf")):
            doc = fitz.open(str(pdf))
            try:
                tm = build_text_map(doc)
                spans = pipeline.analyze(tm.text)
                saida = base / f"{pdf.stem}.redigido.pdf"
                res = redact_document(doc, tm, spans_para_redigir(spans), saida)
            finally:
                doc.close()
            rel = verify(saida, res.valores)
            total_spans += res.spans_redigidos
            vazamentos += len(rel.leaks)
            print(f"   {pdf.name:<28} {res.spans_redigidos:>3} tarjas  "
                  f"{'ok' if rel.ok else 'VAZOU'}")

    print(f"\n   {total_spans} entidades redigidas, {vazamentos} vazamentos")
    print("\n=== APROVADO: pipeline completo executado sem qualquer acesso à rede ===\n")
    return 0 if vazamentos == 0 else 1


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="anonimizador", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="comando", required=True)

    def add_ner(p):
        p.add_argument("--ner", default=config.NER_PADRAO,
                       choices=list(config.NER_CONFIGS),
                       help=f"configuração de NER (padrão: {config.NER_PADRAO})")

    p = sub.add_parser("analyze", help="detecta e lista as entidades de um PDF")
    p.add_argument("--in", dest="entrada", required=True)
    add_ner(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("redact", help="redige um PDF e verifica o resultado")
    p.add_argument("--in", dest="entrada", required=True)
    p.add_argument("--out", dest="saida", required=True)
    add_ner(p)
    p.set_defaults(func=cmd_redact)

    p = sub.add_parser("corpus", help="gera o corpus sintético")
    p.add_argument("--out", dest="saida", default="eval/datasets")
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--seed", type=int, default=20260829)
    p.set_defaults(func=cmd_corpus)

    p = sub.add_parser("eval", help="roda a avaliação completa e gera o report.md")
    p.add_argument("--datasets", default="eval/datasets")
    p.add_argument("--report", default="eval/report.md")
    p.add_argument("--out", dest="saida", default="out")
    p.add_argument("--ner", nargs="*", default=None)
    p.add_argument("--sem-redacao", action="store_true")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("offline-proof", help="prova que o pipeline roda sem rede")
    add_ner(p)
    p.set_defaults(func=cmd_offline_proof)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
