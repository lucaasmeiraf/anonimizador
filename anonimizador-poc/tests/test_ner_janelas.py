"""Janelamento do NER: o corte é em caracteres, o teto do modelo é em tokens.

O defeito que estes testes trancam: `janela=1200` é medida em caracteres e o
BERT aceita 512 tokens. Os dois não são proporcionais. Prosa comum dá ~256
tokens em 1200 caracteres; texto denso em identificadores dá **648**.

O que acontecia: o modelo levantava `RuntimeError`, o `except` do `analyze`
engolia a janela inteira, e a detecção seguia sem nenhum nome daquele trecho —
sem erro na tela. Um bloco de 1.294 caracteres com um nome no meio produzia 60
spans de identificadores e **zero** PERSON. O usuário veria os CPFs tarjados e
concluiria que o documento não tem nomes.

Os testes rápidos aqui substituem a contagem de tokens por uma função de
mentira, para exercitar a subdivisão sem carregar 1 GB de modelo. O teste
marcado `slow` no fim faz a prova real.
"""

import pytest

from anonimizador.ner import TransformersNerRecognizer

PROSA = "Considerando o disposto na legislacao vigente e nos autos do processo. " * 40
DENSO = "Processo 0000000-00.2026.8.26.0100 CPF 529.982.247-25 RG 12.345.678-9\n" * 20


def recognizer(tokens_por_char: float) -> TransformersNerRecognizer:
    """Reconhecedor que não carrega modelo, com contagem de tokens fingida.

    O construtor já é preguiçoso — o modelo só é lido no primeiro `analyze` —
    então basta trocar `_conta_tokens` para exercitar todo o janelamento.
    """
    rec = TransformersNerRecognizer(model_id="fake", label_map={})
    rec._conta_tokens = lambda trecho: int(len(trecho) * tokens_por_char)
    return rec


# --- o caminho que já funcionava não pode mudar ----------------------------
def test_janela_que_cabe_sai_identica():
    """Regressão que mais importa: documento normal produz as mesmas janelas.

    Se este teste cair, a correção deixou de ser cirúrgica e passou a mexer nos
    números de avaliação de todo documento que já funcionava.
    """
    # Linha de base: contagem zero nunca subdivide, então o que sai daqui é
    # exatamente o janelamento por caractere, sem a correção agindo.
    base = recognizer(0.0)._janelas(PROSA)

    magro = recognizer(0.21)   # ~prosa: 1200 chars -> ~256 tokens
    gordo = recognizer(0.54)   # ~denso: 1200 chars -> ~648 tokens

    assert magro._janelas(PROSA) == base, "a correção mexeu em janela que já cabia"
    assert gordo._janelas(PROSA) != base, "a correção não agiu onde precisava"
    assert len(base) > 1, "o texto de teste precisa passar de uma janela"


def test_texto_curto_continua_uma_janela_so():
    assert recognizer(0.21)._janelas("Joao da Silva mora aqui.") == [(0, 24)]


# --- o caminho quebrado ----------------------------------------------------
def test_janela_densa_e_subdividida_ate_caber():
    rec = recognizer(0.54)
    janelas = rec._janelas(DENSO)
    assert len(janelas) > 1
    for ini, fim in janelas:
        cabe = rec._conta_tokens(DENSO[ini:fim]) <= rec.teto_tokens
        curta = fim - ini <= rec.janela_minima
        assert cabe or curta, f"janela {ini}:{fim} continua estourando o teto"


def test_subdivisao_nao_deixa_buraco():
    """Um buraco entre janelas é PII que nunca chega ao modelo.

    É o mesmo vazamento silencioso que a correção existe para fechar, só que
    introduzido pela própria correção — por isso a checagem é de cobertura
    total, caractere a caractere, e não de "as janelas parecem contíguas".
    """
    rec = recognizer(0.54)
    coberto = set()
    for ini, fim in rec._janelas(DENSO):
        coberto.update(range(ini, fim))
    assert coberto == set(range(len(DENSO)))


def test_subdivisao_mantem_sobreposicao_no_corte():
    """Sem sobreposição, um nome exatamente sobre o corte sumiria."""
    rec = recognizer(0.54)
    janelas = sorted(rec._janelas(DENSO))
    pares = [(janelas[i], janelas[i + 1]) for i in range(len(janelas) - 1)]
    assert pares, "o texto de teste precisa produzir mais de uma janela"
    for (_, fim_a), (ini_b, _) in pares:
        assert ini_b < fim_a, "janelas apenas encostadas: entidade no corte se perde"


def test_subdivisao_termina_mesmo_com_texto_impossivel():
    """Texto sem espaço nenhum não pode fazer a recursão rodar para sempre.

    O piso de `janela_minima` é o que garante isso. Uma janela que continue
    grande demais no piso segue para o modelo e cai no `except` — degradado,
    mas em um trecho pequeno e delimitado, não no documento inteiro.
    """
    rec = recognizer(5.0)  # absurdo de propósito: 5 tokens por caractere
    janelas = rec._janelas("0123456789" * 300)
    assert janelas
    assert all(fim > ini for ini, fim in janelas)
    assert max(fim - ini for ini, fim in janelas) <= rec.janela


# --- a prova real ----------------------------------------------------------
@pytest.mark.slow
def test_nome_em_bloco_denso_volta_a_ser_detectado():
    """Ponta a ponta com o modelo de verdade: o caso medido que falhava."""
    from anonimizador.pipeline import DetectionPipeline

    bloco = (
        "Processo 0000000-00.2026.8.26.0100 CPF 529.982.247-25 "
        "RG 12.345.678-9 Tel (11) 98765-4321 CEP 01310-100\n"
    )
    texto = bloco * 6 + "Servidor responsavel: Mariana Aparecida Souza\n" + bloco * 6

    spans = DetectionPipeline().analyze(texto)
    pessoas = [s for s in spans if s.entity == "PERSON"]
    assert pessoas, "o nome voltou a se perder no bloco denso"
    assert "Mariana" in " ".join(texto[s.start:s.end] for s in pessoas)
