"""O dono administra o inquilino dele — e só ele, e só o dele.

Bloco 2b do `goal-fase-4.md` pela tela. O que estes testes protegem não é "a
criação funciona": é cada regra que, faltando, transforma a tela de
configurações numa escada de privilégio.

A mais importante é a ausência: **não existe autocadastro**. Há teste que
percorre as rotas e falha se alguma aparecer.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from anonimizador import db
from anonimizador.db.modelos import (
    DONO,
    OPERADOR,
    PLATAFORMA,
    Identidade,
    Inquilino,
    Usuario,
)
from anonimizador.web import app as app_mod
from anonimizador.web import auth

SENHA = "uma senha longa o suficiente 123"


class PipelineVazio:
    def analyze(self, texto, score_threshold=None):  # noqa: ARG002
        return []


def _semear(email, inquilino_nome, papel=DONO):
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
    url = f"sqlite+pysqlite:///{tmp_path / 'id.db'}"
    db.encerrar()
    db.iniciar(url, criar_esquema=True)
    _semear("dono@alfa.test", "Alfa", DONO)
    _semear("op@alfa.test", "Alfa", OPERADOR)
    _semear("dono@beta.test", "Beta", DONO)
    db.encerrar()

    monkeypatch.setenv("ANON_DB_URL", url)
    monkeypatch.setattr(app_mod, "_pipeline", PipelineVazio())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "s"))
    monkeypatch.setattr(app_mod, "EXIGIR_LOGIN", True)
    monkeypatch.setattr(app_mod, "COOKIE_SEGURO", False)
    yield
    db.encerrar()


def _cliente(email):
    c = TestClient(app_mod.app)
    c.__enter__()
    assert c.post("/api/login", json={"email": email, "senha": SENHA}).status_code == 200
    return c


def _csrf(c):
    return {app_mod.CABECALHO_CSRF: c.cookies[app_mod.COOKIE_CSRF]}


# --------------------------------------------------------------------------
# A ausência que é funcionalidade
# --------------------------------------------------------------------------
def test_nao_existe_rota_de_autocadastro():
    """Ninguém cria a própria conta. O dono cria e entrega por fora.

    Percorre `app.routes` em vez de conferir uma lista escrita à mão: a rota
    que alguém acrescentar amanhã cai aqui, e é justamente a que ninguém
    lembraria de acrescentar a uma lista.
    """
    suspeitas = []
    for r in app_mod.app.routes:
        if not isinstance(r, APIRoute):
            continue
        caminho = r.path.lower()
        if any(p in caminho for p in ("registr", "cadastr", "signup", "inscri")):
            suspeitas.append(f"{sorted(r.methods)} {r.path}")
    assert not suspeitas, "rota de autocadastro apareceu: " + ", ".join(suspeitas)


# --------------------------------------------------------------------------
# Quem pode administrar
# --------------------------------------------------------------------------
def test_dono_cria_usuario_e_recebe_a_senha_uma_vez(ambiente):
    c = _cliente("dono@alfa.test")
    r = c.post(
        "/api/usuarios",
        json={"email": "NOVO@Alfa.test", "papel": "operador"},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["email"] == "novo@alfa.test", "o e-mail precisa ser normalizado"
    assert len(corpo["senha"]) >= 20

    # E a senha serve, uma vez, com troca obrigatória.
    novo = TestClient(app_mod.app)
    with novo:
        entrada = novo.post(
            "/api/login", json={"email": "novo@alfa.test", "senha": corpo["senha"]}
        )
        assert entrada.status_code == 200
        assert entrada.json()["troca_senha_obrigatoria"] is True


def test_a_senha_nao_fica_guardada_em_claro(ambiente):
    c = _cliente("dono@alfa.test")
    senha = c.post(
        "/api/usuarios", json={"email": "x@alfa.test"}, headers=_csrf(c)
    ).json()["senha"]

    with db.sessao() as s:
        ident = (
            s.query(Identidade).filter(Identidade.subject == "x@alfa.test").one()
        )
        assert senha not in ident.segredo_hash
        assert ident.segredo_hash.startswith("$argon2id$")


def test_operador_nao_administra(ambiente):
    """Papel é o eixo: operador faz o laço do documento, não gerencia gente."""
    c = _cliente("op@alfa.test")
    assert c.get("/api/usuarios").status_code == 403
    r = c.post("/api/usuarios", json={"email": "z@alfa.test"}, headers=_csrf(c))
    assert r.status_code == 403


def test_a_lista_mostra_so_o_proprio_inquilino(ambiente):
    alfa = _cliente("dono@alfa.test")
    emails = {u["email"] for u in alfa.get("/api/usuarios").json()["usuarios"]}
    assert emails == {"dono@alfa.test", "op@alfa.test"}
    assert "dono@beta.test" not in emails


def test_dono_nao_alcanca_usuario_de_outro_inquilino(ambiente):
    beta = _cliente("dono@beta.test")
    with db.sessao() as s:
        alvo = s.query(Usuario).filter(Usuario.email == "op@alfa.test").one().id

    assert beta.post(
        f"/api/usuarios/{alvo}/senha", headers=_csrf(beta)
    ).status_code == 403
    assert beta.patch(
        f"/api/usuarios/{alvo}", json={"ativo": False}, headers=_csrf(beta)
    ).status_code == 403


# --------------------------------------------------------------------------
# Limites do que o dono pode
# --------------------------------------------------------------------------
def test_dono_nao_cria_plataforma(ambiente):
    """`plataforma` opera o sistema todo; não é papel que um cliente atribui."""
    c = _cliente("dono@alfa.test")
    r = c.post(
        "/api/usuarios",
        json={"email": "super@alfa.test", "papel": "plataforma"},
        headers=_csrf(c),
    )
    assert r.status_code == 422
    assert "papel inválido" in r.json()["detail"]


def test_email_repetido_e_recusado(ambiente):
    c = _cliente("dono@alfa.test")
    r = c.post("/api/usuarios", json={"email": "op@alfa.test"}, headers=_csrf(c))
    assert r.status_code == 422
    # Não diz de qual inquilino é: um dono não precisa saber que aquele
    # e-mail já usa o sistema noutro cliente.
    assert "Beta" not in r.text and "inquilino" not in r.json()["detail"]


def test_email_invalido_e_recusado(ambiente):
    c = _cliente("dono@alfa.test")
    r = c.post("/api/usuarios", json={"email": "nao-e-email"}, headers=_csrf(c))
    assert r.status_code == 422


def test_dono_nao_desativa_a_si_mesmo(ambiente):
    """Senão o inquilino fica sem administrador, e sem caminho de volta."""
    c = _cliente("dono@alfa.test")
    eu = next(u for u in c.get("/api/usuarios").json()["usuarios"] if u["sou_eu"])
    r = c.patch(f"/api/usuarios/{eu['id']}", json={"ativo": False}, headers=_csrf(c))
    assert r.status_code == 422
    assert "si mesmo" in r.json()["detail"]


# --------------------------------------------------------------------------
# Redefinir e desativar
# --------------------------------------------------------------------------
def test_redefinir_senha_derruba_as_sessoes_do_alvo(ambiente):
    """Se foi redefinida por suspeita de invasão, a sessão do invasor cai."""
    op = _cliente("op@alfa.test")
    assert op.get("/api/eu").status_code == 200
    with db.sessao() as s:
        alvo = s.query(Usuario).filter(Usuario.email == "op@alfa.test").one().id

    dono = _cliente("dono@alfa.test")
    nova = dono.post(f"/api/usuarios/{alvo}/senha", headers=_csrf(dono)).json()["senha"]

    assert op.get("/api/eu").status_code == 401, "a sessão antiga sobreviveu"

    c = TestClient(app_mod.app)
    with c:
        r = c.post("/api/login", json={"email": "op@alfa.test", "senha": nova})
        assert r.status_code == 200
        assert r.json()["troca_senha_obrigatoria"] is True


def test_desativar_derruba_a_sessao_e_barra_novo_login(ambiente):
    op = _cliente("op@alfa.test")
    with db.sessao() as s:
        alvo = s.query(Usuario).filter(Usuario.email == "op@alfa.test").one().id

    dono = _cliente("dono@alfa.test")
    assert dono.patch(
        f"/api/usuarios/{alvo}", json={"ativo": False}, headers=_csrf(dono)
    ).status_code == 200

    assert op.get("/api/eu").status_code == 401
    c = TestClient(app_mod.app)
    with c:
        assert c.post(
            "/api/login", json={"email": "op@alfa.test", "senha": SENHA}
        ).status_code == 401


def test_reativar_devolve_o_acesso(ambiente):
    # O cliente vem primeiro: é a subida do app que liga o banco, e consultar
    # antes dela levanta `BancoIndisponivel`.
    dono = _cliente("dono@alfa.test")
    with db.sessao() as s:
        alvo = s.query(Usuario).filter(Usuario.email == "op@alfa.test").one().id
    dono.patch(f"/api/usuarios/{alvo}", json={"ativo": False}, headers=_csrf(dono))
    dono.patch(f"/api/usuarios/{alvo}", json={"ativo": True}, headers=_csrf(dono))

    c = TestClient(app_mod.app)
    with c:
        assert c.post(
            "/api/login", json={"email": "op@alfa.test", "senha": SENHA}
        ).status_code == 200


# --------------------------------------------------------------------------
# Transporte
# --------------------------------------------------------------------------
def test_administrar_exige_o_cabecalho_anti_csrf(ambiente):
    c = _cliente("dono@alfa.test")
    r = c.post("/api/usuarios", json={"email": "sem-csrf@alfa.test"})
    assert r.status_code == 403


def test_sem_sessao_nao_se_administra_nada(ambiente):
    c = TestClient(app_mod.app)
    with c:
        assert c.get("/api/usuarios").status_code == 401
