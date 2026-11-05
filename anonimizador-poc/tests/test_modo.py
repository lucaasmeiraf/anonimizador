"""A decisão de "esta porta pode ser exposta?" — uma, em Python, testada.

O alvo `tunel` publica a UI na internet. O que o separa de um vazamento é
uma pergunta: **há login exigido?** Até 2026-11-04 essa pergunta era um
`grep` pela string "COM LOGIN", escrito duas vezes — uma no `Makefile`,
outra no `run.ps1`.

Dois jeitos de isso dar errado, e os dois são silenciosos: um `grep` que casa
por engano abre o sistema para qualquer um, e um que deixa de casar quando
alguém reescreve a frase só irrita. Nenhum dos dois quebra teste, porque
shell em `Makefile` não tem teste.

Aqui tem.
"""

from __future__ import annotations

import pytest

from anonimizador.web import app as app_mod
from anonimizador.web import modo


def test_com_login_libera(monkeypatch):
    monkeypatch.setattr(app_mod, "EXIGIR_LOGIN", True)
    ok, recado = modo.exigir_login()
    assert ok is True
    assert recado == []
    assert modo.main(["--exigir-login"]) == 0


def test_sem_login_recusa_e_diz_por_que(monkeypatch):
    """Recusar sem explicar faz a pessoa contornar a trava."""
    monkeypatch.setattr(app_mod, "EXIGIR_LOGIN", False)
    ok, recado = modo.exigir_login()
    assert ok is False
    assert modo.main(["--exigir-login"]) == 1

    texto = "\n".join(recado)
    assert "RECUSADO" in texto
    assert "ANON_EXIGIR_LOGIN=1" in texto, "a saída precisa dizer o que fazer"
    assert "doc_id" in texto, "precisa dizer o que está em risco, não só que negou"


@pytest.mark.parametrize("ligado", [True, False])
def test_descrever_nunca_mente_sobre_o_modo(monkeypatch, ligado):
    """O texto de subida e a decisão vêm da mesma fonte.

    Se divergirem, a tela diz uma coisa e a trava decide outra — e o jeito
    de isso aparecer é alguém expor a porta achando que estava protegida.
    """
    monkeypatch.setattr(app_mod, "EXIGIR_LOGIN", ligado)
    texto = "\n".join(modo.descrever())
    assert ("COM LOGIN" in texto) is ligado
    assert modo.exigir_login()[0] is ligado


def test_a_fonte_da_verdade_e_uma_so(monkeypatch):
    """`modo` lê de `app`, não do ambiente por conta própria.

    Duas leituras independentes da mesma variável divergem no dia em que
    alguém acrescentar normalização num dos lados.
    """
    monkeypatch.setattr(app_mod, "EXIGIR_LOGIN", True)
    assert modo.EXIGIR_LOGIN_ATIVO() is True
    monkeypatch.setattr(app_mod, "EXIGIR_LOGIN", False)
    assert modo.EXIGIR_LOGIN_ATIVO() is False
