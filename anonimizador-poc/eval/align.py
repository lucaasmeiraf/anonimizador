"""Projeção do gabarito no texto extraído do PDF.

O gabarito nasce sobre o texto **fonte** (o que o gerador escreveu). A
detecção roda sobre o texto **extraído** (o que o PyMuPDF lê de volta do PDF).
Os dois são quase iguais, mas não idênticos: espaçamento entre spans, quebras
de bloco e caracteres implícitos divergem. Comparar métricas sem alinhar os
dois seria medir a divergência de extração, não a qualidade da detecção.

O alinhamento usa ``difflib.SequenceMatcher``: os trechos iguais dão o mapa de
offsets, e cada span do gabarito é projetado por ele. Quando a projeção não
bate (a substring projetada difere do valor esperado), caímos numa busca local
pelo valor; e quando nem isso funciona, o span é contabilizado como **defeito
de corpus** e excluído das métricas — em vez de virar silenciosamente um falso
negativo e sujar o número do detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class GoldSpan:
    label: str
    value: str
    start: int
    end: int


@dataclass
class AlignmentResult:
    gold: list[GoldSpan]
    defeitos: list[dict]

    @property
    def taxa_defeito(self) -> float:
        total = len(self.gold) + len(self.defeitos)
        return len(self.defeitos) / total if total else 0.0


def construir_mapa(fonte: str, extraido: str) -> list[int]:
    """Mapa posição-na-fonte -> posição-no-extraído (-1 quando não há par)."""
    mapa = [-1] * (len(fonte) + 1)
    sm = SequenceMatcher(None, fonte, extraido, autojunk=False)
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            mapa[i + k] = j + k
    return mapa


def _projetar(mapa: list[int], pos: int, fim: int) -> int:
    """Primeira posição mapeada a partir de ``pos`` (varre até ``fim``)."""
    for p in range(pos, min(fim, len(mapa))):
        if mapa[p] >= 0:
            return mapa[p]
    return -1


def alinhar(fonte: str, extraido: str, gold: list[dict]) -> AlignmentResult:
    """Projeta cada span do gabarito para os offsets do texto extraído."""
    mapa = construir_mapa(fonte, extraido)
    projetados: list[GoldSpan] = []
    defeitos: list[dict] = []

    for g in gold:
        valor = g["value"]
        inicio = _projetar(mapa, g["start"], g["end"])

        # Caminho normal: o início mapeia e a substring bate.
        if inicio >= 0 and extraido[inicio:inicio + len(valor)] == valor:
            projetados.append(GoldSpan(g["label"], valor, inicio, inicio + len(valor)))
            continue

        # Fallback: busca local em torno da posição projetada. Cobre o caso em
        # que a extração inseriu ou removeu um espaço dentro do valor.
        ancora = inicio if inicio >= 0 else g["start"]
        janela_ini = max(0, ancora - 200)
        janela_fim = min(len(extraido), ancora + len(valor) + 200)
        achado = extraido.find(valor, janela_ini, janela_fim)
        if achado < 0:
            achado = extraido.find(valor)  # última tentativa: documento inteiro

        if achado >= 0:
            projetados.append(GoldSpan(g["label"], valor, achado, achado + len(valor)))
        else:
            defeitos.append(
                {
                    "label": g["label"],
                    "value": valor,
                    "motivo": "valor do gabarito não localizado no texto extraído",
                }
            )

    return AlignmentResult(gold=projetados, defeitos=defeitos)
