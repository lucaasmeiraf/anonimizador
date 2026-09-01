"""Apuração do gate de usabilidade.

Só a lógica pura: ler o registro preenchido e transformá-lo em número. A
colheita dos documentos precisa do modelo de NER e é exercitada pelo próprio
alvo `gate-usabilidade`, não aqui.

O que estes testes protegem é a aritmética de um resultado que vai virar
decisão de produto. Um denominador errado aqui produziria uma taxa
tranquilizadora sobre uma medição ruim — e ninguém confere a conta de um
número que já parece bom.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from gate_usabilidade import apurar, formatar  # noqa: E402


def linha(participante="P1", documento="documento-01.pdf", achou="sim",
          segundos="30", falsos_alarmes="0", observacao=""):
    return {
        "participante": participante,
        "documento": documento,
        "achou": achou,
        "segundos": segundos,
        "falsos_alarmes": falsos_alarmes,
        "observacao": observacao,
    }


def test_registro_vazio_nao_inventa_resultado():
    """Zero sessão tem de dizer zero, não 0% de acerto.

    A diferença importa: "0%" leria como 'ninguém achou', que é uma conclusão
    sobre a interface. Nenhuma sessão não é conclusão nenhuma.
    """
    assert apurar([]) == {"sessoes": 0}
    assert "Nenhuma sessão" in formatar(apurar([]))


def test_linha_sem_participante_nao_entra_na_conta():
    """Linha em branco no fim do CSV é o caso comum, e inflaria o denominador."""
    resumo = apurar([linha(), {"participante": "  ", "achou": "sim"}])
    assert resumo["sessoes"] == 1
    assert resumo["taxa"] == 1.0


def test_taxa_e_mediana():
    linhas = [
        linha("P1", "documento-01.pdf", "sim", "20"),
        linha("P2", "documento-01.pdf", "nao", "300"),
        linha("P3", "documento-02.pdf", "sim", "40"),
        linha("P4", "documento-02.pdf", "sim", "60"),
    ]
    resumo = apurar(linhas)

    assert resumo["sessoes"] == 4
    assert resumo["participantes"] == 4
    assert resumo["achou"] == 3
    assert resumo["taxa"] == 0.75
    # A mediana considera **só quem achou**: incluir o tempo de quem não achou
    # misturaria "demorou para achar" com "desistiu", que são coisas
    # diferentes e puxariam o número para o lado errado.
    assert resumo["mediana_segundos"] == 40


@pytest.mark.parametrize("valor", ["sim", "SIM", " s ", "1", "x", "true"])
def test_achou_aceita_as_grafias_que_alguem_digitaria(valor):
    assert apurar([linha(achou=valor)])["achou"] == 1


@pytest.mark.parametrize("valor", ["nao", "não", "n", "0", "", "  "])
def test_qualquer_outra_coisa_conta_como_nao_achou(valor):
    """Na dúvida, não achou.

    O viés tem de ser para o lado pessimista: um preenchimento ambíguo lido
    como acerto produziria um gate aprovado por erro de digitação.
    """
    assert apurar([linha(achou=valor)])["achou"] == 0


def test_segundos_invalido_nao_derruba_a_apuracao():
    """Campo mal preenchido perde o tempo, não a sessão."""
    resumo = apurar([linha(segundos=""), linha("P2", segundos="45,5")])
    assert resumo["sessoes"] == 2
    assert resumo["achou"] == 2
    assert resumo["mediana_segundos"] == 45.5


def test_falsos_alarmes_somam_mesmo_de_quem_achou():
    """Quem achou o alvo e apontou outros três trechos não teve sessão limpa.

    Uma tela que faz a pessoa desconfiar de tudo não é uma tela que funciona,
    mesmo quando ela acerta o alvo.
    """
    resumo = apurar([linha(falsos_alarmes="3"), linha("P2", achou="nao", falsos_alarmes="1")])
    assert resumo["falsos_alarmes"] == 4


def test_contagem_por_documento():
    linhas = [
        linha("P1", "documento-01.pdf", "sim"),
        linha("P2", "documento-01.pdf", "nao"),
        linha("P3", "documento-02.pdf", "nao"),
    ]
    por_doc = apurar(linhas)["por_documento"]
    assert por_doc["documento-01.pdf"] == {"tentativas": 2, "achou": 1}
    assert por_doc["documento-02.pdf"] == {"tentativas": 1, "achou": 0}


def test_relatorio_traz_taxa_e_ressalva_de_leitura():
    texto = formatar(apurar([linha(), linha("P2", achou="nao")]))
    assert "1/2" in texto and "50%" in texto
    # A ressalva precisa sobreviver a refatoração: sem ela, taxa baixa seria
    # lida como "o modelo esta errado", que e a conclusao oposta a correta.
    assert "limiar objetivo" in texto.lower()
    assert "interface" in texto.lower()
