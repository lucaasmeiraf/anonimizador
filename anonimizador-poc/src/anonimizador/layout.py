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

    def palavras_da_pagina(self, pagina: int) -> list[dict]:
        """Palavras de uma página, **com o offset delas no texto completo**.

        Existe para a camada de texto selecionável da interface, e o offset é
        a razão de ser: com ele, uma seleção feita no navegador vira um
        intervalo de caracteres exato neste mesmo ``text`` — o mesmo índice
        que ``rects_for`` e que os spans de detecção usam.

        A alternativa seria ``page.get_text("words")`` do PyMuPDF, que é mais
        curta e devolve as palavras numa numeração própria, sem relação com
        estes offsets. Aí seria preciso reconciliar as duas por busca textual,
        e a reconciliação erra exatamente onde mais importa: em documento com
        palavra repetida, que é o caso de um formulário.

        Uma palavra é uma sequência máxima de caracteres não-brancos que têm
        caixa. Os separadores sintéticos inseridos por ``build_text_map`` (a
        quebra de linha entre blocos, o espaço implícito entre spans) não têm
        caixa e por isso encerram a palavra naturalmente — que é o
        comportamento certo: eles não existem na página.
        """
        if not 0 <= pagina < len(self.page_offsets):
            return []

        inicio_pagina, fim_pagina = self.page_offsets[pagina]
        palavras: list[dict] = []
        atual: list[int] = []

        def fechar() -> None:
            if not atual:
                return
            caixas = [self._boxes[i] for i in atual]
            palavras.append(
                {
                    "t": "".join(self.text[i] for i in atual),
                    # Offset no texto completo — a ponte entre a seleção do
                    # navegador e a redação.
                    "i": atual[0],
                    "x0": min(c[0] for c in caixas),
                    "y0": min(c[1] for c in caixas),
                    "x1": max(c[2] for c in caixas),
                    "y1": max(c[3] for c in caixas),
                }
            )
            atual.clear()

        for i in range(inicio_pagina, min(fim_pagina, len(self.text))):
            caixa = self._boxes[i]
            if caixa is None or self.text[i].isspace():
                fechar()
                continue
            # Quebra de linha visual sem caractere de espaço entre elas:
            # sem isto, duas linhas viram uma "palavra" com caixa gigante.
            if atual:
                anterior = self._boxes[atual[-1]]
                if abs(caixa[1] - anterior[1]) > _TOLERANCIA_LINHA:
                    fechar()
            atual.append(i)
        fechar()

        return palavras

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


# --------------------------------------------------------------------------
# Recorte vertical da tarja — defeito D-01
# --------------------------------------------------------------------------
# Fração mínima da altura original que o retângulo pode ficar depois do
# recorte. É o limite que decide um conflito entre dois danos, e a escolha não
# é de estilo:
#
#   * retângulo grande demais come o texto das linhas vizinhas;
#   * retângulo pequeno demais **deixa o valor no documento**.
#
# O segundo é pior, e por muito. Então quando as fileiras se sobrepõem tanto
# que não sobra faixa livre, o recorte para aqui e a tarja volta a encostar na
# vizinha — de propósito. Cobrir o valor vence preservar o vizinho.
FRACAO_MINIMA = 0.45

# Folga ao recuar da caixa vizinha. `apply_redactions` remove o caractere cuja
# caixa **encosta** no retângulo, então parar exatamente na borda ainda seria
# encostar.
EPSILON = 0.05


def _fileiras_da_pagina(page: "fitz.Page") -> list[tuple[float, float, float, float]]:
    return [
        tuple(linha["bbox"])
        for bloco in page.get_text("dict")["blocks"]
        for linha in bloco.get("lines", [])
    ]


def recortar_entre_fileiras(page: "fitz.Page", rect: "fitz.Rect") -> "fitz.Rect":
    """Encolhe ``rect`` verticalmente para não alcançar as fileiras vizinhas.

    Existe porque ``apply_redactions`` remove todo caractere cuja caixa
    **encosta** no retângulo, e num documento de entrelinha apertada as caixas
    de fileiras consecutivas se sobrepõem — 12,00pt de entrelinha contra
    13,74pt de caixa dão 1,82pt de invasão, medido em 2026-09-16. O retângulo
    da tarja está correto; ele é que alcança o vizinho.

    O recorte para **dentro** da caixa da fileira vizinha mais próxima, acima e
    abaixo, considerando só as que dividem intervalo horizontal com o
    retângulo — fileira distante na horizontal não corre risco nenhum.

    O alvo continua sendo removido porque a caixa dele ocupa a altura inteira
    do retângulo original: sobra interseção de sobra. Medido na faixa de 1,0 a
    6,0pt de recuo, o valor sai em todas.
    """
    alvo_y0, alvo_y1 = rect.y0, rect.y1
    altura = alvo_y1 - alvo_y0
    if altura <= 0:
        return rect

    # `None` enquanto ninguém invade. A distinção importa: sem vizinho
    # encostando, o retângulo sai **intacto** — recortar por precaução mudaria
    # a saída de todo documento folgado, que é a maioria, sem corrigir nada.
    limite_topo = None
    limite_base = None
    meio = alvo_y0 + altura / 2
    for x0, y0, x1, y1 in _fileiras_da_pagina(page):
        if x1 <= rect.x0 or x0 >= rect.x1:
            continue  # não divide intervalo horizontal: não corre risco
        if y0 <= meio <= y1:
            # A fileira do próprio alvo. Sem esta linha ela entra na conta como
            # se fosse vizinha — a caixa dela cobre a do valor, afinal — e o
            # recorte colapsa, caindo na trava do FRACAO_MINIMA por engano.
            # Aconteceu em 3 dos 8 retângulos do documento que originou o
            # defeito: funcionava, mas encolhia para 45% sem motivo.
            continue
        centro = (y0 + y1) / 2
        if centro < meio and y1 > alvo_y0:
            # Fileira acima cuja caixa entra na nossa.
            limite_topo = min(y1, alvo_y1) if limite_topo is None else max(limite_topo, min(y1, alvo_y1))
        elif centro > meio and y0 < alvo_y1:
            # Fileira abaixo cuja caixa entra na nossa.
            limite_base = max(y0, alvo_y0) if limite_base is None else min(limite_base, max(y0, alvo_y0))

    if limite_topo is None and limite_base is None:
        return rect

    novo_y0 = alvo_y0 if limite_topo is None else min(limite_topo + EPSILON, alvo_y1)
    novo_y1 = alvo_y1 if limite_base is None else max(limite_base - EPSILON, alvo_y0)

    # A trava do FRACAO_MINIMA: nunca encolher a ponto de arriscar o valor.
    minima = altura * FRACAO_MINIMA
    if novo_y1 - novo_y0 < minima:
        centro = (alvo_y0 + alvo_y1) / 2
        novo_y0, novo_y1 = centro - minima / 2, centro + minima / 2

    return fitz.Rect(rect.x0, novo_y0, rect.x1, novo_y1)
