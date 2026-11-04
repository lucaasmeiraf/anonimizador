"""O núcleo de identidade — Bloco 2 do `goal-fase-4.md`.

Roda em SQLite em memória, como `test_db.py`, e pelo mesmo motivo: o serviço
de teste tem `network_mode: none`, então não há Postgres alcançável. O esquema
portável é o que permite isso.

O que estes testes protegem não é "o login funciona" — é cada uma das travas
que, faltando, deixa o login *parecendo* funcionar:

- senha guardada em claro, ou com hash rápido;
- mensagem que diz se o e-mail existe;
- tempo de resposta que diz se o e-mail existe;
- hash lento rodando antes da trava de tentativa, e portanto servindo de
  amplificador de negação de serviço;
- logout que apaga o cookie e deixa a sessão viva;
- senha trocada com a sessão antiga ainda válida;
- usuário desativado que continua entrando até a sessão expirar.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from anonimizador import db
from anonimizador.db.modelos import (
    DONO,
    Identidade,
    Inquilino,
    LoginFalho,
    SessaoLogin,
    Usuario,
    agora,
)
from anonimizador.web import auth

SENHA = "uma senha longa o suficiente 123"
EMAIL = "operador@exemplo.test"


@pytest.fixture
def banco():
    db.encerrar()
    db.iniciar("sqlite+pysqlite:///:memory:", criar_esquema=True)
    yield
    db.encerrar()


@pytest.fixture
def usuario(banco):
    """Um inquilino com um usuário e identidade de senha."""
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
        s.flush()
        return u.id


# --------------------------------------------------------------------------
# Senha
# --------------------------------------------------------------------------
def test_a_senha_nao_fica_recuperavel(usuario):
    """Nem em claro, nem com hash rápido: o formato precisa ser Argon2id."""
    with db.sessao() as s:
        ident = s.query(Identidade).one()
        assert SENHA not in ident.segredo_hash
        assert ident.segredo_hash.startswith("$argon2id$"), (
            f"hash não é Argon2id: {ident.segredo_hash[:20]!r}"
        )


def test_o_mesmo_segredo_gera_hashes_diferentes(banco):
    """Sal por hash. Hash igual para senha igual entrega quem repetiu senha."""
    assert auth.hash_de_senha(SENHA) != auth.hash_de_senha(SENHA)


def test_confere_sem_explodir_com_senha_errada(banco):
    h = auth.hash_de_senha(SENHA)
    assert auth.conferir_senha(h, SENHA) is True
    assert auth.conferir_senha(h, SENHA + "x") is False


def test_hash_corrompido_nao_autentica_ninguem(banco, caplog):
    """Dado ilegível no banco é `False`, nunca `True` por acidente."""
    assert auth.conferir_senha("isto não é um hash", SENHA) is False


# --------------------------------------------------------------------------
# O que o atacante não deve conseguir saber
# --------------------------------------------------------------------------
def test_email_inexistente_e_senha_errada_dizem_a_mesma_coisa(usuario):
    with db.sessao() as s:
        with pytest.raises(auth.CredencialInvalida) as sem_conta:
            auth.autenticar(s, "ninguem@exemplo.test", SENHA)
    with db.sessao() as s:
        with pytest.raises(auth.CredencialInvalida) as senha_errada:
            auth.autenticar(s, EMAIL, "errada")
    assert str(sem_conta.value) == str(senha_errada.value)


def test_email_inexistente_gasta_o_mesmo_tempo(usuario):
    """A latência não pode virar oráculo de "esta pessoa é cliente".

    Sem o hash de descarte, o caminho do e-mail inexistente sairia sem rodar
    Argon2 e responderia numa fração do tempo. A margem é generosa de
    propósito: o que se exige é a mesma ordem de grandeza, não igualdade —
    medir tempo em CI é ruidoso.
    """

    def medir(email, senha):
        with db.sessao() as s:
            inicio = time.perf_counter()
            with pytest.raises(auth.CredencialInvalida):
                auth.autenticar(s, email, senha)
            return time.perf_counter() - inicio

    sem_conta = min(medir("ninguem@exemplo.test", SENHA) for _ in range(3))
    com_conta = min(medir(EMAIL, "errada") for _ in range(3))
    assert sem_conta > com_conta / 3, (
        f"e-mail inexistente respondeu em {sem_conta * 1000:.0f} ms contra "
        f"{com_conta * 1000:.0f} ms — a latência denuncia quem tem conta"
    )


def test_nenhum_log_carrega_email_ou_senha(usuario, caplog):
    """Invariante 4: log é cópia de dado fora do arquivo saneado."""
    import logging

    with caplog.at_level(logging.DEBUG):
        with db.sessao() as s:
            with pytest.raises(auth.CredencialInvalida):
                auth.autenticar(s, EMAIL, "errada")
        with db.sessao() as s:
            auth.autenticar(s, EMAIL, SENHA)

    texto = "\n".join(r.getMessage() for r in caplog.records)
    assert EMAIL not in texto
    assert SENHA not in texto


# --------------------------------------------------------------------------
# Limite de tentativa
# --------------------------------------------------------------------------
def _errar(email=EMAIL, senha="errada"):
    """Uma tentativa falha completa — como a rota faz.

    O registro da falha é do chamador, em transação própria, porque a
    transação de `autenticar` termina em exceção e é desfeita. Esta função
    existe para que os testes exercitem o mesmo caminho da rota, e não o
    acidente de o `pytest.raises` capturar dentro do `with`.
    """
    with db.sessao() as s:
        with pytest.raises(auth.CredencialInvalida):
            auth.autenticar(s, email, senha)
    with db.sessao() as s:
        auth.registrar_falha(s, email)


def test_a_falha_registrada_sobrevive_ao_rollback(usuario):
    """A trava só existe se a linha persistir, e ela quase não persistia.

    `autenticar` levanta; uma transação que acaba em exceção é desfeita. Com o
    registro dentro dela, `login_falho` ficava vazia e o limite contava zero —
    defeito achado em 2026-11-03 pelo teste de HTTP, não por este arquivo.
    """
    _errar()
    with db.sessao() as s:
        assert s.query(LoginFalho).count() == 1
        assert auth.tentativas_recentes(s, EMAIL) == 1


def test_excesso_de_tentativas_barra_mesmo_com_a_senha_certa(usuario):
    for _ in range(auth.MAX_TENTATIVAS):
        _errar()

    with db.sessao() as s:
        with pytest.raises(auth.ExcessoDeTentativas):
            auth.autenticar(s, EMAIL, SENHA)


def test_a_trava_corre_antes_do_hash_lento(usuario, monkeypatch):
    """Se o Argon2 rodasse primeiro, a trava não protegeria a CPU.

    Sabotamos a conferência de senha para explodir. Com a ordem certa, a
    requisição barrada nem chega nela.
    """
    for _ in range(auth.MAX_TENTATIVAS):
        _errar()

    def nao_deveria_rodar(*a, **k):
        raise AssertionError("o hash rodou antes da trava de tentativa")

    monkeypatch.setattr(auth, "conferir_senha", nao_deveria_rodar)
    with db.sessao() as s:
        with pytest.raises(auth.ExcessoDeTentativas):
            auth.autenticar(s, EMAIL, SENHA)


def test_login_bem_sucedido_zera_o_contador(usuario):
    for _ in range(auth.MAX_TENTATIVAS - 1):
        _errar()

    with db.sessao() as s:
        auth.autenticar(s, EMAIL, SENHA)
    with db.sessao() as s:
        assert s.query(LoginFalho).count() == 0


def test_tentativa_velha_nao_conta(usuario):
    """A janela é deslizante: quem errou ontem não é barrado hoje."""
    with db.sessao() as s:
        for _ in range(auth.MAX_TENTATIVAS):
            s.add(
                LoginFalho(
                    email=EMAIL,
                    quando=agora() - auth.JANELA_TENTATIVAS - timedelta(minutes=1),
                )
            )
    with db.sessao() as s:
        assert auth.tentativas_recentes(s, EMAIL) == 0
        auth.autenticar(s, EMAIL, SENHA)  # não levanta


# --------------------------------------------------------------------------
# Sessão
# --------------------------------------------------------------------------
def test_o_token_nao_fica_no_banco(usuario):
    """Vazamento do banco não pode virar acesso."""
    with db.sessao() as s:
        aberta = auth.autenticar(s, EMAIL, SENHA)
        token = aberta.token
    with db.sessao() as s:
        (linha,) = s.query(SessaoLogin).all()
        assert linha.token_hash != token
        assert token not in linha.token_hash


def test_sessao_resolve_o_usuario(usuario):
    with db.sessao() as s:
        token = auth.autenticar(s, EMAIL, SENHA).token
    with db.sessao() as s:
        u = auth.usuario_da_sessao(s, token)
        assert u is not None and u.id == usuario


@pytest.mark.parametrize("token", [None, "", "token-inventado", "a" * 43])
def test_token_invalido_falha_fechado(usuario, token):
    """Ausente, vazio ou inventado: sempre `None`, nunca anônimo-que-passa."""
    with db.sessao() as s:
        assert auth.usuario_da_sessao(s, token) is None


def test_logout_invalida_de_fato(usuario):
    """Critério de aceite §8: não basta apagar o cookie do navegador."""
    with db.sessao() as s:
        token = auth.autenticar(s, EMAIL, SENHA).token
    with db.sessao() as s:
        assert auth.fechar_sessao(s, token) is True
    with db.sessao() as s:
        assert auth.usuario_da_sessao(s, token) is None


def test_sessao_vencida_nao_vale(usuario):
    with db.sessao() as s:
        token = auth.autenticar(s, EMAIL, SENHA).token
    with db.sessao() as s:
        linha = s.query(SessaoLogin).one()
        linha.expira_em = agora() - timedelta(seconds=1)
    with db.sessao() as s:
        assert auth.usuario_da_sessao(s, token) is None
        assert s.query(SessaoLogin).count() == 0, "a linha vencida devia sair"


def test_inatividade_derruba_a_sessao(usuario):
    """A estação destravada com documento em claro na tela."""
    with db.sessao() as s:
        token = auth.autenticar(s, EMAIL, SENHA).token
    with db.sessao() as s:
        linha = s.query(SessaoLogin).one()
        linha.ultimo_uso = agora() - auth.INATIVIDADE - timedelta(minutes=1)
    with db.sessao() as s:
        assert auth.usuario_da_sessao(s, token) is None


def test_uso_renova_a_inatividade(usuario):
    with db.sessao() as s:
        token = auth.autenticar(s, EMAIL, SENHA).token
    with db.sessao() as s:
        antes = s.query(SessaoLogin).one().ultimo_uso
    time.sleep(0.01)
    with db.sessao() as s:
        assert auth.usuario_da_sessao(s, token) is not None
    with db.sessao() as s:
        assert s.query(SessaoLogin).one().ultimo_uso > antes


def test_desativar_usuario_derruba_a_sessao(usuario):
    """Desligar alguém tem de ter efeito agora, não quando a sessão expirar."""
    with db.sessao() as s:
        token = auth.autenticar(s, EMAIL, SENHA).token
    with db.sessao() as s:
        s.get(Usuario, usuario).ativo = False
    with db.sessao() as s:
        assert auth.usuario_da_sessao(s, token) is None


# --------------------------------------------------------------------------
# Troca de senha
# --------------------------------------------------------------------------
def test_trocar_senha_exige_a_atual(usuario):
    """Sessão aberta não basta: senão um navegador esquecido toma a conta."""
    with db.sessao() as s:
        u = s.get(Usuario, usuario)
        with pytest.raises(auth.CredencialInvalida):
            auth.trocar_senha(s, u, "não é a atual", "outra senha longa 456")


def test_trocar_senha_derruba_as_outras_sessoes(usuario):
    """Senha trocada com sessão antiga viva não protege de quem já entrou."""
    with db.sessao() as s:
        antiga = auth.autenticar(s, EMAIL, SENHA).token
    with db.sessao() as s:
        u = s.get(Usuario, usuario)
        auth.trocar_senha(s, u, SENHA, "senha nova bem comprida 789")
    with db.sessao() as s:
        assert auth.usuario_da_sessao(s, antiga) is None
        assert auth.autenticar(s, EMAIL, "senha nova bem comprida 789")


def test_trocar_senha_desarma_a_obrigatoriedade(banco):
    """O primeiro acesso obriga a troca; trocar encerra a obrigação."""
    with db.sessao() as s:
        u = Usuario(email="novo@exemplo.test", troca_senha_obrigatoria=True)
        s.add(u)
        s.flush()
        s.add(
            Identidade(
                usuario_id=u.id,
                provedor=auth.PROVEDOR_SENHA,
                subject="novo@exemplo.test",
                segredo_hash=auth.hash_de_senha("temporaria de uso unico"),
            )
        )
        s.flush()
        uid = u.id

    with db.sessao() as s:
        aberta = auth.autenticar(s, "novo@exemplo.test", "temporaria de uso unico")
        assert aberta.troca_senha_obrigatoria is True

    with db.sessao() as s:
        auth.trocar_senha(
            s, s.get(Usuario, uid), "temporaria de uso unico", "definitiva longa 012"
        )
    with db.sessao() as s:
        assert s.get(Usuario, uid).troca_senha_obrigatoria is False


# --------------------------------------------------------------------------
# Federação, preparada e não implementada
# --------------------------------------------------------------------------
def test_identidade_de_outro_provedor_nao_entra_por_senha(banco):
    """Quem vem de OIDC não tem segredo aqui, e não pode virar porta aberta.

    O teste existe porque o caminho da senha procura por `provedor='senha'`.
    Se alguém relaxar esse filtro, uma identidade federada — que tem
    `segredo_hash` nulo — entraria com qualquer senha pelo caminho do hash de
    descarte.
    """
    with db.sessao() as s:
        u = Usuario(email="federado@exemplo.test")
        s.add(u)
        s.flush()
        s.add(
            Identidade(
                usuario_id=u.id,
                provedor="oidc:gov.br",
                subject="sub-123",
                segredo_hash=None,
            )
        )
    with db.sessao() as s:
        with pytest.raises(auth.CredencialInvalida):
            auth.autenticar(s, "federado@exemplo.test", "qualquer coisa")
        with pytest.raises(auth.CredencialInvalida):
            auth.autenticar(s, "sub-123", "qualquer coisa")
