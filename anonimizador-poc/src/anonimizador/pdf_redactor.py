"""Redação verdadeira de PDF.

"Verdadeira" aqui tem significado técnico preciso: o texto sai do *content
stream*, não fica escondido sob um retângulo preto. O erro de cobrir em vez de
remover é o que produziu os vazamentos públicos conhecidos de documentos
"tarjados" — o texto continua no arquivo e volta com um simples copiar-colar.

Mas remover do content stream **não basta**, e é aqui que o goal original
parava. O mesmo dado costuma existir em paralelo em:

* metadados do documento (autor, título, assunto, produtor)
* metadados XMP (um segundo bloco, em XML, que ``set_metadata`` não toca)
* anotações e seus popups
* campos de formulário AcroForm (valor e valor padrão)
* arquivos embutidos / anexos
* sumário (outline / bookmarks)
* miniaturas de página pré-renderizadas
* objetos órfãos deixados por revisões incrementais anteriores

O saneamento abaixo cobre todos eles, e ``verifier.py`` confere o resultado de
forma independente. O ``save`` é obrigatoriamente **não incremental** com
``garbage=4``: um save incremental anexaria a nova revisão ao arquivo antigo,
preservando intacta a versão com os dados.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import fitz  # PyMuPDF

from .layout import TextMap, recortar_entre_fileiras
from .spans import Span

logger = logging.getLogger(__name__)

PRETO = (0, 0, 0)
BRANCO = (1, 1, 1)

# --------------------------------------------------------------------------
# Escrita de token (operador `pseudonimo`) — A3 a A8 do `goal-fase-2.md`
# --------------------------------------------------------------------------
# Fonte base-14, sempre. **É esta escolha que fecha o A8**: o obstáculo
# registrado era a fonte original poder estar embutida como subconjunto, sem
# os glifos de `[`, `-` ou dos dígitos do token. Reaproveitar a fonte do
# documento traria esse risco por nada — o token não precisa combinar
# tipograficamente com o texto, precisa ser legível e estar no lugar certo.
# Helvetica é uma das 14 fontes que todo leitor de PDF tem, não exige
# embutimento e cobre WinAnsi inteiro.
#
# A consequência visível, e ela é aceita: o token sai em Helvetica mesmo num
# documento composto em outra fonte.
FONTE_TOKEN = "helv"

# Corpo da fonte ÷ altura da caixa do caractere. `TextMap` guarda a caixa de
# cada caractere, não o corpo da fonte — e é o corpo que `get_text_length`
# precisa para medir.
#
# Medido em 2026-09-16, Helvetica, corpos 7, 9, 11 e 14pt: a razão deu 0,728
# **constante** nos quatro. É proporção de ascendente + descendente da fonte,
# não coincidência da amostra.
#
# Vale para Helvetica. Fonte com métrica vertical diferente produz estimativa
# de corpo um pouco diferente — o que desloca a medição de largura na mesma
# proporção, para mais ou para menos. É por isso que a folga abaixo existe.
FATOR_CORPO = 0.728

# Folga exigida além da largura medida, em fração da caixa. Absorve a
# diferença de métrica vertical entre a fonte do documento e a Helvetica.
FOLGA = 0.02

# Distância da base da caixa até a linha de base do texto, em frações do
# corpo. Medido em 2026-09-16 nos corpos 7, 9, 11 e 14: deu 0,299 constante
# nos quatro. É o descendente da Helvetica.
#
# Precisamos disto porque o token é desenhado por nós — ver abaixo.
DESLOCAMENTO_BASE = 0.299


@dataclass(frozen=True)
class TokenQueNaoCoube:
    """Um token mais largo que a caixa do valor que ele substitui.

    Carrega entidade, intervalo, larguras e o token — **nunca o valor**. O
    token é sorteado e não tem relação matemática com o original
    (`pseudonimo.py`), então exibi-lo não é exibir dado pessoal, e é ele que
    torna o defeito rastreável até a linha do documento.
    """

    entity: str
    start: int
    end: int
    token: str
    largura_caixa: float
    largura_token: float
    corpo: float

    def __str__(self) -> str:
        return (
            f"{self.token} ({self.entity}@{self.start}-{self.end}): "
            f"{self.largura_token:.1f}pt de token em {self.largura_caixa:.1f}pt "
            f"de caixa, corpo {self.corpo:.1f}"
        )


class PseudonimoImpossivelNoPDF(RuntimeError):
    """O documento não pode ser pseudonimizado sem ser deformado.

    Erro de documento inteiro, e de propósito: reprova antes de escrever
    qualquer coisa, em vez de entregar um arquivo em que parte dos tokens
    coube e parte saiu torta.

    O motivo de existir está medido, e a medição também decidiu **como** o
    token é escrito. Em 2026-09-16, sobre ``add_redact_annot(text=...)``:

    * ele não recusa texto largo demais — reduz o corpo em silêncio para
      caber. Um token de 48,0pt numa caixa de 43,0pt saiu a 7,0pt no meio de
      uma linha de 9,0pt;
    * e ele **ignora o corpo pedido mesmo quando o texto cabe folgado**:
      pedindo 7, 8, 9, 10 e 12pt numa caixa de 103,5pt onde o token ocupa
      35,5pt, saíram 6,0 / 6,5 / 6,5 / 7,0 / 7,0pt. O corpo escrito fica em
      torno de 0,52 × a altura da caixa, escolha dele.

    Não há parâmetro que desligue isso. Por isso a redação aqui **remove** o
    valor e o token é desenhado depois, com ``insert_text``, que respeita o
    corpo pedido — conferido na mesma medição: 9,002 pedido, 9,002 escrito,
    no mesmo ``x0`` do original.

    Com o desenho sob nosso controle, o estouro de caixa deixa de ser
    absorvido por um encolhimento invisível e volta a ser o que é: um
    documento que não dá para pseudonimizar sem mentir sobre o resultado.
    """

    def __init__(self, casos: list[TokenQueNaoCoube]):
        self.casos = casos
        super().__init__(
            f"{len(casos)} token(s) não cabem na caixa do valor original: "
            + "; ".join(str(c) for c in casos)
            + ". O documento foi reprovado sem ser escrito — PyMuPDF encolheria "
            "a fonte em silêncio."
        )


class TokenSemGlifo(RuntimeError):
    """O token usa caractere que a fonte base-14 não sabe desenhar.

    Hoje não dispara: as siglas de ``config.SIGLAS_TOKEN`` são ASCII. A trava
    existe porque aquela tabela é editável — uma sigla com acento (`ÓRG`)
    passaria por toda a detecção e morreria aqui, que é o lugar certo para
    morrer.
    """


def _corpo_estimado(rect: "fitz.Rect") -> float:
    return rect.height * FATOR_CORPO


def medir_token(token: str, caixa: "fitz.Rect") -> tuple[float, float, bool]:
    """Largura do token, corpo estimado e se ele cabe na caixa.

    Público porque a sessão precisa da **mesma** resposta antes de aprovar:
    é ela que decide, trecho a trecho, entre token e tarja quando o token não
    cabe (decisão de 2026-09-23). Duas medições escritas em lugares
    diferentes acabariam discordando, e aí a tela prometeria token onde o
    redator reprova — ou o contrário.
    """
    corpo = _corpo_estimado(caixa)
    largura = fitz.get_text_length(token, FONTE_TOKEN, corpo)
    return largura, corpo, largura <= caixa.width * (1 - FOLGA)


def _conferir_glifos(token: str) -> None:
    for ch in token:
        try:
            ch.encode("cp1252")  # WinAnsi, a codificação da base-14
        except UnicodeEncodeError as exc:
            raise TokenSemGlifo(
                f"caractere sem glifo na fonte {FONTE_TOKEN!r}: {ch!r} em {token!r}"
            ) from exc


@dataclass(frozen=True)
class SpanSemRetangulo:
    """Um span detectado que não produziu retângulo — sinal de bug de mapeamento.

    Descreve **onde** o defeito está, nunca **o que** estava escrito ali. A
    distinção não é cosmética: este registro é a única coisa deste caminho que
    sai do processo — vai para log, para o stdout da CLI e para o relatório da
    sessão. Carregar o texto original faria dele uma cópia de dado pessoal
    fora do PDF saneado, com retenção própria, sem verificação e sem TTL. O
    arquivo de saída é auditado em dez vetores; a linha de log não é auditada
    em nenhum.

    O que o diagnóstico exige é a entidade e o intervalo: eles apontam o span
    no texto e permitem reproduzir o caso a partir do documento de origem, que
    é onde a investigação tem de acontecer de qualquer forma. O valor não
    acrescenta nada a essa investigação — quem a faz tem o documento em mãos.
    """

    entity: str
    start: int
    end: int

    @property
    def comprimento(self) -> int:
        return self.end - self.start

    def __str__(self) -> str:
        return f"{self.entity}[{self.comprimento}] @{self.start}"


@dataclass
class RedactionResult:
    caminho_saida: str
    spans_redigidos: int = 0
    retangulos: int = 0
    valores: list[str] = field(default_factory=list)
    spans_sem_retangulo: list[SpanSemRetangulo] = field(default_factory=list)
    saneamento: dict[str, bool] = field(default_factory=dict)
    # Tokens efetivamente escritos no PDF. É o que alimenta a conferência de
    # presença do `verify` — sem ela, um token descartado passaria pelo gate,
    # porque a checagem de ausência diria "limpo": o original de fato sumiu.
    tokens_escritos: list[str] = field(default_factory=list)


def redact_document(
    doc: "fitz.Document",
    tm: TextMap,
    spans: list[Span],
    caminho_saida: str | Path,
    cor: tuple[float, float, float] = PRETO,
    tokens: Mapping[tuple[int, int], str] | None = None,
) -> RedactionResult:
    """Aplica a redação e devolve o relatório do que foi feito.

    ``tokens`` mapeia ``(start, end)`` de um span para o token que deve ocupar
    o lugar do valor — é assim que o operador `pseudonimo` chega aqui. Span
    que não estiver no mapa recebe tarja, o comportamento de sempre; com
    ``tokens`` vazio ou ``None`` nada neste caminho muda.

    A chave é o intervalo, e não o objeto ``Span``, porque quem decide o
    operador é a política, que trabalha sobre offsets — a mesma verdade que o
    resto do sistema usa (invariante 7 do `CLAUDE.md`).
    """
    caminho_saida = str(caminho_saida)
    res = RedactionResult(caminho_saida=caminho_saida)
    tokens = tokens or {}

    # --- Primeira passada: resolver caixas e conferir que todo token cabe.
    #
    # Nada é escrito aqui de propósito. Medir antes de mutar é o que permite
    # reprovar o documento inteiro sem deixar um arquivo meio escrito, e é o
    # que faz o erro listar **todos** os trechos problemáticos de uma vez —
    # quem for corrigir não descobre um por execução.
    plano: list[tuple[Span, list[tuple[int, "fitz.Rect"]], str | None]] = []
    nao_couberam: list[TokenQueNaoCoube] = []

    for span in spans:
        rects = tm.rects_for(span.start, span.end)
        if not rects:
            # Nenhuma caixa: o span caiu inteiro sobre separadores sintéticos.
            # Registramos em vez de engolir — é sinal de bug no mapeamento, e
            # significaria PII detectada mas não tarjada.
            #
            # O valor sequer é lido aqui. Materializá-lo para depois não usar
            # convida a próxima pessoa a colocá-lo no log "só para depurar",
            # que foi exatamente como esta linha nasceu.
            sem_caixa = SpanSemRetangulo(span.entity, span.start, span.end)
            res.spans_sem_retangulo.append(sem_caixa)
            logger.warning("span sem retangulo: %s", sem_caixa)
            continue

        token = tokens.get((span.start, span.end))
        if token is not None:
            _conferir_glifos(token)
            _, caixa = rects[0]
            largura, corpo, cabe = medir_token(token, caixa)
            if not cabe:
                nao_couberam.append(
                    TokenQueNaoCoube(
                        entity=span.entity,
                        start=span.start,
                        end=span.end,
                        token=token,
                        largura_caixa=caixa.width,
                        largura_token=largura,
                        corpo=corpo,
                    )
                )

        plano.append((span, rects, token))

    if nao_couberam:
        logger.warning("documento reprovado: %d token(s) nao cabem", len(nao_couberam))
        raise PseudonimoImpossivelNoPDF(nao_couberam)

    # --- Segunda passada: anotar.
    #
    # Nenhum token é passado ao `add_redact_annot`. A anotação só **remove**;
    # o token é desenhado na terceira passada, depois que a remoção já
    # aconteceu. Ver `PseudonimoImpossivelNoPDF` para a medição que forçou
    # essa separação.
    escritas: list[tuple[int, "fitz.Rect", str]] = []
    for span, rects, token in plano:
        res.spans_redigidos += 1
        res.valores.append(span.text_of(tm.text))
        for i, (pno, rect) in enumerate(rects):
            page = doc.load_page(pno)
            # Recorte vertical antes de anotar — defeito D-01. Só a anotação
            # usa o retângulo recortado; `rect` continua sendo a caixa
            # verdadeira do valor, e é dela que saem o corpo da fonte e a
            # linha de base do token, mais abaixo.
            caixa = recortar_entre_fileiras(page, rect)
            if token is None:
                page.add_redact_annot(caixa, fill=cor)
            else:
                # Branco, e não preto: este retângulo não é tarja. É o lugar
                # onde o token vai ser lido — sobre barra preta, não seria.
                page.add_redact_annot(caixa, fill=BRANCO)
                if i == 0:
                    # Só a primeira caixa recebe o token. Um valor que
                    # atravessa a quebra de linha tem duas caixas, e repetir o
                    # token na segunda faria quem lê enxergar dois atores onde
                    # havia um.
                    escritas.append((pno, rect, token))
            res.retangulos += 1

    # Aplicação página a página. `apply_redactions` remove o texto do content
    # stream e os pixels de imagem sob o retângulo; `clean_contents` reescreve
    # o stream, eliminando restos do operador de texto.
    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        page.apply_redactions()
        page.clean_contents()

    # --- Terceira passada: desenhar os tokens.
    #
    # Depois da remoção, nunca antes: `apply_redactions` apaga tudo o que
    # estiver sob o retângulo, e o token escrito antes seria apagado junto.
    for pno, rect, token in escritas:
        corpo = _corpo_estimado(rect)
        doc.load_page(pno).insert_text(
            (rect.x0, rect.y1 - DESLOCAMENTO_BASE * corpo),
            token,
            fontname=FONTE_TOKEN,
            fontsize=corpo,
            color=PRETO,
        )
        res.tokens_escritos.append(token)

    res.saneamento = _sanear(doc)

    # Não incremental, com coleta agressiva de objetos órfãos.
    doc.save(caminho_saida, garbage=4, deflate=True, clean=True, incremental=False)
    return res


def _sanear(doc: "fitz.Document") -> dict[str, bool]:
    """Remove os vetores paralelos de vazamento. Devolve o que foi executado."""
    feito: dict[str, bool] = {}

    # `scrub` cobre a maior parte, mas sua assinatura variou entre versões do
    # PyMuPDF. Filtramos os kwargs pelos que a versão instalada aceita, em vez
    # de fixar uma assinatura e quebrar no upgrade.
    desejado = dict(
        attached_files=True,
        clean_pages=True,
        embedded_files=True,
        hidden_text=True,
        javascript=True,
        metadata=True,
        remove_links=True,
        reset_fields=True,
        reset_responses=True,
        thumbnails=True,
        xml_metadata=True,
        redactions=False,  # já aplicamos as nossas acima
    )
    try:
        aceitos = set(inspect.signature(doc.scrub).parameters)
        doc.scrub(**{k: v for k, v in desejado.items() if k in aceitos})
        feito["scrub"] = True
    except Exception:  # noqa: BLE001
        logger.exception("scrub falhou; aplicando saneamento manual")
        feito["scrub"] = False

    # Redundância deliberada: mesmo com o scrub bem-sucedido, zeramos
    # metadados e XMP explicitamente. Custa nada e cobre diferenças de versão.
    try:
        doc.set_metadata({})
        feito["metadata"] = True
    except Exception:  # noqa: BLE001
        logger.exception("falha ao limpar metadados")
        feito["metadata"] = False

    try:
        doc.del_xml_metadata()
        feito["xml_metadata"] = True
    except Exception:  # noqa: BLE001
        logger.exception("falha ao limpar XMP")
        feito["xml_metadata"] = False

    try:
        doc.set_toc([])
        feito["toc"] = True
    except Exception:  # noqa: BLE001
        logger.exception("falha ao limpar sumário")
        feito["toc"] = False

    return feito


def redact_file(
    caminho_entrada: str | Path,
    caminho_saida: str | Path,
    spans_fn,
) -> tuple[RedactionResult, TextMap, list[Span]]:
    """Fluxo de arquivo: abre, mapeia, detecta via ``spans_fn`` e redige.

    ``spans_fn`` recebe o texto e devolve os spans — assim o redator não
    conhece o pipeline de detecção e pode ser testado com spans fabricados.
    """
    from .layout import build_text_map

    doc = fitz.open(str(caminho_entrada))
    try:
        tm = build_text_map(doc)
        spans = spans_fn(tm.text)
        res = redact_document(doc, tm, spans, caminho_saida)
        return res, tm, spans
    finally:
        doc.close()
