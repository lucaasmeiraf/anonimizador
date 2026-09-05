"""A CLI obedece o mesmo gate da interface: reprovou, não sobra arquivo.

A invariante 2 do CLAUDE.md fala em *entregável*, não em rota HTTP. Até
2026-09-05 o `cmd_redact` escrevia o PDF, verificava, imprimia "VAZAMENTO(S)",
devolvia código 1 — e **deixava o arquivo no disco**.

Não é hipótese: foi assim que um `documento_*.anonimizado.pdf` com um CNPJ
recuperável apareceu na raiz do projeto. Um arquivo com nome de anonimizado e
conteúdo em claro é a pior coisa que este sistema pode produzir, porque ele é
anexado a um e-mail semanas depois por alguém que não viu o console.
"""

from __future__ import annotations

import argparse

import pytest

from anonimizador import pipeline as pipeline_mod
from anonimizador.cli import cmd_redact
from anonimizador.spans import Span

# O mesmo formato do caso real: valor mascarado numa linha, forma crua noutra.
# O DV é inválido de propósito — é o que impede a detecção de pegar a segunda.
LINHAS = [
    "PROCESSO ADMINISTRATIVO 12345",
    "CNPJ ficticio: 61.904.327/0001-18",
    "Chave PIX: 61904327000118",
]


class DetectaSoAPrimeira:
    """Detector que acha a forma mascarada e ignora a crua.

    Reproduz a detecção parcial sem carregar 1 GB de pesos.
    """

    def __init__(self, *a, **kw):
        pass

    def analyze(self, texto, score_threshold=None):
        alvo = "61.904.327/0001-18"
        pos = texto.find(alvo)
        if pos == -1:
            return []
        return [Span(start=pos, end=pos + len(alvo), entity="CNPJ", score=1.0)]


@pytest.fixture
def redigir(monkeypatch, tmp_pdf, tmp_path):
    monkeypatch.setattr(pipeline_mod, "DetectionPipeline", DetectaSoAPrimeira)

    def _rodar():
        entrada = tmp_pdf(LINHAS, nome="pix.pdf")
        saida = tmp_path / "pix.anonimizado.pdf"
        args = argparse.Namespace(
            entrada=str(entrada), saida=str(saida), ner="bert-lenerbr"
        )
        return cmd_redact(args), saida

    return _rodar


def test_reprovado_nao_deixa_arquivo_no_disco(redigir):
    codigo, saida = redigir()
    assert codigo == 1, "a verificacao deveria reprovar: o CNPJ sobrevive cru"
    assert not saida.exists(), (
        "arquivo reprovado ficou no disco — e ele tem nome de anonimizado e "
        "conteudo recuperavel"
    )


def test_aprovado_deixa_o_arquivo(monkeypatch, tmp_pdf, tmp_path):
    """A outra direção: o caminho feliz continua entregando."""

    class DetectaTudo:
        def __init__(self, *a, **kw):
            pass

        def analyze(self, texto, score_threshold=None):
            spans = []
            for alvo in ("61.904.327/0001-18", "61904327000118"):
                pos = texto.find(alvo)
                if pos != -1:
                    spans.append(
                        Span(start=pos, end=pos + len(alvo), entity="CNPJ", score=1.0)
                    )
            return sorted(spans, key=lambda s: s.start)

    monkeypatch.setattr(pipeline_mod, "DetectionPipeline", DetectaTudo)
    entrada = tmp_pdf(LINHAS, nome="pix.pdf")
    saida = tmp_path / "pix.anonimizado.pdf"
    args = argparse.Namespace(
        entrada=str(entrada), saida=str(saida), ner="bert-lenerbr"
    )

    assert cmd_redact(args) == 0
    assert saida.exists()
