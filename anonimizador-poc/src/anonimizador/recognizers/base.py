"""Base comum dos reconhecedores estruturados PT-BR.

Todos seguem o mesmo desenho: um ou mais padrões regex com score modesto, uma
lista de palavras-âncora para o enriquecedor de contexto do Presidio, e um
checksum que arbitra.

A semântica de ``validate_result`` no Presidio:

* ``True``  -> o score vira 1.0 (evidência matemática, não heurística)
* ``False`` -> o resultado é **descartado**
* ``None``  -> mantém o score do padrão (para entidades sem checksum, como CEP)

---

## Por que ``False`` deixou de ser usado

A Fase 0 devolvia ``False`` quando o checksum falhava, e isso produziu um
ponto cego que só apareceu com documento de verdade: **um número com forma de
CPF e dígito verificador errado desaparecia por completo**, mesmo com a
palavra ``CPF:`` imediatamente antes dele. O ``False`` descarta o candidato
antes de o enriquecedor de contexto sequer olhar a vizinhança.

Medido em quatro documentos reais de teste: 35 números com forma de CPF, 23
deles com âncora explícita, **nenhum detectado** — porque nenhum tinha DV
válido. Os documentos diziam, em texto, ``CPF fictício nº``.

Isso não é caso de laboratório. Acontece em:

* minuta, modelo de contrato e material de treinamento, que usam identificador
  fictício por definição;
* ficha preenchida à mão, com dígito trocado;
* PDF vindo de OCR, que confunde 8 com 3.

Nos três casos o número continua sendo dado pessoal no documento — ele
identifica o registro, e se for erro de digitação de um CPF real está a um
dígito de distância dele.

## O que passou a valer: três níveis de evidência

Em vez de passa/reprova, o checksum define **confiança**:

=========================================  ======  ==========================
evidência                                  score   comportamento
=========================================  ======  ==========================
forma + checksum válido                    1.0     certeza matemática
forma **mascarada**, checksum inválido      0.50   forte: a máscara é rara
forma crua + âncora explícita perto         0.45   forte: o texto declarou
forma crua, sem âncora, checksum inválido   —      descartado
=========================================  ======  ==========================

**O score não é o discriminador — a marca é.** O enriquecedor de contexto do
Presidio roda *depois* deste reconhecedor e soma por cima; um valor com DV
inválido e âncora forte chega a 1.0 e fica indistinguível, pelo número, de um
confirmado por checksum. Quem separa os dois é
``recognition_metadata["checksum"]``, que a interface usa para dizer ao
revisor por que aquele trecho foi apontado. Comparar score para essa decisão
daria a resposta errada.

O limiar de ``config.SCORE_THRESHOLD`` (0.35) deixa os três primeiros
passarem. O quarto continua fora, e é o que preserva a precisão: um número de
nota fiscal ou de matrícula com 11 dígitos, solto no texto, segue sendo
ignorado.

A máscara dispensa âncora porque ela própria é a evidência. ``999.999.999-99``
não é uma forma que apareça por acaso; a forma crua, sim.

## O que isso custa, e onde está medido

Afrouxar um reconhecedor que tinha F1 1.000 e zero falso positivo exige
número, não intuição. ``eval/generate_corpus.py`` passou a gerar
identificadores com DV inválido — ancorados e em célula de tabela sem âncora —
em um documento a cada três, e ``eval/report.md`` mede o efeito nas duas
direções.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Callable, Optional, Sequence

from presidio_analyzer import Pattern, PatternRecognizer, RecognizerResult

# Score dos dois níveis intermediários. Ambos acima de SCORE_THRESHOLD (0.35)
# e bem abaixo de 1.0, para que a interface consiga separar visualmente
# "confirmado por checksum" de "provável, confira".
SCORE_MASCARA_SEM_CHECKSUM = 0.50
SCORE_ANCORA_SEM_CHECKSUM = 0.45

# Janela olhada para trás. Mesmo valor de `config.JANELA_ANCORA`, e pelo mesmo
# motivo: cobre "CPF/MF sob o nº " com folga sem alcançar o campo anterior da
# ficha, que é o que produziria âncora cruzada entre entidades vizinhas.
JANELA_ANCORA = 40

# Score de quem tem checksum válido, forma ambígua e **nenhuma** âncora.
# Abaixo de SCORE_THRESHOLD (0.35) de propósito: o candidato continua existindo
# e some no filtro do pipeline, em vez de ser descartado aqui. A diferença
# aparece para quem baixar o limiar por configuração — a evidência não foi
# jogada fora, foi classificada como fraca.
SCORE_AMBIGUO_SEM_ANCORA = 0.20


def _normalizar(texto: str) -> str:
    """Minúsculas e sem acento, para comparar âncora sem depender da grafia."""
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in sem_acento if not unicodedata.combining(c))


class ChecksumRecognizer(PatternRecognizer):
    """Reconhecedor de padrão com validação por dígito verificador."""

    def __init__(
        self,
        supported_entity: str,
        patterns: Sequence[Pattern],
        context: Sequence[str],
        validator: Optional[Callable[[str], bool]] = None,
        supported_language: str = "pt",
        name: Optional[str] = None,
        forma_ambigua: bool = False,
    ) -> None:
        self._validator = validator
        # `forma_ambigua`: o padrão não se distingue de outro identificador
        # comum pela forma, então checksum válido **sozinho** não basta. Ver o
        # bloco de decisão em `analyze`, com a medição que o motiva. Só CNH e
        # PIS marcam isto hoje — os dois são 11 dígitos crus, como o CPF.
        self._forma_ambigua = forma_ambigua
        super().__init__(
            supported_entity=supported_entity,
            patterns=list(patterns),
            context=list(context),
            supported_language=supported_language,
            name=name or f"{supported_entity}Recognizer",
        )

    # ``validate_result`` não recebe o texto ao redor, só o trecho casado, e
    # por isso não consegue decidir sobre âncora. Devolver `None` mantém o
    # candidato vivo com o score do padrão; a classificação em níveis acontece
    # em `analyze`, que tem o texto inteiro.
    def validate_result(self, pattern_text: str) -> Optional[bool]:
        if self._validator is None:
            return None
        return True if self._validator(pattern_text) else None

    def _tem_ancora(self, texto: str, inicio: int) -> bool:
        janela = _normalizar(texto[max(0, inicio - JANELA_ANCORA):inicio])
        return any(_normalizar(a) in janela for a in self.context or ())

    def analyze(self, text, entities, nlp_artifacts=None, regex_flags=None):
        resultados = super().analyze(text, entities, nlp_artifacts, regex_flags)
        if self._validator is None:
            return resultados

        saida: list[RecognizerResult] = []
        for r in resultados:
            trecho = text[r.start:r.end]

            if self._validator(trecho):
                # Checksum fecha: evidência forte, score 1.0 vindo do
                # `validate_result`. É a invariante 8 do `CLAUDE.md`.
                #
                # **Menos para quem tem forma ambígua.** CNH e PIS são 11
                # dígitos crus, iguaizinhos a um CPF, e o dígito verificador
                # deles fecha por acaso com frequência que foi medida em
                # 2026-09-17: 9,22% dos CPFs válidos passam também no checksum
                # de CNH, e 10,74% no de PIS. Numa sequência numérica qualquer
                # de 11 dígitos, 0,92% passa em CNH.
                #
                # Sem âncora, então, "checksum fechou" não distingue um
                # documento de identificação de um número de protocolo no
                # rodapé — e tarjar toda numeração é a outra falha jurídica,
                # a da LAI (`CLAUDE.md` §6). O módulo `cnh.py` sempre disse
                # isso; era a regra uniforme daqui que o atropelava.
                if self._forma_ambigua and not self._tem_ancora(text, r.start):
                    r.score = min(r.score, SCORE_AMBIGUO_SEM_ANCORA)
                saida.append(r)
                continue

            # Checksum falhou. Só sobrevive com outra evidência.
            mascarado = bool(re.search(r"[.\-/]", trecho))
            if mascarado:
                r.score = max(r.score, SCORE_MASCARA_SEM_CHECKSUM)
            elif self._tem_ancora(text, r.start):
                r.score = max(r.score, SCORE_ANCORA_SEM_CHECKSUM)
            else:
                # Forma crua, sem âncora, sem checksum: é ruído numérico.
                # Descartar aqui é o que mantém a precisão do reconhecedor.
                continue

            # Marca a origem da decisão. A interface usa isto para dizer ao
            # revisor *por que* aquele trecho foi apontado — sem essa
            # distinção, um palpite pareceria uma certeza.
            #
            # `analysis_explanation` NÃO pode ser mexido aqui: o enriquecedor
            # de contexto do Presidio roda depois e chama
            # `set_supportive_context_word` nele. Zerá-lo derruba o pipeline.
            if r.recognition_metadata is None:
                r.recognition_metadata = {}
            r.recognition_metadata["checksum"] = "invalido"
            saida.append(r)

        return saida
