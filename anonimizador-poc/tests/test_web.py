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
# O clique tem de ter efeito visível em qualquer estado
# --------------------------------------------------------------------------
# `sera_tarjado` era `ativo AND política == tarja` — duas chaves em série. Com
# a política da entidade em `manter`, a chave do span perdia toda autoridade:
# clicar no retângulo alternava `ativo` sem mudar nada na tela. Num documento
# com 31 datas preservadas por política, eram 31 retângulos em que clicar não
# fazia efeito nenhum.
def test_clique_em_span_de_classe_preservada_liga_a_tarja(cliente, pdf):
    doc = _enviar(cliente, pdf)
    alvo = next(s for s in doc["spans"] if s["entity"] == "ORGANIZATION")
    assert alvo["sera_tarjado"] is False, "o perfil padrão preserva ORGANIZATION"

    d = cliente.patch(
        f"/api/doc/{doc['doc_id']}/span",
        json={"span_id": alvo["id"], "ativo": True},
    ).json()
    depois = next(s for s in d["spans"] if s["id"] == alvo["id"])
    assert depois["sera_tarjado"] is True, (
        "a decisão sobre o trecho precisa vencer o padrão da classe"
    )


def test_clique_alterna_nos_dois_sentidos_com_classe_preservada(cliente, pdf):
    """Ida e volta: o estado visível acompanha cada clique."""
    doc = _enviar(cliente, pdf)
    alvo = next(s for s in doc["spans"] if s["entity"] == "ORGANIZATION")

    vistos = []
    for valor in (True, False, True):
        d = cliente.patch(
            f"/api/doc/{doc['doc_id']}/span",
            json={"span_id": alvo["id"], "ativo": valor},
        ).json()
        vistos.append(next(s for s in d["spans"] if s["id"] == alvo["id"])["sera_tarjado"])
    assert vistos == [True, False, True]


def test_span_intocado_segue_a_politica_da_classe(cliente, pdf):
    """O padrão continua sendo a política; a exceção é o clique."""
    doc = _enviar(cliente, pdf)
    for s in doc["spans"]:
        assert s["ativo"] is None, "span recém-detectado não tem decisão própria"

    d = cliente.put(
        f"/api/doc/{doc['doc_id']}/perfil",
        json={"nome": "x", "padrao": "tarja", "regras": {"ORGANIZATION": "tarja"}},
    ).json()
    org = next(s for s in d["spans"] if s["entity"] == "ORGANIZATION")
    assert org["sera_tarjado"] is True


def test_mudar_a_classe_zera_as_decisoes_individuais_dela(cliente, pdf):
    """A caixa de seleção precisa continuar sendo autoridade.

    Sem zerar, desmarcar a classe deixaria tarjados os trechos que o usuário
    tinha ligado um a um antes, e a contagem na lateral contradiria a tela.
    """
    doc = _enviar(cliente, pdf)
    alvo = next(s for s in doc["spans"] if s["entity"] == "ORGANIZATION")
    cliente.patch(
        f"/api/doc/{doc['doc_id']}/span",
        json={"span_id": alvo["id"], "ativo": True},
    )

    # Liga a classe inteira e desliga de novo: a exceção anterior some.
    cliente.put(
        f"/api/doc/{doc['doc_id']}/perfil",
        json={"nome": "x", "padrao": "tarja", "regras": {"ORGANIZATION": "tarja"}},
    )
    d = cliente.put(
        f"/api/doc/{doc['doc_id']}/perfil",
        json={"nome": "x", "padrao": "tarja", "regras": {"ORGANIZATION": "manter"}},
    ).json()

    org = next(s for s in d["spans"] if s["id"] == alvo["id"])
    assert org["ativo"] is None
    assert org["sera_tarjado"] is False


def test_trecho_manual_sobrevive_a_mudanca_de_politica(cliente, pdf):
    """O que o usuário adicionou não é proposta de classe nenhuma."""
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Rua das Flores"})
    d = cliente.put(
        f"/api/doc/{doc['doc_id']}/perfil",
        json={"nome": "x", "padrao": "manter", "regras": {}},
    ).json()
    manual = next(s for s in d["spans"] if s["origem"] == "usuario")
    assert manual["sera_tarjado"] is True


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
# Busca tolerante a espaçamento
# --------------------------------------------------------------------------
# A camada de texto entrega as palavras separadas por espaço simples. O texto
# extraído do PDF tem os espaçamentos que o documento tem — inclusive quebra
# de linha no meio de um nome. Sem tolerância, selecionar um trecho na tela e
# mandar tarjar não encontrava nada, e o botão parecia morto.
@pytest.mark.parametrize(
    "termo",
    [
        "Rua das Flores",       # como está no texto
        "Rua  das  Flores",     # espaços a mais, como vem de uma seleção
        " Rua das Flores ",     # sobra nas pontas
        "Rua\ndas\nFlores",     # como viria de um trecho quebrado em linhas
    ],
)
def test_termo_tolera_espacamento(cliente, pdf, termo):
    doc = _enviar(cliente, pdf)
    d = cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": termo}).json()
    assert d["adicionados"] == 1, f"nao achou com espacamento {termo!r}"


def test_termo_tolerante_nao_vira_busca_difusa(cliente, pdf):
    """Tolerar espaço não é tolerar erro.

    A flexibilidade vale **só** para espaço em branco. Texto errado continua
    não casando; se casasse, a tarja manual deixaria de ser previsível, e
    previsibilidade é o que a torna auditável.

    Substring continua casando de propósito — ``Rua das Flor`` dentro de
    ``Rua das Flores`` sempre casou, e é o que permite tarjar um sobrenome
    isolado. O que não pode é aproximação.
    """
    doc = _enviar(cliente, pdf)
    for errado in [
        "Ruadas Flores",    # faltou o espaço: não é diferença de espaçamento
        "Rua de Flores",    # palavra trocada
        "Rua das Flarez",   # grafia errada
        "Flores das Rua",   # ordem trocada
    ]:
        d = cliente.post(
            f"/api/doc/{doc['doc_id']}/termo", json={"termo": errado}
        ).json()
        assert d["adicionados"] == 0, f"{errado!r} nao deveria casar"


def test_substring_continua_casando(cliente, pdf):
    """É o que permite tarjar só o sobrenome de um nome já detectado."""
    doc = _enviar(cliente, pdf)
    d = cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Flores"}).json()
    assert d["adicionados"] == 1


def test_termo_quebrado_entre_linhas_e_encontrado(cliente, tmp_pdf):
    """O caso que motivou a mudança.

    O usuário seleciona um nome que a tela mostra numa linha só; no texto
    extraído ele está partido pela quebra de linha do PDF.
    """
    caminho = tmp_pdf(
        ["Requerente: Mariana Aparecida", "Souza, brasileira, servidora."],
        nome="quebrado.pdf",
    )
    with open(caminho, "rb") as fh:
        doc = cliente.post(
            "/api/doc", files={"arquivo": ("quebrado.pdf", fh, "application/pdf")}
        ).json()

    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Mariana Aparecida Souza"}
    ).json()
    assert d["adicionados"] == 1


def test_termo_nao_empilha_sobre_tarja_ativa(cliente, pdf):
    """O defeito que fazia a tarja parecer indesligável.

    Tarjar `Mariana` num documento onde o detector já marcou
    `Mariana Aparecida Souza` criava um segundo retângulo por cima do
    primeiro. Os dois ficavam pretos, o clique acertava só o de cima, e a
    tarja continuava lá.
    """
    doc = _enviar(cliente, pdf)
    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Mariana"}
    ).json()
    assert d["adicionados"] == 0
    assert not [s for s in d["spans"] if s["origem"] == "usuario"]


def test_termo_entra_se_a_tarja_que_cobria_estiver_desligada(cliente, pdf):
    """A intenção explícita do usuário vale mais que proposta desligada."""
    doc = _enviar(cliente, pdf)
    alvo = [s for s in doc["spans"] if s["valor"].startswith("Mariana")][0]
    cliente.patch(
        f"/api/doc/{doc['doc_id']}/span", json={"span_id": alvo["id"], "ativo": False}
    )
    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Mariana"}
    ).json()
    assert d["adicionados"] == 1


# --------------------------------------------------------------------------
# Remoção de trechos adicionados à mão
# --------------------------------------------------------------------------
def test_apagar_span_manual(cliente, pdf):
    doc = _enviar(cliente, pdf)
    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Rua das Flores"}
    ).json()
    sid = [s for s in d["spans"] if s["origem"] == "usuario"][0]["id"]

    d = cliente.delete(f"/api/doc/{doc['doc_id']}/span/{sid}").json()
    assert not [s for s in d["spans"] if s["origem"] == "usuario"]


def test_apagar_span_do_detector_e_recusado(cliente, pdf):
    """Remover uma proposta do detector esconderia que ela existiu.

    Desligar é a operação certa ali: continua visível na tela, com a caixa
    tracejada, e o revisor enxerga o que o sistema achou e ele recusou.
    """
    doc = _enviar(cliente, pdf)
    sid = doc["spans"][0]["id"]
    r = cliente.delete(f"/api/doc/{doc['doc_id']}/span/{sid}")
    assert r.status_code == 409


def test_apagar_todos_os_manuais(cliente, pdf):
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Rua das Flores"})
    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": "certidao"})

    d = cliente.delete(f"/api/doc/{doc['doc_id']}/manuais").json()
    assert not [s for s in d["spans"] if s["origem"] == "usuario"]


def test_apagar_manual_apos_aprovar_invalida_download(cliente, pdf):
    doc = _enviar(cliente, pdf)
    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/termo", json={"termo": "Rua das Flores"}
    ).json()
    sid = [s for s in d["spans"] if s["origem"] == "usuario"][0]["id"]
    cliente.post(f"/api/doc/{doc['doc_id']}/aprovar")

    cliente.delete(f"/api/doc/{doc['doc_id']}/span/{sid}")
    assert cliente.get(f"/api/doc/{doc['doc_id']}/download").status_code == 409


# --------------------------------------------------------------------------
# Camada de texto selecionável
# --------------------------------------------------------------------------
def test_texto_da_pagina_devolve_palavras_com_caixa(cliente, pdf):
    """Sem esta rota a página é só imagem, e imagem não se copia.

    O usuário precisa selecionar o trecho no documento e colar no campo; é o
    fluxo mais natural para apontar o que faltou.
    """
    doc = _enviar(cliente, pdf)
    d = cliente.get(f"/api/doc/{doc['doc_id']}/texto/0").json()

    assert d["pagina"] == 0
    assert len(d["palavras"]) > 10
    p = d["palavras"][0]
    assert set(p) >= {"t", "x0", "y0", "x1", "y1"}
    assert p["x1"] > p["x0"] and p["y1"] > p["y0"]
    # O texto tem de ser utilizável: as palavras do documento estão lá.
    todas = " ".join(w["t"] for w in d["palavras"])
    assert "Mariana" in todas


def test_texto_de_pagina_inexistente_da_404(cliente, pdf):
    doc = _enviar(cliente, pdf)
    assert cliente.get(f"/api/doc/{doc['doc_id']}/texto/99").status_code == 404


def test_palavras_trazem_offset_no_texto_do_documento(cliente, pdf):
    """O offset é o que liga a seleção do navegador à redação.

    Sem ele, a única forma de agir sobre uma seleção seria procurar o texto
    dela no documento — e isso tarja todas as ocorrências, não a que foi
    selecionada.
    """
    doc = _enviar(cliente, pdf)
    d = cliente.get(f"/api/doc/{doc['doc_id']}/texto/0").json()

    sessao = app_mod.sessoes.obter(doc["doc_id"])
    for p in d["palavras"]:
        assert "i" in p
        # A promessa que o front-end usa: o offset aponta para esta palavra.
        assert sessao.tm.text[p["i"] : p["i"] + len(p["t"])] == p["t"]


def test_palavras_nao_se_sobrepoem(cliente, pdf):
    doc = _enviar(cliente, pdf)
    ps = cliente.get(f"/api/doc/{doc['doc_id']}/texto/0").json()["palavras"]
    for a, b in zip(ps, ps[1:]):
        assert a["i"] + len(a["t"]) <= b["i"]


# --------------------------------------------------------------------------
# Tarjar por intervalo — a seleção com o mouse
# --------------------------------------------------------------------------
def _offsets_de(cliente, doc_id, palavra):
    ps = cliente.get(f"/api/doc/{doc_id}/texto/0").json()["palavras"]
    p = next(x for x in ps if x["t"] == palavra)
    return p["i"], p["i"] + len(p["t"])


# Os testes abaixo agem sobre "Flores", que o dublê **não** detecta. Usar um
# trecho já tarjado esbarraria na regra anti-empilhamento — corretamente, mas
# mediria outra coisa.
def test_intervalo_tarja_so_a_ocorrencia_selecionada(cliente, tmp_pdf):
    """A diferença entre selecionar e digitar.

    Selecionar é apontar *esta* ocorrência; digitar é descrever um valor.
    Mandar a seleção para a busca textual — como fazíamos — tarjava o
    documento inteiro a partir de um clique numa cláusula.
    """
    caminho = tmp_pdf(
        [
            "Referencia: Protocolo Alfa Beta arquivado.",
            "Novamente o Protocolo Alfa Beta na segunda via.",
        ],
        nome="repetido.pdf",
    )
    with open(caminho, "rb") as fh:
        doc = cliente.post(
            "/api/doc", files={"arquivo": ("repetido.pdf", fh, "application/pdf")}
        ).json()

    sessao = app_mod.sessoes.obter(doc["doc_id"])
    alvo = "Protocolo Alfa Beta"
    assert sessao.tm.text.count(alvo) == 2, "o corpo do teste precisa repetir"

    inicio = sessao.tm.text.find(alvo)
    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/intervalo",
        json={"inicio": inicio, "fim": inicio + len(alvo), "texto": alvo},
    ).json()

    manuais = [s for s in d["spans"] if s["origem"] == "usuario"]
    assert len(manuais) == 1, "tarjou mais de uma ocorrencia"
    assert manuais[0]["valor"] == alvo
    assert manuais[0]["sera_tarjado"] is True

    # A contraprova: digitar o mesmo texto pega a outra ocorrência também.
    d2 = cliente.post(
        f"/api/doc/{doc['doc_id']}/termo", json={"termo": alvo}
    ).json()
    assert d2["adicionados"] == 1


def test_intervalo_aceita_selecao_no_meio_da_palavra(cliente, pdf):
    """Seleção caractere a caractere, não palavra a palavra."""
    doc = _enviar(cliente, pdf)
    sessao = app_mod.sessoes.obter(doc["doc_id"])
    base = sessao.tm.text.find("Flores")

    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/intervalo",
        json={"inicio": base + 1, "fim": base + 4, "texto": "lor"},
    ).json()
    manual = [s for s in d["spans"] if s["origem"] == "usuario"][0]
    assert manual["valor"] == "lor"


def test_intervalo_apara_espaco_nas_pontas(cliente, pdf):
    """Arrastar o mouse quase sempre pega espaço além do texto."""
    doc = _enviar(cliente, pdf)
    sessao = app_mod.sessoes.obter(doc["doc_id"])
    base = sessao.tm.text.find("Flores")

    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/intervalo",
        json={"inicio": base - 1, "fim": base + 7, "texto": "Flores"},
    ).json()
    manual = [s for s in d["spans"] if s["origem"] == "usuario"][0]
    assert manual["valor"] == "Flores", f"nao aparou: {manual['valor']!r}"


def test_intervalo_corrige_offset_escorregado(cliente, pdf):
    """A proteção contra o pior modo de falha possível.

    JavaScript conta comprimento em unidades UTF-16, Python em code points.
    Um caractere fora do BMP dessincroniza os dois, e a partir dali o servidor
    tarjaria **o trecho errado** — cobrindo texto inocente e deixando o dado
    pessoal à mostra, sem erro nenhum.

    Aqui o offset chega deslocado de propósito; o texto reivindicado é que
    manda, e o servidor se corrige.
    """
    doc = _enviar(cliente, pdf)
    sessao = app_mod.sessoes.obter(doc["doc_id"])
    correto = sessao.tm.text.find("Flores")

    d = cliente.post(
        f"/api/doc/{doc['doc_id']}/intervalo",
        json={
            "inicio": correto + 5,   # deslocado de propósito
            "fim": correto + 11,
            "texto": "Flores",
        },
    ).json()
    manual = [s for s in d["spans"] if s["origem"] == "usuario"][0]
    assert manual["valor"] == "Flores"
    assert manual["rects"], "corrigiu o offset mas perdeu o retangulo"


def test_intervalo_recusa_texto_que_nao_existe(cliente, pdf):
    """Não achando o que o cliente diz ter selecionado, recusa em vez de
    adivinhar. Tarjar por adivinhação é pior que não tarjar."""
    doc = _enviar(cliente, pdf)
    r = cliente.post(
        f"/api/doc/{doc['doc_id']}/intervalo",
        json={"inicio": 5, "fim": 12, "texto": "Xylophone Quixote"},
    )
    assert r.status_code == 422


def test_intervalo_recusa_trecho_ja_tarjado(cliente, pdf):
    """Evita o empilhamento de retângulos que fazia a tarja parecer presa."""
    doc = _enviar(cliente, pdf)
    alvo = [s for s in doc["spans"] if s["entity"] == "CPF"][0]
    sessao = app_mod.sessoes.obter(doc["doc_id"])
    s = sessao.spans[alvo["id"]]

    r = cliente.post(
        f"/api/doc/{doc['doc_id']}/intervalo",
        json={"inicio": s.start, "fim": s.end, "texto": s.valor},
    )
    assert r.status_code == 422
    assert "já está coberto" in r.json()["detail"]


def test_intervalo_fora_do_documento_e_recusado(cliente, pdf):
    doc = _enviar(cliente, pdf)
    r = cliente.post(
        f"/api/doc/{doc['doc_id']}/intervalo",
        json={"inicio": 10**9, "fim": 10**9 + 5, "texto": "x"},
    )
    assert r.status_code == 422


def test_intervalo_apos_aprovar_invalida_download(cliente, pdf):
    doc = _enviar(cliente, pdf)
    cliente.post(f"/api/doc/{doc['doc_id']}/aprovar")
    assert cliente.get(f"/api/doc/{doc['doc_id']}/download").status_code == 200

    sessao = app_mod.sessoes.obter(doc["doc_id"])
    base = sessao.tm.text.find("Flores")
    r = cliente.post(
        f"/api/doc/{doc['doc_id']}/intervalo",
        json={"inicio": base, "fim": base + 6, "texto": "Flores"},
    )
    assert r.status_code == 200, r.text
    assert cliente.get(f"/api/doc/{doc['doc_id']}/download").status_code == 409


# --------------------------------------------------------------------------
# O relatório de falha precisa ser acionável
# --------------------------------------------------------------------------
def test_relatorio_de_sucesso_traz_ocorrencias_vazias(cliente, pdf):
    doc = _enviar(cliente, pdf)
    d = cliente.post(f"/api/doc/{doc['doc_id']}/aprovar").json()
    assert d["relatorio"]["ocorrencias"] == []


def test_relatorio_de_falha_diz_o_que_sobreviveu_e_onde(cliente, tmp_pdf):
    """"Reprovou" sozinho é um beco sem saída.

    Aqui o mesmo nome aparece duas vezes e o dublê só detecta a primeira, o
    que reproduz o caso real: outra ocorrência do mesmo valor que o detector
    não marcou. A tela precisa saber que é isso, para oferecer o conserto.
    """
    from anonimizador.spans import Span

    class SoAPrimeira:
        def analyze(self, texto):
            pos = texto.find("Mariana Aparecida Souza")
            return [Span(pos, pos + 23, "PERSON", 0.99)] if pos != -1 else []

    app_mod._pipeline = SoAPrimeira()
    caminho = tmp_pdf(
        [
            "Interessada: Mariana Aparecida Souza.",
            "Reiteramos que Mariana Aparecida Souza compareceu.",
        ],
        nome="dup.pdf",
    )
    with open(caminho, "rb") as fh:
        doc = cliente.post(
            "/api/doc", files={"arquivo": ("dup.pdf", fh, "application/pdf")}
        ).json()

    d = cliente.post(f"/api/doc/{doc['doc_id']}/aprovar").json()
    rel = d["relatorio"]

    assert rel["verificacao_ok"] is False
    assert d["pode_baixar"] is False
    assert rel["ocorrencias"], "reprovou sem dizer o que sobreviveu"

    o = rel["ocorrencias"][0]
    assert o["valor"] == "Mariana Aparecida Souza"
    assert o["visivel_no_texto"] is True
    assert o["ocorrencias_no_texto"] >= 1


def test_conserto_oferecido_pela_tela_de_falha_funciona(cliente, tmp_pdf):
    """O caminho completo: reprovou -> tarjar todas -> aprova."""
    from anonimizador.spans import Span

    class SoAPrimeira:
        def analyze(self, texto):
            pos = texto.find("Mariana Aparecida Souza")
            return [Span(pos, pos + 23, "PERSON", 0.99)] if pos != -1 else []

    app_mod._pipeline = SoAPrimeira()
    caminho = tmp_pdf(
        [
            "Interessada: Mariana Aparecida Souza.",
            "Reiteramos que Mariana Aparecida Souza compareceu.",
        ],
        nome="dup2.pdf",
    )
    with open(caminho, "rb") as fh:
        doc = cliente.post(
            "/api/doc", files={"arquivo": ("dup2.pdf", fh, "application/pdf")}
        ).json()

    rel = cliente.post(f"/api/doc/{doc['doc_id']}/aprovar").json()["relatorio"]
    valor = rel["ocorrencias"][0]["valor"]

    # É exatamente o que o botão "Tarjar todas as ocorrências" dispara.
    cliente.post(f"/api/doc/{doc['doc_id']}/termo", json={"termo": valor})
    d = cliente.post(f"/api/doc/{doc['doc_id']}/aprovar").json()

    assert d["relatorio"]["verificacao_ok"] is True
    assert d["pode_baixar"] is True
    assert cliente.get(f"/api/doc/{doc['doc_id']}/download").status_code == 200


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
