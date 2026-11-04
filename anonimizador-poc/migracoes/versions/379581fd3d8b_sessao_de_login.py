"""sessao de login

Tabela de sessao aberta, para o Bloco 2 da Fase 4.

Existe porque cookie assinado NAO da para invalidar: quem tem o cookie segue
entrando ate ele expirar, inclusive depois do logout. O critério de aceite do
goal-fase-4 secao 8 exige que logout invalide de fato, e que trocar a senha
derrube as outras sessoes. As duas coisas pedem estado no servidor.

A chave primaria e o HASH do token, nunca o token: vazamento do banco nao
vira acesso. SHA-256 e suficiente aqui — o token e 256 bits de `secrets`, nao
ha o que adivinhar, e Argon2 nele só tornaria cada requisicao mais lenta.

Revision ID: 379581fd3d8b
Revises: 9b2e8f63be3c
Create Date: 2026-11-04 01:11:58.991283
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '379581fd3d8b'
down_revision: Union[str, None] = '9b2e8f63be3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('sessao_login',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('usuario_id', sa.String(length=36), nullable=False),
    sa.Column('criado_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expira_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ultimo_uso', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['usuario_id'], ['usuario.id'], ),
    sa.PrimaryKeyConstraint('token_hash')
    )
    op.create_index('ix_sessao_login_expira', 'sessao_login', ['expira_em'], unique=False)
    op.create_index('ix_sessao_login_usuario', 'sessao_login', ['usuario_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_sessao_login_usuario', table_name='sessao_login')
    op.drop_index('ix_sessao_login_expira', table_name='sessao_login')
    op.drop_table('sessao_login')
