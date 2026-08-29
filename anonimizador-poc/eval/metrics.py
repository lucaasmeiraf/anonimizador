"""Métricas da Fase 0.

Três leituras da mesma detecção, porque uma só engana:

* **Estrito** — tipo e fronteiras idênticos ao gabarito. É a métrica dura, e a
  única honesta para identificadores estruturados: um CPF detectado "quase
  todo" não serve para nada.
* **Relaxado** — mesmo tipo e ao menos um caractere em comum. É a métrica justa
  para ``PERSON``: "Dr. João da Silva Jr." tem fronteira legitimamente
  discutível, e reprovar por causa do "Dr." mediria etiquetagem, não detecção.
* **Cobertura em caracteres, agnóstica de tipo** — fração dos caracteres de PII
  do gabarito cobertos por *qualquer* span detectado. É a que corresponde ao
  risco real: rotular um CPF como RG e tarjá-lo não vaza nada; deixar de
  tarjá-lo, sim.

Os gates do goal usam estrito para CPF/CNPJ e relaxado para PERSON. A
cobertura é reportada como indicador de risco residual.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Contagem:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precisao(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precisao, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def suporte(self) -> int:
        return self.tp + self.fn


@dataclass
class Resultado:
    estrito: dict[str, Contagem] = field(default_factory=lambda: defaultdict(Contagem))
    relaxado: dict[str, Contagem] = field(default_factory=lambda: defaultdict(Contagem))
    chars_gold: int = 0
    chars_cobertos: int = 0
    docs: int = 0
    paginas: int = 0
    segundos: float = 0.0
    defeitos_corpus: int = 0

    @property
    def cobertura_chars(self) -> float:
        return self.chars_cobertos / self.chars_gold if self.chars_gold else 0.0

    @property
    def seg_por_pagina(self) -> float:
        return self.segundos / self.paginas if self.paginas else 0.0

    @property
    def seg_por_doc(self) -> float:
        return self.segundos / self.docs if self.docs else 0.0


def _sobrepoe(a_ini: int, a_fim: int, b_ini: int, b_fim: int) -> bool:
    return a_ini < b_fim and b_ini < a_fim


def acumular(
    resultado: Resultado,
    gold: list,          # list[GoldSpan]
    preditos: list,      # list[Span]
) -> None:
    """Soma as contagens de um documento ao resultado agregado."""

    # ---- estrito: casamento exato de (tipo, início, fim) ------------------
    chaves_gold = {(g.label, g.start, g.end) for g in gold}
    chaves_pred = {(p.entity, p.start, p.end) for p in preditos}

    for chave in chaves_gold & chaves_pred:
        resultado.estrito[chave[0]].tp += 1
    for chave in chaves_gold - chaves_pred:
        resultado.estrito[chave[0]].fn += 1
    for chave in chaves_pred - chaves_gold:
        resultado.estrito[chave[0]].fp += 1

    # ---- relaxado: mesmo tipo, sobreposição > 0, casamento 1:1 -----------
    gold_livre = list(range(len(gold)))
    pred_usado: set[int] = set()

    for gi in list(gold_livre):
        g = gold[gi]
        casou = None
        for pi, p in enumerate(preditos):
            if pi in pred_usado or p.entity != g.label:
                continue
            if _sobrepoe(g.start, g.end, p.start, p.end):
                casou = pi
                break
        if casou is not None:
            pred_usado.add(casou)
            resultado.relaxado[g.label].tp += 1
            gold_livre.remove(gi)

    for gi in gold_livre:
        resultado.relaxado[gold[gi].label].fn += 1
    for pi, p in enumerate(preditos):
        if pi not in pred_usado:
            resultado.relaxado[p.entity].fp += 1

    # ---- cobertura em caracteres, agnóstica de tipo ----------------------
    cobertos: set[int] = set()
    for p in preditos:
        cobertos.update(range(p.start, p.end))
    for g in gold:
        alvo = set(range(g.start, g.end))
        resultado.chars_gold += len(alvo)
        resultado.chars_cobertos += len(alvo & cobertos)


def tabela_markdown(contagens: dict[str, Contagem], titulo: str) -> str:
    linhas = [
        f"**{titulo}**",
        "",
        "| Entidade | Suporte | Precisão | Recall | F1 | FP |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for ent in sorted(contagens, key=lambda e: -contagens[e].suporte):
        c = contagens[ent]
        linhas.append(
            f"| {ent} | {c.suporte} | {c.precisao:.3f} | {c.recall:.3f} | {c.f1:.3f} | {c.fp} |"
        )
    return "\n".join(linhas)


def macro_f1(contagens: dict[str, Contagem], entidades: list[str]) -> float:
    vals = [contagens[e].f1 for e in entidades if e in contagens and contagens[e].suporte]
    return sum(vals) / len(vals) if vals else 0.0
