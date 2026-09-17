"""D-02: desligar de uma vez os trechos apontados à mão.

O relato: o usuário seleciona trechos no documento, eles aparecem na lista "O
que será anonimizado" sob `MANUAL`, e desmarcar aquela caixa não desliga nada.

A causa são duas camadas, e a primeira escondia a segunda:

1. a caixa do `MANUAL` era **desabilitada** na tela — o clique não fazia nada;
2. e não adiantaria habilitar: `MANUAL` não está em `config.ENTIDADES_ATIVAS`,
   então `PUT /perfil` com uma regra para ela é recusado com 422. A caixa
   governa a **política de entidades**, e trecho apontado à mão não é uma
   entidade da política — é uma decisão sobre um trecho.

Por isso o conserto não é liberar a caixa para o caminho do perfil. É dar ao
lote o mesmo caminho que o clique individual já tem: ligar e desligar o trecho,
não mudar a política. A regra de que **a decisão explícita vence o padrão da
classe** continua inteira — desligar em lote também é decisão explícita.
"""

from __future__ import annotations

import pytest

from test_web import _enviar, cliente, pdf  # noqa: F401


def _manuais(doc):
    return [s for s in doc["spans"] if s["origem"] == "usuario"]


def test_a_politica_nao_governa_trecho_apontado_a_mao(cliente, pdf):
    """A segunda camada, travada: `MANUAL` não é entidade de perfil.

    Se um dia alguém "consertar" o defeito acrescentando `MANUAL` a
    `ENTIDADES_ATIVAS`, ela passa a ter operador por política — e o trecho que
    o usuário apontou explicitamente volta a poder ser desligado por um padrão
    de classe, que é exatamente o que a regra proíbe. Este teste falha nessa
    hora.
    """
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Flores"})

    r = cliente.put(
        f"/api/doc/{doc['doc_id']}/perfil",
        json={"nome": "x", "padrao": "tarja", "regras": {"MANUAL": "manter"}},
    )
    assert r.status_code == 422
    assert "entidade desconhecida" in r.json()["detail"]


def test_desligar_em_lote_os_trechos_manuais(cliente, pdf):
    doc = _enviar(cliente, pdf)
    depois = cliente.post(
        f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Flores"}
    ).json()
    assert _manuais(depois), "o termo não virou trecho manual"
    assert all(s["sera_tarjado"] for s in _manuais(depois))

    r = cliente.patch(f"/api/doc/{doc['doc_id']}/manuais", json={"ativo": False})
    assert r.status_code == 200, r.text
    desligados = r.json()
    assert r.json()["alterados"] == len(_manuais(depois))
    assert not any(s["sera_tarjado"] for s in _manuais(desligados)), (
        "desmarcar em lote não desligou os trechos apontados à mão"
    )


def test_religar_em_lote(cliente, pdf):
    """A caixa é de dois estados: o que ela desliga, ela religa."""
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Flores"})
    cliente.patch(f"/api/doc/{doc['doc_id']}/manuais", json={"ativo": False})

    religados = cliente.patch(
        f"/api/doc/{doc['doc_id']}/manuais", json={"ativo": True}
    ).json()
    assert all(s["sera_tarjado"] for s in _manuais(religados))


def test_desligar_em_lote_nao_apaga_os_trechos(cliente, pdf):
    """Desligar não é apagar, e a diferença é visível na tela.

    `DELETE /manuais` já existia e **remove** os trechos da proposta. Desligar
    mantém o retângulo no lugar, tracejado: o revisor continua vendo o que
    apontou e resolveu não usar. Confundir os dois esconderia do próprio
    usuário uma decisão que ele tomou.
    """
    doc = _enviar(cliente, pdf)
    antes = cliente.post(
        f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Flores"}
    ).json()

    depois = cliente.patch(
        f"/api/doc/{doc['doc_id']}/manuais", json={"ativo": False}
    ).json()
    assert len(_manuais(depois)) == len(_manuais(antes))


def test_desligar_em_lote_invalida_a_aprovacao(cliente, pdf):
    """Invariante 3: qualquer edição derruba a aprovação e apaga o PDF gerado."""
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Flores"})
    assert cliente.post(f"/api/doc/{doc['doc_id']}/aprovar").status_code == 200
    assert cliente.get(f"/api/doc/{doc['doc_id']}/download").status_code == 200

    cliente.patch(f"/api/doc/{doc['doc_id']}/manuais", json={"ativo": False})
    assert cliente.get(f"/api/doc/{doc['doc_id']}/download").status_code == 409


def test_sem_trecho_manual_a_rota_nao_quebra(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.patch(f"/api/doc/{doc['doc_id']}/manuais", json={"ativo": False})
    assert r.status_code == 200
    assert r.json()["alterados"] == 0
