"""A trava de pré-envio, e o que ela recusa.

Esta é a única rota do sistema que faz conteúdo sair da máquina. O que estes
testes protegem é a ordem em que as travas correm — porque a falha aqui não
tem desfazer: um nome que sai para um terceiro saiu.

O serviço `analise` é substituído por um dublê. Estes testes são sobre as
travas do `ui`, não sobre a chamada HTTP ao OpenRouter, e nenhum deles toca a
rede — se algum tocasse, o próprio teste seria a violação que ele deveria
impedir.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from anonimizador.spans import Span
from anonimizador.web import app as app_mod

from test_web import ALVOS, _enviar, cliente, pdf  # noqa: F401


# --------------------------------------------------------------------------
# A conferência de pré-envio, isolada
# --------------------------------------------------------------------------


def _sessao_com_texto(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.post(f"/api/doc/{doc['doc_id']}/pseudonimizar")
    assert r.status_code == 200, r.text
    return app_mod.sessoes.obter(doc["doc_id"]), doc["doc_id"]


def test_conferencia_aprova_texto_limpo(cliente, pdf):
    """Detector que não acha nada no texto de saída: o envio pode seguir."""
    sessao, _ = _sessao_com_texto(cliente, pdf)
    achados = sessao.conferir_antes_do_envio(lambda texto, limiar: [])
    assert achados == []


def test_conferencia_recusa_quando_sobrou_pii(cliente, pdf):
    """O caso que a trava existe para pegar: sobrou uma ocorrência.

    Simula um detector que acha um CPF no texto que já deveria estar limpo.
    A resposta traz entidade e posição, **nunca o valor** — copiá-lo criaria
    uma segunda cópia do dado no exato momento em que descobrimos que ele não
    deveria estar em lugar nenhum.
    """
    sessao, _ = _sessao_com_texto(cliente, pdf)

    def detector_que_acha(texto, limiar):
        return [Span(start=10, end=24, entity="CPF", score=0.9)]

    achados = sessao.conferir_antes_do_envio(detector_que_acha)
    assert achados == [{"entidade": "CPF", "inicio": 10, "fim": 24}]
    assert "valor" not in achados[0]


def test_conferencia_ignora_entidade_preservada_por_politica(cliente, pdf):
    """Achar `ORGANIZATION` no texto é o sistema funcionando, não falha.

    `ORGANIZATION` nasce em `manter` porque a LAI cobra que o órgão do ato
    continue legível. Recusar o envio por causa dele seria confundir a
    política com o defeito.
    """
    sessao, _ = _sessao_com_texto(cliente, pdf)

    def detector(texto, limiar):
        return [Span(start=0, end=17, entity="ORGANIZATION", score=0.9)]

    assert sessao.conferir_antes_do_envio(detector) == []


def test_conferencia_usa_limiar_mais_baixo(cliente, pdf):
    """O limiar de pré-envio precisa aceitar evidência mais fraca.

    Antes de um envio externo a conta se inverte: falso positivo custa recusar
    um envio seguro; falso negativo custa um nome real num terceiro.
    """
    from anonimizador.web.sessao import LIMIAR_PRE_ENVIO

    from anonimizador import config

    assert LIMIAR_PRE_ENVIO < config.SCORE_THRESHOLD

    sessao, _ = _sessao_com_texto(cliente, pdf)
    vistos = []
    sessao.conferir_antes_do_envio(
        lambda texto, limiar: vistos.append(limiar) or []
    )
    assert vistos == [LIMIAR_PRE_ENVIO]


def test_conferencia_sem_texto_gerado_falha(cliente, pdf):
    doc = _enviar(cliente, pdf)
    sessao = app_mod.sessoes.obter(doc["doc_id"])
    with pytest.raises(RuntimeError, match="ausente ou reprovado"):
        sessao.conferir_antes_do_envio(lambda texto, limiar: [])


# --------------------------------------------------------------------------
# A rota
# --------------------------------------------------------------------------


class RespostaDuble:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


@pytest.fixture
def analise_duble(monkeypatch):
    """Substitui a chamada ao serviço de análise. Nenhum teste toca a rede."""
    chamadas = []

    def falso_post(url, json=None, timeout=None):
        chamadas.append({"url": url, "corpo": json})
        return RespostaDuble(
            200,
            {
                "resposta": "O documento trata de um contrato entre [P-7F3A] e "
                            "o Instituto Exemplo.",
                "modelo": "anthropic/claude-sonnet-4.5",
                "duracao_s": 1.2,
                "tokens_prompt": 900,
                "tokens_saida": 120,
                "caracteres_enviados": 1234,
            },
        )

    monkeypatch.setattr(app_mod.httpx, "post", falso_post)
    return chamadas


def test_analisar_sem_texto_gerado_e_recusado(cliente, pdf, analise_duble):
    doc = _enviar(cliente, pdf)
    r = cliente.post(f"/api/doc/{doc['doc_id']}/analisar", json={"prompt": "resuma"})
    assert r.status_code == 409
    assert not analise_duble, "nada pode ter sido enviado"


def test_analisar_envia_o_texto_pseudonimizado(cliente, pdf, analise_duble):
    _, doc_id = _sessao_com_texto(cliente, pdf)
    r = cliente.post(f"/api/doc/{doc_id}/analisar", json={"prompt": "quem assinou?"})
    assert r.status_code == 200, r.text

    assert len(analise_duble) == 1
    enviado = analise_duble[0]["corpo"]["texto"]
    # O que sai é o texto com token, não o original.
    assert "Mariana Aparecida Souza" not in enviado
    assert "529.982.247-25" not in enviado
    assert "[P-" in enviado
    assert analise_duble[0]["corpo"]["prompt"] == "quem assinou?"


def test_analisar_registra_a_trilha_de_auditoria(cliente, pdf, analise_duble):
    """Sem trilha, o envio externo é um caminho sem dono."""
    _, doc_id = _sessao_com_texto(cliente, pdf)
    r = cliente.post(f"/api/doc/{doc_id}/analisar", json={"prompt": "resuma"})
    envio = r.json()["envio"]

    assert envio["destino"] == "openrouter"
    assert envio["modelo"] == "anthropic/claude-sonnet-4.5"
    assert envio["caracteres_enviados"] == 1234
    assert envio["quando"] > 0

    estado = cliente.get(f"/api/doc/{doc_id}").json()
    assert len(estado["envios"]) == 1
    # Metadado apenas: nada do que foi enviado nem do que voltou.
    assert "texto" not in estado["envios"][0]
    assert "resposta" not in estado["envios"][0]


def test_servico_de_analise_indisponivel_vira_502(cliente, pdf, monkeypatch):
    import httpx

    def post_que_falha(url, json=None, timeout=None):
        raise httpx.ConnectError("sem rota")

    monkeypatch.setattr(app_mod.httpx, "post", post_que_falha)
    _, doc_id = _sessao_com_texto(cliente, pdf)
    r = cliente.post(f"/api/doc/{doc_id}/analisar", json={"prompt": "resuma"})
    assert r.status_code == 502
    assert "indisponível" in r.json()["detail"]


def test_editar_depois_de_gerar_bloqueia_o_envio(cliente, pdf, analise_duble):
    """A edição invalida o texto, e sem texto verificado nada sai."""
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/pseudonimizar")
    cliente.patch(
        f"/api/doc/{doc['doc_id']}/span",
        json={"span_id": doc["spans"][0]["id"], "ativo": False},
    )
    r = cliente.post(f"/api/doc/{doc['doc_id']}/analisar", json={"prompt": "resuma"})
    assert r.status_code == 409
    assert not analise_duble


# --------------------------------------------------------------------------
# O serviço de egress, sem rede
# --------------------------------------------------------------------------


def test_analise_sem_chave_falha_alto(monkeypatch):
    """Chave ausente não pode virar resposta vazia.

    Uma falha de configuração que virasse string vazia apareceria na tela como
    "o modelo não achou nada", que é a forma mais cara possível de errar aqui.
    """
    from anonimizador.web import analise

    monkeypatch.setattr(analise, "CHAVE", "")
    with pytest.raises(analise.SemChave, match="OPENROUTER_API_KEY"):
        analise.analisar("texto", "prompt")


def test_analise_recusa_texto_acima_do_teto(monkeypatch):
    from anonimizador.web import analise

    monkeypatch.setattr(analise, "CHAVE", "chave-de-teste")
    monkeypatch.setattr(analise, "MAX_CARACTERES", 10)
    with pytest.raises(ValueError, match="excede o teto"):
        analise.analisar("x" * 11, "prompt")


def test_prompt_de_sistema_instrui_a_nao_adivinhar_o_nome():
    """O modelo não pode tentar reconstruir quem está por trás do token.

    É o risco específico de mandar documento pseudonimizado a um LLM: ele é
    bom em inferir identidade a partir de contexto, e essa é exatamente a
    inferência que não pode acontecer.
    """
    from anonimizador.web import analise

    assert "nunca invente o nome real" in analise.SISTEMA.lower()
    assert "adivinh" in analise.SISTEMA.lower()
