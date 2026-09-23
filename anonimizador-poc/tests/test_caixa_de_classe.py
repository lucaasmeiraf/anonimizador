"""A caixa da classe no inventário desliga a classe inteira — sempre.

Relatado em 2026-09-23: o revisor ligou à mão um trecho de ``LOCATION`` (classe
que nasce em ``manter``), depois desmarcou a caixa de ``LOCATION`` — e nada
aconteceu. A caixa continuou marcada, o trecho continuou ligado.

A causa: a caixa passava por ``PUT /perfil``, e ``aplicar_perfil`` só zera as
exceções das classes cuja regra **mudou**. Desmarcar uma classe que já estava
em ``manter`` pede ``manter`` de novo; nada muda, e a exceção criada pelo
clique sobrevive. A caixa conta os trechos ligados, então seguia marcada.

Aqui com ``ORGANIZATION``, que nasce em ``manter`` pelo mesmo motivo de LAI e
é a que o dublê de detecção produz.
"""

from test_web import _enviar, cliente, pdf  # noqa: F401


def _org(doc):
    return next(s for s in doc["spans"] if s["entity"] == "ORGANIZATION")


def test_desmarcar_classe_mantida_desliga_o_trecho_ligado_a_mao(cliente, pdf):
    doc = _enviar(cliente, pdf)
    doc_id = doc["doc_id"]
    assert doc["perfil"]["regras"]["ORGANIZATION"] == "manter"

    ligado = cliente.patch(
        f"/api/doc/{doc_id}/span", json={"span_id": _org(doc)["id"], "ativo": True}
    ).json()
    assert _org(ligado)["sera_tarjado"] is True

    r = cliente.patch(
        f"/api/doc/{doc_id}/entidade", json={"entidade": "ORGANIZATION", "ligar": False}
    )
    assert r.status_code == 200, r.text
    depois = r.json()
    assert _org(depois)["sera_tarjado"] is False, "a caixa desmarcada não desligou"
    assert depois["perfil"]["regras"]["ORGANIZATION"] == "manter"


def test_marcar_classe_liga_no_modo_do_documento(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.patch(
        f"/api/doc/{doc['doc_id']}/entidade",
        json={"entidade": "ORGANIZATION", "ligar": True},
    ).json()
    assert r["perfil"]["regras"]["ORGANIZATION"] == "tarja"
    assert _org(r)["sera_tarjado"] is True


def test_caixa_da_classe_nao_mexe_no_trecho_apontado_a_mao(cliente, pdf):
    """Trecho manual não tem classe; tem a própria caixa (`MANUAL`)."""
    doc = _enviar(cliente, pdf)
    doc_id = doc["doc_id"]
    com_manual = cliente.post(
        f"/api/doc/{doc_id}/termo", json={"termo": "Testemunha"}
    ).json()
    manuais = [s["id"] for s in com_manual["spans"] if s["origem"] == "usuario"]
    assert manuais

    depois = cliente.patch(
        f"/api/doc/{doc_id}/entidade", json={"entidade": "ORGANIZATION", "ligar": False}
    ).json()
    ainda = [s for s in depois["spans"] if s["id"] in manuais]
    assert ainda and all(s["sera_tarjado"] for s in ainda)


def test_entidade_desconhecida_e_recusada(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.patch(
        f"/api/doc/{doc['doc_id']}/entidade", json={"entidade": "MANUAL", "ligar": False}
    )
    assert r.status_code == 400


def test_edicao_pela_caixa_invalida_a_aprovacao(cliente, pdf):
    """Invariante 3: qualquer edição derruba a aprovação e apaga o PDF."""
    doc = _enviar(cliente, pdf)
    doc_id = doc["doc_id"]
    assert cliente.post(f"/api/doc/{doc_id}/aprovar").status_code == 200
    assert cliente.get(f"/api/doc/{doc_id}/download").status_code == 200

    cliente.patch(
        f"/api/doc/{doc_id}/entidade", json={"entidade": "ORGANIZATION", "ligar": True}
    )
    assert cliente.get(f"/api/doc/{doc_id}/download").status_code == 409
