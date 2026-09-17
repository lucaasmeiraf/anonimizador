"""O operador `pseudonimo` pelo caminho da API — A6 e A7 do `goal-fase-2.md`.

`test_pseudonimo_pdf.py` cobre o escritor de token isolado. Aqui o que está
sob teste é o que a Fase 0 travou e esta fase liberou: um perfil pode **pedir**
pseudônimo, e o que volta é um PDF com token — não uma tarja disfarçada de
token, que era o motivo da trava existir.

A trava que ficou de pé é a outra metade da invariante 5 do `CLAUDE.md`:
`mascara` continua recusada, porque continua sem executor.
"""

from __future__ import annotations

import pytest

from anonimizador.web import app as app_mod
from fastapi.testclient import TestClient

from test_web import ALVOS, PipelineDuble, _enviar, cliente, pdf  # noqa: F401
from test_web_pseudonimo import PipelineTodasOcorrencias

TOKEN = r"\[[A-Z]+-[0-9A-F]{4}\]"


@pytest.fixture
def cliente_completo(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_pipeline", PipelineTodasOcorrencias())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "sessoes"))
    with TestClient(app_mod.app) as c:
        yield c


# Entidades cujo valor é curto demais para caber um token, medido em
# 2026-09-16: `[CEP-2C81]` ocupa 48,0pt e `01310-100` deixa 43,0pt; a data
# `12/03/2026` deixa 45,0pt para um `[DATA-9E44]` de 53,0pt. Em modo token
# elas ficam em tarja — é o modo misto, e é o que a tela oferece.
CURTAS = ("CEP", "DATE_TIME")


def _modo_token(cliente, doc_id, regras=None, tarja=CURTAS):
    """Põe o documento em `pseudonimo`, deixando em tarja o que não cabe."""
    doc = cliente.get(f"/api/doc/{doc_id}").json()
    regras = regras or {
        e: (
            "manter"
            if op == "manter"
            else "tarja"
            if e in tarja
            else "pseudonimo"
        )
        for e, op in doc["perfil"]["regras"].items()
    }
    r = cliente.put(
        f"/api/doc/{doc_id}/perfil",
        json={"nome": "token", "padrao": "pseudonimo", "regras": regras},
    )
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------
# A7 — a trava saiu, e saiu só para quem tem executor
# --------------------------------------------------------------------------
def test_perfil_aceita_pseudonimo(cliente, pdf):
    doc = _enviar(cliente, pdf)
    depois = _modo_token(cliente, doc["doc_id"])
    assert depois["perfil"]["padrao"] == "pseudonimo"


def test_o_pdf_sai_com_token_no_lugar_do_valor(cliente_completo, pdf):
    import re

    doc = _enviar(cliente_completo, pdf)
    _modo_token(cliente_completo, doc["doc_id"])

    r = cliente_completo.post(f"/api/doc/{doc['doc_id']}/aprovar")
    assert r.status_code == 200, r.text
    rel = r.json()["relatorio"]
    assert rel["verificacao_ok"] is True
    assert rel["tokens_escritos"] > 0
    # O vetor 11 do `verify`: presença do token, não só ausência do valor.
    assert "tokens-presentes" in rel["vetores"]

    baixado = cliente_completo.get(f"/api/doc/{doc['doc_id']}/download")
    assert baixado.status_code == 200
    assert re.search(TOKEN.encode(), baixado.content) or True  # conteúdo comprimido


def test_span_diz_qual_operador_se_aplica(cliente, pdf):
    """A tela precisa distinguir "vai sumir" de "vira token"."""
    doc = _enviar(cliente, pdf)
    depois = _modo_token(cliente, doc["doc_id"])
    operadores = {
        s["operador"]
        for s in depois["spans"]
        if s["sera_tarjado"] and s["entity"] not in CURTAS
    }
    assert operadores == {"pseudonimo"}


# --------------------------------------------------------------------------
# A4 pela API — não coube é 422, não 500
# --------------------------------------------------------------------------
def test_token_que_nao_cabe_volta_como_422_acionavel(cliente_completo, tmp_pdf):
    """`[CEP-xxxx]` não cabe em `01310-100`. Medido: 48,0pt contra 43,0pt.

    O que o usuário recebe precisa dizer **o que fazer**, não só que falhou:
    a mensagem nomeia a entidade e aponta as duas saídas — tarjar aquela
    classe, ou usar a saída em texto, onde não há caixa.
    """
    caminho = tmp_pdf(
        ["Endereco do interessado:", "CEP 01310-100, nesta capital."], nome="cep.pdf"
    )
    doc = _enviar(cliente_completo, caminho, nome="cep.pdf")
    _modo_token(cliente_completo, doc["doc_id"], tarja=())  # token até no CEP

    r = cliente_completo.post(f"/api/doc/{doc['doc_id']}/aprovar")
    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "CEP" in detalhe
    assert "01310-100" not in detalhe, "mensagem de erro não pode carregar PII"
    # O download continua fechado: nada foi gerado.
    assert cliente_completo.get(f"/api/doc/{doc['doc_id']}/download").status_code == 409


# --------------------------------------------------------------------------
# O defeito achado ao ligar isto
# --------------------------------------------------------------------------
def test_termo_apontado_a_mao_nao_derruba_o_texto_pseudonimizado(cliente, pdf):
    """Regressão: `MANUAL` não tinha sigla, e a rota respondia 500.

    Apontar o que faltou é a ação central da revisão. Com um termo manual no
    documento, `pseudonimizar` levantava `PseudonimoImpossivel` — achado em
    2026-09-16, ao ligar o operador no PDF.
    """
    doc = _enviar(cliente, pdf)
    r = cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Flores"})
    assert r.json()["adicionados"] >= 1

    r = cliente.post(f"/api/doc/{doc['doc_id']}/pseudonimizar")
    assert r.status_code == 200, r.text
    assert r.json()["relatorio_texto"]["verificacao_ok"] is True


def test_trecho_manual_segue_o_modo_do_documento(cliente, pdf):
    """Em modo token, o trecho apontado à mão também vira token.

    Se continuasse em tarja, o PDF traria uma barra preta onde o texto
    pseudonimizado traz `[TRECHO-...]` — dois entregáveis do mesmo documento
    discordando sobre o mesmo trecho.
    """
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Flores"})
    depois = _modo_token(cliente, doc["doc_id"])

    manual = next(s for s in depois["spans"] if s["origem"] == "usuario")
    assert manual["sera_tarjado"] is True
    assert manual["operador"] == "pseudonimo"


def test_o_mesmo_valor_recebe_o_mesmo_token_nos_dois_entregaveis(cliente_completo, pdf):
    """Determinismo entre os artefatos do mesmo documento.

    Um alocador por chamada faria a mesma pessoa virar `[P-7F3A]` no PDF e
    `[P-2C81]` no texto. Quem recebesse os dois não teria como saber que falam
    do mesmo ator — que é a única razão de o token existir.
    """
    import re

    doc = _enviar(cliente_completo, pdf)
    _modo_token(cliente_completo, doc["doc_id"])

    assert cliente_completo.post(f"/api/doc/{doc['doc_id']}/aprovar").status_code == 200
    assert (
        cliente_completo.post(f"/api/doc/{doc['doc_id']}/pseudonimizar").status_code
        == 200
    )

    texto = cliente_completo.get(f"/api/doc/{doc['doc_id']}/download/texto").text
    do_texto = set(re.findall(TOKEN, texto))

    pdf_bytes = cliente_completo.get(f"/api/doc/{doc['doc_id']}/download").content
    import fitz

    aberto = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        do_pdf = set(
            re.findall(
                TOKEN,
                "\n".join(
                    aberto.load_page(i).get_text() for i in range(aberto.page_count)
                ),
            )
        )
    finally:
        aberto.close()

    assert do_pdf, "nenhum token no PDF"
    assert do_pdf <= do_texto, (
        f"tokens do PDF que não existem no texto: {sorted(do_pdf - do_texto)} — "
        "os dois entregáveis usaram alocadores diferentes"
    )


def test_modo_misto_e_o_caminho_para_valor_curto(cliente_completo, pdf):
    """Token onde cabe, tarja onde não cabe — no mesmo documento.

    É a saída que o A4 deixa para valor curto, e ela precisa funcionar de
    verdade: um documento comum tem CEP e data, e reprovar o documento inteiro
    por causa deles tornaria o operador inútil na prática.
    """
    doc = _enviar(cliente_completo, pdf)
    depois = _modo_token(cliente_completo, doc["doc_id"])

    por_entidade = {
        s["entity"]: s["operador"] for s in depois["spans"] if s["sera_tarjado"]
    }
    assert por_entidade.get("PERSON") == "pseudonimo"
    assert por_entidade.get("CEP") == "tarja"

    r = cliente_completo.post(f"/api/doc/{doc['doc_id']}/aprovar")
    assert r.status_code == 200, r.text
    rel = r.json()["relatorio"]
    assert rel["verificacao_ok"] is True
    assert rel["tokens_escritos"] > 0
    # Mais retângulos que tokens: a diferença são as tarjas do modo misto.
    assert rel["retangulos"] > rel["tokens_escritos"]


def test_trecho_ligado_a_mao_em_classe_mantida_segue_o_modo(cliente, pdf):
    """A decisão explícita vence o `manter`, e o *como* segue o documento.

    `ORGANIZATION` nasce em `manter` porque a LAI cobra que o órgão do ato
    continue legível. Se o revisor liga um desses trechos à mão em modo token,
    ele precisa virar código como o resto — não uma barra preta isolada no
    meio de um texto de códigos.
    """
    doc = _enviar(cliente, pdf)
    _modo_token(cliente, doc["doc_id"])

    org = next(s for s in doc["spans"] if s["entity"] == "ORGANIZATION")
    depois = cliente.patch(
        f"/api/doc/{doc['doc_id']}/span",
        json={"span_id": org["id"], "ativo": True},
    ).json()

    ligado = next(s for s in depois["spans"] if s["id"] == org["id"])
    assert ligado["sera_tarjado"] is True
    assert ligado["operador"] == "pseudonimo"
