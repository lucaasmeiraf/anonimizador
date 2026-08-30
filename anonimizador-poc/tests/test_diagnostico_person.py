"""Classificação de vazamento de PERSON: não detectado vs. rótulo errado.

Esta lógica não altera nenhum documento — ela decide a **escolha de modelo**
da Fase 1 (D1 em `goal-fase-1.md`). Um erro aqui não vaza dado, mas manda a
equipe consertar o problema errado: trocar de checkpoint quando bastava um
reconhecedor de contexto, ou o inverso.

O caso que exige mais cuidado é a fronteira entre `PARCIAL` e
`ROTULO_ERRADO`. Só cobertura **zero** faz a string contígua sobreviver no PDF
e ser achada pelo `verifier`; um único caractere tarjado no meio já quebra o
valor. Classificar cobertura parcial como vazamento inflaria a contagem e
apontaria para a decisão errada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from align import GoldSpan  # noqa: E402
from diagnostico_person import (  # noqa: E402
    COBERTO,
    NAO_DETECTADO,
    PARCIAL,
    ROTULO_ERRADO,
    classificar,
)

from anonimizador.spans import Span  # noqa: E402

# "Lunna Casa Grande" ocupando os offsets 10..27.
GOLD = GoldSpan(label="PERSON", value="Lunna Casa Grande", start=10, end=27)


def _span(start, end, entity, score=0.9):
    return Span(start=start, end=end, entity=entity, score=score)


def test_coberto_por_span_redigido():
    spans = [_span(10, 27, "PERSON")]
    assert classificar(GOLD, spans, spans) == (COBERTO, ["PERSON"])


def test_coberto_por_span_maior_que_o_gabarito():
    # Fronteira deslocada para a esquerda ("Sr. Lunna Casa Grande") continua
    # cobrindo o gabarito inteiro. É acerto, não defeito.
    spans = [_span(6, 30, "PERSON")]
    classe, _ = classificar(GOLD, spans, spans)
    assert classe == COBERTO


def test_coberto_por_dois_spans_adjacentes():
    # A cobertura é medida em caracteres, não em spans: nome partido em dois
    # spans contíguos está inteiramente tarjado.
    spans = [_span(10, 15, "PERSON"), _span(15, 27, "PERSON")]
    classe, _ = classificar(GOLD, spans, spans)
    assert classe == COBERTO


def test_parcial_nao_conta_como_vazamento():
    # Só "Lunna" tarjado. "Casa Grande" sobra, mas a string do gabarito
    # inteira não sobrevive contígua — não é o que o verifier acha.
    spans = [_span(10, 15, "PERSON")]
    classe, _ = classificar(GOLD, spans, spans)
    assert classe == PARCIAL


def test_rotulo_errado_quando_a_politica_preserva():
    # O detector viu o trecho e chamou de LOCATION. LOCATION não está em
    # ENTIDADES_REDIGIDAS, então nada foi tarjado — este é o caso "Casa Grande".
    todos = [_span(10, 27, "LOCATION")]
    assert classificar(GOLD, todos, []) == (ROTULO_ERRADO, ["LOCATION"])


def test_rotulo_errado_com_sobreposicao_parcial():
    # Detectou só parte do nome, e com o rótulo errado. Continua sendo
    # "foi visto, a política preservou" — não é limite de detecção.
    todos = [_span(16, 27, "LOCATION")]
    classe, rotulos = classificar(GOLD, todos, [])
    assert classe == ROTULO_ERRADO
    assert rotulos == ["LOCATION"]


def test_rotulo_errado_agrega_todos_os_rotulos_sobrepostos():
    todos = [_span(10, 15, "ORGANIZATION"), _span(16, 27, "LOCATION")]
    classe, rotulos = classificar(GOLD, todos, [])
    assert classe == ROTULO_ERRADO
    assert rotulos == ["LOCATION", "ORGANIZATION"]  # ordenado


def test_nao_detectado_quando_nao_ha_span_algum():
    assert classificar(GOLD, [], []) == (NAO_DETECTADO, [])


def test_span_vizinho_que_nao_toca_nao_conta():
    # Um CPF logo depois do nome não é evidência de que o nome foi visto.
    todos = [_span(28, 40, "CPF")]
    assert classificar(GOLD, todos, []) == (NAO_DETECTADO, [])


def test_span_colado_na_fronteira_nao_toca():
    # end exclusivo: um span que termina exatamente onde o gabarito começa
    # não sobrepõe. Errar isso classificaria vizinhança como detecção.
    todos = [_span(0, 10, "PERSON")]
    assert classificar(GOLD, todos, []) == (NAO_DETECTADO, [])
