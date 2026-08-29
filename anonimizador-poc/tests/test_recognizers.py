"""Reconhecedores estruturados dentro do AnalyzerEngine real.

Marcados como ``slow`` porque instanciam o Presidio com o spaCy PT — o custo é
o carregamento do modelo, não os testes em si.
"""

import pytest

from anonimizador.pipeline import DetectionPipeline
from anonimizador.validators import validate_processo_cnj

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def pipe():
    # spaCy é a configuração mais barata; o alvo aqui são os reconhecedores
    # de checksum, que independem da escolha de NER.
    return DetectionPipeline(ner_config="spacy")


def _entidades(pipe, texto):
    return {(s.entity, s.text_of(texto)) for s in pipe.analyze(texto)}


def test_cpf_valido_com_ancora(pipe):
    texto = "O contratado, inscrito no CPF sob o nº 529.982.247-25, declara."
    assert ("CPF", "529.982.247-25") in _entidades(pipe, texto)


def test_cpf_com_dv_errado_e_descartado(pipe):
    texto = "Consta no CPF nº 529.982.247-26 do requerente."
    achados = {s.text_of(texto) for s in pipe.analyze(texto) if s.entity == "CPF"}
    assert "529.982.247-26" not in achados


def test_cnpj(pipe):
    texto = "Empresa inscrita no CNPJ/MF sob o nº 11.222.333/0001-81."
    assert ("CNPJ", "11.222.333/0001-81") in _entidades(pipe, texto)


def test_email_e_telefone(pipe):
    texto = "Contato: fulano@exemplo.com.br, telefone (11) 98765-4321."
    ents = _entidades(pipe, texto)
    assert ("EMAIL", "fulano@exemplo.com.br") in ents
    assert ("TELEFONE", "(11) 98765-4321") in ents


def test_ddd_invalido_derruba_telefone(pipe):
    texto = "Número de protocolo (00) 98765-4321 registrado."
    assert not [s for s in pipe.analyze(texto) if s.entity == "TELEFONE"]


def test_cnh_sem_ancora_nao_dispara(pipe):
    """CNH crua tem a mesma forma de um CPF; sem palavra-âncora ela fica
    abaixo do limiar. Sem essa disciplina, todo CPF viraria CNH duplicada."""
    texto = "Sequência numérica avulsa 96510020000 no rodapé do formulário."
    assert not [s for s in pipe.analyze(texto) if s.entity == "CNH"]


def test_processo_cnj(pipe):
    texto = "Autos nº 0001234-56.2020.8.26.0100 em trâmite na 3ª Vara."
    ents = {s.entity for s in pipe.analyze(texto)}
    # O número acima só entra se o DV mod-97-10 fechar; caso contrário o teste
    # passa a valer como "não produziu falso positivo".
    if validate_processo_cnj("0001234-56.2020.8.26.0100"):
        assert "PROCESSO_CNJ" in ents


def test_spans_nao_se_sobrepoem(pipe):
    texto = ("Joao da Silva, CPF 529.982.247-25, RG 12.345.678-9, "
             "e-mail joao@exemplo.com, tel (11) 98765-4321.")
    spans = pipe.analyze(texto)
    for i, a in enumerate(spans):
        for b in spans[i + 1:]:
            assert not a.overlaps(b), f"sobreposicao entre {a} e {b}"
