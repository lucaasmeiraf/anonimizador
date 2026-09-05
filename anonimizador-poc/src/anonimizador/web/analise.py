"""Serviço de análise por LLM externa — a segunda peça do sistema com egress.

## O que ele é, e por que é separado

O serviço ``ui`` faz todo o trabalho de documento e vive numa rede
``internal: true``: sem rota para fora, garantido pelo kernel. Ele **não pode**
chamar o OpenRouter, e essa impossibilidade é a característica de segurança do
produto, não um obstáculo a contornar.

Então o egress mora aqui, sozinho, pelo mesmo raciocínio que criou o
``forward.py``: o componente com saída de rede é pequeno o bastante para ser
lido inteiro numa sentada, e não importa torch, transformers, presidio nem
PyMuPDF. A superfície de dependência onde o risco de telefonar para casa de
fato mora continua sem rede.

## O que ele deliberadamente não faz

* **Não vê o documento original.** O compose não monta ``./out`` aqui, então a
  pasta das sessões — onde o PDF em claro vive durante a revisão — é
  inalcançável. Ele recebe só o texto que já passou pelo gate.
* **Não detecta, não redige, não verifica.** Recebe texto pronto e o envia.
  Quem decide se o texto *pode* ser enviado é o ``ui``, que tem o modelo e não
  tem rede.
* **Não registra conteúdo.** O log traz contagem, modelo e duração. Nunca o
  texto, nunca o prompt, nunca a resposta — cada um deles seria uma cópia de
  material sensível fora do arquivo verificado, com retenção própria.
* **Não guarda estado.** Sem disco, sem cache, sem histórico.

## O limite honesto

Os bytes do texto pseudonimizado passam por aqui, e este processo tem saída de
rede. A garantia não é "o conteúdo nunca toca um processo com rede" — é que o
único processo com rede é auditável em minutos, e que o que ele recebe já foi
verificado duas vezes: uma pelo ``verify_texto`` que produziu o artefato, e
outra pela re-detecção que o ``ui`` roda imediatamente antes de chamar aqui.

O que nenhuma das duas verificações prova é que *tudo* que era dado pessoal foi
detectado. Nomes escapam em cerca de 1 documento a cada 50, e identificador
indireto por contexto não é detectado de forma alguma. Com envio externo isso
deixa de ser defeito local e vira incidente com terceiro. Está registrado em
``goal-fase-3.md`` §2 e em ``docs/05-politica-llm.md`` §2.6.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s analise: %(message)s")
log = logging.getLogger("analise")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Sem valor padrão embutido: a chave vem do ambiente, e a ausência dela é um
# erro alto na primeira chamada, não um fallback silencioso.
CHAVE = os.getenv("OPENROUTER_API_KEY", "").strip()
MODELO_PADRAO = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5").strip()
TIMEOUT = int(os.getenv("ANON_ANALISE_TIMEOUT", "120"))

# Teto de tamanho do que se manda. Não é limite de token do modelo — é uma
# trava contra mandar um documento inteiro de 500 páginas por engano e
# descobrir pelo custo.
MAX_CARACTERES = int(os.getenv("ANON_ANALISE_MAX_CHARS", "200000"))

SISTEMA = (
    "Você analisa documentos administrativos brasileiros que passaram por "
    "anonimização. Identificadores de pessoas e organizações foram "
    "substituídos por códigos no formato [TIPO-XXXX] — por exemplo [P-7F3A] "
    "para uma pessoa, [CPF-2C81] para um CPF.\n\n"
    "Regras ao responder:\n"
    "- Trate cada código como um ator estável: o mesmo código é sempre a "
    "mesma entidade dentro deste documento.\n"
    "- Use os códigos na resposta, exatamente como aparecem. Assim quem tem o "
    "documento original consegue mapear de volta.\n"
    "- Nunca invente o nome real por trás de um código, nem tente adivinhá-lo "
    "a partir do contexto. Se a resposta depender de saber quem é, diga que a "
    "informação foi anonimizada.\n"
    "- Responda em português do Brasil."
)


class SemChave(RuntimeError):
    """A chave do OpenRouter não foi configurada."""


def analisar(texto: str, prompt: str, modelo: str = "") -> dict:
    """Manda o texto e a pergunta ao OpenRouter e devolve a resposta.

    Levanta em vez de devolver resposta vazia: uma falha de rede que virasse
    string vazia apareceria na tela como "o modelo não achou nada", que é a
    forma mais cara possível de errar aqui.
    """
    if not CHAVE:
        raise SemChave(
            "OPENROUTER_API_KEY ausente. Adicione a chave no arquivo .env na "
            "raiz de anonimizador-poc/ e suba o servico de novo."
        )
    if len(texto) > MAX_CARACTERES:
        raise ValueError(
            f"texto com {len(texto)} caracteres excede o teto de "
            f"{MAX_CARACTERES}; ajuste ANON_ANALISE_MAX_CHARS se for proposital"
        )

    corpo = json.dumps(
        {
            "model": modelo or MODELO_PADRAO,
            "messages": [
                {"role": "system", "content": SISTEMA},
                {
                    "role": "user",
                    "content": f"{prompt}\n\n--- DOCUMENTO ---\n{texto}",
                },
            ],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        OPENROUTER_URL,
        data=corpo,
        headers={
            "Authorization": f"Bearer {CHAVE}",
            "Content-Type": "application/json",
            # O OpenRouter usa estes dois para atribuição no painel dele.
            "HTTP-Referer": "https://github.com/lucaasmeiraf/anonimizador",
            "X-Title": "Anonimizador",
        },
        method="POST",
    )

    inicio = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # O corpo do erro do OpenRouter descreve o problema (chave inválida,
        # crédito, modelo inexistente) e não contém o documento.
        detalhe = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"OpenRouter respondeu {exc.code}: {detalhe}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"falha de rede ao chamar o OpenRouter: {exc.reason}") from exc

    duracao = time.monotonic() - inicio

    try:
        resposta = dados["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"resposta do OpenRouter em formato inesperado: {exc}") from exc

    uso = dados.get("usage") or {}
    # Contagem, modelo e duração. Nunca o texto, o prompt ou a resposta.
    log.info(
        "enviados %d caracteres ao modelo %s; %.1fs; tokens prompt=%s saida=%s",
        len(texto),
        dados.get("model", modelo or MODELO_PADRAO),
        duracao,
        uso.get("prompt_tokens", "?"),
        uso.get("completion_tokens", "?"),
    )

    return {
        "resposta": resposta,
        "modelo": dados.get("model", modelo or MODELO_PADRAO),
        "duracao_s": round(duracao, 2),
        "tokens_prompt": uso.get("prompt_tokens"),
        "tokens_saida": uso.get("completion_tokens"),
        "caracteres_enviados": len(texto),
    }


class Handler(BaseHTTPRequestHandler):
    """HTTP mínimo, com a biblioteca padrão. Duas rotas, nenhum estado."""

    def _responder(self, codigo: int, payload: dict) -> None:
        corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/saude":
            self._responder(404, {"erro": "rota desconhecida"})
            return
        self._responder(200, {"ok": True, "chave_configurada": bool(CHAVE),
                              "modelo_padrao": MODELO_PADRAO})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/analisar":
            self._responder(404, {"erro": "rota desconhecida"})
            return
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            pedido = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            resultado = analisar(
                texto=pedido["texto"],
                prompt=pedido.get("prompt", "Resuma este documento."),
                modelo=pedido.get("modelo", ""),
            )
        except SemChave as exc:
            self._responder(503, {"erro": str(exc)})
        except KeyError as exc:
            self._responder(400, {"erro": f"campo ausente no pedido: {exc}"})
        except ValueError as exc:
            self._responder(413, {"erro": str(exc)})
        except Exception as exc:  # noqa: BLE001
            # A mensagem descreve a falha da chamada, não o conteúdo enviado.
            log.error("falha na analise: %s", type(exc).__name__)
            self._responder(502, {"erro": str(exc)})
        else:
            self._responder(200, resultado)

    def log_message(self, formato: str, *args) -> None:
        """Silencia o log de acesso padrão.

        Ele imprimiria a linha de request, que é inofensiva — mas o padrão
        aqui é registrar só o que este módulo decide registrar, em vez de
        herdar o que a biblioteca resolveu imprimir.
        """
        return


def servir(host: str, porta: int) -> None:
    servidor = ThreadingHTTPServer((host, porta), Handler)
    log.info(
        "escutando em %s:%s; chave %s; modelo padrao %s",
        host,
        porta,
        "configurada" if CHAVE else "AUSENTE",
        MODELO_PADRAO,
    )
    servidor.serve_forever()


def main() -> int:
    p = argparse.ArgumentParser(description="servico de analise por LLM externa")
    p.add_argument("--escuta", default="0.0.0.0:8100")
    args = p.parse_args()
    host, _, porta = args.escuta.rpartition(":")
    servir(host or "0.0.0.0", int(porta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
