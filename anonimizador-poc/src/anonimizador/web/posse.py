"""De quem é cada documento — Bloco 3 do `goal-fase-4.md`.

Lógica pura sobre o banco, sem HTTP, como `auth.py`. É o módulo que separa
"uma pessoa por servidor" de "vários clientes no mesmo servidor".

## O que muda, e é pouco código para muita consequência

Até aqui o `doc_id` era a autorização: quem tivesse o link tinha o documento.
Ele continua sendo `secrets.token_urlsafe(9)` e continua imprevisível — o que
é bom —, mas imprevisível **não é** o mesmo que autorizado. Dois usuários
autenticados no mesmo servidor alcançavam o documento um do outro bastando
saber o id.

Quem autoriza passa a ser a tabela `sessao_dono`.

## Três decisões que vêm do goal e não devem ser relaxadas

**404, nunca 403.** Documento de outro inquilino responde "não existe". O 403
diria *"existe, mas não é seu"*, que é uma informação a mais do que o chamador
precisa ter — num produto de anonimização, confirmar que um processo existe
num servidor já diz algo sobre quem é cliente de quem.

**`plataforma` não abre documento, de nenhum inquilino.** Ela administra:
cria inquilino, aprova cadastro. Um super-usuário que atravessa inquilinos e
ainda lê documento é porta dos fundos por desenho, e é a primeira coisa que
uma revisão de segurança de cliente institucional procura. Administrar e ler
são eixos diferentes; só o primeiro atravessa inquilino.

**A posse é do inquilino, não da pessoa.** Quem revisa é uma pessoa, mas o
documento é do órgão: se o operador sai de férias, o dono do inquilino
precisa alcançar o que ficou em revisão. Guardamos os dois — `usuario_id`
para a trilha saber quem subiu, `inquilino_id` para decidir quem alcança.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db.modelos import PLATAFORMA, SessaoDono, Usuario

logger = logging.getLogger(__name__)


def registrar(s: Session, doc_id: str, usuario: Usuario) -> None:
    """Marca o dono na criação do documento.

    `plataforma` não tem inquilino — e também não deveria chegar aqui, porque
    não abre documento. Se chegar, é defeito de rota, e falhar alto é melhor
    que gravar uma posse sem dono possível.
    """
    if usuario.inquilino_id is None:
        raise ValueError(
            f"usuário {usuario.id} ({usuario.papel}) não pertence a inquilino "
            "e não pode ser dono de documento"
        )
    s.add(
        SessaoDono(
            doc_id=doc_id,
            inquilino_id=usuario.inquilino_id,
            usuario_id=usuario.id,
        )
    )
    logger.info("documento %s registrado para o inquilino %s", doc_id, usuario.inquilino_id)


def alcanca(s: Session, doc_id: str, usuario: Usuario) -> bool:
    """O usuário pode abrir este documento?

    Devolve `False` — nunca levanta — para documento sem dono registrado. Um
    documento assim existe em memória e não no banco, o que acontece se
    alguém subiu antes de o login ser exigido; tratá-lo como inalcançável é o
    lado seguro.
    """
    if usuario.papel == PLATAFORMA:
        return False
    dono = s.get(SessaoDono, doc_id)
    if dono is None:
        return False
    return dono.inquilino_id == usuario.inquilino_id


def esquecer(s: Session, doc_id: str) -> None:
    """Apaga a posse quando o documento é descartado ou expira.

    Sem isto a tabela cresce para sempre guardando o id de documentos que já
    não existem — e `sessao_dono` é a única tabela cujas linhas falam de
    documento, ainda que só do id.
    """
    s.execute(delete(SessaoDono).where(SessaoDono.doc_id == doc_id))
