"""O envio do documento: o que é recusado, e o que a recusa deixa para trás.

A propriedade que importa é a invariante 9: o original em claro só existe
dentro de uma sessão registrada, alcançável por TTL e por `DELETE`. Medido em
2026-09-23: um PDF com senha passava pela checagem de `%PDF`, era gravado, e a
extração estourava — 500 para o usuário e o original numa pasta que nenhuma
sessão registrava.
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from anonimizador.web import app as app_mod


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_pipeline", type("P", (), {"analyze": lambda s, t, **k: []})())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "sessoes"))
    with TestClient(app_mod.app) as c:
        yield c


def _pastas():
    return [p for p in app_mod.sessoes.raiz.iterdir() if p.is_dir()]


def _subir(cliente, dados, nome="doc.pdf"):
    return cliente.post("/api/doc", files={"arquivo": (nome, dados, "application/pdf")})


def test_pdf_com_senha_e_recusado_sem_deixar_o_original_em_disco(cliente, tmp_path):
    pdf = fitz.open()
    pdf.new_page().insert_text((56, 64), "Contratante: Mariana Aparecida Souza.", fontname="helv", fontsize=9)
    caminho = tmp_path / "senha.pdf"
    pdf.save(str(caminho), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="abc", owner_pw="xyz")
    pdf.close()

    r = _subir(cliente, caminho.read_bytes())

    assert r.status_code == 422
    assert "senha" in r.json()["detail"]
    assert _pastas() == [], "o original com senha ficou gravado fora de uma sessão"


def test_pdf_ilegivel_e_recusado_sem_deixar_nada(cliente):
    r = _subir(cliente, b"%PDF-1.7\nisto nao e um pdf de verdade")
    assert r.status_code == 422
    assert _pastas() == []


def test_falha_depois_de_gravar_apaga_a_pasta(cliente, tmp_path, monkeypatch):
    """Qualquer erro depois da gravação não pode deixar o original solto."""
    from anonimizador.web import sessao as sessao_mod

    def explode(doc):
        raise RuntimeError("falha simulada na extração")

    monkeypatch.setattr(sessao_mod, "build_text_map", explode)
    pdf = fitz.open()
    pdf.new_page().insert_text((56, 64), "Texto qualquer.", fontname="helv", fontsize=9)
    dados = pdf.tobytes()
    pdf.close()

    with pytest.raises(RuntimeError):
        app_mod.sessoes.criar("doc.pdf", dados)
    assert _pastas() == []


def test_paginas_sem_texto_sao_informadas(cliente):
    """Documento parcialmente escaneado: segue para a revisão, mas a tela
    precisa dizer quais páginas a detecção não leu."""
    pdf = fitz.open()
    pdf.new_page().insert_text((56, 64), "Pagina com texto.", fontname="helv", fontsize=9)
    pdf.new_page()  # sem texto, como uma digitalização
    pdf.new_page().insert_text((56, 64), "Outra pagina com texto.", fontname="helv", fontsize=9)
    dados = pdf.tobytes()
    pdf.close()

    r = _subir(cliente, dados)
    assert r.status_code == 200
    assert r.json()["caracteristicas"]["paginas_sem_texto"] == [2]


def test_saude_informa_tipos_e_limite(cliente):
    from anonimizador import config

    d = cliente.get("/api/saude").json()
    assert d["tipos"] == list(config.ENTIDADES_ATIVAS)
    assert d["limite_mb"] == app_mod.MAX_BYTES // (1024 * 1024)
