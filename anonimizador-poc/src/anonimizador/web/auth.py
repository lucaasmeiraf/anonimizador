"""Identidade: hash de senha, sessão de login e limite de tentativa.

Bloco 2 do `goal-fase-4.md`. Lógica pura sobre o banco — **sem HTTP**. Cookie,
código de status e rota moram em `app.py`; o que está aqui é testável sem
subir servidor, como o resto das regras.

## Nada de criptografia escrita aqui

A regra que organiza este módulo: toda primitiva vem de biblioteca vetada ou
da biblioteca padrão. O que este arquivo escreve é o **fluxo** — e fluxo é o
que nenhuma biblioteca pode escrever por você, porque depende das regras do
produto.

| Peça | De onde vem |
|---|---|
| Hash de senha | ``argon2-cffi`` — `PasswordHasher`, Argon2id, parâmetros do próprio pacote |
| Token de sessão | ``secrets.token_urlsafe`` — CSPRNG do sistema |
| Hash do token | ``hashlib.sha256`` — ver a nota em `modelos.SessaoLogin` |
| Comparação | ``secrets.compare_digest`` — tempo constante |

Argon2id é a escolha do `goal-fase-4.md` §5, e os parâmetros são os padrões
do `argon2-cffi` de propósito: eles acompanham a recomendação corrente do
pacote, e fixá-los aqui à mão congelaria em 2026 um número que deve subir com
o hardware. `check_needs_rehash` cuida da migração quando o padrão mudar.

## Três coisas que são fáceis de errar, e por que estão como estão

**1. Não dizer se o e-mail existe.** `autenticar` devolve a mesma falha para
e-mail inexistente e senha errada, **e gasta o mesmo tempo nos dois casos** —
verificando a senha contra um hash de descarte quando o usuário não existe.
Sem isso, o tempo de resposta vira um oráculo de "esta pessoa tem conta
aqui", que num produto de anonimização de documento é informação sensível por
si: diz quem é cliente.

**2. O limite de tentativa vem antes do hash.** Argon2 é lento de propósito;
se a conferência rodasse antes da trava, cada tentativa recusada ainda
custaria CPU, e a trava protegeria a senha mas não o servidor.

**3. Nada de e-mail no log.** E-mail é dado pessoal, e a invariante 4 do
`CLAUDE.md` não fala só de PII de documento: um log é cópia fora do arquivo
saneado, com retenção própria. O log daqui registra id de usuário, contagem e
resultado — nunca o e-mail, nunca o IP, nunca a senha. A tabela `login_falho`
guarda e-mail e IP porque o limite por e-mail precisa deles, e isso é decisão
registrada do `goal-fase-4.md` §4; log é outra coisa.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db.modelos import Identidade, LoginFalho, SessaoLogin, Usuario, agora

logger = logging.getLogger(__name__)

PROVEDOR_SENHA = "senha"

# --------------------------------------------------------------------------
# Parâmetros
# --------------------------------------------------------------------------
# Bytes de entropia do token de sessão. 32 bytes = 256 bits: não há força
# bruta contra isso, e é o que dispensa hash lento na tabela.
TOKEN_BYTES = 32

# Validade absoluta da sessão. Expira mesmo em uso — sessão eterna é risco
# eterno, do mesmo jeito que cofre eterno e trilha eterna.
VALIDADE = timedelta(hours=12)

# Validade por inatividade. Mais curta de propósito: o caso que ela cobre é a
# estação destravada numa repartição, com o documento em claro na tela.
INATIVIDADE = timedelta(minutes=30)

# Limite de tentativa. Cinco falhas na janela e o e-mail para de ser aceito,
# **mesmo com a senha certa** — é o que impede que o hash lento seja o único
# obstáculo. A janela é curta para não transformar o limite em negação de
# serviço contra o dono da conta: quem errou cinco vezes espera 15 minutos.
MAX_TENTATIVAS = 5
JANELA_TENTATIVAS = timedelta(minutes=15)

_hasher = PasswordHasher()

# Hash de descarte, para gastar tempo quando o usuário não existe. O valor da
# senha é irrelevante: ninguém o usa para entrar.
_HASH_DESCARTE = _hasher.hash(secrets.token_urlsafe(32))


class FalhaDeLogin(RuntimeError):
    """Base. A mensagem é mostrada ao usuário e nunca distingue causas."""


class CredencialInvalida(FalhaDeLogin):
    def __init__(self) -> None:
        super().__init__("e-mail ou senha incorretos")


class ExcessoDeTentativas(FalhaDeLogin):
    def __init__(self) -> None:
        super().__init__(
            "muitas tentativas; espere alguns minutos antes de tentar de novo"
        )


@dataclass(frozen=True)
class SessaoAberta:
    """O resultado de um login. ``token`` só existe aqui e no cookie."""

    token: str
    usuario_id: str
    papel: str
    inquilino_id: str | None
    troca_senha_obrigatoria: bool
    expira_em: datetime


# --------------------------------------------------------------------------
# Senha
# --------------------------------------------------------------------------
def hash_de_senha(senha: str) -> str:
    return _hasher.hash(senha)


def conferir_senha(hash_armazenado: str, senha: str) -> bool:
    """Confere, sem levantar exceção para senha errada.

    `VerifyMismatchError` é senha errada. O resto é hash corrompido ou de
    formato desconhecido, e também vira `False` — com log, porque é defeito de
    dado, não tentativa de invasão.

    `ValueError` está na lista por um caso que apareceu ao escrever o teste:
    hash com caractere não-ASCII faz o `argon2-cffi` levantar
    `UnicodeEncodeError` — que é `ValueError`, e **não** é exceção dele. Sem
    isto, dado corrompido no banco viraria erro 500 na rota de login em vez de
    credencial recusada.

    O que deliberadamente **não** se faz aqui é capturar `Exception`: numa
    conferência de credencial, engolir o inesperado é como um defeito de
    código se transforma em "entrou".
    """
    try:
        return _hasher.verify(hash_armazenado, senha)
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHashError, ValueError, TypeError):
        logger.error("hash de senha ilegível no banco; identidade precisa de reset")
        return False


def precisa_rehash(hash_armazenado: str) -> bool:
    """O hash foi feito com parâmetros mais fracos que os de hoje?"""
    try:
        return _hasher.check_needs_rehash(hash_armazenado)
    except (VerificationError, InvalidHashError):
        return False


# --------------------------------------------------------------------------
# Limite de tentativa
# --------------------------------------------------------------------------
def _chave_email(email: str) -> str:
    return email.strip().lower()


def tentativas_recentes(s: Session, email: str, de: datetime | None = None) -> int:
    desde = (de or agora()) - JANELA_TENTATIVAS
    return int(
        s.execute(
            select(func.count())
            .select_from(LoginFalho)
            .where(LoginFalho.email == _chave_email(email))
            .where(LoginFalho.quando >= desde)
        ).scalar_one()
    )


def registrar_falha(s: Session, email: str, ip: str | None = None) -> None:
    s.add(LoginFalho(email=_chave_email(email), ip=ip))


def limpar_falhas(s: Session, email: str) -> None:
    """Login bem-sucedido zera o contador daquele e-mail.

    Sem isto, quem erra quatro vezes, acerta, e erra uma quinta semanas depois
    é bloqueado por tentativas que já não dizem nada.
    """
    s.execute(delete(LoginFalho).where(LoginFalho.email == _chave_email(email)))


# --------------------------------------------------------------------------
# Sessão
# --------------------------------------------------------------------------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def abrir_sessao(s: Session, usuario: Usuario) -> str:
    """Cria a sessão e devolve o token em claro — a única vez que ele existe."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    s.add(
        SessaoLogin(
            token_hash=_hash_token(token),
            usuario_id=usuario.id,
            expira_em=agora() + VALIDADE,
        )
    )
    logger.info("sessao de login aberta para usuario %s", usuario.id)
    return token


def usuario_da_sessao(s: Session, token: str | None) -> Usuario | None:
    """Resolve o cookie em usuário, ou ``None``. **Falha fechada.**

    Devolve ``None`` para token ausente, desconhecido, expirado por validade,
    expirado por inatividade, ou de usuário desativado. Quem chama transforma
    isso em 401 — nunca em "segue como anônimo".
    """
    if not token:
        return None

    linha = s.get(SessaoLogin, _hash_token(token))
    if linha is None:
        return None

    momento = agora()
    if momento >= _consciente(linha.expira_em):
        s.delete(linha)
        return None
    if momento - _consciente(linha.ultimo_uso) >= INATIVIDADE:
        s.delete(linha)
        return None

    usuario = s.get(Usuario, linha.usuario_id)
    if usuario is None or not usuario.ativo:
        # Desativar o usuário derruba a sessão dele na próxima requisição. Sem
        # isto, desligar alguém não teria efeito até a sessão expirar sozinha.
        s.delete(linha)
        return None

    linha.ultimo_uso = momento
    return usuario


def fechar_sessao(s: Session, token: str | None) -> bool:
    """Logout. Apaga a linha — o cookie deixa de valer de fato."""
    if not token:
        return False
    linha = s.get(SessaoLogin, _hash_token(token))
    if linha is None:
        return False
    s.delete(linha)
    logger.info("sessao de login encerrada para usuario %s", linha.usuario_id)
    return True


def fechar_sessoes_do_usuario(s: Session, usuario_id: str) -> int:
    """Derruba **todas** as sessões de um usuário.

    É o que a troca de senha precisa chamar: senha trocada com sessão antiga
    ainda válida não protege contra quem já estava dentro, que é justamente o
    motivo de alguém trocar a senha.
    """
    n = s.execute(
        delete(SessaoLogin).where(SessaoLogin.usuario_id == usuario_id)
    ).rowcount
    logger.info("%d sessao(oes) derrubada(s) do usuario %s", n or 0, usuario_id)
    return int(n or 0)


def expirar_sessoes(s: Session) -> int:
    """Varredura das vencidas, para a tabela não crescer sem fim."""
    n = s.execute(
        delete(SessaoLogin).where(SessaoLogin.expira_em < agora())
    ).rowcount
    return int(n or 0)


# --------------------------------------------------------------------------
# O laço completo
# --------------------------------------------------------------------------
def autenticar(
    s: Session, email: str, senha: str, ip: str | None = None
) -> SessaoAberta:
    """Confere a credencial e abre a sessão. Levanta `FalhaDeLogin` ao falhar.

    A ordem das etapas é a parte que importa, e cada uma está comentada na
    seção "três coisas fáceis de errar" do cabeçalho.

    **Quem falha não registra a falha: quem chama registra.** Esta função
    levanta, e uma transação que termina em exceção é desfeita — então a linha
    de `login_falho` gravada aqui dentro ia embora no `rollback`, e o limite
    de tentativa contava zero para sempre.

    Isso **aconteceu**, em 2026-11-03, e passou pelo teste unitário: lá o
    `pytest.raises` captura a exceção dentro do `with db.sessao()`, o commit
    roda, e a linha persiste. Pela rota HTTP a exceção sobe, o rollback
    acontece, e a trava não existia. Verde pelo motivo errado.

    Por isso o registro é do chamador, em transação própria — ver
    `app.login`. O preço é uma linha a mais na rota; o ganho é não haver
    commit escondido dentro de uma função de regra.
    """
    if tentativas_recentes(s, email) >= MAX_TENTATIVAS:
        # Antes de qualquer Argon2: a trava protege a senha **e** a CPU.
        logger.warning("login recusado por excesso de tentativas")
        raise ExcessoDeTentativas()

    identidade = s.execute(
        select(Identidade)
        .where(Identidade.provedor == PROVEDOR_SENHA)
        .where(Identidade.subject == _chave_email(email))
    ).scalar_one_or_none()

    # Usuário inexistente gasta o mesmo tempo que senha errada: a conferência
    # roda de verdade, contra um hash de descarte, e o resultado é ignorado.
    # Sem isso a latência da resposta diz quem tem conta aqui.
    armazenado = (
        identidade.segredo_hash
        if identidade is not None and identidade.segredo_hash
        else _HASH_DESCARTE
    )
    senha_confere = conferir_senha(armazenado, senha)

    usuario = s.get(Usuario, identidade.usuario_id) if identidade else None
    if identidade is None or not senha_confere or usuario is None or not usuario.ativo:
        logger.warning("login recusado")
        raise CredencialInvalida()

    if precisa_rehash(armazenado):
        # Parâmetros do Argon2 subiram desde que a senha foi criada. O único
        # momento em que a senha em claro está disponível para refazer o hash
        # é agora.
        identidade.segredo_hash = hash_de_senha(senha)
        logger.info("hash de senha atualizado para usuario %s", usuario.id)

    limpar_falhas(s, email)
    usuario.ultimo_acesso = agora()
    token = abrir_sessao(s, usuario)

    return SessaoAberta(
        token=token,
        usuario_id=usuario.id,
        papel=usuario.papel,
        inquilino_id=usuario.inquilino_id,
        troca_senha_obrigatoria=usuario.troca_senha_obrigatoria,
        expira_em=agora() + VALIDADE,
    )


def trocar_senha(s: Session, usuario: Usuario, atual: str, nova: str) -> None:
    """Troca a senha, confere a atual e derruba as outras sessões.

    Pede a senha atual mesmo com a sessão já autenticada: sem isso, um XSS ou
    um navegador deixado aberto troca a senha e toma a conta. É a mesma razão
    pela qual todo sistema sério repete a senha nessa tela.
    """
    identidade = s.execute(
        select(Identidade)
        .where(Identidade.provedor == PROVEDOR_SENHA)
        .where(Identidade.usuario_id == usuario.id)
    ).scalar_one_or_none()
    if identidade is None or not identidade.segredo_hash:
        raise CredencialInvalida()
    if not conferir_senha(identidade.segredo_hash, atual):
        raise CredencialInvalida()

    identidade.segredo_hash = hash_de_senha(nova)
    usuario.troca_senha_obrigatoria = False
    fechar_sessoes_do_usuario(s, usuario.id)
    logger.info("senha trocada para usuario %s", usuario.id)


def _consciente(momento: datetime) -> datetime:
    """SQLite devolve datetime ingênuo; Postgres devolve consciente.

    Comparar os dois levanta `TypeError`, e o lugar onde isso apareceria é a
    expiração de sessão — ou seja, falharia exatamente na trava de segurança,
    e só no banco que os testes não usam.
    """
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)
