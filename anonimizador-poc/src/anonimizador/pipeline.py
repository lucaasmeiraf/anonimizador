"""Orquestração das camadas de detecção.

Camadas, nesta ordem:

1. regex + checksum (reconhecedores de ``recognizers/``)
2. NER local (spaCy ou transformer, conforme ``config.NER_CONFIGS``)
3. contexto (enriquecedor por lema do próprio Presidio, sobre as palavras-
   âncora declaradas em cada reconhecedor)
4. resolução de spans sobrepostos

A camada 4 é a que evita o erro clássico de empilhar detecções: um CPF dentro
de um trecho que o NER marcou como PERSON produziria duas tarjas concorrentes.
A política está em ``config.PRECEDENCIA`` e é explícita: **evidência de
checksum ganha de evidência estatística**, sempre.
"""

from __future__ import annotations

import time
from typing import Iterable, Optional

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.predefined_recognizers import SpacyRecognizer

from . import config, ner
from .recognizers import build_registry
from .spans import (
    Span,
    desambiguar_por_ancora,
    resolver_sobreposicoes,
    spans_para_redigir,
)

__all__ = [
    "DetectionPipeline",
    "Span",
    "desambiguar_por_ancora",
    "resolver_sobreposicoes",
    "spans_para_redigir",
]


class DetectionPipeline:
    """Pipeline completo de detecção para uma configuração de NER."""

    def __init__(
        self,
        ner_config: Optional[str] = None,
        device: Optional[str] = None,
        score_threshold: Optional[float] = None,
        entidades: Optional[Iterable[str]] = None,
    ) -> None:
        nome = ner_config or config.NER_PADRAO
        if nome not in config.NER_CONFIGS:
            raise ValueError(
                f"configuração de NER desconhecida: {nome!r}. "
                f"Opções: {', '.join(config.NER_CONFIGS)}"
            )
        self.ner_config = config.NER_CONFIGS[nome]
        self.device = device or config.DEVICE
        self.score_threshold = (
            config.SCORE_THRESHOLD if score_threshold is None else score_threshold
        )
        self.entidades = list(entidades or config.ENTIDADES_ATIVAS)

        usar_spacy_ner = self.ner_config.tipo == "spacy"
        registry = build_registry(config.LANG)

        if usar_spacy_ner:
            registry.add_recognizer(SpacyRecognizer(supported_language=config.LANG))
        else:
            rec = ner.build_ner_recognizer(self.ner_config, self.device)
            if rec is not None:
                registry.add_recognizer(rec)

        self.analyzer = AnalyzerEngine(
            registry=registry,
            nlp_engine=ner.build_nlp_engine(usar_ner_do_spacy=usar_spacy_ner),
            supported_languages=[config.LANG],
        )

    # -- detecção ----------------------------------------------------------
    def analyze(self, texto: str, score_threshold: Optional[float] = None) -> list[Span]:
        """Detecta e resolve sobreposições, devolvendo spans disjuntos.

        ``score_threshold`` sobrescreve o limiar só desta chamada. Existe para
        a conferência de pré-envio (`Sessao.conferir_antes_do_envio`), que
        precisa de um limiar mais baixo — aceitar evidência mais fraca, achar
        mais candidatos — sem pagar o custo de carregar um segundo modelo.
        Quem não passa o argumento tem exatamente o comportamento de antes.
        """
        if not texto.strip():
            return []

        brutos = self.analyzer.analyze(
            text=texto,
            language=config.LANG,
            entities=self.entidades,
            score_threshold=(
                self.score_threshold if score_threshold is None else score_threshold
            ),
        )
        spans = [
            Span(
                r.start,
                r.end,
                r.entity_type,
                float(r.score),
                nota=(
                    "checksum_invalido"
                    if (r.recognition_metadata or {}).get("checksum") == "invalido"
                    else None
                ),
            )
            for r in brutos
            if r.end > r.start
        ]
        return resolver_sobreposicoes(spans, texto)

    def analyze_timed(self, texto: str) -> tuple[list[Span], float]:
        t0 = time.perf_counter()
        spans = self.analyze(texto)
        return spans, time.perf_counter() - t0
