"""Token intradocumento e saída de texto pseudonimizado — lógica pura.

Plano em `goal-fase-2a.md`. Sem PyMuPDF, sem Presidio, sem disco: dado um
texto e uma lista de spans, devolve o mesmo texto com cada valor trocado por
um token estável **dentro daquele documento**.

Por que isto existe, se `tarja` já protege
------------------------------------------
A tarja não apaga só o nome: apaga o *ator*. O texto extraído de um PDF
tarjado diz ``O servidor  compareceu`` — quem lê não sabe que havia alguém
ali, nem se é a mesma pessoa do parágrafo seguinte. Para publicar no Diário
Oficial isso é aceitável; para submeter o documento a análise, é convite a
alucinação exatamente onde a análise precisa ser confiável.

Com token, ``O servidor [P-7F3A] compareceu`` preserva três coisas que a
tarja destrói: que existe um ator, de que tipo ele é, e que é o mesmo ator da
outra passagem. Esse é o ganho de legibilidade que a LAI cobra em documento
público, e ele não custa nada em LGPD **enquanto não houver cofre** — ver a
seção 0 do `goal-fase-2.md`.

As duas armadilhas que este módulo existe para evitar
-----------------------------------------------------
**1. O token não pode ser derivado do valor.** ``sha256(valor)[:4]`` é a
implementação intuitiva e é reversível por força bruta: o espaço de nomes
brasileiros plausíveis é enumerável, e quem tiver o texto pseudonimizado mais
uma lista de candidatos confirma cada um por tentativa — sem chave, sem
cofre, sem nada que possamos controlar. Um CPF é pior ainda: 11 dígitos com
dígito verificador dão um espaço percorrível.

Isso transformaria uma saída que deveria estar fora do alcance da LGPD numa
saída reidentificável, que é precisamente a distinção que a Fase 2 existe
para preservar. Por isso o token é **sorteado**, não derivado: não há relação
matemática com o original, e a saída é irreversível inclusive para nós.

**2. Colisão precisa ser impedida, não ser improvável.** Com 4 dígitos
hexadecimais são 65.536 tokens. Num documento com 50 entidades distintas a
probabilidade de duas receberem o mesmo token é ``1 - exp(-50²/(2*65536))``,
cerca de **1,9%** — mais ou menos 1 documento em 50, a mesma ordem de
grandeza do vazamento de PERSON já conhecido, e igualmente inaceitável em
silêncio. Duas pessoas com o mesmo token fazem quem lê fundir dois atores num
só, que é um erro de interpretação pior do que a ausência do nome. Sortear
rejeitando repetido leva a probabilidade a **zero**, e custa um `set`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from . import config
from .spans import Span

# Dígitos hexadecimais do sufixo. Quatro é o equilíbrio medido: curto o
# bastante para caber onde o valor cabia (a aresta de largura do A4, quando a
# escrita no PDF existir) e largo o bastante para que a rejeição de colisão
# quase nunca precise de um segundo sorteio.
LARGURA_SUFIXO = 4

# Tentativas antes de desistir. Só é alcançado se o espaço de tokens estiver
# praticamente esgotado, e nesse caso falhar alto é a única saída honesta:
# devolver token repetido funde dois atores em silêncio.
MAX_TENTATIVAS = 10_000


class PseudonimoImpossivel(RuntimeError):
    """Não foi possível emitir um token distinto, ou o tipo é desconhecido."""


@dataclass(frozen=True)
class Substituicao:
    """Um trecho que foi trocado, e por quê. Sem o valor original."""

    entity: str
    start: int
    end: int
    token: str


@dataclass
class TextoPseudonimizado:
    """Resultado da substituição.

    ``valores`` carrega os originais porque é o que alimenta a verificação —
    mesmo papel de ``RedactionResult.valores``. Ele **nunca** vai para log,
    para mensagem de erro nem para resposta de API.
    """

    texto: str
    substituicoes: list[Substituicao] = field(default_factory=list)
    valores: list[str] = field(default_factory=list)

    @property
    def tokens(self) -> list[str]:
        return [s.token for s in self.substituicoes]


class AlocadorDeToken:
    """Emite o token de cada valor, e garante o determinismo intradocumento.

    Um alocador **por documento**. Reaproveitá-lo entre documentos faria o
    mesmo nome virar o mesmo token em arquivos diferentes, e isso é
    exatamente o que a seção 0 do `goal-fase-2.md` proíbe: quem tiver dois
    documentos saberia que a mesma pessoa aparece nos dois, sem ter chave
    nenhuma. Dependendo do contexto isso já é reidentificação por meios
    razoáveis.
    """

    def __init__(self, rng: random.Random | None = None, largura: int = LARGURA_SUFIXO):
        # `SystemRandom` por padrão: o token não deve ser previsível a partir
        # de semente. Os testes injetam um `Random` semeado para exercitar o
        # caminho de colisão de forma determinística.
        self._rng = rng or random.SystemRandom()
        self._largura = largura
        self._por_valor: dict[tuple[str, str], str] = {}
        self._emitidos: set[str] = set()

    @property
    def emitidos(self) -> int:
        return len(self._emitidos)

    def token_de(self, entity: str, valor: str) -> str:
        """Token deste valor neste documento. Estável entre chamadas."""
        chave = (entity, _chave_de(valor))
        existente = self._por_valor.get(chave)
        if existente is not None:
            return existente

        sigla = config.SIGLAS_TOKEN.get(entity)
        if sigla is None:
            # Cair num prefixo genérico é como uma entidade nova entra no
            # sistema sem ninguém decidir seu tratamento. O CLAUDE.md exige
            # que adicionar entidade toque todos os pontos de uma vez; este
            # erro é o que torna a exigência verificável.
            raise PseudonimoImpossivel(
                f"entidade sem sigla declarada em config.SIGLAS_TOKEN: {entity!r}"
            )

        token = self._sortear(sigla)
        self._por_valor[chave] = token
        self._emitidos.add(token)
        return token

    def _sortear(self, sigla: str) -> str:
        teto = 16 ** self._largura
        for _ in range(MAX_TENTATIVAS):
            sufixo = format(self._rng.randrange(teto), f"0{self._largura}X")
            token = f"[{sigla}-{sufixo}]"
            if token not in self._emitidos:
                return token
        raise PseudonimoImpossivel(
            f"espaco de tokens esgotado para {sigla!r} apos "
            f"{MAX_TENTATIVAS} tentativas ({self.emitidos} emitidos)"
        )


def _chave_de(valor: str) -> str:
    """Forma sob a qual dois trechos contam como o mesmo valor.

    Colapsa apenas espaço em branco — a mesma pessoa costuma reaparecer com
    quebra de linha no meio do nome, e sem isto ela receberia dois tokens.

    **Não** normaliza caixa nem acento de propósito. Seria melhor para a
    narrativa (``MARIANA SOUZA`` e ``Mariana Souza`` viram tokens distintos
    hoje), mas alargar a chave é alargar heurística, e o CLAUDE.md exige
    medição nas duas direções antes disso: uma chave frouxa demais funde duas
    pessoas de nome parecido, que é o mesmo dano da colisão. Fica registrado
    como limitação conhecida, não como descuido.
    """
    return " ".join(valor.split())


def pseudonimizar_texto(
    texto: str,
    spans: Sequence[Span],
    alocador: AlocadorDeToken | None = None,
) -> TextoPseudonimizado:
    """Devolve o texto com cada span trocado pelo seu token.

    A ordem de leitura sai correta **por construção**: a substituição acontece
    sobre a string original, nas posições originais, sem passar pelo content
    stream do PDF. É a diferença medida no A1 — no PDF os tokens são anexados
    ao fim do fluxo da página e metade dos extratores lê fora de ordem; aqui
    não existe fluxo, existe offset.
    """
    alocador = alocador or AlocadorDeToken()
    ordenados = sorted(spans, key=lambda s: (s.start, s.end))
    _recusar_sobreposicao(ordenados)

    substituicoes: list[Substituicao] = []
    valores: list[str] = []
    for span in ordenados:
        valor = texto[span.start:span.end]
        token = alocador.token_de(span.entity, valor)
        substituicoes.append(
            Substituicao(entity=span.entity, start=span.start, end=span.end, token=token)
        )
        valores.append(valor)

    # De trás para frente: substituir do início moveria os offsets seguintes.
    partes = list(texto)
    for sub in reversed(substituicoes):
        partes[sub.start:sub.end] = sub.token

    return TextoPseudonimizado(
        texto="".join(partes),
        substituicoes=substituicoes,
        valores=valores,
    )


def _recusar_sobreposicao(ordenados: Sequence[Span]) -> None:
    """Span sobreposto é bug de montagem, e aqui ele é fatal.

    ``resolver_sobreposicoes`` já entrega lista disjunta; se algo sobreposto
    chega aqui, a substituição produziria texto corrompido — um token no meio
    de outro — e o resultado *pareceria* pronto. Falhar alto é a regra do
    CLAUDE.md para exatamente este caso.
    """
    for anterior, atual in zip(ordenados, ordenados[1:]):
        if atual.start < anterior.end:
            raise PseudonimoImpossivel(
                "spans sobrepostos na pseudonimizacao: "
                f"{anterior.entity}@{anterior.start}-{anterior.end} e "
                f"{atual.entity}@{atual.start}-{atual.end}"
            )


def tokens_de(subs: Iterable[Substituicao]) -> list[str]:
    """Tokens distintos, para a verificação de presença."""
    return sorted({s.token for s in subs})
