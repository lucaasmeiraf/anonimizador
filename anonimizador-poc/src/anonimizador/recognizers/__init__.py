"""Registro dos reconhecedores estruturados PT-BR no Presidio."""

from __future__ import annotations

from presidio_analyzer import RecognizerRegistry

from . import (
    cep,
    cnh,
    cnj,
    cnpj,
    cns,
    cpf,
    email,
    endereco,
    pis,
    rg,
    telefone,
    titulo_eleitor,
)

MODULOS = (
    cpf, cnpj, cns, pis, cnj, cnh, titulo_eleitor,
    rg, cep, telefone, email, endereco,
)


def build_recognizers(language: str = "pt") -> list:
    """Instancia todos os reconhecedores customizados."""
    recs = []
    for mod in MODULOS:
        rec = mod.build()
        rec.supported_language = language
        recs.append(rec)
    return recs


def build_registry(language: str = "pt") -> RecognizerRegistry:
    """Registry contendo **apenas** os reconhecedores PT-BR.

    Deliberadamente não carregamos os reconhecedores padrão do Presidio: eles
    são calibrados para os EUA (SSN, driver license americana, ITIN) e, em
    documento brasileiro, geram falso positivo em cima justamente dos campos
    numéricos que nos interessam. O NER entra separado, em ``ner.py``.
    """
    # `supported_languages` precisa ser declarado aqui: o padrao do Presidio e
    # ["en"], e o AnalyzerEngine recusa a combinacao registry(en) + engine(pt).
    registry = RecognizerRegistry(supported_languages=[language])
    for rec in build_recognizers(language):
        registry.add_recognizer(rec)
    return registry
