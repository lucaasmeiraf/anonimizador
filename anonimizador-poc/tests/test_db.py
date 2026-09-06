"""Bloco 1 da Fase 4: a camada de banco, e o que ela não pode fazer.

Estes testes rodam no serviço `test`, que tem `network_mode: none` — sem
Postgres alcançável, por desenho. Eles usam **SQLite em memória**, e isso só é
possível porque o esquema foi mantido portável de propósito (sem `JSONB`, sem
array, sem `SERIAL`).

O teste de portabilidade abaixo não é decorativo: é ele que impede alguém
acrescentar um tipo específico do Postgres e, sem perceber, quebrar tanto a
suíte quanto a promessa de que o banco do cliente pode ser outro.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect

from anonimizador import db
from anonimizador.db import modelos


@pytest.fixture
def banco():
    """SQLite em memória, esquema criado a partir dos modelos."""
    db.encerrar()
    db.iniciar("sqlite+pysqlite:///:memory:", criar_esquema=True)
    yield
    db.encerrar()


# --------------------------------------------------------------------------
# A invariante: nenhum documento no banco
# --------------------------------------------------------------------------


def test_nenhuma_tabela_guarda_conteudo_de_documento(banco):
    """A invariante do `goal-fase-4.md` §1, travada por inspeção do esquema.

    Se alguém acrescentar uma coluna para "guardar o texto extraído" ou "o
    valor do span", este teste falha. É a defesa contra a decisão que parece
    puramente de engenharia — persistir a sessão para escalar — e que
    transformaria o banco num arquivo de dados pessoais com backup, réplica e
    retenção própria, fora dos dez vetores do verificador.
    """
    proibidas = {
        "texto", "conteudo", "valor", "valores", "span", "spans",
        "pdf", "documento", "original", "texto_extraido", "corpo",
    }
    insp = inspect(db.engine_atual())

    achadas = []
    for tabela in insp.get_table_names():
        for coluna in insp.get_columns(tabela):
            if coluna["name"].lower() in proibidas:
                achadas.append(f"{tabela}.{coluna['name']}")

    assert not achadas, (
        "coluna com cara de conteúdo de documento no banco de identidade: "
        f"{achadas}. Ver goal-fase-4.md §1 — o documento fica em disco, "
        "com TTL."
    )


def test_sessao_dono_guarda_so_a_posse(banco):
    """`sessao_dono` é a autorização, não um espelho da sessão."""
    colunas = {c["name"] for c in inspect(db.engine_atual()).get_columns("sessao_dono")}
    assert colunas == {"doc_id", "inquilino_id", "usuario_id", "criado_em"}


# --------------------------------------------------------------------------
# Portabilidade
# --------------------------------------------------------------------------


def test_esquema_nao_usa_tipo_exclusivo_do_postgres():
    """O banco do cliente pode não ser Postgres.

    Também é o que permite estes testes rodarem sem rede. Um `JSONB` aqui
    quebraria as duas coisas de uma vez.
    """
    proibidos = ("JSONB", "ARRAY", "SERIAL", "UUID", "INET", "TSVECTOR", "HSTORE")
    ofensas = []
    for tabela in modelos.Base.metadata.tables.values():
        for coluna in tabela.columns:
            nome_tipo = type(coluna.type).__name__.upper()
            if nome_tipo in proibidos:
                ofensas.append(f"{tabela.name}.{coluna.name}: {nome_tipo}")
    assert not ofensas, f"tipo específico do Postgres no esquema: {ofensas}"


def test_todas_as_tabelas_do_goal_existem(banco):
    esperadas = {
        "inquilino", "usuario", "identidade", "solicitacao",
        "sessao_dono", "trilha", "login_falho", "token_servico",
    }
    assert esperadas <= set(inspect(db.engine_atual()).get_table_names())


# --------------------------------------------------------------------------
# Falhar alto, nunca em silêncio
# --------------------------------------------------------------------------


def test_sem_url_configurada_falha_alto(monkeypatch):
    """Servir sem autenticação seria pior que não servir."""
    monkeypatch.delenv(db.URL_ENV, raising=False)
    with pytest.raises(db.BancoIndisponivel, match=db.URL_ENV):
        db.url_configurada()


def test_banco_fora_do_ar_falha_na_subida():
    """`create_engine` é preguiçoso; sem o SELECT 1 o erro só apareceria na
    primeira requisição de um usuário."""
    with pytest.raises(db.BancoIndisponivel, match="não respondeu"):
        db.iniciar("sqlite+pysqlite:////caminho/que/nao/existe/x.db")


def test_a_url_com_senha_nao_vaza_na_mensagem_de_erro():
    """A URL carrega a senha do banco. O dialeto basta para diagnosticar."""
    senha = "senha-secreta-do-banco"
    with pytest.raises(db.BancoIndisponivel) as exc:
        db.iniciar(f"sqlite+pysqlite:////nao/existe/{senha}/x.db")
    assert senha not in str(exc.value)


def test_usar_sessao_sem_iniciar_falha():
    db.encerrar()
    with pytest.raises(db.BancoIndisponivel):
        with db.sessao():
            pass


# --------------------------------------------------------------------------
# Escrita e leitura básicas
# --------------------------------------------------------------------------


def test_ciclo_de_gravacao(banco):
    with db.sessao() as s:
        inq = modelos.Inquilino(nome="Prefeitura Exemplo")
        s.add(inq)
        s.flush()
        usr = modelos.Usuario(
            inquilino_id=inq.id, email="alguem@exemplo.gov.br", papel=modelos.OPERADOR
        )
        s.add(usr)
        s.flush()
        s.add(
            modelos.Identidade(
                usuario_id=usr.id,
                provedor=modelos.PROVEDOR_SENHA,
                subject="alguem@exemplo.gov.br",
                segredo_hash="$argon2id$fake",
            )
        )
        ident_inq, ident_usr = inq.id, usr.id

    with db.sessao() as s:
        achado = s.get(modelos.Usuario, ident_usr)
        assert achado is not None
        assert achado.inquilino_id == ident_inq
        # Padrão: primeiro acesso obriga troca. Sem isso a senha temporária
        # vira permanente.
        assert achado.troca_senha_obrigatoria is True


def test_plataforma_nao_pertence_a_inquilino(banco):
    """`inquilino_id` nulo é o que a impede de abrir documento de alguém."""
    with db.sessao() as s:
        s.add(
            modelos.Usuario(
                email="plataforma@exemplo", papel=modelos.PLATAFORMA, inquilino_id=None
            )
        )
    with db.sessao() as s:
        p = s.query(modelos.Usuario).filter_by(papel=modelos.PLATAFORMA).one()
        assert p.inquilino_id is None


def test_identidade_permite_provedor_alem_de_senha(banco):
    """A federação é um acréscimo, não uma refatoração.

    Critério de aceite do `goal-fase-4.md` §8: precisa existir usuário com
    provedor diferente de `senha`, sem segredo guardado. Sem isso, "preparado
    para federação" é intenção, não fato.
    """
    with db.sessao() as s:
        u = modelos.Usuario(email="fed@exemplo.gov.br", papel=modelos.OPERADOR)
        s.add(u)
        s.flush()
        s.add(
            modelos.Identidade(
                usuario_id=u.id,
                provedor="oidc:https://login.exemplo.gov.br",
                subject="sub-opaco-do-emissor",
                segredo_hash=None,
            )
        )
        uid = u.id

    with db.sessao() as s:
        ident = s.query(modelos.Identidade).filter_by(usuario_id=uid).one()
        assert ident.provedor.startswith("oidc:")
        assert ident.segredo_hash is None
