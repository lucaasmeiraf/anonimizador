"""O caso da Chave PIX: identificador sem pontuação, longe da própria âncora.

Reproduz um defeito real, encontrado em 2026-09-05 ao rodar um documento pelo
fluxo completo da interface. O documento trazia o mesmo CNPJ duas vezes:

    CNPJ fictício: 61.904.327/0001-18     <- detectado
    Chave PIX: 61904327000118             <- NÃO detectado

A primeira ocorrência foi tarjada; a segunda sobreviveu. O `verify` a encontrou
pela variante numérica e reprovou o documento — que é o comportamento certo,
mas deixava o usuário sem entregável e, por causa do segundo defeito abaixo,
sem saber o que consertar.

**Por que a segunda escapava.** O CNPJ era fictício, com dígito verificador
inválido — o documento dizia isso em texto. Por `base.py`, forma crua sem
checksum válido só sobrevive com âncora explícita na janela anterior, e
"Chave PIX" não estava na lista de âncoras do CNPJ. Sem âncora, `base.py`
descarta como ruído numérico, que é o que preserva a precisão do reconhecedor.

Uma chave PIX de pessoa jurídica **é** um CNPJ, e de pessoa física é quase
sempre o CPF — e nesse campo eles aparecem sem pontuação, justamente a forma
descartada. A âncora faltava.
"""

from __future__ import annotations

import pytest

from anonimizador.recognizers import cnpj, cpf
from anonimizador.validators import validate_cnpj, validate_cpf

# Fictícios e com DV inválido de propósito: é a combinação que produziu o
# defeito. Um identificador com DV válido nunca dependeu da âncora — o
# checksum já o levaria a score 1.0.
CNPJ_DV_INVALIDO = "61904327000118"
CPF_DV_INVALIDO = "12345678900"


def test_os_identificadores_do_caso_tem_dv_invalido():
    """Fixa a premissa. Se um DV virar válido, o teste abaixo perde o sentido."""
    assert validate_cnpj(CNPJ_DV_INVALIDO) is False
    assert validate_cpf(CPF_DV_INVALIDO) is False


@pytest.mark.parametrize("modulo", [cnpj, cpf])
def test_chave_pix_e_ancora(modulo):
    assert "chave pix" in modulo.CONTEXT


@pytest.mark.parametrize(
    "modulo,valor",
    [(cnpj, CNPJ_DV_INVALIDO), (cpf, CPF_DV_INVALIDO)],
)
def test_forma_crua_ancorada_em_chave_pix_e_detectada(modulo, valor):
    """O conserto, exercitado no reconhecedor isolado — sem carregar NER."""
    rec = modulo.build()
    texto = f"Conta corrente: 123456-7\nChave PIX: {valor}\nAnexo I"
    achados = rec.analyze(texto, [rec.supported_entities[0]])

    assert achados, "identificador ancorado em 'Chave PIX' passou despercebido"
    achado = achados[0]
    assert texto[achado.start:achado.end] == valor
    # Marcado como palpite, não como certeza: o DV não confere, e a interface
    # precisa poder dizer ao revisor por que o trecho foi apontado.
    assert (achado.recognition_metadata or {}).get("checksum") == "invalido"


@pytest.mark.parametrize(
    "modulo,valor",
    [(cnpj, CNPJ_DV_INVALIDO), (cpf, CPF_DV_INVALIDO)],
)
def test_forma_crua_sem_ancora_continua_descartada(modulo, valor):
    """A trava que a âncora não pode afrouxar.

    Número solto com DV inválido continua sendo ruído — nota fiscal, matrícula,
    protocolo. Se este teste falhar junto com o de cima, o conserto virou um
    afrouxamento geral do reconhecedor, que é outra coisa.
    """
    rec = modulo.build()
    texto = f"Protocolo interno numero {valor} registrado no setor."
    achados = rec.analyze(texto, [rec.supported_entities[0]])
    assert not achados


@pytest.mark.parametrize("modulo", [cnpj, cpf])
def test_pixel_nao_e_ancora(modulo):
    """A âncora é "chave pix", não "pix".

    A janela de âncora casa por substring, então "pix" sozinho casaria dentro
    de "pixel" — e um documento técnico com dimensões de imagem perto de um
    número comprido viraria falso positivo.
    """
    assert "pix" not in modulo.CONTEXT
    rec = modulo.build()
    valor = CNPJ_DV_INVALIDO if modulo is cnpj else CPF_DV_INVALIDO
    texto = f"Resolucao da imagem: 1920 pixels. Codigo {valor} do lote."
    assert not rec.analyze(texto, [rec.supported_entities[0]])
