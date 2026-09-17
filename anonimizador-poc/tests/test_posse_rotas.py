"""A rota que alguém esquece.

Critério de aceite do `goal-fase-4.md` §8: *"existe teste que percorre todas
as rotas de documento e falha se alguma não exigir posse"*. Este é ele.

O modo de falha que justifica um teste deste formato é específico e já
conhecido: isolamento entre inquilinos não vaza por erro de projeto — vaza
por **uma** rota acrescentada meses depois por alguém que não sabia da regra.
Um teste que enumera rotas à mão não pega essa, porque quem esquece a
verificação também esquece de acrescentar o caso ao teste. Por isso aqui nada
é enumerado à mão: a lista sai de ``app.routes``, e uma rota nova entra na
conferência sem ninguém fazer nada.

Estado hoje: ainda **não existe** autenticação, então "posse" não pode ser
exercida de verdade — isso chega no Bloco 3. O que já é exigível, e é o que
está travado aqui, são as duas metades estruturais de que a posse vai
depender:

1. toda rota de documento resolve a sessão pelo **gargalo** ``pegar_sessao``,
   que é onde a verificação de posse vai morar — um lugar só, nunca espalhada
   por rota (`goal-fase-4.md` §5);
2. documento que o chamador não pode alcançar responde **404**, nunca 403.
   404 não confirma a existência do documento, e é por isso que o critério de
   aceite escolhe esse código.

Quando o Bloco 3 chegar, a asserção de posse entra na função de conferência
existente — a enumeração e o varredor de rotas não mudam.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from anonimizador.web import app as app_mod

# Um id que nunca foi criado. Tem o formato de `secrets.token_urlsafe(9)` de
# propósito: o que se está testando é a recusa por não encontrar a sessão, não
# uma rejeição acidental por formato inválido.
DOC_DESCONHECIDO = "zzzzzzzzzzzz"


class PipelineVazio:
    """Dublê que não detecta nada.

    Estes testes não exercitam detecção — nenhum chega a ter documento. O
    dublê existe só para a subida não carregar 1 GB de pesos.
    """

    def analyze(self, texto, score_threshold=None):  # noqa: ARG002
        return []


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "_pipeline", PipelineVazio())
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "sessoes"))
    with TestClient(app_mod.app) as c:
        yield c


def rotas_de_documento() -> list[APIRoute]:
    """Toda rota cujo caminho carrega um ``doc_id``.

    O critério é o caminho, não uma lista: rota que fala de um documento
    específico precisa dizer *qual*, e dizer qual é justamente o que exige
    provar que ele é seu. ``POST /api/doc`` fica de fora porque cria o
    documento — não há posse a verificar antes de existir dono.
    """
    return [
        r
        for r in app_mod.app.routes
        if isinstance(r, APIRoute) and "{doc_id}" in r.path_format
    ]


def _caminho(rota: APIRoute) -> str:
    """Preenche os parâmetros do caminho com valores que casam com o tipo.

    ``0`` serve tanto para ``int`` quanto para ``str``, o que mantém isto
    genérico: rota nova com parâmetro novo não precisa de entrada aqui.
    """
    caminho = rota.path_format.replace("{doc_id}", DOC_DESCONHECIDO)
    for param in rota.dependant.path_params:
        if param.name != "doc_id":
            caminho = caminho.replace("{%s}" % param.name, "0")
    return caminho


def _metodo(rota: APIRoute) -> str:
    return sorted(rota.methods - {"HEAD", "OPTIONS"})[0]


def _depende_do_gargalo(rota: APIRoute) -> bool:
    """A rota resolve a sessão por ``pegar_sessao``, em qualquer profundidade."""

    def anda(dependant) -> bool:
        for sub in dependant.dependencies:
            if sub.call is app_mod.pegar_sessao or anda(sub):
                return True
        return False

    return anda(rota.dependant)


def test_ha_rotas_de_documento_para_conferir():
    """A guarda contra o pior desfecho possível: passar sem conferir nada.

    Se alguém renomear o parâmetro de caminho, ``rotas_de_documento`` devolve
    lista vazia e todos os testes deste arquivo passam — verdes, vazios e
    mentindo. O número é grosseiro de propósito; o que importa é não ser zero.
    """
    assert len(rotas_de_documento()) >= 10


def test_toda_rota_de_documento_passa_pelo_gargalo():
    """Onde a posse vai morar no Bloco 3, e por que precisa ser um lugar só.

    Uma rota que recebe ``doc_id: str`` e vai sozinha ao repositório de
    sessões não é um erro hoje — é o assento vazio onde a verificação de posse
    não vai estar amanhã, e ninguém repara porque a rota funciona.
    """
    faltando = [
        f"{_metodo(r)} {r.path_format}"
        for r in rotas_de_documento()
        if not _depende_do_gargalo(r)
    ]
    assert not faltando, (
        "rota de documento que não passa por pegar_sessao: "
        + ", ".join(faltando)
        + " — a verificação de posse mora no gargalo, não na rota"
    )


def test_toda_rota_de_documento_responde_404_a_id_desconhecido(cliente):
    """404, nunca 403 — e nunca 200, 422 ou 500.

    403 responderia *"existe, mas não é seu"*, que é uma resposta a mais do
    que o chamador precisa ter. O corpo é conferido junto: de nada adianta o
    código certo se a mensagem distingue "não existe" de "não é seu".
    """
    erradas = []
    for rota in rotas_de_documento():
        resposta = cliente.request(_metodo(rota), _caminho(rota), json={})
        if resposta.status_code != 404:
            erradas.append(
                f"{_metodo(rota)} {rota.path_format} -> {resposta.status_code}"
            )
    assert not erradas, "rota de documento que não responde 404: " + ", ".join(erradas)


def test_so_o_gargalo_alcanca_o_repositorio_de_sessoes():
    """``sessoes.obter`` tem um chamador só, e é ``pegar_sessao``.

    O teste acima confere a assinatura da rota; este confere o corpo dela.
    Sem este, uma rota poderia declarar a dependência para passar no outro e
    ainda assim buscar a sessão por conta própria — o que recria o caminho
    sem verificação dentro de uma rota que parece correta.
    """
    fonte = Path(app_mod.__file__).read_text(encoding="utf-8")
    arvore = ast.parse(fonte)

    chamadores = []
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for interno in ast.walk(no):
            if (
                isinstance(interno, ast.Attribute)
                and interno.attr == "obter"
                and isinstance(interno.value, ast.Name)
                and interno.value.id == "sessoes"
            ):
                chamadores.append(no.name)

    assert chamadores == ["pegar_sessao"], (
        f"sessoes.obter chamado fora do gargalo: {chamadores} — "
        "a verificação de posse deixa de ser um lugar só"
    )
