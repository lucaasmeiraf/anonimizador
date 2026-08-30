"""Contratos da camada estática que testes de API não pegam.

Duas regressões reais motivaram este arquivo, e as duas passaram por toda a
suíte sem serem notadas — porque os testes exercitavam a API, e o defeito
estava na relação entre dois arquivos estáticos.

1. **A camada de tarjas bloqueava a seleção de texto.** Ela cobre a página
   inteira (``inset: 0``) e ficava acima da camada de texto. Sem
   ``pointer-events: none``, virou um vidro invisível: nenhum texto do painel
   Anonimizado podia ser selecionado. Só apareceu quando a seleção passou a
   viver nesse painel — antes o texto estava no painel Original, que não tem
   camada de tarjas, e o defeito ficou latente.

2. **O navegador servia JS antigo depois de uma correção.** Sem carimbo de
   versão, o usuário recarregava, não via mudança, e concluía que o conserto
   não funcionou — mandando investigar o lugar errado.

Nenhum destes testa aparência. Testam propriedades que, se quebradas, tornam
a tela silenciosamente inutilizável.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anonimizador.web import app as app_mod

ESTATICOS = Path(app_mod.__file__).parent / "static"


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    # Dublê vazio: estes testes não tocam detecção.
    monkeypatch.setattr(app_mod, "_pipeline", type("P", (), {"analyze": lambda s, t: []})())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "s"))
    with TestClient(app_mod.app) as c:
        yield c


# --------------------------------------------------------------------------
# Regressão 1 — a seleção de texto precisa atravessar a camada de tarjas
# --------------------------------------------------------------------------
def test_camada_de_tarjas_nao_bloqueia_o_mouse():
    """O container é transparente ao mouse; só os retângulos capturam.

    Se esta regra sumir, a seleção de texto morre em silêncio: nada quebra,
    nenhum erro aparece no console, o usuário só não consegue mais selecionar
    e não tem como saber por quê.
    """
    css = (ESTATICOS / "estilo.css").read_text(encoding="utf-8")
    regra = re.search(r"\.camada-tarjas\s*\{[^}]*\}", css)
    assert regra, "regra .camada-tarjas sumiu"
    assert "pointer-events: none" in regra.group(), (
        "sem pointer-events:none a camada vira um vidro sobre a pagina inteira "
        "e impede toda selecao de texto"
    )


def test_tarja_continua_clicavel():
    """A contrapartida: desligar uma tarja com o clique tem de continuar."""
    css = (ESTATICOS / "estilo.css").read_text(encoding="utf-8")
    regra = re.search(r"\n\.tarja\s*\{[^}]*\}", css)
    assert regra, "regra .tarja sumiu"
    assert "pointer-events: auto" in regra.group(), (
        "sem reativar no retangulo, clicar na tarja para desliga-la para de "
        "funcionar"
    )


def test_camada_de_texto_fica_abaixo_das_tarjas():
    """Ordem de empilhamento: a tarja precisa cobrir o texto visualmente."""
    css = (ESTATICOS / "estilo.css").read_text(encoding="utf-8")
    texto = re.search(r"\.camada-texto\s*\{[^}]*\}", css).group()
    z_texto = int(re.search(r"z-index:\s*(\d+)", texto).group(1))
    z_tarja = int(re.search(r"\.camada-tarjas\s*\{\s*z-index:\s*(\d+)", css).group(1))
    assert z_tarja > z_texto


# --------------------------------------------------------------------------
# Regressão 2 — o navegador não pode servir JS/CSS velho
# --------------------------------------------------------------------------
def test_index_carimba_versao_nos_estaticos(cliente):
    html = cliente.get("/").text
    for arquivo in ("estilo.css", "app.js"):
        assert re.search(rf"/static/{re.escape(arquivo)}\?v=\d+", html), (
            f"{arquivo} sem carimbo de versao: o navegador vai servir a versao "
            "antiga depois de uma correcao"
        )


def test_index_nao_e_cacheado(cliente):
    """A página carrega os carimbos; ela mesma cacheada anula o mecanismo."""
    r = cliente.get("/")
    assert "no-store" in r.headers.get("cache-control", "")


def test_carimbo_muda_quando_o_arquivo_muda(cliente, monkeypatch, tmp_path):
    """A propriedade que faz o mecanismo valer a pena.

    Um carimbo fixo seria pior que nenhum: daria a impressão de que o cache
    está resolvido enquanto o navegador continua servindo a versão antiga.

    Roda sobre uma cópia — em execução normal `src/` entra no container como
    somente leitura, e alterar o arquivo real seria efeito colateral de teste.
    """
    import os
    import shutil

    copia = tmp_path / "static"
    shutil.copytree(ESTATICOS, copia)
    monkeypatch.setattr(app_mod, "ESTATICOS", copia)

    versao_antes = re.search(r"app\.js\?v=(\d+)", cliente.get("/").text).group(1)

    alvo = copia / "app.js"
    st = alvo.stat()
    os.utime(alvo, (st.st_atime, st.st_mtime + 10))

    versao_depois = re.search(r"app\.js\?v=(\d+)", cliente.get("/").text).group(1)
    assert versao_depois != versao_antes


# --------------------------------------------------------------------------
# Os estáticos existem e são servidos
# --------------------------------------------------------------------------
@pytest.mark.parametrize("caminho", ["/static/app.js", "/static/estilo.css"])
def test_estatico_e_servido(cliente, caminho):
    r = cliente.get(caminho)
    assert r.status_code == 200
    assert len(r.content) > 500


def test_todo_id_usado_pelo_js_existe_no_html():
    """Renomear um id no HTML e esquecer o JS quebra a tela em silêncio."""
    html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    ids_html = set(re.findall(r'id="([^"]+)"', html))
    ids_js = set(re.findall(r'\$\("([^"]+)"\)', js))
    assert not (ids_js - ids_html), f"ids ausentes no HTML: {ids_js - ids_html}"


def test_tamanho_da_fonte_da_camada_de_texto_nao_usa_porcentagem():
    """O erro de unidade que quebrou a seleção inteira.

    ``font-size: N%`` é percentual da fonte do **elemento pai**, não da altura
    do container. Escrito assim, ``(100 * 10pt) / 842pt = 1.19%`` virava 1.19%
    de 14px — **0.17 pixel**. A camada de texto ficava microscópica, e daí:

    * o realce da seleção era invisível, e o usuário selecionava às cegas;
    * a largura medida era quase zero, o ``scaleX`` de correção calculava um
      fator gigante e esticava cada palavra por cima da linha inteira, de modo
      que arrastar o cursor atravessava dezenas de spans sobrepostos.

    Um único erro de unidade produziu dois sintomas que pareciam
    independentes. O tamanho tem de sair em pixel, calculado da altura
    renderizada.
    """
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    atribuicoes = re.findall(r"style\.fontSize\s*=\s*([^;]+);", js)
    assert atribuicoes, "a camada de texto deixou de definir fontSize"
    for a in atribuicoes:
        assert '"%"' not in a and "'%'" not in a, (
            f"fontSize em porcentagem ({a.strip()}): e percentual da fonte do "
            "pai, nao da altura da pagina"
        )
        assert '"px"' in a or "'px'" in a, (
            f"fontSize sem unidade px ({a.strip()}): o tamanho precisa vir da "
            "altura renderizada"
        )


def test_camada_de_texto_reajusta_quando_a_pagina_muda_de_tamanho():
    """A altura renderizada só existe depois de a imagem carregar.

    Sem reajuste, o primeiro cálculo acontece com a página ainda sem altura e
    a camada fica fora de escala para sempre — a seleção deixa de cair sobre
    as letras que o usuário vê.
    """
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    assert "ResizeObserver" in js


def test_clique_em_tarja_manual_remove_em_vez_de_desligar():
    """Desligar deixa um retângulo tracejado no lugar.

    Para uma proposta do detector isso é certo — o revisor precisa ver o que o
    sistema achou e ele recusou. Para um trecho que o próprio usuário
    adicionou, não: ele não propôs nada, ele mandou tarjar, e clicar é
    desfazer. Com o tracejado no lugar, a leitura correta é "não saiu".
    """
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    trecho = re.search(
        r'caixa\.addEventListener\("click".{0,220}', js, re.S
    )
    assert trecho, "o clique na tarja sumiu"
    corpo = trecho.group()
    assert "removerSpan" in corpo, "clique em tarja manual precisa remover"
    assert 'origem === "usuario"' in corpo, "a distinção por origem sumiu"


def test_sessao_sobrevive_a_recarga():
    """Um F5 acidental não pode jogar fora a revisão.

    A sessão vive no servidor; o navegador só precisa lembrar qual é. Sem
    isso, todo o trabalho — tarjas desligadas, trechos apontados à mão —
    ficava inalcançável enquanto a sessão seguia intacta do outro lado.
    """
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    assert "localStorage" in js
    assert "restaurarSessao" in js
    # E some quando o documento é descartado, senão a próxima carga tenta
    # retomar uma sessão que não existe mais.
    assert "esquecerSessao" in js


def test_so_o_identificador_vai_para_o_navegador():
    """Nenhum conteúdo de documento pode ir para o armazenamento local.

    O `localStorage` persiste em disco, fora do ciclo de vida da sessão e do
    saneamento do servidor. Guardar ali um trecho de documento seria uma
    cópia de dado pessoal que ninguém apaga.
    """
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    for m in re.finditer(r"localStorage\.setItem\(([^)]*)\)", js):
        args = m.group(1)
        assert "doc_id" in args or "id" in args, (
            f"localStorage.setItem({args}) guarda algo que nao e o identificador"
        )


def test_nenhuma_caixa_de_dialogo_do_navegador():
    """`confirm`/`alert` destoam da interface e não explicam o que fazem."""
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    # Ignora as ocorrências em comentário, que documentam por que sumiram.
    codigo = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    codigo = re.sub(r"//.*", "", codigo)
    for proibida in ("confirm(", "alert(", "prompt("):
        assert proibida not in codigo, f"{proibida} voltou ao codigo"
