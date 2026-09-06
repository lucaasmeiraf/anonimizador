"""Conexão com o banco de identidade. Falha alto, nunca em silêncio.

## A decisão do Bloco 1 do `goal-fase-4.md`

> *"O `ui` sobe **sem o banco no ar**? Decidir: falhar alto na subida é
> preferível a servir sem autenticação por engano."*

**Resposta: falha na subida.** A alternativa seria subir e descobrir o
problema na primeira requisição — e aí só há dois desfechos possíveis, os dois
ruins: ou toda requisição devolve 500, o que é inútil, ou alguém "conserta"
deixando o sistema seguir sem autenticação, que é catastrófico.

É a mesma regra do resto do projeto: falhar alto e cedo é sempre preferível a
degradar em silêncio.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .modelos import Base

logger = logging.getLogger(__name__)

# Sem valor padrão de produção embutido. O compose injeta a URL do serviço
# `postgres`; os testes injetam SQLite em memória. Ausência é erro, não
# convite a um fallback silencioso.
URL_ENV = "ANON_DB_URL"

_engine: Engine | None = None
_Sessao: sessionmaker[Session] | None = None


class BancoIndisponivel(RuntimeError):
    """Não há banco utilizável. Erro terminal, nunca contornável."""


def url_configurada() -> str:
    url = os.getenv(URL_ENV, "").strip()
    if not url:
        raise BancoIndisponivel(
            f"{URL_ENV} não definida. O serviço de identidade não sobe sem "
            "banco — servir sem autenticação seria pior que não servir."
        )
    return url


def iniciar(url: str | None = None, criar_esquema: bool = False) -> Engine:
    """Abre o pool e **confere que o banco responde**, na subida.

    A conferência não é cerimônia: `create_engine` é preguiçoso e não conecta
    até a primeira consulta. Sem o `SELECT 1` aqui, um banco fora do ar
    passaria despercebido até a primeira requisição de um usuário.

    ``criar_esquema`` existe para os testes, que montam SQLite em memória.
    Em Postgres o esquema vem das migrações do Alembic — criar tabela na
    subida do serviço apagaria o histórico que permite atualizar a instalação
    de um cliente.
    """
    global _engine, _Sessao

    url = url or url_configurada()
    engine = create_engine(url, pool_pre_ping=True, future=True)

    try:
        with engine.connect() as con:
            con.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        # A URL carrega a senha. Registrar o dialeto basta para diagnosticar.
        raise BancoIndisponivel(
            f"banco não respondeu ({engine.dialect.name}): {type(exc).__name__}"
        ) from exc

    if criar_esquema:
        Base.metadata.create_all(engine)

    _engine = engine
    _Sessao = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    logger.info("banco de identidade pronto (%s)", engine.dialect.name)
    return engine


def encerrar() -> None:
    global _engine, _Sessao
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Sessao = None


@contextmanager
def sessao() -> Iterator[Session]:
    """Uma transação. Confirma no fim, desfaz em qualquer erro."""
    if _Sessao is None:
        raise BancoIndisponivel("banco não iniciado; chame iniciar() na subida")
    s = _Sessao()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def engine_atual() -> Engine:
    if _engine is None:
        raise BancoIndisponivel("banco não iniciado")
    return _engine
