"""Esquema de identidade, inquilino e trilha.

Plano em `goal-fase-4.md`. **Nada aqui guarda documento.**

## A invariante que este módulo existe para respeitar

> O banco guarda identidade e trilha. O documento e seus valores ficam em
> disco, com TTL.

`SpanUI.valor` carrega o valor da PII em texto. Quando um banco entra num
projeto, a tentação natural é *"persistir a sessão para poder escalar"* — e
isso transformaria o banco num arquivo de dados pessoais, com backup, réplica,
WAL e retenção própria, fora dos dez vetores que o `verifier` confere e sem TTL
nenhum. Quebra a invariante 9 do `CLAUDE.md`, e é a brecha mais fácil de abrir
porque tudo continuaria funcionando.

Por isso `sessao_dono` guarda **só a posse** — `doc_id`, inquilino, usuário.
O conteúdo da sessão não entra aqui, e não deve entrar depois.

## Por que o esquema é portável

Sem `JSONB`, sem array, sem `SERIAL`, sem `now()` do servidor. Chave primária
é UUID gerado pela aplicação, e o carimbo de tempo vem do Python.

Dois motivos, e os dois são práticos:

1. O banco do cliente pode acabar não sendo Postgres. Descobrir isso depois de
   escrever SQL específico é caro.
2. Os testes rodam em container `network_mode: none` — sem rede, sem Postgres
   alcançável. Com esquema portável eles rodam em SQLite em memória, e o
   mesmo código serve aos dois. Foi um efeito colateral feliz da decisão de
   portabilidade, e é o que mantém a suíte rápida.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Papéis. Ver `goal-fase-4.md` §3: o eixo é escopo de acesso, não estágio do
# fluxo. O operador faz o laço inteiro do documento sozinho — revisar e
# aprovar são a mesma pessoa, de propósito.
OPERADOR = "operador"
DONO = "dono"
PLATAFORMA = "plataforma"
PAPEIS = (OPERADOR, DONO, PLATAFORMA)

# Provedores de identidade. `senha` é o de hoje; `oidc:<emissor>` entra depois
# sem tocar em sessão nem em autorização — é o ponto da tabela `Identidade`.
PROVEDOR_SENHA = "senha"

# Ações da trilha.
ACOES = (
    "upload",
    "revisao",
    "aprovacao",
    "download",
    "pseudonimizar",
    "envio_externo",
    "remocao",
    "login",
    "login_falho",
    "usuario_criado",
    "senha_trocada",
)


def _novo_id() -> str:
    """UUID gerado pela aplicação, não sequência do banco.

    Sequência é o tipo de coisa que muda de nome entre dialetos (`SERIAL`,
    `IDENTITY`, `AUTOINCREMENT`) e que impede gerar o id antes de gravar.
    """
    return str(uuid.uuid4())


def agora() -> datetime:
    """Sempre em UTC e explícito.

    `now()` do servidor amarraria o esquema ao dialeto, e `datetime.utcnow()`
    devolve um objeto ingênuo que compara errado com um consciente.
    """
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Inquilino(Base):
    """Um cliente. No plano pessoa física, um inquilino de um usuário só."""

    __tablename__ = "inquilino"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_novo_id)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=agora
    )


class Usuario(Base):
    """Quem entra. A credencial **não** mora aqui — mora em `Identidade`."""

    __tablename__ = "usuario"
    __table_args__ = (
        UniqueConstraint("email", name="uq_usuario_email"),
        Index("ix_usuario_inquilino", "inquilino_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_novo_id)
    # NULO para `plataforma`: ela não pertence a um inquilino, e é exatamente
    # por isso que não abre documento. Ver `goal-fase-4.md` §3.
    inquilino_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inquilino.id"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    papel: Mapped[str] = mapped_column(String(20), nullable=False, default=OPERADOR)
    ativo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Sem e-mail não há autoatendimento de senha: a aprovação gera uma senha
    # temporária, e o primeiro acesso obriga a troca. Sem esta trava a senha
    # temporária vira permanente — o modo de falha padrão de todo
    # provisionamento sem e-mail.
    troca_senha_obrigatoria: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=agora
    )
    ultimo_acesso: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Identidade(Base):
    """Como um usuário prova quem é. Uma linha por provedor.

    É esta tabela que torna a federação um acréscimo em vez de uma refatoração:
    a sessão referencia `Usuario`, nunca a senha. Ligar OIDC depois é inserir
    linhas com `provedor='oidc:<emissor>'` e uma rota de callback — nada em
    autorização muda.
    """

    __tablename__ = "identidade"
    __table_args__ = (
        UniqueConstraint("provedor", "subject", name="uq_identidade_provedor_subject"),
        Index("ix_identidade_usuario", "usuario_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_novo_id)
    usuario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("usuario.id"), nullable=False
    )
    provedor: Mapped[str] = mapped_column(String(64), nullable=False)
    # E-mail no provedor `senha`; o `sub` do token no OIDC.
    subject: Mapped[str] = mapped_column(String(320), nullable=False)
    # Só existe no provedor `senha`. Hash lento (Argon2id) — nunca a senha.
    segredo_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=agora
    )


class Solicitacao(Base):
    """Pedido de cadastro, aprovado na tela por `dono` ou `plataforma`."""

    __tablename__ = "solicitacao"
    __table_args__ = (Index("ix_solicitacao_estado", "estado"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_novo_id)
    inquilino_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inquilino.id"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendente")
    decidida_por: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("usuario.id"), nullable=True
    )
    quando: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=agora
    )


class SessaoDono(Base):
    """A quem pertence um documento em revisão. **Só a posse.**

    O `doc_id` continua sendo `secrets.token_urlsafe(9)` e continua
    imprevisível — o que é bom —, mas deixa de ser a autorização. Quem
    autoriza é esta tabela.

    Nada do conteúdo da sessão entra aqui: nem texto, nem span, nem valor.
    Ver o cabeçalho deste módulo.
    """

    __tablename__ = "sessao_dono"
    __table_args__ = (Index("ix_sessao_dono_inquilino", "inquilino_id"),)

    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    inquilino_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("inquilino.id"), nullable=False
    )
    usuario_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("usuario.id"), nullable=False
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=agora
    )


class Trilha(Base):
    """Quem fez o quê, quando. **Nunca o quê em si.**

    `detalhe` aceita contagem, entidade, vetor, modelo — nunca valor de PII.
    É a mesma regra da invariante 4 do `CLAUDE.md` e o mesmo raciocínio do
    `SpanSemRetangulo`: quem investiga tem o documento em mãos, e o valor só
    criaria mais uma cópia com retenção própria.

    `nome_arquivo` é o campo mais perigoso desta tabela: `processo-fulano.pdf`
    carrega um nome. Fica **nulo por padrão** e a decisão de preenchê-lo é
    consciente — ver `goal-fase-4.md` §4.
    """

    __tablename__ = "trilha"
    __table_args__ = (
        Index("ix_trilha_inquilino_quando", "inquilino_id", "quando"),
        Index("ix_trilha_doc", "doc_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_novo_id)
    inquilino_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inquilino.id"), nullable=True
    )
    usuario_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("usuario.id"), nullable=True
    )
    doc_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acao: Mapped[str] = mapped_column(String(32), nullable=False)
    # Texto curto, serializado pela aplicação. `Text` e não `JSONB`: o segundo
    # não existe fora do Postgres.
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    nome_arquivo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quando: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=agora
    )


class LoginFalho(Base):
    """Tentativas malsucedidas, para o limite de tentativa.

    Sem limite, o hash lento perde o efeito: quem tem tempo tenta à vontade.
    """

    __tablename__ = "login_falho"
    __table_args__ = (Index("ix_login_falho_email_quando", "email", "quando"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quando: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=agora
    )


class TokenServico(Base):
    """Credencial de automação — provisionamento por MCP, adiante.

    Existe separada da sessão humana por um motivo de segurança: uma rota de
    automação que aceitasse cookie de navegador seria um caminho de CSRF com
    privilégio de administrador.

    O escopo **nunca** alcança documento, pelo mesmo motivo que `plataforma`
    não abre documento.
    """

    __tablename__ = "token_servico"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_novo_id)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    escopo: Mapped[str] = mapped_column(String(200), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=agora
    )
    revogado_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
