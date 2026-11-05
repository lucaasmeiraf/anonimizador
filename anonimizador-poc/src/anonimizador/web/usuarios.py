"""Quem o dono do inquilino pode criar, e sob que regras.

Bloco 2b do `goal-fase-4.md`, pela tela em vez da linha de comando. Lógica
pura sobre o banco, sem HTTP — como `auth.py` e `posse.py`.

## Não existe autocadastro, e isso é decisão

Ninguém cria a própria conta. O dono do inquilino cria, entrega a credencial
por fora, e o primeiro acesso obriga a troca. A tabela `solicitacao` existe
no esquema para o dia em que houver convite, e continua sem rota: enquanto
não houver, autocadastro seria uma porta aberta num produto que guarda
documento de terceiro.

## A senha é sorteada, não escolhida por quem cria

Duas razões, e a segunda é a que decide:

1. Senha escolhida por quem provisiona costuma ser fraca e reaproveitada
   entre as pessoas que recebem.
2. **Quem cria não deveria saber a senha final de ninguém.** A sorteada vale
   para um login só — `troca_senha_obrigatoria` nasce `True` —, então o dono
   entrega um bilhete de uso único e não fica sabendo a senha com que a
   pessoa vai trabalhar. É o que separa "administrar acesso" de "poder entrar
   como a outra pessoa".

Ela aparece **uma vez**, em claro, para quem criou. Não é guardada: no banco
só existe o hash Argon2id, como qualquer outra.

## O que o dono não pode fazer

| | Por quê |
|---|---|
| criar `plataforma` | papel de quem opera o sistema, não de quem usa um inquilino |
| mexer em usuário de outro inquilino | é o mesmo isolamento de `posse.py` |
| desativar a si mesmo | trancaria o inquilino sem administrador |
| ver ou escolher a senha de alguém | ver acima |

Desativar, e não apagar: a trilha referencia o usuário, e apagar deixaria a
auditoria apontando para o nada.
"""

from __future__ import annotations

import logging
import re
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.modelos import DONO, OPERADOR, PLATAFORMA, Identidade, Usuario, agora
from . import auth

logger = logging.getLogger(__name__)

# Papéis que o dono de um inquilino pode atribuir. `plataforma` fica de fora:
# ela não pertence a inquilino nenhum e administra o sistema todo.
PAPEIS_ATRIBUIVEIS = (OPERADOR, DONO)

# Bytes da senha temporária. 18 bytes de `secrets` em base64 dão 24
# caracteres — curto o bastante para ser ditado ao telefone, longo o bastante
# para não ser adivinhado no uso único que ela tem.
BYTES_SENHA = 18

# Validação de e-mail deliberadamente frouxa: aqui ele é só identificador de
# login, e não há envio de mensagem. Recusar endereço exótico de órgão
# público custaria mais do que a rigidez compraria.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NaoAutorizado(RuntimeError):
    """Quem pediu não tem papel, ou não alcança o alvo."""


class DadosInvalidos(ValueError):
    """E-mail malformado, papel inexistente, e-mail já em uso."""


def _exigir_dono(solicitante: Usuario) -> None:
    if solicitante.papel != DONO:
        raise NaoAutorizado(
            "apenas o dono do inquilino administra usuários"
        )
    if solicitante.inquilino_id is None:
        # `dono` sem inquilino não deveria existir; se existir, é defeito de
        # provisionamento, e seguir daqui criaria usuário órfão.
        raise NaoAutorizado("usuário sem inquilino não administra ninguém")


def _mesmo_inquilino(s: Session, solicitante: Usuario, usuario_id: str) -> Usuario:
    alvo = s.get(Usuario, usuario_id)
    if alvo is None or alvo.inquilino_id != solicitante.inquilino_id:
        # Mesmo motivo do 404 em `posse.py`: não confirmar que a conta existe.
        raise NaoAutorizado("usuário inexistente neste inquilino")
    return alvo


def nova_senha() -> str:
    """Senha temporária. Usada aqui e pela CLI, para não haver duas receitas."""
    return secrets.token_urlsafe(BYTES_SENHA)


def listar(s: Session, solicitante: Usuario) -> list[dict]:
    """Os usuários do inquilino de quem perguntou. Nunca de outro."""
    _exigir_dono(solicitante)
    linhas = s.execute(
        select(Usuario)
        .where(Usuario.inquilino_id == solicitante.inquilino_id)
        .order_by(Usuario.criado_em)
    ).scalars()
    return [
        {
            "id": u.id,
            "email": u.email,
            "papel": u.papel,
            "ativo": u.ativo,
            "troca_senha_obrigatoria": u.troca_senha_obrigatoria,
            "ultimo_acesso": u.ultimo_acesso.isoformat() if u.ultimo_acesso else None,
            "sou_eu": u.id == solicitante.id,
        }
        for u in linhas
    ]


def criar(
    s: Session, solicitante: Usuario, email: str, papel: str = OPERADOR
) -> tuple[str, str]:
    """Cria no inquilino de quem pediu. Devolve `(id, senha em claro)`.

    A senha volta **uma vez** e some: quem chamou precisa mostrá-la na hora.
    """
    _exigir_dono(solicitante)

    email = (email or "").strip().lower()
    if not _EMAIL.match(email):
        raise DadosInvalidos("e-mail inválido")
    if papel not in PAPEIS_ATRIBUIVEIS:
        raise DadosInvalidos(
            f"papel inválido: {papel!r}. Use {' ou '.join(PAPEIS_ATRIBUIVEIS)}."
        )

    existente = s.execute(
        select(Usuario).where(Usuario.email == email)
    ).scalar_one_or_none()
    if existente is not None:
        # A unicidade é global (há `UniqueConstraint` em `usuario.email`), e a
        # mensagem não diz de qual inquilino é — um dono não precisa saber que
        # aquele e-mail já usa o sistema noutro cliente.
        raise DadosInvalidos("este e-mail já está em uso")

    senha = nova_senha()
    novo = Usuario(
        inquilino_id=solicitante.inquilino_id,
        email=email,
        papel=papel,
        troca_senha_obrigatoria=True,
    )
    s.add(novo)
    s.flush()
    s.add(
        Identidade(
            usuario_id=novo.id,
            provedor=auth.PROVEDOR_SENHA,
            subject=email,
            segredo_hash=auth.hash_de_senha(senha),
        )
    )
    # Id e papel no log; e-mail e senha nunca. Ver invariante 4.
    logger.info("usuario %s criado (%s) por %s", novo.id, papel, solicitante.id)
    return novo.id, senha


def redefinir_senha(s: Session, solicitante: Usuario, usuario_id: str) -> str:
    """Nova senha temporária, e todas as sessões do alvo caem.

    Sem e-mail não há "esqueci minha senha": redefinir é ação de
    administrador, e está registrado como dívida no `goal-fase-4.md` §3.

    Derrubar as sessões é parte do conserto, não extra: se a conta foi
    redefinida porque alguém suspeita de acesso indevido, deixar a sessão do
    invasor viva não resolveria nada.
    """
    _exigir_dono(solicitante)
    alvo = _mesmo_inquilino(s, solicitante, usuario_id)

    identidade = s.execute(
        select(Identidade)
        .where(Identidade.provedor == auth.PROVEDOR_SENHA)
        .where(Identidade.usuario_id == alvo.id)
    ).scalar_one_or_none()
    if identidade is None:
        raise DadosInvalidos("este usuário não entra por senha")

    senha = nova_senha()
    identidade.segredo_hash = auth.hash_de_senha(senha)
    alvo.troca_senha_obrigatoria = True
    auth.fechar_sessoes_do_usuario(s, alvo.id)
    logger.info("senha redefinida para %s por %s", alvo.id, solicitante.id)
    return senha


def alternar_ativo(
    s: Session, solicitante: Usuario, usuario_id: str, ativo: bool
) -> dict:
    """Liga ou desliga o acesso. Desativar derruba as sessões abertas."""
    _exigir_dono(solicitante)
    alvo = _mesmo_inquilino(s, solicitante, usuario_id)

    if alvo.id == solicitante.id and not ativo:
        raise DadosInvalidos(
            "você não pode desativar a si mesmo; o inquilino ficaria sem "
            "administrador"
        )

    alvo.ativo = ativo
    if not ativo:
        # Sem isto, desligar alguém só teria efeito quando a sessão dele
        # expirasse sozinha — até 12 h depois.
        auth.fechar_sessoes_do_usuario(s, alvo.id)
    logger.info("usuario %s ativo=%s por %s", alvo.id, ativo, solicitante.id)
    return {"id": alvo.id, "ativo": alvo.ativo}
