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


def test_cpf_com_dv_errado_continua_sendo_cpf(pipe):
    """DV errado não muda o **rótulo**, muda a força da evidência.

    Este teste exigia o contrário — que o trecho fosse descartado — e passava
    por um motivo que não era o dele. Descoberto em 2026-09-17, ao exigir
    âncora para as entidades de forma ambígua:

    `52998224726` fecha o checksum de **PIS**. Então o PIS disparava com score
    1.0, vencia a sobreposição contra o CPF de checksum inválido, e o span
    sumia da lista de CPFs — o teste ficava verde. Só que o trecho não estava
    descartado: estava na tela **rotulado como PIS_PASEP**, numa frase que diz
    literalmente "CPF nº".

    Rótulo errado é o terceiro modo de falha da tabela do `CLAUDE.md` §1 com
    outra roupa: o revisor lê a razão errada para a tarja e não tem como
    desconfiar. Pior que não detectar, porque parece certo.

    O que se exige agora é o comportamento decidido em `8701910`: o trecho
    aparece, **como CPF**, com a marca de checksum inválido que a tela
    transforma em borda âmbar.
    """
    texto = "Consta no CPF nº 529.982.247-26 do requerente."
    achados = [s for s in pipe.analyze(texto) if s.text_of(texto) == "529.982.247-26"]
    assert achados, "o trecho não pode sumir em silêncio"
    (achado,) = achados
    assert achado.entity == "CPF", (
        f"rotulado como {achado.entity} — a forma ambígua venceu a âncora"
    )
    assert achado.nota == "checksum_invalido"


def test_cnpj(pipe):
    texto = "Empresa inscrita no CNPJ/MF sob o nº 11.222.333/0001-81."
    assert ("CNPJ", "11.222.333/0001-81") in _entidades(pipe, texto)


def test_email_e_telefone(pipe):
    texto = "Contato: fulano@exemplo.com.br, telefone (11) 98765-4321."
    ents = _entidades(pipe, texto)
    assert ("EMAIL", "fulano@exemplo.com.br") in ents
    assert ("TELEFONE", "(11) 98765-4321") in ents


def test_ddd_invalido_vira_suspeita_e_nao_sumico(pipe):
    """DDD inválido derruba a *certeza*, não o candidato.

    Este teste exigia o contrário até 2026-09-17 — que o trecho não fosse
    detectado — e ficou vermelho, sem ninguém ver, desde `8701910`
    ("identificador com checksum invalido deixa de ser invisivel"). Como
    `make test` desmarca os `slow`, a suíte rápida seguiu verde.

    A decisão daquele commit é a que vale, e está registrada na seção 5 do
    `CLAUDE.md` com a medição que a motivou: sumir com o identificador cujo
    dígito verificador não fecha escondia do revisor justamente o caso que ele
    precisa olhar — minuta, modelo e material de treinamento são cheios deles.
    O trecho sobrevive com score baixo e marcado, e a tela o desenha com borda
    âmbar em vez de tarja cheia.

    O que este teste trava agora é a distinção: **detectado, mas como palpite,
    nunca como certeza.** Se alguém devolver o score a 1.0, ou apagar a marca,
    um palpite volta a parecer evidência fechada.
    """
    texto = "Número de protocolo (00) 98765-4321 registrado."
    achados = [s for s in pipe.analyze(texto) if s.entity == "TELEFONE"]
    assert achados, "o candidato não pode sumir em silêncio"
    (achado,) = achados
    assert achado.score < 1.0, "DDD inválido não pode dar certeza"
    assert achado.nota == "checksum_invalido"


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
