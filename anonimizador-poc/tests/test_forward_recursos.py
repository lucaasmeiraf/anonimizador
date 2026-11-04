"""O encaminhador precisa degradar, não cair.

Achado em 2026-11-03, ao avaliar a exposição pública: `forward.py` abria
**três threads por conexão** (uma que atende, duas que bombeiam), sem teto e
sem nenhum timeout de socket. Em `127.0.0.1` isso nunca importou — só o dono
da máquina conecta. Publicada a porta, bastava abrir conexões TCP ociosas,
**sem falar HTTP e sem credencial nenhuma**, para esgotar threads e o serviço
parar de responder.

O que estes testes exigem é o comportamento sob pressão, não a ausência do
problema: conexão calada é descartada, conexão além do teto é recusada na
hora, e conexão legítima atravessa. O limite desta correção está dito no
cabeçalho de `forward.py` e em `DEFEITOS.md` — defesa de perímetro de verdade
mora no proxy reverso da frente, não aqui.
"""

from __future__ import annotations

import socket
import threading

import pytest

from anonimizador.web import forward


@pytest.fixture
def eco():
    """Servidor de destino que devolve o que recebe, numa porta efêmera."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(64)
    porta = srv.getsockname()[1]
    parar = threading.Event()

    def laco():
        while not parar.is_set():
            try:
                cli, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=_devolver, args=(cli,), daemon=True).start()

    def _devolver(cli):
        try:
            while True:
                d = cli.recv(4096)
                if not d:
                    break
                cli.sendall(d)
        except OSError:
            pass
        finally:
            cli.close()

    threading.Thread(target=laco, daemon=True).start()
    yield porta
    parar.set()
    srv.close()


@pytest.fixture
def proxy(eco, monkeypatch):
    """Sobe o encaminhador com teto e espera pequenos, em porta efêmera."""
    monkeypatch.setattr(forward, "ESPERA_PRIMEIRO_BYTE", 0.4)

    tomada = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tomada.bind(("127.0.0.1", 0))
    porta = tomada.getsockname()[1]
    tomada.close()

    pronto = threading.Event()
    threading.Thread(
        target=forward.servir,
        args=("127.0.0.1", porta, f"127.0.0.1:{eco}"),
        kwargs={"max_conexoes": 2, "pronto": pronto},
        daemon=True,
    ).start()
    assert pronto.wait(5), "o encaminhador não subiu"
    return porta


def _conectar(porta, timeout=5.0):
    s = socket.create_connection(("127.0.0.1", porta), timeout=timeout)
    return s


def test_conexao_legitima_atravessa(proxy):
    """A correção não pode custar a função: bytes vão e voltam."""
    with _conectar(proxy) as s:
        s.sendall(b"GET / HTTP/1.0\r\n\r\n")
        assert s.recv(64) == b"GET / HTTP/1.0\r\n\r\n"


def test_conexao_calada_e_descartada(proxy):
    """Conectar e não falar é o ataque mais barato que existe aqui.

    Sem a espera pelo primeiro byte, esta conexão ficaria de pé para sempre
    segurando três threads. Com ela, o encaminhador fecha e o `recv` do
    cliente volta vazio.
    """
    with _conectar(proxy) as s:
        s.settimeout(3.0)
        assert s.recv(16) == b"", "a conexão calada deveria ter sido fechada"


def test_acima_do_teto_recusa_na_hora(proxy):
    """Teto de 2: a terceira conexão é fechada, não enfileirada.

    Enfileirar é o que transforma pico em queda — a fila cresce sem limite e o
    cliente já desistiu quando chega a vez dele.
    """
    abertas = []
    try:
        for _ in range(2):
            s = _conectar(proxy)
            s.sendall(b"x")          # ocupa a vaga de verdade
            assert s.recv(8) == b"x"
            abertas.append(s)

        terceira = _conectar(proxy)
        abertas.append(terceira)
        terceira.settimeout(3.0)
        assert terceira.recv(16) == b"", "a terceira deveria ter sido recusada"
    finally:
        for s in abertas:
            s.close()


def test_vaga_e_devolvida_quando_a_conexao_fecha(proxy):
    """Teto não pode virar vazamento: quem sai libera a vaga.

    Sem o `release` no `finally`, o serviço sobreviveria ao ataque e morreria
    sozinho depois de 2 conexões — trocando um defeito por outro pior, porque
    este não precisaria de atacante.
    """
    for _ in range(4):  # o dobro do teto, em série
        with _conectar(proxy) as s:
            s.sendall(b"ping")
            assert s.recv(8) == b"ping"
