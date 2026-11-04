"""Encaminhador TCP mínimo — a única peça do sistema com acesso à rede.

## Por que ele existe

A Fase 0 roda tudo com ``network_mode: none``, que é a *prova executável* da
restrição de soberania: não é promessa de configuração, é ausência de
interface de rede. Uma interface web precisa de porta publicada, e
``network_mode: none`` não publica porta. O conflito é real.

Quatro configurações foram testadas neste ambiente (Docker Desktop / WSL2),
e o resultado está registrado em ``goal-fase-1.md``:

===========================================  =============  =================
configuração                                 porta no host  egress bloqueado
===========================================  =============  =================
``network_mode: none``                       impossível     sim
rede ``internal: true``                      inalcançável   sim
bridge com ``enable_ip_masquerade=false``    **funciona**   **não** (1)
sabotagem in-process do ``socket``           **funciona**   **não** (2)
app em rede interna + este encaminhador      **funciona**   **sim**
===========================================  =============  =================

(1) O Docker Desktop faz NAT na própria VM WSL2; a opção de bridge do Docker
    não tem efeito sobre isso. Medido, não deduzido.
(2) Bloqueia o processo, mas ``subprocess`` escapa — herda o socket do kernel,
    não o módulo sabotado do Python. Também medido.

## O desenho

O serviço ``ui`` fica numa rede ``internal: true``: sem egress, garantido pelo
kernel, subprocesso incluído. Ele é inalcançável do host, então este processo
— sozinho numa rede com saída — encaminha bytes entre a porta publicada e o
``ui``.

O que isso compra: **todo o pipeline de detecção fica sem rede.** torch,
transformers, presidio, huggingface, PyMuPDF — a superfície de dependência
inteira, que é onde o risco de telefonar para casa de fato mora — roda sob a
garantia forte. O único processo com saída é este arquivo.

## O que ele deliberadamente não faz

Não interpreta HTTP, não faz parsing de PDF, não importa dependência alguma
além da biblioteca padrão, não escreve em disco e não registra conteúdo. Ele
copia bytes entre dois sockets. Essa pobreza é a característica de segurança:
o componente com egress é pequeno o bastante para ser lido inteiro numa
sentada.

**Limite honesto:** os bytes do documento passam por aqui, e este processo tem
saída de rede. A garantia não é "o documento nunca toca um processo com rede";
é "o único processo com rede é auditável em cinco minutos e não tem árvore de
dependências". Um atacante com execução de código aqui exfiltra. O que o
desenho elimina é o vetor realista — uma dependência da pilha de ML fazendo
telemetria — não um adversário com RCE.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import threading

logging.basicConfig(level=logging.INFO, format="%(asctime)s forward: %(message)s")
log = logging.getLogger("forward")

BUFFER = 64 * 1024

# Teto de conexões simultâneas. Cada conexão custa TRÊS threads (uma que
# atende e duas que bombeiam), então sem teto o processo morre por exaustão —
# e para derrubá-lo bastam conexões TCP ociosas, sem falar HTTP e sem
# credencial nenhuma.
#
# Em `127.0.0.1` isso nunca importou: só o dono da máquina conecta. O teto
# existe para o dia em que a porta estiver publicada, e o que ele compra é
# **degradar previsivelmente** em vez de parar de responder.
MAX_CONEXOES = int(os.getenv("ANON_PROXY_MAX_CONEXOES", "64"))

# Tempo que uma conexão tem para dizer a primeira palavra.
#
# Só o PRIMEIRO byte é cronometrado, e isso é deliberado: um cliente HTTP
# real manda a requisição assim que conecta, enquanto uma requisição legítima
# pode ficar MINUTOS sem tráfego depois disso — a detecção de um documento de
# 102 páginas levou 74 s, e durante esse tempo o lado do cliente está calado,
# esperando a resposta. Cronometrar o fluxo todo mataria justamente o caso
# pesado que o produto precisa atender.
ESPERA_PRIMEIRO_BYTE = float(os.getenv("ANON_PROXY_ESPERA_INICIAL", "15"))


def _bombear(origem: socket.socket, destino: socket.socket) -> None:
    """Copia bytes numa direção até a origem fechar."""
    try:
        while True:
            dados = origem.recv(BUFFER)
            if not dados:
                break
            destino.sendall(dados)
    except OSError:
        pass
    finally:
        # Meio-fechamento: sinaliza fim de fluxo sem derrubar a outra direção,
        # que ainda pode estar entregando a resposta.
        try:
            destino.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _esperar_primeira_palavra(cliente: socket.socket) -> bytes | None:
    """Lê o primeiro trecho do cliente, ou devolve ``None`` se ele ficar calado.

    É o que separa um navegador de uma conexão aberta só para ocupar recurso.
    Devolve os bytes lidos para que sejam repassados adiante — sem isso, a
    conferência comeria o início da requisição.
    """
    try:
        cliente.settimeout(ESPERA_PRIMEIRO_BYTE)
        dados = cliente.recv(BUFFER)
    except OSError:
        return None
    finally:
        # Volta ao modo bloqueante: daqui em diante o silêncio é legítimo.
        try:
            cliente.settimeout(None)
        except OSError:
            pass
    return dados or None


def _atender(cliente: socket.socket, destino_host: str, destino_porta: int) -> None:
    primeiro = _esperar_primeira_palavra(cliente)
    if primeiro is None:
        # Conectou e não falou. Sem conteúdo nenhum para registrar — nem
        # haveria: este processo não loga conteúdo (ver o cabeçalho).
        cliente.close()
        return

    alvo = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        alvo.connect((destino_host, destino_porta))
        alvo.sendall(primeiro)
    except OSError as exc:
        log.warning("destino %s:%s indisponível: %s", destino_host, destino_porta, exc)
        cliente.close()
        alvo.close()
        return

    ida = threading.Thread(target=_bombear, args=(cliente, alvo), daemon=True)
    volta = threading.Thread(target=_bombear, args=(alvo, cliente), daemon=True)
    ida.start()
    volta.start()
    ida.join()
    volta.join()
    cliente.close()
    alvo.close()


def servir(
    escuta_host: str,
    escuta_porta: int,
    destino: str,
    max_conexoes: int = MAX_CONEXOES,
    pronto: threading.Event | None = None,
) -> None:
    destino_host, _, porta_txt = destino.rpartition(":")
    destino_porta = int(porta_txt)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((escuta_host, escuta_porta))
    srv.listen(128)
    if pronto is not None:
        # Só para os testes: dizer que a porta já aceita, sem dormir e torcer.
        pronto.set()
    log.info(
        "%s:%s -> %s:%s (teto %d conexões)",
        escuta_host, escuta_porta, destino_host, destino_porta, max_conexoes,
    )

    vagas = threading.Semaphore(max_conexoes)

    def atender_e_liberar(cliente: socket.socket) -> None:
        try:
            _atender(cliente, destino_host, destino_porta)
        finally:
            vagas.release()

    while True:
        cliente, _ = srv.accept()
        if not vagas.acquire(blocking=False):
            # Lotado. Fecha na hora em vez de enfileirar: enfileirar é o que
            # transforma pico em queda, porque a fila cresce sem limite e o
            # cliente já desistiu quando sua vez chega.
            log.warning("teto de %d conexões atingido; recusando", max_conexoes)
            cliente.close()
            continue
        threading.Thread(target=atender_e_liberar, args=(cliente,), daemon=True).start()


def main() -> int:
    p = argparse.ArgumentParser(description="encaminhador TCP para o serviço de UI")
    p.add_argument("--escuta", default="0.0.0.0:8000")
    p.add_argument("--destino", default="ui:8000")
    args = p.parse_args()

    host, _, porta = args.escuta.rpartition(":")
    servir(host or "0.0.0.0", int(porta), args.destino)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
