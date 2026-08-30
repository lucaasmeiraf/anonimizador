"""Modelo de span e resolução de sobreposição — lógica pura.

Separado de ``pipeline.py`` de propósito: aqui não há Presidio, spaCy nem
torch. É a parte do sistema que decide *qual* detecção prevalece, e é a que
mais precisa ser testável sem carregar 2 GB de modelo.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional

from . import config


@dataclass(frozen=True)
class Span:
    """Um trecho detectado, em offsets de caractere do texto analisado."""

    start: int
    end: int
    entity: str
    score: float
    # Por que este trecho foi apontado, quando a evidencia nao e o checksum.
    # `None` = caminho normal. `"checksum_invalido"` = forma correta com
    # digito verificador errado, aceito por mascara ou ancora.
    #
    # Existe para a interface poder dizer ao revisor o que ela sabe e o que
    # ela supoe. Sem essa distincao um palpite chega na tela com a mesma cara
    # de uma certeza matematica, e o revisor perde a unica informacao que
    # torna a revisao dele util.
    nota: str | None = None

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end

    def text_of(self, texto: str) -> str:
        return texto[self.start:self.end]


def _normalizar(texto: str) -> str:
    """Minúsculas e sem acento, para comparar âncoras sem depender da grafia."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower()


def _tem_ancora(texto: str, span: Span, termos: Iterable[str]) -> bool:
    """A âncora aparece na janela imediatamente anterior ao span?"""
    inicio = max(0, span.start - config.JANELA_ANCORA)
    anterior = _normalizar(texto[inicio:span.start])
    return any(t in anterior for t in termos)


def desambiguar_por_ancora(spans: list[Span], texto: str) -> list[Span]:
    """Resolve identificadores de mesma forma pela palavra-âncora do texto.

    Só age sobre spans **exatamente coincidentes** de `AMBIGUAS_MESMA_FORMA`,
    isto é, o caso em que o mesmo número satisfez mais de um checksum. Fora
    dessa situação a precedência estática continua valendo.

    A regra é conservadora de propósito: se nenhuma âncora aparece, ou se mais
    de uma aparece (o número vem depois de "CPF ... PIS ..." na mesma janela),
    não decidimos nada e deixamos a precedência resolver. Adivinhar no empate
    trocaria um rótulo errado determinístico por um rótulo errado imprevisível.
    """
    grupos: dict[tuple[int, int], list[Span]] = defaultdict(list)
    for s in spans:
        if s.entity in config.AMBIGUAS_MESMA_FORMA:
            grupos[(s.start, s.end)].append(s)

    descartar: set[tuple[int, int, str]] = set()
    for grupo in grupos.values():
        if len(grupo) < 2:
            continue
        ancorados = [
            s for s in grupo
            if _tem_ancora(texto, s, config.ANCORAS_DESAMBIGUACAO.get(s.entity, ()))
        ]
        if len(ancorados) != 1:
            continue
        vencedor = ancorados[0]
        for s in grupo:
            if s.entity != vencedor.entity:
                descartar.add((s.start, s.end, s.entity))

    if not descartar:
        return spans
    return [s for s in spans if (s.start, s.end, s.entity) not in descartar]


def resolver_sobreposicoes(spans: list[Span], texto: Optional[str] = None) -> list[Span]:
    """Seleção gulosa de spans disjuntos.

    Quando ``texto`` é fornecido, roda antes a desambiguação por âncora — ela
    conhece o texto, a precedência não. Sem ``texto``, o comportamento é o
    anterior, o que mantém os testes puros de precedência válidos.

    Critério de desempate, em ordem: precedência da entidade (checksum antes
    de NER), span mais longo, score maior, posição. Determinístico — dois eval
    runs sobre o mesmo corpus produzem exatamente o mesmo resultado, então uma
    variação de métrica é sempre variação de código.
    """
    if texto is not None:
        spans = desambiguar_por_ancora(spans, texto)
    ordenados = sorted(
        spans,
        key=lambda s: (
            -config.peso_precedencia(s.entity),
            -s.length,
            -s.score,
            s.start,
        ),
    )
    aceitos: list[Span] = []
    for cand in ordenados:
        if any(cand.overlaps(a) for a in aceitos):
            continue
        aceitos.append(cand)
    return sorted(aceitos, key=lambda s: (s.start, s.end))


def spans_para_redigir(spans: Iterable[Span]) -> list[Span]:
    """Filtra as entidades que efetivamente vão para a tarja."""
    return [s for s in spans if s.entity in config.ENTIDADES_REDIGIDAS]
