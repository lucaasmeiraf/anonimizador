"""A2 — o token: determinismo, ausência de colisão, irreversibilidade.

Plano em `goal-fase-2a.md` §2. Os testes aqui cobrem as duas armadilhas que o
módulo existe para evitar (token derivado do valor, e colisão tratada como
improvável em vez de impedida), porque as duas falham em silêncio.
"""

from __future__ import annotations

import random

import pytest

from anonimizador import config
from anonimizador.pseudonimo import (
    AlocadorDeToken,
    PseudonimoImpossivel,
    pseudonimizar_texto,
    tokens_de,
)
from anonimizador.spans import Span


# --------------------------------------------------------------------------
# Determinismo intradocumento
# --------------------------------------------------------------------------


def test_mesmo_valor_recebe_o_mesmo_token():
    a = AlocadorDeToken()
    primeiro = a.token_de("PERSON", "Mariana Aparecida Souza")
    segundo = a.token_de("PERSON", "Mariana Aparecida Souza")
    assert primeiro == segundo


def test_valores_distintos_recebem_tokens_distintos():
    a = AlocadorDeToken()
    tokens = {
        a.token_de("PERSON", f"Pessoa Numero {i}") for i in range(200)
    }
    assert len(tokens) == 200


def test_quebra_de_linha_no_meio_do_nome_nao_gera_dois_tokens():
    """A mesma pessoa reaparece com quebra de linha no meio do nome.

    Sem colapsar espaço em branco ela receberia dois tokens, e quem lesse o
    documento veria dois atores onde há um.
    """
    a = AlocadorDeToken()
    assert a.token_de("PERSON", "Mariana Aparecida\nSouza") == a.token_de(
        "PERSON", "Mariana Aparecida Souza"
    )


def test_documentos_diferentes_dao_tokens_diferentes():
    """Determinismo é intradocumento, e isso é escolha, não limitação.

    Token estável *entre* documentos criaria capacidade de vínculo: quem
    tivesse dois arquivos saberia que a mesma pessoa aparece nos dois, sem
    ter chave nenhuma. Um alocador por documento é o que impede isso.
    """
    valor = "Joaquim Ferreira Lima"
    tokens = {AlocadorDeToken().token_de("PERSON", valor) for _ in range(20)}
    # Com 65.536 possibilidades, 20 sorteios independentes praticamente nunca
    # coincidem todos; exigir mais de um distinto basta para provar que não há
    # derivação do valor.
    assert len(tokens) > 1


def test_token_nao_e_derivado_do_valor():
    """A armadilha principal: `sha256(valor)[:4]` é reversível por força bruta.

    Se o token fosse derivado, dois alocadores independentes produziriam o
    mesmo token para o mesmo valor — e quem tivesse uma lista de candidatos
    reidentificaria o documento por tentativa, sem chave e sem cofre.
    """
    valor = "Mariana Aparecida Souza"
    # Uma implementação derivada do valor daria sempre o mesmo token em
    # alocadores independentes. Com sorteio em 65.536 possibilidades, 30
    # emissões independentes coincidirem todas é improvável ao ponto de não
    # acontecer — então "todas iguais" identifica a implementação errada.
    emitidos = [AlocadorDeToken().token_de("PERSON", valor) for _ in range(30)]
    assert len(set(emitidos)) > 1, (
        "token parece derivado do valor: alocadores independentes deram o "
        "mesmo resultado, o que o torna reversível por força bruta"
    )


# --------------------------------------------------------------------------
# Colisão
# --------------------------------------------------------------------------


def test_colisao_e_impedida_e_nao_apenas_improvavel():
    """Força o caminho de colisão com um espaço de token minúsculo.

    Com `largura=1` há 16 sufixos possíveis. Pedir 16 tokens esgota o espaço
    e obriga o alocador a rejeitar repetidos em quase toda emissão — o que
    torna o teste determinístico em vez de depender de sorte.
    """
    a = AlocadorDeToken(rng=random.Random(20260905), largura=1)
    tokens = [a.token_de("PERSON", f"Pessoa {i}") for i in range(16)]
    assert len(set(tokens)) == 16


def test_espaco_esgotado_falha_alto():
    """Devolver token repetido fundiria dois atores em silêncio."""
    a = AlocadorDeToken(rng=random.Random(1), largura=1)
    for i in range(16):
        a.token_de("PERSON", f"Pessoa {i}")
    with pytest.raises(PseudonimoImpossivel, match="esgotado"):
        a.token_de("PERSON", "Pessoa 17")


# --------------------------------------------------------------------------
# Tipo
# --------------------------------------------------------------------------


def test_o_tipo_sobrevive_no_token():
    a = AlocadorDeToken()
    assert a.token_de("PERSON", "Fulano de Tal").startswith("[P-")
    assert a.token_de("CPF", "529.982.247-25").startswith("[CPF-")
    assert a.token_de("EMAIL", "x@y.com").startswith("[MAIL-")


def test_entidade_sem_sigla_falha_em_vez_de_cair_em_generico():
    """Prefixo genérico silencioso é como entidade nova entra sem decisão."""
    a = AlocadorDeToken()
    with pytest.raises(PseudonimoImpossivel, match="SIGLAS_TOKEN"):
        a.token_de("ENTIDADE_QUE_NAO_EXISTE", "qualquer coisa")


def test_toda_entidade_ativa_tem_sigla():
    """Fecha a lacuna que o CLAUDE.md descreve ao adicionar entidade nova."""
    faltando = [e for e in config.ENTIDADES_ATIVAS if e not in config.SIGLAS_TOKEN]
    assert not faltando, f"entidades sem sigla: {faltando}"


# --------------------------------------------------------------------------
# Substituição no texto
# --------------------------------------------------------------------------

TEXTO = (
    "O servidor Mariana Aparecida Souza compareceu.\n"
    "Coube a Mariana Aparecida Souza relatar.\n"
    "O interessado Joaquim Ferreira Lima apresentou defesa.\n"
)


def _spans_do_texto() -> list[Span]:
    spans = []
    for valor in ("Mariana Aparecida Souza", "Joaquim Ferreira Lima"):
        inicio = 0
        while (i := TEXTO.find(valor, inicio)) != -1:
            spans.append(Span(start=i, end=i + len(valor), entity="PERSON", score=1.0))
            inicio = i + len(valor)
    return spans


def test_token_ocupa_a_posicao_do_valor_no_texto():
    """O análogo textual do A1 — aqui tem de passar por construção."""
    res = pseudonimizar_texto(TEXTO, _spans_do_texto())
    assert "O servidor [P-" in res.texto
    assert "] compareceu." in res.texto
    assert "O interessado [P-" in res.texto
    assert "] apresentou defesa." in res.texto


def test_mesmo_nome_vira_o_mesmo_token_nas_duas_ocorrencias():
    res = pseudonimizar_texto(TEXTO, _spans_do_texto())
    tokens = [s.token for s in res.substituicoes if s.entity == "PERSON"]
    # Mariana aparece 2x, Joaquim 1x -> 2 tokens distintos em 3 substituições.
    assert len(tokens) == 3
    assert len(set(tokens)) == 2


def test_nenhum_valor_original_sobrevive():
    res = pseudonimizar_texto(TEXTO, _spans_do_texto())
    assert "Mariana Aparecida Souza" not in res.texto
    assert "Joaquim Ferreira Lima" not in res.texto


def test_o_texto_fora_dos_spans_fica_intacto():
    res = pseudonimizar_texto(TEXTO, _spans_do_texto())
    for trecho in ("O servidor ", " compareceu.", "Coube a ", " relatar."):
        assert trecho in res.texto


def test_spans_sobrepostos_falham_alto():
    """Token dentro de token produziria texto corrompido que parece pronto."""
    spans = [
        Span(start=11, end=34, entity="PERSON", score=1.0),
        Span(start=19, end=34, entity="PERSON", score=1.0),
    ]
    with pytest.raises(PseudonimoImpossivel, match="sobrepostos"):
        pseudonimizar_texto(TEXTO, spans)


def test_sem_spans_devolve_o_texto_inalterado():
    res = pseudonimizar_texto(TEXTO, [])
    assert res.texto == TEXTO
    assert res.substituicoes == []


def test_tokens_de_devolve_distintos_ordenados():
    res = pseudonimizar_texto(TEXTO, _spans_do_texto())
    tokens = tokens_de(res.substituicoes)
    assert tokens == sorted(set(tokens))
    assert len(tokens) == 2


# --------------------------------------------------------------------------
# Spans adjacentes e documento do corpus
# --------------------------------------------------------------------------


def test_spans_adjacentes_sao_permitidos():
    """Encostar não é sobrepor.

    Dois spans em que ``a.end == b.start`` são disjuntos e legítimos — um CEP
    colado a um telefone, por exemplo. Recusá-los seria confundir adjacência
    com sobreposição e quebrar documentos válidos.
    """
    texto = "CEP 01310-100(11) 98765-4321 fim"
    i = texto.find("01310-100")
    j = texto.find("(11) 98765-4321")
    spans = [
        Span(start=i, end=i + len("01310-100"), entity="CEP", score=1.0),
        Span(start=j, end=j + len("(11) 98765-4321"), entity="TELEFONE", score=1.0),
    ]
    assert spans[0].end == spans[1].start  # encostam

    res = pseudonimizar_texto(texto, spans)
    assert "01310-100" not in res.texto
    assert "98765-4321" not in res.texto
    assert res.texto.startswith("CEP [CEP-")
    assert res.texto.endswith(" fim")
    assert len(res.substituicoes) == 2


def test_documento_do_corpus_inteiro():
    """Ponta a ponta sobre um documento real do corpus, com o gabarito.

    Usa `source_text` e os spans `gold`, então não carrega modelo e não
    depende do alinhamento — o que está sob teste aqui é a substituição, não
    a detecção.
    """
    import json
    from pathlib import Path

    from anonimizador.spans import resolver_sobreposicoes
    from anonimizador.verifier import verify_texto

    caminho = Path("/app/eval/datasets/contrato-000.json")
    if not caminho.exists():  # corpus não gerado neste ambiente
        pytest.skip("corpus ausente; rode `make corpus`")

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    texto = dados["source_text"]
    spans = resolver_sobreposicoes(
        [
            Span(
                start=g["start"],
                end=g["end"],
                entity=g["label"],
                score=1.0,
            )
            for g in dados["gold"]
            if g["label"] in config.SIGLAS_TOKEN
        ]
    )
    assert spans, "gabarito sem spans utilizáveis"

    res = pseudonimizar_texto(texto, spans)
    rel = verify_texto(res.texto, res.valores, tokens_de(res.substituicoes))

    assert rel.ok, f"vazamentos: {[str(l) for l in rel.leaks]}"
    assert len(res.substituicoes) == len(spans)
    # O texto ao redor não foi tocado: o tamanho só varia pelo que foi trocado.
    assert res.texto != texto
    assert "CONTRATO DE PRESTAÇÃO DE SERVIÇOS" in res.texto
