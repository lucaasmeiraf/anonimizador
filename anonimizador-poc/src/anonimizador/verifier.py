"""Verificação independente pós-redação.

A regra da Fase 0 é que a redação **falha o processo** se qualquer valor
tarjado ainda for recuperável do arquivo final. Verificar apenas o texto
extraído da página seria autoengano: é justamente o vetor que o
``apply_redactions`` já limpou. O que derruba uma redação na prática são os
outros caminhos.

Vetores checados, do mais óbvio ao menos:

1. texto das páginas (PyMuPDF)
2. texto das páginas por uma segunda biblioteca (pdfplumber) — implementações
   diferentes de extração recuperam coisas diferentes
3. anotações e seus conteúdos
4. campos de formulário AcroForm (valor atual e valor padrão)
5. arquivos embutidos / anexos
6. sumário (outline)
7. metadados do documento
8. metadados XMP
9. streams de objeto descomprimidos, um a um
10. bytes brutos do arquivo, em UTF-8, Latin-1 e UTF-16BE

O item 9 é o que pega revisão incremental mal salva e objeto órfão; o 10 é a
rede de segurança final para conteúdo não comprimido.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Valores muito curtos produzem colisão fortuita com bytes de estrutura do PDF
# e tornariam a verificação inútil de tão ruidosa.
TAMANHO_MINIMO = 5


@dataclass(frozen=True)
class Leak:
    vetor: str
    valor: str
    detalhe: str = ""

    def __str__(self) -> str:
        return f"[{self.vetor}] {self.valor!r} {self.detalhe}".strip()


@dataclass
class VerificationReport:
    caminho: str
    valores_checados: int
    vetores_executados: list[str]
    leaks: list[Leak]

    @property
    def ok(self) -> bool:
        return not self.leaks


def _normalizar(texto: str) -> str:
    """Colapsa espaços — um valor pode reaparecer com espaçamento diferente."""
    return re.sub(r"\s+", " ", texto or "")


def _variantes(valor: str) -> list[str]:
    """Formas sob as quais o mesmo valor pode reaparecer.

    Um CPF tarjado como ``123.456.789-09`` pode ressurgir como ``12345678909``
    num campo de formulário ou num stream. Comparar só a forma literal deixaria
    passar exatamente o caso que mais importa.
    """
    formas = {valor, _normalizar(valor)}
    digitos = re.sub(r"\D", "", valor)
    if len(digitos) >= TAMANHO_MINIMO:
        formas.add(digitos)
    sem_espaco = re.sub(r"\s", "", valor)
    if len(sem_espaco) >= TAMANHO_MINIMO:
        formas.add(sem_espaco)
    return [f for f in formas if len(f) >= TAMANHO_MINIMO]


def _procurar(agulhas: dict[str, list[str]], palheiro: str, vetor: str) -> list[Leak]:
    if not palheiro:
        return []
    palheiro_norm = _normalizar(palheiro)
    palheiro_digitos = re.sub(r"\D", "", palheiro)
    achados = []
    for valor, formas in agulhas.items():
        for forma in formas:
            alvo = palheiro_digitos if forma.isdigit() else palheiro_norm
            if forma in alvo:
                achados.append(Leak(vetor, valor, f"como {forma!r}"))
                break
    return achados


def verify(caminho: str | Path, valores: Iterable[str]) -> VerificationReport:
    """Confere que nenhum dos ``valores`` sobrevive no PDF final."""
    caminho = str(caminho)
    agulhas = {
        v: _variantes(v)
        for v in {x.strip() for x in valores if x and len(x.strip()) >= TAMANHO_MINIMO}
    }
    leaks: list[Leak] = []
    vetores: list[str] = []

    doc = fitz.open(caminho)
    try:
        # 1. texto das páginas
        texto = "\n".join(doc.load_page(i).get_text("text") for i in range(doc.page_count))
        leaks += _procurar(agulhas, texto, "texto-pymupdf")
        vetores.append("texto-pymupdf")

        # 3. anotações
        partes = []
        for i in range(doc.page_count):
            for annot in doc.load_page(i).annots() or []:
                info = annot.info or {}
                partes += [str(v) for v in info.values() if v]
        leaks += _procurar(agulhas, "\n".join(partes), "anotacoes")
        vetores.append("anotacoes")

        # 4. campos de formulário
        partes = []
        for i in range(doc.page_count):
            for w in doc.load_page(i).widgets() or []:
                partes += [str(x) for x in (w.field_name, w.field_value, w.field_label) if x]
        leaks += _procurar(agulhas, "\n".join(partes), "acroform")
        vetores.append("acroform")

        # 5. arquivos embutidos
        partes = []
        try:
            for nome in doc.embfile_names():
                partes.append(nome)
                try:
                    partes.append(doc.embfile_get(nome).decode("utf-8", "ignore"))
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        leaks += _procurar(agulhas, "\n".join(partes), "anexos")
        vetores.append("anexos")

        # 6. sumário
        toc = doc.get_toc() or []
        leaks += _procurar(agulhas, "\n".join(str(t[1]) for t in toc), "sumario")
        vetores.append("sumario")

        # 7. metadados
        meta = doc.metadata or {}
        leaks += _procurar(agulhas, "\n".join(str(v) for v in meta.values() if v), "metadados")
        vetores.append("metadados")

        # 8. XMP
        try:
            xmp = doc.get_xml_metadata() or ""
        except Exception:  # noqa: BLE001
            xmp = ""
        leaks += _procurar(agulhas, xmp, "xmp")
        vetores.append("xmp")

        # 9. streams descomprimidos
        blob = []
        for xref in range(1, doc.xref_length()):
            try:
                if doc.xref_is_stream(xref):
                    blob.append(doc.xref_stream(xref).decode("latin-1", "ignore"))
            except Exception:  # noqa: BLE001
                continue
        leaks += _procurar(agulhas, "\n".join(blob), "streams")
        vetores.append("streams")
    finally:
        doc.close()

    # 2. segunda biblioteca de extração
    try:
        import pdfplumber

        with pdfplumber.open(caminho) as pdf:
            texto2 = "\n".join(p.extract_text() or "" for p in pdf.pages)
        leaks += _procurar(agulhas, texto2, "texto-pdfplumber")
        vetores.append("texto-pdfplumber")
    except Exception:  # noqa: BLE001
        logger.exception("pdfplumber indisponível; vetor pulado")

    # 10. bytes brutos
    dados = Path(caminho).read_bytes()
    brutos = "\n".join(
        dados.decode(enc, "ignore") for enc in ("utf-8", "latin-1", "utf-16-be")
    )
    leaks += _procurar(agulhas, brutos, "bytes-brutos")
    vetores.append("bytes-brutos")

    # Um mesmo valor pode aparecer em vários vetores; mantemos todos, é
    # informação de diagnóstico.
    return VerificationReport(
        caminho=caminho,
        valores_checados=len(agulhas),
        vetores_executados=vetores,
        leaks=leaks,
    )
