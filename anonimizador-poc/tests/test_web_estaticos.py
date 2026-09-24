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
        # `cqw` também serve, e pelo mesmo motivo que `px`: é relativo à
        # largura *renderizada* do container (`.camada-tarjas`), não à fonte do
        # pai. É o que o código na prévia usa — lá a imagem pode não ter
        # carregado ainda quando a caixa é desenhada, e um `px` calculado
        # nesse momento sairia zero.
        assert '"px"' in a or "'px'" in a or "}cqw`" in a, (
            f"fontSize sem unidade px ou cqw ({a.strip()}): o tamanho precisa "
            "vir do tamanho renderizado"
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
    # Desde o redesenho de 2026-09-23 o clique abre as ações da marcação, em
    # vez de agir direto; a propriedade vive agora em `acoesDaMarca`.
    clique = re.search(r'caixa\.addEventListener\("click".{0,220}', js, re.S)
    assert clique, "o clique na marcação sumiu"
    assert "abrirPopoverMarca" in clique.group()

    acoes = js[js.index("function acoesDaMarca") :]
    acoes = acoes[: acoes.index("\n}")]
    manual = acoes[acoes.index('origem === "usuario"') :]
    manual = manual[: manual.index("return acoes")]
    assert "removerSpan" in manual, "trecho manual precisa ser removido, não desligado"
    assert "alternar(" not in manual, "trecho manual não pode oferecer desligar"


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


# --------------------------------------------------------------------------
# A6 / RN-01 — a tela diz a verdade no momento da escolha
# --------------------------------------------------------------------------
def test_a_escolha_entre_os_dois_operadores_esta_na_tela():
    """Não pode ser configuração escondida — é o A6 do `goal-fase-2.md`.

    A escolha muda o que o documento serve para fazer depois: tarja para
    publicar, código para mandar a uma análise. Um seletor atrás de "avançado"
    faria a maioria nunca descobrir a metade do produto.
    """
    html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
    assert 'name="modo"' in html
    assert 'value="tarja"' in html and 'value="pseudonimo"' in html


def test_a_tela_afirma_a_irreversibilidade_no_momento_da_escolha():
    """RN-01, e é a afirmação jurídica mais sensível da interface.

    Enquanto não há cofre, a saída é irreversível **inclusive para nós** — o
    código é sorteado, não derivado do valor. É o que sustenta dizer que o
    arquivo de saída não é dado pessoal.

    No dia em que a Fase B ligar o cofre, esta frase deixa de ser verdadeira
    para o arquivo com cofre, e a tela terá de dizer o contrário **no mesmo
    lugar**. Este teste existe para que a frase não seja apagada nem alterada
    sem que alguém repare no que está mexendo.
    """
    html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
    bloco = html[html.index('id="bloco-modo"') : html.index('id="fim-bloco-modo"')]
    assert "removido do arquivo" in bloco
    assert "nem nós conseguimos voltar atrás" in bloco
    assert "não há mapa guardado" in bloco or "não existe chave" in bloco

    # O texto longo foi para "Como funciona?", que nasce fechado. A afirmação
    # central precisa continuar **visível** ao lado da escolha, não só dentro
    # de um painel que o usuário talvez nunca abra.
    visivel = re.search(r'<p class="aviso-irreversivel">(.*?)</p>', bloco, re.S)
    assert visivel, "a linha visível de irreversibilidade sumiu"
    assert "removido do arquivo" in visivel.group(1)
    assert "não há mapa guardado" in re.sub(r"\s+", " ", visivel.group(1))


def test_trecho_que_vai_sair_do_pdf_nunca_some_da_tela():
    """Esconder fragmento de palavra e categoria desligada é limpeza de tela.

    Esconder algo que **vai** sair do PDF seria a tela mentindo sobre o
    arquivo. A regra de `visivelNoDocumento` decide primeiro por
    `sera_tarjado`, e só depois olha se é fragmento.
    """
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    corpo = js[js.index("function visivelNoDocumento") :]
    corpo = corpo[: corpo.index("\n}")]
    assert corpo.index("if (s.sera_tarjado) return true") < corpo.index(
        "if (s.fragmento) return false"
    )


def test_preverificacao_atrasada_e_descartada():
    """Resposta que chega depois de outra edição fala de uma proposta que já
    não existe; mostrá-la seria pendência falsa, ou pior, ok falso."""
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    corpo = js[js.index("async function rodarPreverificacao") :]
    corpo = corpo[: corpo.index("\n}")]
    assert "dados.versao === doc.versao" in corpo


def test_documento_e_inspetor_rolam_dentro_da_janela():
    """Regressão achada na captura de tela do redesenho, em 2026-09-23.

    Sem limitar a linha da grade, ela crescia até caber o conteúdo — o
    contêiner de rolagem de um documento de 3 páginas media 3.778px —, e nem
    o documento nem o inspetor rolavam: ficavam cortados na borda da janela.
    Nada quebrava, nenhum erro aparecia; só não dava para chegar à página 2.
    """
    css = (ESTATICOS / "estilo.css").read_text(encoding="utf-8")
    regra = re.search(r"#tela-revisao\s*\{[^}]*\}", css).group()
    assert "grid-template-rows: minmax(0, 1fr)" in regra
    assert re.search(r"#tela-revisao > \*\s*\{\s*min-height: 0", css)


def test_etapas_sao_dados():
    """A etapa de análise por IA entra como uma linha, sem refazer o layout."""
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    assert "const ETAPAS = [" in js
    html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
    assert 'id="etapas"' in html
    assert "Revisar</" not in html, "as etapas voltaram a ser marcação fixa"


def test_o_texto_dos_vetores_acompanha_o_modo():
    """"10 vetores" vira mentira quando o verificador roda o décimo primeiro."""
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    assert "11 vetores" in js and "10 vetores" in js
    assert "sincronizarModo" in js


def test_trecho_manual_desligado_perde_o_preenchimento():
    """Desligado tem de **parecer** desligado, inclusive o apontado à mão.

    Regressão real, relatada em 2026-09-17: o usuário desmarcava os trechos
    manuais, o servidor desligava, e o retângulo continuava preenchido — só
    ganhava a borda tracejada. A tela afirmava "ligado" para algo que ele
    acabara de mandar desligar.

    A causa era especificidade: `.tarja.desligada` e `.tarja.manual` empatam, e
    `.manual` vencia por vir depois no arquivo. Por isso a asserção aqui é
    sobre a regra de **três** classes — resolver por ordem funcionaria e
    quebraria de novo na próxima edição do arquivo.

    Isto não testa aparência: testa que o estado desligado é distinguível do
    ligado. Sem essa distinção o revisor aprova achando que tarjou algo que
    não vai ser tarjado, ou o contrário.
    """
    css = (ESTATICOS / "estilo.css").read_text(encoding="utf-8")
    regra = re.search(r"\.tarja\.manual\.desligada\s*\{[^}]*\}", css)
    assert regra, (
        "regra .tarja.manual.desligada sumiu — sem ela `.tarja.manual` volta a "
        "vencer por especificidade e o trecho desligado continua preenchido"
    )
    assert "background" in regra.group(0) and "transparent" in regra.group(0)


# --------------------------------------------------------------------------
# Envio a modelo externo — a tela diz o que as travas não provam
# --------------------------------------------------------------------------
def _bloco_analise() -> str:
    html = (ESTATICOS / "index.html").read_text(encoding="utf-8")
    return html[html.index('id="bloco-analise"') : html.index('class="bloco limitacoes"')]


def test_o_aviso_de_envio_vem_antes_do_botao():
    """`goal-fase-3.md` §2: o aviso existe no momento da escolha, não depois.

    As três frases travadas aqui são as que o sistema **não** pode deixar de
    dizer antes de um envio: que a detecção não é completa, que referência
    indireta não é detectada de forma alguma, e que o envio não tem desfazer.
    Cada uma delas é uma lacuna medida, não uma ressalva de estilo.
    """
    bloco = _bloco_analise()
    aviso = bloco.index('id="aviso-envio"')
    assert aviso < bloco.index('id="btn-analisar"')
    assert "não garante que tudo que era dado pessoal foi" in bloco
    assert "Referências indiretas" in bloco
    assert "O envio é irreversível" in bloco
    assert "não confere" in bloco, "a retenção no provedor não é verificada aqui"


def test_a_tela_nunca_chama_o_envio_de_seguro():
    """A frase que `goal-fase-3.md` §2 proíbe literalmente."""
    for arquivo in ("index.html", "app.js"):
        texto = (ESTATICOS / arquivo).read_text(encoding="utf-8").lower()
        assert "seguro para enviar" not in texto
        assert "seguro enviar" not in texto


def test_envio_exige_consentimento_e_ele_nao_persiste():
    """Consentimento por envio, não por sessão nem por configuração.

    O botão nasce desabilitado, só destrava com a caixa marcada, e o clique
    desmarca a caixa antes de enviar — um segundo envio exige decidir de novo.
    """
    bloco = _bloco_analise()
    assert re.search(r'id="btn-analisar"[^>]*\bdisabled\b', bloco)
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    clique = js[js.index('$("btn-analisar").addEventListener') :]
    clique = clique[: clique.index("fetch(")]
    assert '$("chk-consentimento").checked = false' in clique


def test_recusa_do_pre_envio_mostra_trecho_por_code_point():
    """Offset do Python é code point; `slice` do JS é UTF-16 (invariante 7).

    Com um emoji antes do achado, `texto.slice(ini, fim)` mostraria o trecho
    vizinho — e o botão "substituir" tarjaria o texto errado.
    """
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    recusa = js[js.index("function mostrarRecusaEnvio") :]
    assert "Array.from(textoPrevia)" in recusa
    assert "textoPrevia.slice(" not in recusa


def test_resposta_do_modelo_nunca_vai_para_innerhtml():
    """Texto vindo de fora da máquina é texto, não marcação."""
    js = (ESTATICOS / "app.js").read_text(encoding="utf-8")
    corpo = js[js.index("function mostrarResposta") :]
    corpo = corpo[: corpo.index("\n}")]
    # O comentário que explica a regra cita o nome proibido; só o código conta.
    corpo = re.sub(r"//.*", "", corpo)
    assert "innerHTML" not in corpo
    assert "textContent = a.resposta" in corpo
