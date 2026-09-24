"""O envio de um documento não pode parar o servidor para os outros.

Medido em 2026-09-24 com um PDF sintético de 102 páginas: a detecção levou
69 s e, durante todo esse tempo, `/api/saude` ficou sem resposta. A causa era
`criar_doc` declarada `async def` — a detecção, que é CPU pura, rodava dentro
do laço de eventos e bloqueava toda requisição de qualquer outra pessoa.

O teste reproduz o formato do defeito sem carregar modelo: um duble de
detecção que fica parado até ser liberado. Com a rota bloqueando o laço, a
consulta de saúde só volta quando o duble desiste (5 s); com a rota no pool
de threads, ela volta na hora.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from anonimizador.web import app as app_mod


class DeteccaoLenta:
    def __init__(self):
        self.entrou = threading.Event()
        self.liberar = threading.Event()

    def analyze(self, texto, score_threshold=None):
        self.entrou.set()
        self.liberar.wait(5)
        return []


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    duble = DeteccaoLenta()
    monkeypatch.setattr(app_mod, "_pipeline", duble)
    monkeypatch.setattr(app_mod, "sessoes", app_mod.Sessoes(tmp_path / "sessoes"))
    # O aquecimento da subida também passa pelo duble: ele sobe liberado, e
    # só depois é armado, para que `entrou` passe a significar "o upload
    # chegou à detecção".
    duble.liberar.set()
    with TestClient(app_mod.app) as c:
        duble.entrou.clear()
        duble.liberar.clear()
        yield c, duble
    duble.liberar.set()


def test_saude_responde_enquanto_um_documento_e_detectado(cenario, tmp_pdf):
    cliente, duble = cenario
    caminho = tmp_pdf(["Contratante: Mariana Aparecida Souza."], nome="a.pdf")
    resultado = {}

    def enviar():
        with open(caminho, "rb") as fh:
            resultado["r"] = cliente.post(
                "/api/doc", files={"arquivo": ("a.pdf", fh, "application/pdf")}
            )

    t = threading.Thread(target=enviar)
    t.start()
    try:
        assert duble.entrou.wait(5), "o upload não chegou à detecção"
        inicio = time.perf_counter()
        r = cliente.get("/api/saude")
        demora = time.perf_counter() - inicio
        assert r.status_code == 200
        assert demora < 2, (
            f"/api/saude levou {demora:.1f}s com uma detecção em curso — "
            "a rota de upload voltou a bloquear o laço de eventos"
        )
    finally:
        duble.liberar.set()
        t.join(10)
    assert resultado["r"].status_code == 200, resultado["r"].text


def test_deteccoes_simultaneas_sao_serializadas(monkeypatch):
    """Duas detecções nunca entram no pipeline ao mesmo tempo.

    Nem o `AnalyzerEngine` do Presidio nem o pipeline do transformers se
    declaram seguros para chamada concorrente; a trava de `app.detectar`
    garante que a pergunta nem se coloque.
    """
    dentro = 0
    maximo = 0
    contador = threading.Lock()

    class Contador:
        def analyze(self, texto, score_threshold=None):
            nonlocal dentro, maximo
            with contador:
                dentro += 1
                maximo = max(maximo, dentro)
            time.sleep(0.05)
            with contador:
                dentro -= 1
            return []

    monkeypatch.setattr(app_mod, "_pipeline", Contador())
    threads = [
        threading.Thread(target=app_mod.detectar, args=("texto",)) for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert maximo == 1
