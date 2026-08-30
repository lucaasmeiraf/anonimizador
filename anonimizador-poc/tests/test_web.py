"""As travas da interface de revisão.

O que estes testes protegem não é a tela — é a promessa que a tela faz. Um
anonimizador que entrega arquivo não verificado é pior que nenhum, porque a
pessoa assina embaixo confiando no que viu.

Três invariantes, e cada uma tem um jeito específico de ser quebrada por
alguém mexendo no código depois:

1. **Download exige verificação aprovada.** Quebra-se adicionando uma rota
   nova que sirva ``sessao.redigido`` sem consultar ``pode_baixar``.
2. **Editar depois de aprovar invalida a aprovação.** Quebra-se esquecendo
   ``_invalidar()`` num método de edição novo — e o sintoma é o pior possível:
   o usuário baixa um PDF que não corresponde ao que aprovou.
3. **Operador não implementado é recusado.** Quebra-se "só habilitando" um
   operador na UI. O resultado seria um PDF com o dado intacto e um relatório
   dizendo que foi anonimizado.

O pipeline de NER é substituído por um dublê: estes testes são sobre o fluxo,
não sobre detecção, e carregar 1 GB de pesos por teste os tornaria inúteis na
prática. A redação e a verificação são as **de verdade** — é o que está sendo
testado.
"""

import fitz
import pytest
from fastapi.testclient import TestClient

from anonimizador.spans import Span
from anonimizador.web import app as app_mod

# Texto com PII sintética. O CPF tem checksum válido; os nomes são fictícios.
LINHAS = [
    "CONTRATO DE PRESTACAO DE SERVICOS",
    "Contratante: Mariana Aparecida Souza, portadora do CPF 529.982.247-25,",
    "residente na Rua das Flores, 100, CEP 01310-100, Sao Paulo.",
    "Contato: mariana.souza@exemplo.com.br, telefone (11) 98765-4321.",
    "Testemunha: Joaquim Barbosa Lima.",
    "Assinado em 12 de marco de 2026 pelo Instituto Exemplo.",
]

# Offsets são calculados sobre o texto extraído, não fixados à mão — o
# `build_text_map` insere separadores próprios entre linhas.
ALVOS = [
    ("Mariana Aparecida Souza", "PERSON"),
    ("529.982.247-25", "CPF"),
    ("01310-100", "CEP"),
    ("mariana.souza@exemplo.com.br", "EMAIL"),
    ("Joaquim Barbosa Lima", "PERSON"),
    ("Instituto Exemplo", "ORGANIZATION"),
]


class PipelineDuble:
    """Devolve spans achando os alvos por busca literal no texto extraído."""

    def analyze(self, texto: str):
        spans = []
        for valor, entidade in ALVOS:
            pos = texto.find(valor)
            if pos != -1:
                spans.append(
                    Span(start=pos, end=pos + len(valor), entity=entidade, score=0.99)
                )
        return sorted(spans, key=lambda s: s.start)


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_pipeline", PipelineDuble())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "sessoes"))
    with TestClient(app_mod.app) as c:
        yield c


@pytest.fixture
def pdf(tmp_pdf):
    return tmp_pdf(LINHAS, nome="contrato.pdf")


def _enviar(cliente, caminho, nome="contrato.pdf"):
    with open(caminho, "rb") as fh:
        r = cliente.post("/api/doc", files={"arquivo": (nome, fh, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------
# Upload e detecção
# --------------------------------------------------------------------------
def test_upload_devolve_spans_com_retangulos(cliente, pdf):
    doc = _enviar(cliente, pdf)
    assert len(doc["spans"]) == len(ALVOS)
    assert doc["paginas"][0]["largura"] > 0
    # Todo span precisa de retângulo: span sem caixa é PII detectada e não
    # tarjada, que é exatamente o que o produto não pode fazer.
    for s in doc["spans"]:
        assert s["rects"], f"span {s['entity']} sem retangulo"


def test_upload_recusa_nao_pdf(cliente):
    r = cliente.post(
        "/api/doc", files={"arquivo": ("x.txt", b"nao sou pdf", "text/plain")}
    )
    assert r.status_code == 415


def test_upload_recusa_pdf_sem_texto(cliente, tmp_path):
    """PDF escaneado precisa falhar alto.

    Uma tela vazia sem explicação faria o usuário concluir que o documento
    está limpo, quando na verdade ele não foi analisado.
    """
    caminho = tmp_path / "vazio.pdf"
    d = fitz.open()
    d.new_page()
    d.save(str(caminho))
    d.close()

    with open(caminho, "rb") as fh:
        r = cliente.post(
            "/api/doc", files={"arquivo": ("vazio.pdf", fh, "application/pdf")}
        )
    assert r.status_code == 422
    assert "escaneado" in r.json()["detail"]


def test_perfil_padrao_preserva_organizacao(cliente, pdf):
    doc = _enviar(cliente, pdf)
    por_ent = {s["entity"]: s for s in doc["spans"]}
    assert por_ent["PERSON"]["sera_tarjado"] is True
    assert por_ent["CPF"]["sera_tarjado"] is True
    # Em documento público o nome do órgão costuma ser o que precisa ficar
    # legível. Detectado, reportado, não tarjado.
    assert por_ent["ORGANIZATION"]["sera_tarjado"] is False


# --------------------------------------------------------------------------
# Invariante 1 — o gate de download
# --------------------------------------------------------------------------
def test_download_recusa_antes_de_aprovar(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.get(f"/api/doc/{doc['doc_id']}/download")
    assert r.status_code == 409


def test_aprovar_verifica_e_libera(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.post(f"/api/doc/{doc['doc_id']}/aprovar")
    assert r.status_code == 200
    d = r.json()

    rel = d["relatorio"]
    assert rel["verificacao_ok"] is True
    assert rel["total_vazamentos"] == 0
    assert rel["spans_sem_retangulo"] == 0
    assert len(rel["vetores"]) >= 9
    assert d["pode_baixar"] is True

    r = cliente.get(f"/api/doc/{doc['doc_id']}/download")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")


def test_pdf_baixado_nao_contem_a_pii(cliente, pdf, tmp_path):
    """Verificação independente do que a API afirma.

    O relatório dizer `verificacao_ok` e o arquivo ainda conter o dado seria a
    falha mais grave possível. Aqui reabrimos o PDF por fora e conferimos.
    """
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/aprovar")
    r = cliente.get(f"/api/doc/{doc['doc_id']}/download")

    saida = tmp_path / "baixado.pdf"
    saida.write_bytes(r.content)

    d = fitz.open(str(saida))
    try:
        texto = "\n".join(d.load_page(i).get_text() for i in range(d.page_count))
        metadados = d.metadata or {}
    finally:
        d.close()

    for valor, entidade in ALVOS:
        if entidade == "ORGANIZATION":
            continue  # preservada de propósito pelo perfil padrão
        assert valor not in texto, f"{entidade} sobreviveu no PDF"

    assert not (metadados.get("author") or metadados.get("title"))


def test_aprovar_sem_tarja_ativa_e_recusado(cliente, pdf):
    doc = _enviar(cliente, pdf)
    for s in doc["spans"]:
        cliente.patch(
            f"/api/doc/{doc['doc_id']}/span",
            json={"span_id": s["id"], "ativo": False},
        )
    r = cliente.post(f"/api/doc/{doc['doc_id']}/aprovar")
    assert r.status_code == 400


# --------------------------------------------------------------------------
# Invariante 2 — editar invalida a aprovação
# --------------------------------------------------------------------------
def test_desligar_span_apos_aprovar_invalida_download(cliente, pdf):
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/aprovar")
    assert cliente.get(f"/api/doc/{doc['doc_id']}/download").status_code == 200

    alvo = doc["spans"][0]["id"]
    d = cliente.patch(
        f"/api/doc/{doc['doc_id']}/span", json={"span_id": alvo, "ativo": False}
    ).json()

    assert d["aprovada"] is False
    assert d["pode_baixar"] is False
    assert cliente.get(f"/api/doc/{doc['doc_id']}/download").status_code == 409


def test_adicionar_termo_apos_aprovar_invalida_download(cliente, pdf):
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/aprovar")

    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Rua das Flores"})
    assert cliente.get(f"/api/doc/{doc['doc_id']}/download").status_code == 409


def test_trocar_perfil_apos_aprovar_invalida_download(cliente, pdf):
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/aprovar")

    cliente.put(
        f"/api/doc/{doc['doc_id']}/perfil",
        json={"nome": "x", "padrao": "tarja", "regras": {"PERSON": "manter"}},
    )
    assert cliente.get(f"/api/doc/{doc['doc_id']}/download").status_code == 409


# --------------------------------------------------------------------------
# Invariante 3 — operador não implementado é recusado
# --------------------------------------------------------------------------
@pytest.mark.parametrize("operador", ["pseudonimo", "mascara"])
def test_perfil_recusa_operador_nao_implementado(cliente, pdf, operador):
    doc = _enviar(cliente, pdf)
    r = cliente.put(
        f"/api/doc/{doc['doc_id']}/perfil",
        json={"nome": "x", "padrao": operador, "regras": {}},
    )
    assert r.status_code == 422
    assert operador in r.json()["detail"]


def test_perfil_recusa_entidade_desconhecida(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.put(
        f"/api/doc/{doc['doc_id']}/perfil",
        json={"nome": "x", "padrao": "tarja", "regras": {"INVENTADA": "tarja"}},
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Termo — o caminho determinístico do chat
# --------------------------------------------------------------------------
def test_termo_tarja_todas_as_ocorrencias(cliente, pdf):
    doc = _enviar(cliente, pdf)
    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Rua das Flores"}
    ).json()

    assert d["adicionados"] == 1
    manuais = [s for s in d["spans"] if s["origem"] == "usuario"]
    assert len(manuais) == 1
    assert manuais[0]["entity"] == "MANUAL"
    # O usuário apontou explicitamente: a política de entidades não tem
    # jurisdição sobre isso.
    assert manuais[0]["sera_tarjado"] is True


def test_termo_manual_sobrevive_a_perfil_restritivo(cliente, pdf):
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Rua das Flores"})
    d = cliente.put(
        f"/api/doc/{doc['doc_id']}/perfil",
        json={"nome": "x", "padrao": "manter", "regras": {}},
    ).json()

    manual = [s for s in d["spans"] if s["origem"] == "usuario"][0]
    assert manual["sera_tarjado"] is True


def test_termo_inexistente_nao_adiciona(cliente, pdf):
    doc = _enviar(cliente, pdf)
    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Xylophone Quixote"}
    ).json()
    assert d["adicionados"] == 0


def test_termo_curto_demais_e_recusado(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "a"})
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Ciclo de vida
# --------------------------------------------------------------------------
def test_apagar_sessao_remove_os_arquivos_do_disco(cliente, pdf):
    doc = _enviar(cliente, pdf)
    pasta = app_mod.sessoes.obter(doc["doc_id"]).pasta
    assert (pasta / "original.pdf").exists()

    assert cliente.delete(f"/api/doc/{doc['doc_id']}").status_code == 200
    assert not pasta.exists()
    assert cliente.get(f"/api/doc/{doc['doc_id']}").status_code == 404


def test_sessao_expirada_some(cliente, pdf):
    doc = _enviar(cliente, pdf)
    app_mod.sessoes.ttl = -1  # tudo já venceu
    assert cliente.get(f"/api/doc/{doc['doc_id']}").status_code == 404


def test_sessao_inexistente_da_404(cliente):
    assert cliente.get("/api/doc/naoexiste").status_code == 404


def test_pagina_png_renderiza(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.get(f"/api/doc/{doc['doc_id']}/pagina/0.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_pagina_inexistente_da_404(cliente, pdf):
    doc = _enviar(cliente, pdf)
    assert cliente.get(f"/api/doc/{doc['doc_id']}/pagina/99.png").status_code == 404
