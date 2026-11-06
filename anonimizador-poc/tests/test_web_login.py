"""Login pela API: os dois modos, e a trava que separa um do outro.

`test_auth.py` cobre o núcleo sem HTTP. Aqui o que está sob teste é o
transporte — cookie, código de status, CSRF — e sobretudo a pergunta que não
pode ter resposta ambígua: **com login exigido, o que acontece sem sessão?**

O sistema tem dois modos legítimos (ver o cabeçalho de `app.py`):

* **local**, o padrão: a porta sai em `127.0.0.1` e o perímetro é o endereço;
* **com login** (`ANON_EXIGIR_LOGIN=1`): a porta pode ser pública.

O interruptor é explícito de propósito. O teste que mais importa neste arquivo
é o que prova que ligá-lo fecha de fato todas as rotas de documento — porque o
modo de falha aqui é servir documento de todos para qualquer um.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from anonimizador import db
from anonimizador.db.modelos import DONO, Identidade, Inquilino, Usuario
from anonimizador.web import app as app_mod
from anonimizador.web import auth

SENHA = "uma senha longa o suficiente 123"
EMAIL = "operador@exemplo.test"


class PipelineVazio:
    def analyze(self, texto, score_threshold=None):  # noqa: ARG002
        return []


def _semear(url):
    db.encerrar()
    db.iniciar(url, criar_esquema=True)
    with db.sessao() as s:
        inq = Inquilino(nome="Órgão de Exemplo")
        s.add(inq)
        s.flush()
        u = Usuario(
            inquilino_id=inq.id,
            email=EMAIL,
            papel=DONO,
            troca_senha_obrigatoria=False,
        )
        s.add(u)
        s.flush()
        s.add(
            Identidade(
                usuario_id=u.id,
                provedor=auth.PROVEDOR_SENHA,
                subject=EMAIL,
                segredo_hash=auth.hash_de_senha(SENHA),
            )
        )
    db.encerrar()


@pytest.fixture
def cliente_local(tmp_path, monkeypatch):
    """Modo padrão: sem login, como o produto homologado hoje."""
    monkeypatch.setattr(app_mod, "_pipeline", PipelineVazio())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "s"))
    monkeypatch.setattr(app_mod, "EXIGIR_LOGIN", False)
    with TestClient(app_mod.app) as c:
        yield c


@pytest.fixture
def cliente_login(tmp_path, monkeypatch):
    """Modo com login, sobre SQLite em arquivo.

    Arquivo e não memória: a subida do app reabre o banco pela `ANON_DB_URL`,
    e `:memory:` daria um banco vazio na segunda conexão.

    `COOKIE_SEGURO` desligado só aqui: o `TestClient` fala `http://testserver`,
    e o cofre de cookies do httpx recusa cookie `Secure` em HTTP. O padrão de
    produção continua sendo `Secure`, e há teste abaixo que trava isso.
    """
    url = f"sqlite+pysqlite:///{tmp_path / 'identidade.db'}"
    _semear(url)
    monkeypatch.setenv("ANON_DB_URL", url)
    monkeypatch.setattr(app_mod, "_pipeline", PipelineVazio())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "s"))
    monkeypatch.setattr(app_mod, "EXIGIR_LOGIN", True)
    monkeypatch.setattr(app_mod, "COOKIE_SEGURO", False)
    with TestClient(app_mod.app) as c:
        yield c
    db.encerrar()


def _entrar(cliente, senha=SENHA, email=EMAIL):
    return cliente.post("/api/login", json={"email": email, "senha": senha})


def _com_csrf(cliente):
    """Cabeçalho que o JS da página monta a partir do cookie legível."""
    return {app_mod.CABECALHO_CSRF: cliente.cookies[app_mod.COOKIE_CSRF]}


# --------------------------------------------------------------------------
# A trava que separa os dois modos
# --------------------------------------------------------------------------
def test_com_login_exigido_rota_de_documento_responde_401(cliente_login):
    """O teste mais importante deste arquivo.

    Sem sessão, nenhuma rota de documento responde — nem a de upload, nem as
    que levam `doc_id`. A exigência mora no gargalo `pegar_sessao`, e
    `test_posse_rotas.py` prova que toda rota de documento passa por ele.
    """
    assert cliente_login.get("/api/doc/qualquer").status_code == 401
    assert cliente_login.get("/api/doc/qualquer/pagina/0.png").status_code == 401
    assert cliente_login.post("/api/doc/qualquer/aprovar").status_code == 401


def test_com_login_exigido_o_upload_tambem_fecha(cliente_login, tmp_pdf):
    caminho = tmp_pdf(["Documento de teste"], nome="x.pdf")
    with open(caminho, "rb") as fh:
        r = cliente_login.post(
            "/api/doc", files={"arquivo": ("x.pdf", fh, "application/pdf")}
        )
    assert r.status_code == 401


def test_a_pagina_e_a_saude_continuam_abertas(cliente_login):
    """Senão não há como chegar à tela de login nem monitorar o serviço."""
    assert cliente_login.get("/").status_code == 200
    assert cliente_login.get("/api/saude").status_code == 200


def test_em_modo_local_nao_existe_login(cliente_local):
    """Ligar o login é decisão de quem publica a porta, não acidente."""
    assert _entrar(cliente_local).status_code == 409


# --------------------------------------------------------------------------
# Entrar e sair
# --------------------------------------------------------------------------
def test_login_correto_abre_sessao(cliente_login):
    r = _entrar(cliente_login)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["papel"] == DONO
    assert corpo["troca_senha_obrigatoria"] is False
    assert app_mod.COOKIE_SESSAO in cliente_login.cookies


def test_depois_de_entrar_a_rota_de_documento_responde(cliente_login):
    assert _entrar(cliente_login).status_code == 200
    # 404 e não 401: passou pela autenticação e o documento é que não existe.
    assert cliente_login.get("/api/doc/inexistente").status_code == 404


def test_o_cookie_de_sessao_e_inacessivel_ao_javascript(cliente_login):
    """`HttpOnly` é o que faz um XSS não virar roubo de sessão.

    O cookie anti-CSRF é o oposto, e precisa ser: é o JS da própria página que
    o copia para o cabeçalho. A assimetria é o desenho, não descuido.
    """
    r = _entrar(cliente_login)
    # `get_list`: `items()` colapsa Set-Cookie repetido num só valor.
    cabecalhos = r.headers.get_list("set-cookie")
    sessao = [c for c in cabecalhos if c.startswith(app_mod.COOKIE_SESSAO)]
    csrf = [c for c in cabecalhos if c.startswith(app_mod.COOKIE_CSRF)]
    assert sessao and "httponly" in sessao[0].lower()
    assert csrf and "httponly" not in csrf[0].lower()
    for c in sessao + csrf:
        assert "samesite=lax" in c.lower()


def test_senha_errada_e_email_inexistente_respondem_igual(cliente_login):
    errada = _entrar(cliente_login, senha="errada")
    sem_conta = _entrar(cliente_login, email="ninguem@exemplo.test")
    assert errada.status_code == 401 and sem_conta.status_code == 401
    assert errada.json()["detail"] == sem_conta.json()["detail"]


def test_excesso_de_tentativas_responde_429(cliente_login):
    for _ in range(auth.MAX_TENTATIVAS):
        assert _entrar(cliente_login, senha="errada").status_code == 401
    r = _entrar(cliente_login)
    assert r.status_code == 429, "a trava de tentativa precisa ser distinguível"


def test_logout_mata_a_sessao_no_servidor(cliente_login):
    """Não basta apagar o cookie: o token antigo não pode mais valer."""
    assert _entrar(cliente_login).status_code == 200
    token = cliente_login.cookies[app_mod.COOKIE_SESSAO]

    r = cliente_login.post("/api/logout", headers=_com_csrf(cliente_login))
    assert r.status_code == 200 and r.json()["encerrada"] is True

    # Reapresenta o token à mão, como faria quem o tivesse copiado.
    r = cliente_login.get(
        "/api/doc/qualquer", cookies={app_mod.COOKIE_SESSAO: token}
    )
    assert r.status_code == 401


# --------------------------------------------------------------------------
# CSRF
# --------------------------------------------------------------------------
def test_requisicao_com_cookie_e_sem_cabecalho_e_recusada(cliente_login):
    """O formato do ataque: o navegador manda o cookie, o site de fora colhe.

    Sem o cabeçalho — que só o JS da própria origem consegue montar — a
    requisição é 403.
    """
    assert _entrar(cliente_login).status_code == 200
    assert cliente_login.post("/api/logout").status_code == 403


def test_cabecalho_errado_e_recusado(cliente_login):
    assert _entrar(cliente_login).status_code == 200
    r = cliente_login.post(
        "/api/logout", headers={app_mod.CABECALHO_CSRF: "nao-e-o-token"}
    )
    assert r.status_code == 403


def test_sem_cookie_de_sessao_nao_se_exige_csrf(cliente_local, tmp_pdf):
    """Em modo local não há cookie, então não há CSRF a montar.

    Exigir o cabeçalho aqui quebraria todo cliente de linha de comando sem
    comprar segurança nenhuma — CSRF é ataque que monta em cookie.
    """
    caminho = tmp_pdf(["Documento de teste"], nome="x.pdf")
    with open(caminho, "rb") as fh:
        r = cliente_local.post(
            "/api/doc", files={"arquivo": ("x.pdf", fh, "application/pdf")}
        )
    assert r.status_code in (200, 422)  # 422 = sem texto extraível; não é 403


# --------------------------------------------------------------------------
# Troca de senha
# --------------------------------------------------------------------------
def test_trocar_senha_derruba_as_sessoes_e_a_antiga_para_de_valer(cliente_login):
    assert _entrar(cliente_login).status_code == 200
    token_antigo = cliente_login.cookies[app_mod.COOKIE_SESSAO]
    r = cliente_login.post(
        "/api/senha",
        json={"atual": SENHA, "nova": "outra senha bem comprida 456"},
        headers=_com_csrf(cliente_login),
    )
    assert r.status_code == 200, r.text

    # O token de antes da troca morreu — é o que derruba quem já estava dentro.
    r = cliente_login.get(
        "/api/doc/qualquer", cookies={app_mod.COOKIE_SESSAO: token_antigo}
    )
    assert r.status_code == 401
    assert _entrar(cliente_login, senha=SENHA).status_code == 401
    assert _entrar(cliente_login, senha="outra senha bem comprida 456").status_code == 200


def test_trocar_senha_segue_logado_com_token_novo(cliente_login):
    """Primeiro acesso: troca a senha e cai na tela inicial, sem novo login.

    Quem fez a requisição já provou a senha atual. O token novo é outro — o
    antigo não é reaproveitado — e a obrigação de trocar fica para trás.
    """
    assert _entrar(cliente_login).status_code == 200
    token_antigo = cliente_login.cookies[app_mod.COOKIE_SESSAO]
    r = cliente_login.post(
        "/api/senha",
        json={"atual": SENHA, "nova": "outra senha bem comprida 456"},
        headers=_com_csrf(cliente_login),
    )
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["papel"] == DONO
    assert corpo["troca_senha_obrigatoria"] is False

    token_novo = cliente_login.cookies[app_mod.COOKIE_SESSAO]
    assert token_novo != token_antigo
    eu = cliente_login.get("/api/eu")
    assert eu.status_code == 200
    assert eu.json()["troca_senha_obrigatoria"] is False
    # 404 e não 401: a sessão nova autentica.
    assert cliente_login.get("/api/doc/inexistente").status_code == 404


def test_senha_nova_curta_e_recusada(cliente_login):
    assert _entrar(cliente_login).status_code == 200
    r = cliente_login.post(
        "/api/senha",
        json={"atual": SENHA, "nova": "curta"},
        headers=_com_csrf(cliente_login),
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Travas de configuração
# --------------------------------------------------------------------------
def test_o_padrao_do_cookie_e_secure():
    """O teste desliga `Secure`; o produto não pode.

    Cookie de sessão sem `Secure` viaja em HTTP claro, e aí a sessão é
    capturável por quem estiver no caminho. O padrão precisa ser seguro
    mesmo que alguém esqueça de configurar.
    """
    import importlib

    recarregado = importlib.reload(app_mod)
    try:
        assert recarregado.COOKIE_SEGURO is True
        assert recarregado.EXIGIR_LOGIN is False, (
            "o padrão precisa ser o modo local; publicar a porta é decisão "
            "explícita de quem publica"
        )
    finally:
        importlib.reload(app_mod)
