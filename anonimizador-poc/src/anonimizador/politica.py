"""Perfil de politica de anonimizacao — o contrato entre decisao e execucao.

Ate aqui a Fase 0 tinha uma politica implicita: `ENTIDADES_REDIGIDAS` decidia
o que era tarjado, no codigo, igual para todo documento. Isso basta para medir
deteccao e nao basta para nada depois disso — a UI precisa oferecer a escolha,
e o copiloto LLM (Fase 3) precisa de algo que ele possa **preencher e propor**
sem tocar no conteudo do documento.

O perfil e esse algo: um dado serializavel que diz, por entidade, qual
operador aplicar. Quem decide (humano na tela, ou LLM propondo para aprovacao)
fica separado de quem executa.

**O que esta implementado hoje:** apenas `TARJA`. Os demais operadores estao
declarados porque o vocabulario precisa existir antes da UI, mas
`validar_perfil` recusa um perfil que os use. Um operador que existe no
vocabulario e nao no executor seria a pior falha possivel neste sistema:
o usuario pediria pseudonimo, o pipeline nao aplicaria nada, e o PDF sairia
com o dado intacto e um relatorio dizendo que foi anonimizado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# --------------------------------------------------------------------------
# Vocabulario de operadores
# --------------------------------------------------------------------------
TARJA = "tarja"                # redacao verdadeira: o texto sai do PDF
PSEUDONIMO = "pseudonimo"      # substitui por token estavel (Fase 2, com cofre)
MASCARA = "mascara"            # substitui por asteriscos preservando formato
MANTER = "manter"              # detecta, reporta, nao altera

OPERADORES = (TARJA, PSEUDONIMO, MASCARA, MANTER)

# Executaveis hoje. `MANTER` entra porque nao-fazer-nada e trivialmente
# implementavel; `PSEUDONIMO` e `MASCARA` exigem reescrever texto no PDF, o
# que nao existe na Fase 0.
OPERADORES_IMPLEMENTADOS = frozenset({TARJA, MANTER})


class PoliticaInvalida(ValueError):
    """Perfil que pede algo que o executor nao sabe fazer."""


@dataclass(frozen=True)
class PerfilPolitica:
    """Politica de anonimizacao de um documento ou lote."""

    nome: str
    descricao: str = ""
    padrao: str = TARJA
    regras: dict[str, str] = field(default_factory=dict)
    threshold: float | None = None

    def operador_de(self, entidade: str) -> str:
        return self.regras.get(entidade, self.padrao)

    def entidades_com(self, operador: str, universo: Iterable[str]) -> list[str]:
        return [e for e in universo if self.operador_de(e) == operador]

    # -- serializacao ------------------------------------------------------
    def to_dict(self) -> dict:
        d = {
            "nome": self.nome,
            "descricao": self.descricao,
            "padrao": self.padrao,
            "regras": dict(self.regras),
        }
        if self.threshold is not None:
            d["threshold"] = self.threshold
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "PerfilPolitica":
        if "nome" not in d:
            raise PoliticaInvalida("perfil sem 'nome'")
        return cls(
            nome=d["nome"],
            descricao=d.get("descricao", ""),
            padrao=d.get("padrao", TARJA),
            regras=dict(d.get("regras", {})),
            threshold=d.get("threshold"),
        )

    @classmethod
    def carregar(cls, caminho: str | Path) -> "PerfilPolitica":
        texto = Path(caminho).read_text(encoding="utf-8")
        return cls.from_dict(json.loads(texto))

    def salvar(self, caminho: str | Path) -> None:
        Path(caminho).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def validar_perfil(perfil: PerfilPolitica, entidades_conhecidas: Iterable[str]) -> None:
    """Recusa o perfil antes de ele tocar em qualquer documento.

    Falhar aqui, alto e cedo, e o ponto: um perfil invalido que passasse
    silenciosamente produziria um PDF com dado intacto e um relatorio
    afirmando que ele foi tratado.
    """
    conhecidas = set(entidades_conhecidas)

    if perfil.padrao not in OPERADORES:
        raise PoliticaInvalida(f"operador padrao desconhecido: {perfil.padrao!r}")

    for entidade, operador in perfil.regras.items():
        if entidade not in conhecidas:
            raise PoliticaInvalida(f"entidade desconhecida no perfil: {entidade!r}")
        if operador not in OPERADORES:
            raise PoliticaInvalida(
                f"operador desconhecido para {entidade}: {operador!r}"
            )

    usados = {perfil.padrao} | set(perfil.regras.values())
    nao_implementados = sorted(usados - OPERADORES_IMPLEMENTADOS)
    if nao_implementados:
        raise PoliticaInvalida(
            "operador declarado mas nao implementado nesta fase: "
            + ", ".join(nao_implementados)
            + ". Implementados: "
            + ", ".join(sorted(OPERADORES_IMPLEMENTADOS))
        )

    if perfil.threshold is not None and not 0.0 <= perfil.threshold <= 1.0:
        raise PoliticaInvalida(f"threshold fora de [0,1]: {perfil.threshold}")


# --------------------------------------------------------------------------
# Perfis de fabrica
# --------------------------------------------------------------------------
# Sao pontos de partida para a tela e para a proposta do copiloto, nao
# recomendacoes juridicas. Quem responde pela escolha e o controlador.
PERFIL_MAXIMA_PROTECAO = PerfilPolitica(
    nome="maxima-protecao",
    descricao=(
        "Tarja tudo que o pipeline sabe identificar. Ponto de partida para "
        "documento que sai da organizacao sem destinatario definido."
    ),
    padrao=TARJA,
    regras={"ORGANIZATION": MANTER, "LOCATION": MANTER, "DATE_TIME": MANTER},
)

PERFIL_PUBLICACAO_OFICIAL = PerfilPolitica(
    nome="publicacao-oficial",
    descricao=(
        "Publicacao em diario oficial: identificadores documentais saem, mas "
        "orgao, data do ato e municipio permanecem legiveis — sem eles o ato "
        "administrativo perde o efeito de publicidade que justifica publica-lo."
    ),
    padrao=TARJA,
    regras={
        "ORGANIZATION": MANTER,
        "LOCATION": MANTER,
        "DATE_TIME": MANTER,
        "ENDERECO": TARJA,
    },
)

PERFIS_DE_FABRICA = {
    p.nome: p for p in (PERFIL_MAXIMA_PROTECAO, PERFIL_PUBLICACAO_OFICIAL)
}
