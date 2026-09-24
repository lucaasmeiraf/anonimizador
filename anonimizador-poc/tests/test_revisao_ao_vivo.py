"""O que a tela de revisão precisa saber **antes** do clique final.

A verificação só rodava na aprovação e reprovava tarde: o usuário apontava um
termo, a tela dizia "1 ocorrência tarjada", e só na geração do PDF descobria
que sobravam 2. Estes testes travam as peças que antecipam isso — a
pré-verificação, a contagem de termo pelas duas réguas — e as edições que o
popover das marcações oferece.

A propriedade que mais importa aqui é negativa: nada disto libera arquivo. A
pré-verificação redige e verifica de verdade, mas o PDF de prova não pode
sobrar em disco nem ser alcançável por rota nenhuma.
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from anonimizador.spans import Span
from anonimizador.web import app as app_mod


class DetectaSoAPrimeira:
    """Marca só a primeira ocorrência de cada valor — o "detector não marcou
    a outra", que é o caso que a pré-verificação existe para antecipar."""

    def __init__(self, alvos):
        self.alvos = alvos

    def analyze(self, texto, score_threshold=None):
        spans = []
        for valor, entidade in self.alvos:
            pos = texto.find(valor)
            if pos != -1:
                spans.append(Span(pos, pos + len(valor), entidade, 0.99))
        return sorted(spans, key=lambda s: s.start)


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "sessoes"))
    with TestClient(app_mod.app) as c:
        yield c


def _pdf(tmp_path, paginas, nome="doc.pdf"):
    """Uma lista de linhas por página."""
    pdf = fitz.open()
    for linhas in paginas:
        page = pdf.new_page()
        y = 64
        for linha in linhas:
            page.insert_text((56, y), linha, fontname="helv", fontsize=9)
            y += 13
    caminho = tmp_path / nome
    pdf.save(str(caminho), garbage=4, deflate=True)
    pdf.close()
    return caminho


def _subir(cliente, monkeypatch, caminho, alvos):
    monkeypatch.setattr(app_mod, "_pipeline", DetectaSoAPrimeira(alvos))
    with open(caminho, "rb") as fh:
        r = cliente.post("/api/doc", files={"arquivo": (caminho.name, fh, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------
# Pré-verificação
# --------------------------------------------------------------------------
def test_preverificacao_aponta_a_ocorrencia_nao_marcada_antes_de_aprovar(
    cliente, monkeypatch, tmp_path
):
    caminho = _pdf(tmp_path, [
        ["Interessada: Mariana Aparecida Souza."],
        ["Pagina sem o nome."],
        ["Reiteramos que Mariana Aparecida Souza compareceu."],
    ])
    doc = _subir(cliente, monkeypatch, caminho, [("Mariana Aparecida Souza", "PERSON")])

    pre = cliente.post(f"/api/doc/{doc['doc_id']}/preverificar").json()

    assert pre["ok"] is False
    assert pre["versao"] == doc["versao"]
    [o] = pre["ocorrencias"]
    assert o["visivel_no_texto"] is True
    assert o["paginas"] == [3], "a pendência precisa dizer onde está"


def test_preverificacao_nao_libera_nem_deixa_arquivo(cliente, monkeypatch, tmp_path):
    """Redige e verifica de verdade — e por isso mesmo não pode sobrar nada."""
    caminho = _pdf(tmp_path, [["Contratante: Mariana Aparecida Souza."]])
    doc = _subir(cliente, monkeypatch, caminho, [("Mariana Aparecida Souza", "PERSON")])
    did = doc["doc_id"]

    pre = cliente.post(f"/api/doc/{did}/preverificar").json()
    assert pre["ok"] is True

    sessao = app_mod.sessoes.obter(did)
    assert not list(sessao.pasta.glob("previa-*")), "o PDF de prova ficou em disco"
    assert sessao.aprovada is False
    assert sessao.redigido is None
    assert cliente.get(f"/api/doc/{did}/download").status_code == 409


def test_preverificacao_diz_o_mesmo_que_a_aprovacao(cliente, monkeypatch, tmp_path):
    """A contagem ao vivo tem de ser a que a aprovação encontra — é o motivo
    de ela rodar o mesmo código em vez de uma aproximação."""
    caminho = _pdf(tmp_path, [[
        "CNPJ ficticio: 61.904.327/0001-18",
        "Chave PIX: 61904327000118",
        "Contratante: Mariana Aparecida Souza.",
    ]])
    doc = _subir(cliente, monkeypatch, caminho, [
        ("61.904.327/0001-18", "CNPJ"), ("Mariana Aparecida Souza", "PERSON"),
    ])
    did = doc["doc_id"]

    pre = cliente.post(f"/api/doc/{did}/preverificar").json()
    rel = cliente.post(f"/api/doc/{did}/aprovar").json()["relatorio"]

    assert pre["ok"] == rel["verificacao_ok"] is False
    assert pre["total_vazamentos"] == rel["total_vazamentos"]
    assert pre["ocorrencias"] == rel["ocorrencias"]


def test_edicao_derruba_a_preverificacao_guardada(cliente, monkeypatch, tmp_path):
    caminho = _pdf(tmp_path, [[
        "Interessada: Mariana Aparecida Souza.",
        "Reiteramos que Mariana Aparecida Souza compareceu.",
    ]])
    doc = _subir(cliente, monkeypatch, caminho, [("Mariana Aparecida Souza", "PERSON")])
    did = doc["doc_id"]

    antes = cliente.post(f"/api/doc/{did}/preverificar").json()
    assert antes["ok"] is False

    depois_termo = cliente.post(
        f"/api/doc/{did}/termo", json={"termo": "Mariana Aparecida Souza"}
    ).json()
    assert depois_termo["versao"] > antes["versao"]

    agora = cliente.post(f"/api/doc/{did}/preverificar").json()
    assert agora["versao"] == depois_termo["versao"]
    assert agora["ok"] is True


# --------------------------------------------------------------------------
# Contagem de termo pelas duas réguas
# --------------------------------------------------------------------------
def test_contar_termo_mostra_o_que_a_verificacao_vai_achar(cliente, monkeypatch, tmp_path):
    """O caso de "1 ocorrência tarjada" que reprovava com 2.

    A busca do termo é literal; a verificação procura também a forma só com
    dígitos. Uma data escrita de dois jeitos é marcada uma vez e encontrada
    duas. A tela precisa saber disso antes do clique.
    """
    caminho = _pdf(tmp_path, [[
        "Brasilia, 18/02/2026.",
        "Protocolo recebido em 18.02.2026.",
    ]])
    doc = _subir(cliente, monkeypatch, caminho, [])

    c = cliente.get(f"/api/doc/{doc['doc_id']}/contar", params={"termo": "18/02/2026"}).json()

    assert c["novas"] == 1
    assert c["no_texto"] == 2
    assert c["paginas"] == [1]

    # E a pré-verificação, depois de marcar, confirma a sobra.
    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "18/02/2026"})
    pre = cliente.post(f"/api/doc/{doc['doc_id']}/preverificar").json()
    assert pre["ok"] is False


def test_contar_termo_nao_cria_nada(cliente, monkeypatch, tmp_path):
    caminho = _pdf(tmp_path, [["Contratante: Mariana Aparecida Souza."]])
    doc = _subir(cliente, monkeypatch, caminho, [])
    cliente.get(f"/api/doc/{doc['doc_id']}/contar", params={"termo": "Mariana"})
    depois = cliente.get(f"/api/doc/{doc['doc_id']}").json()
    assert depois["spans"] == []
    assert depois["versao"] == doc["versao"]


# --------------------------------------------------------------------------
# Edições do popover
# --------------------------------------------------------------------------
def test_nao_anonimizar_nenhuma_igual(cliente, monkeypatch, tmp_path):
    class TodasAsOcorrencias:
        def analyze(self, texto, score_threshold=None):
            alvo = "Mariana Aparecida Souza"
            spans, i = [], texto.find(alvo)
            while i != -1:
                spans.append(Span(i, i + len(alvo), "PERSON", 0.99))
                i = texto.find(alvo, i + 1)
            return spans

    caminho = _pdf(tmp_path, [[
        "Interessada: Mariana Aparecida Souza.",
        "Reiteramos que Mariana Aparecida Souza compareceu.",
    ]])
    monkeypatch.setattr(app_mod, "_pipeline", TodasAsOcorrencias())
    with open(caminho, "rb") as fh:
        doc = cliente.post("/api/doc", files={"arquivo": ("d.pdf", fh, "application/pdf")}).json()
    assert len(doc["spans"]) == 2

    r = cliente.patch(
        f"/api/doc/{doc['doc_id']}/span/iguais",
        json={"span_id": doc["spans"][0]["id"], "ativo": False},
    ).json()

    assert r["alterados"] == 2
    assert not any(s["sera_tarjado"] for s in r["spans"])


def test_mudar_categoria_nao_desliga_a_tarja(cliente, monkeypatch, tmp_path):
    """Empresa detectada como pessoa: corrigir o rótulo para ORGANIZATION —
    classe em `manter` — não pode ser um jeito escondido de parar de tarjar."""
    caminho = _pdf(tmp_path, [["Contratante: Construtora Horizonte Azul."]])
    doc = _subir(cliente, monkeypatch, caminho, [("Construtora Horizonte Azul", "PERSON")])
    sid = doc["spans"][0]["id"]
    assert doc["spans"][0]["sera_tarjado"] is True

    r = cliente.patch(
        f"/api/doc/{doc['doc_id']}/span/entidade",
        json={"span_id": sid, "entidade": "ORGANIZATION"},
    ).json()

    [s] = r["spans"]
    assert s["entity"] == "ORGANIZATION"
    assert s["sera_tarjado"] is True
    assert r["versao"] > doc["versao"], "mudar rótulo é edição e invalida a aprovação"


def test_mudar_categoria_recusa_entidade_desconhecida_e_trecho_manual(
    cliente, monkeypatch, tmp_path
):
    caminho = _pdf(tmp_path, [["Contratante: Mariana Aparecida Souza."]])
    doc = _subir(cliente, monkeypatch, caminho, [("Mariana Aparecida Souza", "PERSON")])
    did = doc["doc_id"]
    sid = doc["spans"][0]["id"]

    r = cliente.patch(f"/api/doc/{did}/span/entidade", json={"span_id": sid, "entidade": "XYZ"})
    assert r.status_code == 400

    manual = cliente.post(f"/api/doc/{did}/termo", json={"termo": "Contratante"}).json()
    mid = next(s["id"] for s in manual["spans"] if s["origem"] == "usuario")
    r = cliente.patch(f"/api/doc/{did}/span/entidade", json={"span_id": mid, "entidade": "PERSON"})
    assert r.status_code == 400


# --------------------------------------------------------------------------
# O que a tela recebe para decidir o que mostrar
# --------------------------------------------------------------------------
def test_fragmento_de_palavra_e_sinalizado(cliente, monkeypatch, tmp_path):
    caminho = _pdf(tmp_path, [["SUPERINTENDENCIA RODOVIARIA FEDERAL"]])
    doc = _subir(cliente, monkeypatch, caminho, [("RO", "LOCATION"), ("FEDERAL", "ORGANIZATION")])
    por_valor = {s["valor"]: s for s in doc["spans"]}
    assert por_valor["RO"]["fragmento"] is True
    assert por_valor["FEDERAL"]["fragmento"] is False


def test_caracteristicas_do_pdf_de_origem(cliente, monkeypatch, tmp_path):
    """Os avisos da exportação dependem do que este arquivo tem."""
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((56, 64), "Ver https://exemplo.gov.br", fontname="helv", fontsize=9)
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(56, 55, 200, 66),
                      "uri": "https://exemplo.gov.br"})
    pdf.set_toc([[1, "Capitulo", 1]])
    caminho = tmp_path / "links.pdf"
    pdf.save(str(caminho))
    pdf.close()

    doc = _subir(cliente, monkeypatch, caminho, [])
    c = doc["caracteristicas"]
    assert c["links"] == 1
    assert c["marcadores"] == 1
    assert c["assinatura"] is False
