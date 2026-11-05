"""Bloco 3 da Fase 4: o documento de um inquilino não é alcançável por outro.

É o que separa "uma pessoa por servidor" de "vários clientes no mesmo
servidor". Até aqui o `doc_id` era a autorização — imprevisível, mas
imprevisível não é autorizado: dois usuários autenticados no mesmo servidor
alcançavam o documento um do outro bastando saber o id.

Os critérios de aceite do `goal-fase-4.md` §8 que este arquivo cobre:

* usuário do inquilino A recebe **404 — não 403** em documento do inquilino B;
* `plataforma` recebe **404 em toda rota de documento**, de todo inquilino;
* existe teste que percorre **todas** as rotas de documento, e não uma
  amostra — é o que impede a rota nova esquecida.

O 404 não é detalhe de estilo. O 403 diria "existe, mas não é seu", e num
produto de anonimização confirmar que um processo existe neste servidor já
diz algo sobre quem é cliente de quem.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from anonimizador import db
from anonimizador.db.modelos import DONO, OPERADOR, PLATAFORMA, Identidade, Inquilino, Usuario
from anonimizador.web import app as app_mod
from anonimizador.web import auth

SENHA = "uma senha longa o suficiente 123"


class PipelineVazio:
    def analyze(self, texto, score_threshold=None):  # noqa: ARG002
        return []


def _criar(email, inquilino_nome, papel=DONO):
    """Cria (ou reusa) inquilino e devolve um usuário pronto para entrar."""
    with db.sessao() as s:
        inq = None
        if papel != PLATAFORMA:
            inq = (
                s.query(Inquilino).filter(Inquilino.nome == inquilino_nome).one_or_none()
            )
            if inq is None:
                inq = Inquilino(nome=inquilino_nome)
                s.add(inq)
                s.flush()
        u = Usuario(
            inquilino_id=None if papel == PLATAFORMA else inq.id,
            email=email,
            papel=papel,
            troca_senha_obrigatoria=False,
        )
        s.add(u)
        s.flush()
        s.add(
            Identidade(
                usuario_id=u.id,
                provedor=auth.PROVEDOR_SENHA,
                subject=email,
                segredo_hash=auth.hash_de_senha(SENHA),
            )
        )


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Dois inquilinos, três usuários, login exigido."""
    url = f"sqlite+pysqlite:///{tmp_path / 'identidade.db'}"
    db.encerrar()
    db.iniciar(url, criar_esquema=True)
    _criar("a@exemplo.test", "Orgao A")
    _criar("b@exemplo.test", "Orgao B")
    _criar("colega@exemplo.test", "Orgao A", papel=OPERADOR)
    _criar("plataforma@exemplo.test", "", papel=PLATAFORMA)
    db.encerrar()

    monkeypatch.setenv("ANON_DB_URL", url)
    monkeypatch.setattr(app_mod, "_pipeline", PipelineVazio())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "s"))
    monkeypatch.setattr(app_mod, "EXIGIR_LOGIN", True)
    monkeypatch.setattr(app_mod, "COOKIE_SEGURO", False)
    yield
    db.encerrar()


def _cliente(email=None):
    c = TestClient(app_mod.app)
    c.__enter__()
    if email:
        r = c.post("/api/login", json={"email": email, "senha": SENHA})
        assert r.status_code == 200, r.text
    return c


def _csrf(c):
    return {app_mod.CABECALHO_CSRF: c.cookies[app_mod.COOKIE_CSRF]}


def _enviar(c, tmp_pdf):
    caminho = tmp_pdf(["Documento do inquilino", "Mariana Aparecida Souza"], nome="d.pdf")
    with open(caminho, "rb") as fh:
        r = c.post(
            "/api/doc",
            files={"arquivo": ("d.pdf", fh, "application/pdf")},
            headers=_csrf(c),
        )
    assert r.status_code == 200, r.text
    return r.json()["doc_id"]


# --------------------------------------------------------------------------
# O isolamento
# --------------------------------------------------------------------------
def test_documento_de_outro_inquilino_responde_404(ambiente, tmp_pdf):
    """O teste que o Bloco 3 existe para fazer passar."""
    a = _cliente("a@exemplo.test")
    doc_id = _enviar(a, tmp_pdf)
    assert a.get(f"/api/doc/{doc_id}").status_code == 200

    b = _cliente("b@exemplo.test")
    r = b.get(f"/api/doc/{doc_id}")
    assert r.status_code == 404, (
        "usuário de outro inquilino alcançou o documento"
    )
    assert "não é seu" not in r.text and "403" not in r.text


def test_a_recusa_e_indistinguivel_de_documento_inexistente(ambiente, tmp_pdf):
    """404 e **a mesma mensagem**: o corpo não pode denunciar a existência."""
    a = _cliente("a@exemplo.test")
    doc_id = _enviar(a, tmp_pdf)

    b = _cliente("b@exemplo.test")
    alheio = b.get(f"/api/doc/{doc_id}")
    inexistente = b.get("/api/doc/zzzzzzzzzzzz")
    assert alheio.status_code == inexistente.status_code == 404
    assert alheio.json() == inexistente.json()


def test_colega_do_mesmo_inquilino_alcanca(ambiente, tmp_pdf):
    """A posse é do inquilino, não da pessoa.

    Quem revisa é uma pessoa, mas o documento é do órgão: se quem subiu sai de
    férias, o colega precisa alcançar o que ficou em revisão.
    """
    a = _cliente("a@exemplo.test")
    doc_id = _enviar(a, tmp_pdf)

    colega = _cliente("colega@exemplo.test")
    assert colega.get(f"/api/doc/{doc_id}").status_code == 200


# --------------------------------------------------------------------------
# `plataforma` administra, não lê
# --------------------------------------------------------------------------
def test_plataforma_nao_abre_documento_de_ninguem(ambiente, tmp_pdf):
    """Administrar e ler são eixos diferentes; só o primeiro atravessa inquilino.

    Um super-usuário que atravessa inquilinos **e** lê documento é porta dos
    fundos por desenho — inaceitável num produto cujo argumento de venda é
    soberania, e a primeira coisa que uma revisão de segurança procura.
    """
    a = _cliente("a@exemplo.test")
    doc_id = _enviar(a, tmp_pdf)

    plataforma = _cliente("plataforma@exemplo.test")
    assert plataforma.get(f"/api/doc/{doc_id}").status_code == 404


def test_plataforma_nem_consegue_enviar_documento(ambiente, tmp_pdf):
    """Recusado na rota, com 403 e motivo.

    403 e não 404 aqui porque a pessoa conhece o próprio papel: não há o que
    esconder, e "não existe" seria confuso num caminho de criação. Para **ler**
    documento alheio o código continua sendo 404.

    `posse.registrar` também recusa, com `ValueError`, e continua recusando:
    aquela é a trava contra defeito de rota, esta é a resposta ao usuário.
    """
    plataforma = _cliente("plataforma@exemplo.test")
    caminho = tmp_pdf(["Documento"], nome="d.pdf")
    with open(caminho, "rb") as fh:
        r = plataforma.post(
            "/api/doc",
            files={"arquivo": ("d.pdf", fh, "application/pdf")},
            headers=_csrf(plataforma),
        )
    assert r.status_code == 403
    assert "não abre documento" in r.json()["detail"]


# --------------------------------------------------------------------------
# Toda rota, não uma amostra
# --------------------------------------------------------------------------
def test_nenhuma_rota_de_documento_escapa_da_posse(ambiente, tmp_pdf):
    """Percorre `app.routes`: é o que impede a rota nova esquecida.

    Irmão do `test_posse_rotas.py`, que confere a **estrutura** (toda rota
    passa pelo gargalo). Este confere o **efeito**: nenhuma delas responde
    algo diferente de 404 para o dono errado.
    """
    a = _cliente("a@exemplo.test")
    doc_id = _enviar(a, tmp_pdf)
    b = _cliente("b@exemplo.test")

    rotas = [
        r for r in app_mod.app.routes
        if isinstance(r, APIRoute) and "{doc_id}" in r.path_format
    ]
    assert len(rotas) >= 10, "a enumeração ficou vazia; o teste não prova nada"

    vazaram = []
    for rota in rotas:
        caminho = rota.path_format.replace("{doc_id}", doc_id)
        for param in rota.dependant.path_params:
            if param.name != "doc_id":
                caminho = caminho.replace("{%s}" % param.name, "0")
        metodo = sorted(rota.methods - {"HEAD", "OPTIONS"})[0]
        r = b.request(metodo, caminho, json={}, headers=_csrf(b))
        if r.status_code != 404:
            vazaram.append(f"{metodo} {rota.path_format} -> {r.status_code}")

    assert not vazaram, "rota alcançável pelo inquilino errado: " + ", ".join(vazaram)


# --------------------------------------------------------------------------
# O que não pode regredir
# --------------------------------------------------------------------------
def test_em_modo_local_nada_disto_se_aplica(tmp_path, monkeypatch, tmp_pdf):
    """Sem login não há inquilino, e exigir posse trancaria o uso de uma pessoa."""
    monkeypatch.setattr(app_mod, "_pipeline", PipelineVazio())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "s"))
    monkeypatch.setattr(app_mod, "EXIGIR_LOGIN", False)
    with TestClient(app_mod.app) as c:
        caminho = tmp_pdf(["Documento", "Mariana Aparecida Souza"], nome="d.pdf")
        with open(caminho, "rb") as fh:
            r = c.post("/api/doc", files={"arquivo": ("d.pdf", fh, "application/pdf")})
        assert r.status_code == 200, r.text
        assert c.get(f"/api/doc/{r.json()['doc_id']}").status_code == 200


def test_descartar_apaga_a_posse(ambiente, tmp_pdf):
    """`sessao_dono` é a única tabela que fala de documento, ainda que só do id."""
    from anonimizador.db.modelos import SessaoDono

    a = _cliente("a@exemplo.test")
    doc_id = _enviar(a, tmp_pdf)
    with db.sessao() as s:
        assert s.get(SessaoDono, doc_id) is not None

    assert a.delete(f"/api/doc/{doc_id}", headers=_csrf(a)).status_code == 200
    with db.sessao() as s:
        assert s.get(SessaoDono, doc_id) is None, "a posse ficou órfã no banco"
