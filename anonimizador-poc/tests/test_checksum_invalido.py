"""Os três níveis de evidência do ``ChecksumRecognizer``.

A Fase 0 tratava checksum como passa/reprova: DV errado devolvia ``False`` e o
Presidio **descartava** o candidato — antes mesmo de o enriquecedor de
contexto olhar a palavra ``CPF:`` imediatamente anterior.

Medido em quatro documentos reais de teste: 35 números com forma de CPF, 23
com âncora explícita, **nenhum detectado**, porque nenhum tinha DV válido. Os
documentos diziam, em texto, ``CPF fictício nº``.

Estes testes fixam a fronteira nas duas direções, porque errar para qualquer
lado é grave:

* **frouxo demais** → tarja número de nota fiscal e matrícula, e a precisão do
  reconhecedor (hoje 1.000 com zero falso positivo) desaba;
* **rígido demais** → volta o ponto cego: CPF com dígito trocado, minuta com
  identificador fictício e PDF vindo de OCR passam legíveis.

Os testes rodam sobre o reconhecedor isolado, sem carregar modelo de NER. O
score aqui é o do reconhecedor puro; no pipeline completo o enriquecedor de
contexto ainda soma por cima, o que só reforça os casos ancorados.
"""

import pytest

from anonimizador.recognizers.base import (
    SCORE_ANCORA_SEM_CHECKSUM,
    SCORE_MASCARA_SEM_CHECKSUM,
)
from anonimizador.recognizers.cpf import build as build_cpf

CPF_VALIDO = "529.982.247-25"
CPF_VALIDO_CRU = "52998224725"
# Mesma forma, último dígito trocado: é o "CPF fictício" dos modelos.
CPF_INVALIDO = "529.982.247-26"
CPF_INVALIDO_CRU = "52998224726"


@pytest.fixture
def rec():
    return build_cpf()


def achar(rec, texto):
    return rec.analyze(texto, ["CPF"])


# --------------------------------------------------------------------------
# Nível 1 — checksum válido é certeza, e não depende de nada mais
# --------------------------------------------------------------------------
def test_checksum_valido_sem_ancora_tem_score_maximo(rec):
    r = achar(rec, f"Pagamento referente a {CPF_VALIDO} na conta corrente.")
    assert len(r) == 1
    assert r[0].score == 1.0


def test_checksum_valido_cru_sem_ancora_tambem(rec):
    r = achar(rec, f"Registro {CPF_VALIDO_CRU} arquivado.")
    assert len(r) == 1
    assert r[0].score == 1.0


# --------------------------------------------------------------------------
# Nível 2 — máscara é evidência suficiente sem âncora
# --------------------------------------------------------------------------
def test_mascara_sem_checksum_e_detectada(rec):
    """`999.999.999-99` não é forma que apareça por acaso."""
    r = achar(rec, f"Consta no cadastro o número {CPF_INVALIDO} sem conferência.")
    assert len(r) == 1
    assert r[0].score >= SCORE_MASCARA_SEM_CHECKSUM
    assert r[0].score < 1.0, "não pode se passar por certeza matemática"


def test_mascara_sem_checksum_vem_marcada(rec):
    """A interface precisa distinguir palpite forte de certeza."""
    r = achar(rec, f"Número {CPF_INVALIDO} pendente.")
    assert (r[0].recognition_metadata or {}).get("checksum") == "invalido"


def test_checksum_valido_nao_vem_marcado(rec):
    r = achar(rec, f"Número {CPF_VALIDO} conferido.")
    assert (r[0].recognition_metadata or {}).get("checksum") is None


# --------------------------------------------------------------------------
# Nível 3 — forma crua exige que o texto declare o que o número é
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "frase",
    [
        "Requerente inscrito no CPF {v}, servidor.",
        "CPF: {v}",
        "portador do CPF nº {v}",
        "CPF/MF sob o nº {v}",
    ],
)
def test_forma_crua_com_ancora_e_detectada(rec, frase):
    r = achar(rec, frase.format(v=CPF_INVALIDO_CRU))
    assert len(r) == 1, f"nao achou em {frase!r}"
    assert r[0].score >= SCORE_ANCORA_SEM_CHECKSUM


def test_forma_crua_sem_ancora_e_descartada(rec):
    """O que preserva a precisão.

    Onze dígitos soltos são nota fiscal, protocolo, matrícula. Sem checksum e
    sem o texto dizendo o que é, não há evidência de nada.
    """
    assert achar(rec, f"Nota fiscal {CPF_INVALIDO_CRU} emitida em janeiro.") == []


# Todos com checksum comprovadamente inválido — conferido com `validate_cpf`.
# Um número de 11 dígitos escolhido a esmo tem ~1% de chance de fechar o
# mod-11 por acaso, e aí o teste mediria a coisa errada.
@pytest.mark.parametrize(
    "ruido",
    [
        "Protocolo 20260830112 recebido pelo setor.",
        "Processo 12345678901 em tramitação.",
        "Matrícula 40028922000 do servidor.",
        "Nota fiscal 19730115200 emitida.",
    ],
)
def test_numero_de_11_digitos_sem_ancora_nao_vira_cpf(rec, ruido):
    assert achar(rec, ruido) == []


def test_ancora_longe_demais_nao_conta(rec):
    """A janela é curta de propósito.

    Alargá-la faria o rótulo de um campo alcançar o valor do campo seguinte —
    o erro que a desambiguação de CNH já teve de consertar uma vez.
    """
    texto = "CPF" + " preenchimento pendente de conferência posterior. " * 2
    texto += CPF_INVALIDO_CRU
    assert achar(rec, texto) == []


# --------------------------------------------------------------------------
# Ordenação dos níveis
# --------------------------------------------------------------------------
def test_checksum_valido_vence_os_demais_niveis(rec):
    valido = achar(rec, f"CPF: {CPF_VALIDO}")[0].score
    mascara = achar(rec, f"Número {CPF_INVALIDO} solto")[0].score
    crua = achar(rec, f"CPF: {CPF_INVALIDO_CRU}")[0].score
    assert valido > mascara
    assert valido > crua
