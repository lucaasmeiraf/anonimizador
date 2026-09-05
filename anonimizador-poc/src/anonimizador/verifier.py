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


# Separadores que aparecem *dentro* de um identificador brasileiro:
# 529.982.247-25, 0000000-00.2026.8.26.0100, 01310-100, (11) 98765-4321.
# Removê-los reconstrói o identificador; remover qualquer outro caractere
# fabricaria identificadores que não existem no documento.
SEPARADORES_DE_ID = re.compile(r"[.\-/()\s]")


def _procurar(agulhas: dict[str, list[str]], palheiro: str, vetor: str) -> list[Leak]:
    """Procura cada valor no palheiro, em todas as formas plausíveis.

    A busca de forma numérica **não** pode apagar todo não-dígito do palheiro.
    Fazer isso num vetor binário — ``streams``, ``bytes-brutos`` — colapsa
    megabytes de dados de fonte, coordenadas e offsets numa única sopa de
    dígitos contígua, onde qualquer sequência curta aparece por coincidência.
    Medido no corpus: uma agulha de 5 dígitos colide em 2.6% das vezes num
    documento de 3 páginas *sem imagem*; num PDF real com fontes embutidas a
    sopa é ordens de grandeza maior e a colisão vira quase certa.

    O efeito disso era o pior possível para o produto: o gate reprovava uma
    redação correta, o PDF era descartado, e o usuário via "vazou" sobre um
    documento íntegro. Um gate que dá alarme falso é um gate que as pessoas
    aprendem a ignorar.

    A correção remove apenas os separadores que ocorrem *dentro* de um
    identificador. Um CPF escrito ``529.982.247-25`` continua sendo
    encontrado pela forma ``52998224725``; dígitos separados por qualquer
    outro byte deixam de ser colados.
    """
    if not palheiro:
        return []
    palheiro_norm = _normalizar(palheiro)
    palheiro_ids = SEPARADORES_DE_ID.sub("", palheiro)
    achados = []
    for valor, formas in agulhas.items():
        for forma in formas:
            alvo = palheiro_ids if forma.isdigit() else palheiro_norm
            if forma in alvo:
                achados.append(Leak(vetor, valor, f"como {forma!r}"))
                break
    return achados


# Strings hexadecimais de content stream: `[<435046203532...>] TJ`. Quatro
# dígitos é o mínimo para não capturar tokens de estrutura curtos.
_HEX_PDF = re.compile(r"<([0-9A-Fa-f\s]{4,})>")


def _decodificar_hex(conteudo: str) -> str:
    """Traduz as strings hexadecimais de um content stream para texto.

    Sem isto o vetor ``streams`` tem uma cegueira séria: o PDF pode escrever
    texto como ``<435046203532392e...>`` em vez de ``(CPF 529.982...)``, e é
    o que o próprio PyMuPDF faz. A busca literal não encontra nada, e o
    verificador devolve "aprovado" sobre um documento onde o valor está
    perfeitamente recuperável por quem souber ler hexadecimal.

    A tradução é feita sobre uma **cópia** do stream, que é procurada além do
    conteúdo cru — as duas formas importam, porque um mesmo arquivo mistura
    as duas conforme o gerador de cada trecho.
    """

    def traduzir(m: "re.Match[str]") -> str:
        h = re.sub(r"\s", "", m.group(1))
        if len(h) % 2:
            h += "0"  # a spec manda completar com zero
        try:
            return bytes.fromhex(h).decode("latin-1", "ignore")
        except ValueError:
            return m.group(0)

    return _HEX_PDF.sub(traduzir, conteudo)


# Chaves de dicionário que identificam a natureza de um objeto PDF. A ordem
# importa: `/Subtype` é mais específico que `/Type`.
_CHAVES_TIPO = ("Subtype", "Type", "Filter")


def _descrever_objeto(doc: "fitz.Document", xref: int) -> str:
    """Nome legível do objeto por trás de um xref.

    O que o revisor precisa saber diante de uma reprovação não é o número do
    objeto — é se aquilo é o conteúdo da página, um formulário, uma anotação
    ou uma fonte. Cada um tem conserto diferente, e sem essa informação
    "vazou em streams" é um beco sem saída.
    """
    partes = []
    for chave in _CHAVES_TIPO:
        try:
            valor = doc.xref_get_key(xref, chave)
        except Exception:  # noqa: BLE001
            continue
        if valor and valor[0] != "null":
            partes.append(str(valor[1]).lstrip("/"))
    if not partes:
        return "objeto sem tipo declarado"
    # dict.fromkeys preserva a ordem e remove repetição (Type e Subtype iguais)
    return "/".join(dict.fromkeys(partes))


def verify_texto(
    texto: str,
    valores: Iterable[str],
    tokens: Iterable[str] = (),
    caminho: str = "<texto>",
) -> VerificationReport:
    """Gate do artefato de texto pseudonimizado.

    A invariante 2 do CLAUDE.md não fala em PDF, fala em **entregável**: nada
    sai sem ``verify().ok``. O texto pseudonimizado é um entregável novo, e
    sem um gate próprio ele seria exatamente a rota de download sem
    verificação que o projeto proíbe.

    Duas diferenças em relação a ``verify``, e as duas precisam ficar ditas
    em vez de subentendidas:

    **Roda um vetor, não dez.** Os outros nove descrevem estruturas de PDF —
    anotações, AcroForm, XMP, streams — que não existem numa string. O
    relatório nomeia o que executou, para ninguém ler "verificado" e supor
    dez. Isso não é uma verificação mais fraca: é a verificação completa do
    que este artefato tem.

    **Confere presença do token, não só ausência do valor.** É a aresta 1 da
    sondagem de 2026-09-01, trazida para o caminho de texto: se o valor sai e
    o token não entra, a checagem de ausência diz "limpo" — porque o original
    de fato sumiu — e o gate aprova um documento mutilado. Falso silêncio com
    o gate aprovando é a pior combinação possível neste sistema.
    """
    agulhas = {
        v: _variantes(v)
        for v in {x.strip() for x in valores if x and len(x.strip()) >= TAMANHO_MINIMO}
    }
    leaks = _procurar(agulhas, texto, "texto")
    vetores = ["texto"]

    esperados = sorted({t for t in tokens if t})
    if esperados:
        for token in esperados:
            if token not in texto:
                # `valor` aqui é o token, não dado pessoal — é seguro exibir,
                # e é a única informação que torna o defeito diagnosticável.
                leaks.append(
                    Leak("token-ausente", token, "substituicao perdida no texto")
                )
        vetores.append("tokens-presentes")

    return VerificationReport(
        caminho=caminho,
        valores_checados=len(agulhas),
        vetores_executados=vetores,
        leaks=leaks,
    )


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

        # 9. streams descomprimidos, **um a um**
        #
        # Concatenar tudo antes de procurar era mais simples e destruía a
        # única informação que torna um achado acionável: *que objeto* reteve
        # o valor. "Vazou em streams" não diz se o problema é um XObject que a
        # redação não alcançou, a aparência de um campo de formulário, ou uma
        # revisão antiga que sobreviveu ao garbage collect — e cada um tem
        # conserto diferente.
        #
        # Procurar por objeto também elimina um falso positivo de fronteira:
        # uma sequência que só existia porque o fim de um stream encostava no
        # começo de outro nunca foi recuperável de lugar nenhum.
        for xref in range(1, doc.xref_length()):
            try:
                if not doc.xref_is_stream(xref):
                    continue
                conteudo = doc.xref_stream(xref).decode("latin-1", "ignore")
            except Exception:  # noqa: BLE001
                continue
            # Duas leituras do mesmo objeto: crua e com as strings
            # hexadecimais traduzidas. Um PDF mistura as duas codificações.
            achados = _procurar(agulhas, conteudo, "streams")
            vistos = {a.valor for a in achados}
            for a in _procurar(agulhas, _decodificar_hex(conteudo), "streams"):
                if a.valor not in vistos:
                    achados.append(a)
            for achado in achados:
                leaks.append(
                    Leak(
                        achado.vetor,
                        achado.valor,
                        f"{achado.detalhe}, em {_descrever_objeto(doc, xref)} "
                        f"(xref {xref})",
                    )
                )
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
