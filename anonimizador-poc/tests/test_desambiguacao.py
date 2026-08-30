"""Desambiguacao de identificadores que compartilham a mesma forma.

CPF, PIS/PASEP e CNH sao todos 11 digitos, e um mesmo numero pode satisfazer
mais de um checksum. Quando isso acontece, a precedencia estatica escolheria
sempre CPF, ignorando a ancora que o texto oferece de graca. Estes testes
travam o comportamento nas quatro situacoes que importam.

Logica pura: nada aqui carrega Presidio, spaCy ou torch.
"""

from anonimizador.spans import Span, desambiguar_por_ancora, resolver_sobreposicoes

NUM = "22393559907"


def _texto(prefixo: str) -> str:
    return f"{prefixo}{NUM} - categoria B"


def _par(texto: str) -> list[Span]:
    """O mesmo trecho reivindicado por dois reconhecedores."""
    ini = texto.index(NUM)
    fim = ini + len(NUM)
    return [Span(ini, fim, "CPF", 1.0), Span(ini, fim, "CNH", 1.0)]


def test_ancora_decide_contra_a_precedencia():
    texto = _texto("CNH n ")
    vencedores = resolver_sobreposicoes(_par(texto), texto)
    assert [s.entity for s in vencedores] == ["CNH"]


def test_ancora_de_pis_decide_contra_cpf():
    texto = "PIS/PASEP: " + NUM
    ini = texto.index(NUM)
    spans = [Span(ini, ini + len(NUM), "CPF", 1.0), Span(ini, ini + len(NUM), "PIS_PASEP", 1.0)]
    assert [s.entity for s in resolver_sobreposicoes(spans, texto)] == ["PIS_PASEP"]


def test_sem_ancora_mantem_precedencia():
    texto = "Numero de referencia " + NUM
    vencedores = resolver_sobreposicoes(_par(texto), texto)
    assert [s.entity for s in vencedores] == ["CPF"]


def test_ancoras_conflitantes_nao_decidem():
    """Duas ancoras na mesma janela: nao adivinhamos, cai na precedencia.

    Trocar um rotulo errado deterministico por um imprevisivel seria pior:
    o operador de anonimizacao aplicado depende do rotulo.
    """
    texto = "CPF/CNH " + NUM
    vencedores = resolver_sobreposicoes(_par(texto), texto)
    assert [s.entity for s in vencedores] == ["CPF"]


def test_ancora_ignora_acento_e_caixa():
    texto = "HABILITAÇÃO n " + NUM
    vencedores = resolver_sobreposicoes(_par(texto), texto)
    assert [s.entity for s in vencedores] == ["CNH"]


def test_ancora_fora_da_janela_nao_conta():
    """A ancora precisa estar perto. Longe, ela e do campo anterior da ficha."""
    texto = "CNH" + " " * 80 + NUM
    vencedores = resolver_sobreposicoes(_par(texto), texto)
    assert [s.entity for s in vencedores] == ["CPF"]


def test_nao_mexe_em_spans_nao_coincidentes():
    """So agimos no empate exato. Sobreposicao parcial e outro problema."""
    texto = "CNH n " + NUM
    ini = texto.index(NUM)
    spans = [Span(ini, ini + len(NUM), "CNH", 1.0), Span(ini, ini + 5, "CPF", 1.0)]
    assert desambiguar_por_ancora(spans, texto) == spans


def test_sem_texto_comporta_se_como_antes():
    """A assinatura antiga continua valendo, sem desambiguacao."""
    texto = "CNH n " + NUM
    assert [s.entity for s in resolver_sobreposicoes(_par(texto))] == ["CPF"]
