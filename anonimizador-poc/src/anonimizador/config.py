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
# Siglas do token de pseudônimo
# --------------------------------------------------------------------------
# O tipo tem de sobreviver ao token: quem lê `[P-7F3A]` precisa saber que ali
# havia uma pessoa e não um CNPJ. Sem isso o token vira ruído opaco e metade
# da legibilidade que motivou trocar a tarja pelo token se perde.
#
# Curtas de propósito. Quando a escrita do token dentro do PDF existir
# (A3-A8), o token precisa caber na caixa do valor original — `[PESSOA-7F3A]`
# já estoura uma caixa de 42pt, medido na sondagem de 2026-09-01.
#
# Entidade ausente daqui faz `AlocadorDeToken.token_de` levantar erro, em vez
# de cair num prefixo genérico: prefixo genérico silencioso é como uma
# entidade nova entra no sistema sem ninguém decidir seu tratamento.
SIGLAS_TOKEN: dict[str, str] = {
    "PERSON": "P",
    "CPF": "CPF",
    "CNPJ": "CNPJ",
    "RG": "RG",
    "CEP": "CEP",
    "TELEFONE": "TEL",
    "EMAIL": "MAIL",
    "CNS": "CNS",
    "PIS_PASEP": "PIS",
    "PROCESSO_CNJ": "PROC",
    "CNH": "CNH",
    "TITULO_ELEITOR": "TE",
    "ENDERECO": "END",
    "ORGANIZATION": "ORG",
    "LOCATION": "LOC",
    "DATE_TIME": "DATA",
}

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


# --------------------------------------------------------------------------
# Desambiguação de identificadores de mesma forma
# --------------------------------------------------------------------------
# CPF, PIS/PASEP e CNH são todos 11 dígitos e nada na *forma* os distingue.
# Pior: um mesmo número pode satisfazer mais de um checksum ao mesmo tempo —
# não é hipótese, acontece no corpus da Fase 0. Nesse caso `PRECEDENCIA`
# resolvia sempre pela ordem estática (CPF antes de PIS antes de CNH),
# descartando a única evidência que de fato desambigua: a palavra-âncora que
# vem imediatamente antes do número no texto ("CNH nº 22393559907").
#
# O trecho continuava sendo tarjado — não havia risco de vazamento — mas o
# rótulo saía errado, o que degrada a métrica de CNH e cria falso positivo
# fantasma em CPF e PIS_PASEP. Rótulo errado também importa para o produto:
# é ele que decide o operador de anonimização aplicado a cada trecho.
AMBIGUAS_MESMA_FORMA = ("CPF", "PIS_PASEP", "CNH")

# Termos que, encontrados imediatamente antes do número, decidem o rótulo.
# Normalizados (minúsculas, sem acento) antes da comparação.
ANCORAS_DESAMBIGUACAO: dict[str, tuple[str, ...]] = {
    "CNH": ("cnh", "habilitacao", "renach", "condutor", "detran", "registro cnh"),
    "PIS_PASEP": ("pis", "pasep", "nit", "nis"),
    "CPF": ("cpf", "cadastro de pessoa", "cadastro nacional da pessoa fisica"),
}

# Janela, em caracteres, olhada para trás a partir do início do número.
# 40 cobre "CNH nº " e "PIS/PASEP: " com folga sem alcançar o campo anterior
# da ficha, que é o que produziria âncora cruzada.
JANELA_ANCORA = 40
