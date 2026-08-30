"""Perfil de política de anonimização.

O teste que mais importa aqui é o que garante que um perfil pedindo operador
não implementado **falha alto**. Essa é a falha que o sistema não pode ter:
o usuário pede pseudônimo, o executor não sabe fazer, e o PDF sai com o dado
intacto acompanhado de um relatório dizendo que foi anonimizado.
"""

import json

import pytest

from anonimizador import config
from anonimizador.politica import (
    MANTER,
    MASCARA,
    PSEUDONIMO,
    TARJA,
    PerfilPolitica,
    PoliticaInvalida,
    PERFIS_DE_FABRICA,
    validar_perfil,
)


def test_operador_padrao_se_aplica_a_entidade_sem_regra():
    p = PerfilPolitica(nome="t", padrao=TARJA, regras={"ORGANIZATION": MANTER})
    assert p.operador_de("CPF") == TARJA
    assert p.operador_de("ORGANIZATION") == MANTER


def test_entidades_com_filtra_pelo_operador():
    p = PerfilPolitica(nome="t", padrao=TARJA, regras={"ORGANIZATION": MANTER})
    assert p.entidades_com(MANTER, ["CPF", "ORGANIZATION"]) == ["ORGANIZATION"]


def test_roundtrip_de_serializacao():
    p = PerfilPolitica(nome="t", descricao="d", padrao=TARJA,
                       regras={"CPF": TARJA}, threshold=0.5)
    assert PerfilPolitica.from_dict(p.to_dict()) == p


def test_roundtrip_em_arquivo(tmp_path):
    p = PERFIS_DE_FABRICA["publicacao-oficial"]
    caminho = tmp_path / "perfil.json"
    p.salvar(caminho)
    assert json.loads(caminho.read_text(encoding="utf-8"))["nome"] == p.nome
    assert PerfilPolitica.carregar(caminho) == p


def test_perfil_sem_nome_e_recusado():
    with pytest.raises(PoliticaInvalida):
        PerfilPolitica.from_dict({"padrao": TARJA})


@pytest.mark.parametrize("nome", sorted(PERFIS_DE_FABRICA))
def test_perfis_de_fabrica_sao_validos(nome):
    validar_perfil(PERFIS_DE_FABRICA[nome], config.ENTIDADES_ATIVAS)


def test_operador_nao_implementado_falha_alto():
    p = PerfilPolitica(nome="t", padrao=TARJA, regras={"PERSON": PSEUDONIMO})
    with pytest.raises(PoliticaInvalida, match="nao implementado"):
        validar_perfil(p, config.ENTIDADES_ATIVAS)


def test_mascara_tambem_falha_enquanto_nao_existir():
    p = PerfilPolitica(nome="t", padrao=MASCARA)
    with pytest.raises(PoliticaInvalida, match="nao implementado"):
        validar_perfil(p, config.ENTIDADES_ATIVAS)


def test_entidade_desconhecida_e_recusada():
    p = PerfilPolitica(nome="t", padrao=TARJA, regras={"NAO_EXISTE": TARJA})
    with pytest.raises(PoliticaInvalida, match="entidade desconhecida"):
        validar_perfil(p, config.ENTIDADES_ATIVAS)


def test_operador_inventado_e_recusado():
    p = PerfilPolitica(nome="t", padrao=TARJA, regras={"CPF": "borrar"})
    with pytest.raises(PoliticaInvalida, match="operador desconhecido"):
        validar_perfil(p, config.ENTIDADES_ATIVAS)


@pytest.mark.parametrize("valor", [-0.1, 1.5])
def test_threshold_fora_da_faixa_e_recusado(valor):
    p = PerfilPolitica(nome="t", padrao=TARJA, threshold=valor)
    with pytest.raises(PoliticaInvalida, match="threshold"):
        validar_perfil(p, config.ENTIDADES_ATIVAS)


def test_perfil_de_fabrica_reproduz_a_politica_atual_do_pipeline():
    """`maxima-protecao` tem de coincidir com `ENTIDADES_REDIGIDAS`.

    Enquanto as duas representações da política coexistirem, elas precisam
    concordar — senão a tela prometeria uma coisa e o executor faria outra.
    """
    p = PERFIS_DE_FABRICA["maxima-protecao"]
    tarjadas = set(p.entidades_com(TARJA, config.ENTIDADES_ATIVAS))
    assert tarjadas == set(config.ENTIDADES_REDIGIDAS)
