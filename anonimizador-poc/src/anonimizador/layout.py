"""Ponte entre offsets de caractere e coordenadas na página.

Este é o item de maior risco técnico da Fase 0, e o que estava faltando no
goal original. Os reconhecedores trabalham sobre uma string; o
``apply_redactions`` do PyMuPDF trabalha sobre retângulos. Alguém precisa
traduzir um no outro, e a tradução tem de ser exata — uma tarja deslocada
por um caractere é um vazamento.

**Por que não usar ``page.search_for()``**, que seria o caminho óbvio:

* o texto de um PDF é fatiado em *spans* por mudança de fonte, corpo ou cor;
  um nome em negrito no meio da frase vira três spans e a busca literal falha;
* hifenização, ligaduras e espaçamento por kerning fazem a string extraída
  divergir da string desenhada;
* a mesma string aparecendo cinco vezes devolve cinco retângulos sem dizer
  qual corresponde a qual ocorrência detectada;
* e, sobretudo, a busca reintroduz o valor sensível como *string de consulta*,
  o que é exatamente o acoplamento que queremos evitar.

A abordagem aqui é inversa e determinística: percorremos ``rawdict``
(blocos → linhas → spans → caracteres) **uma vez**, construindo ao mesmo tempo
(a) o texto que será analisado e (b) um vetor de bounding boxes indexado pelo
mesmo offset. Qualquer span ``(início, fim)`` vira retângulo por consulta
direta no vetor, sem busca e sem ambiguidade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF

# Separadores sintéticos que inserimos entre spans/linhas/blocos. Ocupam
# posição no texto (para que os offsets fechem) mas não têm caixa própria.
_SEM_CAIXA = None

# Distância horizontal, em pontos, a partir da qual assumimos que há um espaço
# entre dois spans que o PDF não codificou explicitamente.
_LIMIAR_ESPACO = 1.0

# Tolerância vertical para considerar dois caracteres na mesma linha visual.
_TOLERANCIA_LINHA = 2.0


@dataclass
class TextMap:
    """Texto de um documento com a caixa de cada caractere."""

    text: str = ""
    _boxes: list[Optional[tuple[float, float, float, float]]] = field(default_factory=list)
    _pages: list[int] = field(default_factory=list)
    page_offsets: list[tuple[int, int]] = field(default_factory=list)  # (início, fim) por página

    def __len__(self) -> int:
        return len(self.text)

    def page_of(self, pos: int) -> int:
        return self._pages[pos]

    def rects_for(self, start: int, end: int) -> list[tuple[int, fitz.Rect]]:
        """Converte ``[start, end)`` em retângulos, um por linha visual.

        Um span que atravessa uma quebra de linha (nome no fim de uma linha,
        sobrenome no início da seguinte) devolve dois retângulos — tarjar o
        envoltório único apagaria o texto inocente entre eles.
        """
        if start < 0 or end > len(self.text) or start >= end:
            return []

        grupos: list[tuple[int, list[tuple[float, float, float, float]]]] = []
        for i in range(start, end):
            caixa = self._boxes[i]
            if caixa is None:
                continue
            pagina = self._pages[i]
            if grupos and grupos[-1][0] == pagina:
                anterior = grupos[-1][1][-1]
                mesma_linha = (
                    abs(caixa[1] - anterior[1]) <= _TOLERANCIA_LINHA
                    and abs(caixa[3] - anterior[3]) <= _TOLERANCIA_LINHA
                )
                if mesma_linha:
                    grupos[-1][1].append(caixa)
                    continue
            grupos.append((pagina, [caixa]))

        saida = []
        for pagina, caixas in grupos:
            x0 = min(c[0] for c in caixas)
            y0 = min(c[1] for c in caixas)
            x1 = max(c[2] for c in caixas)
            y1 = max(c[3] for c in caixas)
            saida.append((pagina, fitz.Rect(x0, y0, x1, y1)))
        return saida

    # -- construção --------------------------------------------------------
    def _append(self, ch: str, box, pagina: int) -> None:
        self.text += ch
        self._boxes.append(box)
        self._pages.append(pagina)


def build_text_map(doc: "fitz.Document") -> TextMap:
    """Percorre o documento inteiro produzindo texto + caixas alinhados."""
    tm = TextMap()

    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        inicio_pagina = len(tm.text)
        raw = page.get_text("rawdict")

        primeiro_bloco = True
        for bloco in raw.get("blocks", []):
            if bloco.get("type") != 0:  # 0 = texto; 1 = imagem
                continue
            if not primeiro_bloco:
                tm._append("\n", _SEM_CAIXA, pno)
            primeiro_bloco = False

            primeira_linha = True
            for linha in bloco.get("lines", []):
                if not primeira_linha:
                    tm._append("\n", _SEM_CAIXA, pno)
                primeira_linha = False

                fim_span_anterior: Optional[float] = None
                for span in linha.get("spans", []):
                    chars = span.get("chars", [])
                    if not chars:
                        continue

                    # Espaço implícito entre spans: o PDF pode posicionar as
                    # palavras sem codificar o caractere de espaço.
                    if fim_span_anterior is not None:
                        gap = chars[0]["bbox"][0] - fim_span_anterior
                        if gap > _LIMIAR_ESPACO and not tm.text.endswith(" "):
                            tm._append(" ", _SEM_CAIXA, pno)

                    for c in chars:
                        tm._append(c["c"], tuple(c["bbox"]), pno)

                    fim_span_anterior = chars[-1]["bbox"][2]

        tm._append("\n", _SEM_CAIXA, pno)
        tm.page_offsets.append((inicio_pagina, len(tm.text)))

    return tm


def build_text_map_from_path(caminho: str) -> tuple["fitz.Document", TextMap]:
    doc = fitz.open(caminho)
    return doc, build_text_map(doc)
