"""A9 pelo caminho da API: geração, gate e invalidação.

Reaproveita o dublê de pipeline de `test_web.py` — estes testes são sobre o
fluxo e sobre as travas, não sobre detecção.

A trava que mais importa aqui é a mesma do PDF, e quebra do mesmo jeito:
alguém acrescenta uma rota que serve `sessao.texto_pseudo` sem consultar
`pode_baixar_texto`.
"""

from __future__ import annotations

import pytest

from anonimizador.spans import Span
from anonimizador.web import app as app_mod
from fastapi.testclient import TestClient

from test_web import ALVOS, PipelineDuble, _enviar, cliente, pdf  # noqa: F401


class PipelineTodasOcorrencias:
    """Como o dublê de `test_web.py`, mas achando **todas** as ocorrências.

    O dublê de lá para na primeira (`texto.find`), o que é suficiente para os
    testes de fluxo dele. Aqui a repetição é justamente o que está sob teste:
    o determinismo intradocumento só é observável quando o mesmo valor
    aparece duas vezes.
    """

    def analyze(self, texto: str, score_threshold: float | None = None):
        spans = []
        for valor, entidade in ALVOS:
            inicio = 0
            while (pos := texto.find(valor, inicio)) != -1:
                spans.append(
                    Span(start=pos, end=pos + len(valor), entity=entidade, score=0.99)
                )
                inicio = pos + len(valor)
        return sorted(spans, key=lambda s: s.start)


@pytest.fixture
def cliente_completo(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_pipeline", PipelineTodasOcorrencias())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "sessoes"))
    with TestClient(app_mod.app) as c:
        yield c


def _gerar(cliente, doc_id):
    r = cliente.post(f"/api/doc/{doc_id}/pseudonimizar")
    assert r.status_code == 200, r.text
    return r.json()


def test_pseudonimizar_gera_texto_verificado(cliente, pdf):
    doc = _enviar(cliente, pdf)
    estado = _gerar(cliente, doc["doc_id"])

    rel = estado["relatorio_texto"]
    assert rel["verificacao_ok"] is True
    assert rel["spans_substituidos"] > 0
    assert rel["vetores"] == ["texto", "tokens-presentes"]
    assert estado["pode_baixar_texto"] is True


def test_download_do_texto_traz_tokens_e_nao_traz_valores(cliente, pdf):
    doc = _enviar(cliente, pdf)
    _gerar(cliente, doc["doc_id"])

    r = cliente.get(f"/api/doc/{doc['doc_id']}/download/texto")
    assert r.status_code == 200
    texto = r.text

    # Os valores tarjados sumiram...
    assert "Mariana Aparecida Souza" not in texto
    assert "529.982.247-25" not in texto
    # ...e o token ficou no lugar, com o tipo preservado.
    assert "[P-" in texto
    assert "[CPF-" in texto


def test_organizacao_preservada_por_politica_continua_no_texto(cliente, pdf):
    """A política manda igual nos dois artefatos.

    `ORGANIZATION` nasce em `manter` porque a LAI cobra que o órgão do ato
    continue legível. O texto pseudonimizado não pode ser mais agressivo que
    o PDF — seria a outra falha jurídica.
    """
    doc = _enviar(cliente, pdf)
    _gerar(cliente, doc["doc_id"])
    r = cliente.get(f"/api/doc/{doc['doc_id']}/download/texto")
    assert "Instituto Exemplo" in r.text


REPETIDO = [
    "CONTRATO",
    "Contratante: Mariana Aparecida Souza, brasileira.",
    "Fica Mariana Aparecida Souza responsavel pelo pagamento.",
]


def test_mesmo_nome_recebe_o_mesmo_token_no_documento(cliente_completo, tmp_pdf):
    caminho = tmp_pdf(REPETIDO, nome="repetido.pdf")
    doc = _enviar(cliente_completo, caminho, nome="repetido.pdf")
    estado = _gerar(cliente_completo, doc["doc_id"])

    assert estado["relatorio_texto"]["spans_substituidos"] == 2
    assert estado["relatorio_texto"]["tokens_distintos"] == 1
    assert estado["relatorio_texto"]["verificacao_ok"] is True

    r = cliente_completo.get(f"/api/doc/{doc['doc_id']}/download/texto")
    # O mesmo token nas duas passagens: é isso que permite seguir o ator sem
    # saber quem ele é.
    import re

    tokens = re.findall(r"\[P-[0-9A-F]{4}\]", r.text)
    assert len(tokens) == 2
    assert tokens[0] == tokens[1]


def test_ocorrencia_nao_detectada_reprova_o_texto(cliente, tmp_pdf):
    """O gate pega o que a detecção deixou passar — e é assim que deve ser.

    Este caso não é hipotético: o dublê de `test_web.py` só marca a primeira
    ocorrência de cada valor, exatamente como um detector que erra a segunda.
    O valor sobrevive no texto, `verify_texto` acha, e **nada é entregue**.

    É a diferença entre este sistema e um que "parece pronto": o artefato
    reprovado não fica em disco esperando alguém alcançá-lo.
    """
    caminho = tmp_pdf(REPETIDO, nome="repetido.pdf")
    doc = _enviar(cliente, caminho, nome="repetido.pdf")
    estado = _gerar(cliente, doc["doc_id"])

    assert estado["relatorio_texto"]["verificacao_ok"] is False
    assert estado["relatorio_texto"]["vazamentos"] == ["texto"]
    assert estado["pode_baixar_texto"] is False

    r = cliente.get(f"/api/doc/{doc['doc_id']}/download/texto")
    assert r.status_code == 409


def test_download_do_texto_sem_gerar_e_recusado(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.get(f"/api/doc/{doc['doc_id']}/download/texto")
    assert r.status_code == 409


def test_editar_depois_de_gerar_invalida_e_apaga(cliente, pdf):
    """Invariante 3: qualquer edição derruba o que foi gerado antes dela."""
    doc = _enviar(cliente, pdf)
    _gerar(cliente, doc["doc_id"])

    span = doc["spans"][0]
    r = cliente.patch(
        f"/api/doc/{doc['doc_id']}/span",
        json={"span_id": span["id"], "ativo": False},
    )
    assert r.status_code == 200
    assert r.json()["pode_baixar_texto"] is False
    assert r.json()["relatorio_texto"] is None

    r = cliente.get(f"/api/doc/{doc['doc_id']}/download/texto")
    assert r.status_code == 409


def test_pseudonimizar_sem_span_ativo_e_recusado(cliente, pdf):
    doc = _enviar(cliente, pdf)
    for s in doc["spans"]:
        cliente.patch(
            f"/api/doc/{doc['doc_id']}/span",
            json={"span_id": s["id"], "ativo": False},
        )
    r = cliente.post(f"/api/doc/{doc['doc_id']}/pseudonimizar")
    assert r.status_code == 400


def test_nenhum_mapa_de_token_fica_em_disco(cliente, pdf):
    """Critério de aceite do goal: sem cofre, sem mapa, sem retenção.

    Um mapa token -> valor em disco seria a "informação adicional mantida
    separadamente" do art. 13 §4º, e transformaria a saída em dado
    pseudonimizado — que é exatamente o que a Fase A evita.
    """
    doc = _enviar(cliente, pdf)
    _gerar(cliente, doc["doc_id"])

    sessao = __import__(
        "anonimizador.web.app", fromlist=["sessoes"]
    ).sessoes.obter(doc["doc_id"])
    arquivos = sorted(p.name for p in sessao.pasta.iterdir())
    assert arquivos == ["original.pdf", "pseudonimizado.txt"]


def test_o_pdf_continua_intocado_pelo_caminho_do_texto(cliente, pdf):
    """A restrição do usuário: nada aqui muda o funcionamento atual."""
    doc = _enviar(cliente, pdf)
    _gerar(cliente, doc["doc_id"])

    r = cliente.post(f"/api/doc/{doc['doc_id']}/aprovar")
    assert r.status_code == 200
    assert r.json()["relatorio"]["verificacao_ok"] is True
    assert r.json()["pode_baixar"] is True
