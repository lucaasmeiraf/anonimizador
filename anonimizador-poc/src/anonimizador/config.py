"""Configuração central da Fase 0.

Um único lugar para: entidades ativas, limiar de score, escolha da configuração
de NER e política de resolução de spans sobrepostos. O `run_eval` varia
`NER_CONFIGS` para produzir a tabela comparativa que decide a Fase 1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

LANG = "pt"

# --------------------------------------------------------------------------
# Entidades
# --------------------------------------------------------------------------
# Faixa 1 — com decision gate no goal.
ENTIDADES_COM_GATE = ("CPF", "CNPJ", "PERSON")

# Faixa 2 — medidas e reportadas, sem meta rígida.
ENTIDADES_MEDIDAS = (
    "RG", "CEP", "TELEFONE", "EMAIL",
    "CNS", "PIS_PASEP", "PROCESSO_CNJ", "CNH", "TITULO_ELEITOR",
)

# Faixa 3 — best-effort, apenas reportadas.
ENTIDADES_BEST_EFFORT = ("ENDERECO", "ORGANIZATION", "LOCATION", "DATE_TIME")

ENTIDADES_ATIVAS = ENTIDADES_COM_GATE + ENTIDADES_MEDIDAS + ENTIDADES_BEST_EFFORT

# Entidades que efetivamente vão para a tarja no PDF. ORGANIZATION/LOCATION/
# DATE_TIME entram na medição mas não são tarjadas por padrão: em documento
# público o nome do órgão e a data do ato costumam ser justamente o que precisa
# permanecer legível. Ajustável por caso de uso.
ENTIDADES_REDIGIDAS = ENTIDADES_COM_GATE + ENTIDADES_MEDIDAS + ("ENDERECO",)

# --------------------------------------------------------------------------
# Limiar de score
# --------------------------------------------------------------------------
# 0.35 deixa passar tudo que teve checksum confirmado (score 1.0) e tudo que
# foi impulsionado por contexto (>= 0.4 pelo enriquecedor do Presidio), mas
# descarta padrões numéricos crus sem nenhuma âncora — que são a principal
# fonte de falso positivo em CNH e RG.
SCORE_THRESHOLD = float(os.getenv("ANON_SCORE_THRESHOLD", "0.35"))

# --------------------------------------------------------------------------
# Configurações de NER comparadas na avaliação
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class NerConfig:
    nome: str
    tipo: str                      # "spacy" | "transformers"
    model_id: str = ""
    descricao: str = ""
    label_map: dict[str, str] = field(default_factory=dict)


# Mapa comum dos rótulos PT-BR dos checkpoints para o vocabulário do Presidio.
# VALOR, LEGISLACAO e JURISPRUDENCIA são descartados: não são dado pessoal.
_LABEL_MAP_PT = {
    "PESSOA": "PERSON",
    "PER": "PERSON",
    "ORGANIZACAO": "ORGANIZATION",
    "ORG": "ORGANIZATION",
    "LOCAL": "LOCATION",
    "LOC": "LOCATION",
    "TEMPO": "DATE_TIME",
}

NER_CONFIGS: dict[str, NerConfig] = {
    "spacy": NerConfig(
        nome="spacy",
        tipo="spacy",
        model_id="pt_core_news_lg",
        descricao="spaCy pt_core_news_lg (CPU, rápido, baseline do goal v1)",
    ),
    "bert-lenerbr": NerConfig(
        nome="bert-lenerbr",
        tipo="transformers",
        model_id="pierreguillou/ner-bert-base-cased-pt-lenerbr",
        descricao="BERT PT-BR ajustado em LeNER-Br (domínio jurídico)",
        label_map=_LABEL_MAP_PT,
    ),
    "bertimbau-harem": NerConfig(
        nome="bertimbau-harem",
        tipo="transformers",
        model_id="marquesafonso/bertimbau-large-ner-selective",
        descricao="BERTimbau-large ajustado em HAREM selective (domínio geral)",
        label_map=_LABEL_MAP_PT,
    ),
}

NER_PADRAO = os.getenv("ANON_NER", "bert-lenerbr")
DEVICE = os.getenv("ANON_DEVICE", "cpu")

# --------------------------------------------------------------------------
# Resolução de spans sobrepostos
# --------------------------------------------------------------------------
# Ordem de precedência quando dois reconhecedores disputam o mesmo trecho.
# Um acerto de checksum é evidência matemática; ganha do NER sempre.
PRECEDENCIA = (
    "CPF", "CNPJ", "PROCESSO_CNJ", "CNS", "PIS_PASEP", "TITULO_ELEITOR",
    "CNH", "RG", "CEP", "EMAIL", "TELEFONE",
    "PERSON", "ENDERECO", "ORGANIZATION", "LOCATION", "DATE_TIME",
)


def peso_precedencia(entidade: str) -> int:
    try:
        return len(PRECEDENCIA) - PRECEDENCIA.index(entidade)
    except ValueError:
        return 0
