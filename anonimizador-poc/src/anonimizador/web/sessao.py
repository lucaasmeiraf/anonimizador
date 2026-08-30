"""Estado de um documento em revisão, e as travas que o cercam.

Este módulo existe para que ``app.py`` seja só transporte HTTP. Toda regra que
decide *o que é tarjado* e *quando o arquivo pode ser baixado* mora aqui, onde
dá para testar sem subir servidor.

Três invariantes, na ordem em que importam:

1. **O preview nunca é o entregável.** A tela desenha retângulos sobre uma
   imagem da página. O arquivo que sai vem de ``redact_document`` +
   ``verify``, executados na aprovação. Nada que o navegador desenha influencia
   o PDF final — só a lista de spans ativos influencia.

2. **Download exige verificação aprovada.** ``pode_baixar`` é falso enquanto
   ``verify().ok`` não for verdadeiro. É o mesmo gate do ``run_eval.py``,
   movido para dentro do produto: se o valor sobrevive em qualquer um dos dez
   vetores, não existe arquivo para baixar.

3. **Nenhum valor de PII em log.** Os métodos aqui registram identificador de
   span e contagem, nunca o texto. A Fase 0 logava o valor em
   ``pdf_redactor``; num serviço isso seria uma cópia de dado pessoal fora do
   PDF saneado, com retenção própria e sem verificação.
"""

from __future__ import annotations

import logging
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from .. import config
from ..layout import TextMap, build_text_map
from ..pdf_redactor import redact_document
from ..politica import MANTER, TARJA, PerfilPolitica, validar_perfil
from ..spans import Span
from ..verifier import verify

logger = logging.getLogger(__name__)

# Rótulo dos spans que o usuário adicionou à mão. Não é entidade detectável:
# existe para separar, no relatório e na auditoria, o que o pipeline achou do
# que a pessoa apontou.
MANUAL = "MANUAL"

TTL_PADRAO = 2 * 60 * 60  # 2 h


@dataclass
class SpanUI:
    """Um span como a interface o manipula."""

    id: str
    entity: str
    score: float
    start: int
    end: int
    valor: str
    origem: str = "detector"  # "detector" | "usuario"
    ativo: bool = True

    def para_span(self) -> Span:
        return Span(start=self.start, end=self.end, entity=self.entity, score=self.score)


@dataclass
class Sessao:
    doc_id: str
    pasta: Path
    original: Path
    nome_arquivo: str
    tm: TextMap
    paginas: list[dict]
    spans: dict[str, SpanUI] = field(default_factory=dict)
    perfil: PerfilPolitica = field(
        default_factory=lambda: PerfilPolitica(nome="padrao", padrao=TARJA)
    )
    criada_em: float = field(default_factory=time.time)
    aprovada: bool = False
    redigido: Path | None = None
    relatorio: dict | None = None

    # -- política ---------------------------------------------------------
    def operador_de(self, entidade: str) -> str:
        if entidade == MANUAL:
            # O usuário apontou explicitamente. A política de entidades não
            # tem jurisdição sobre isso — ela descreve classes detectadas.
            return TARJA
        return self.perfil.operador_de(entidade)

    def spans_ativos(self) -> list[SpanUI]:
        """Os spans que de fato serão tarjados.

        Duas condições independentes, e as duas precisam valer: o span não foi
        desligado individualmente, **e** a política manda tarjar a classe dele.
        Separadas de propósito — desligar `PERSON` inteiro e desligar um nome
        específico são intenções diferentes.
        """
        return [
            s
            for s in self.spans.values()
            if s.ativo and self.operador_de(s.entity) == TARJA
        ]

    def inventario(self) -> dict[str, int]:
        inv: dict[str, int] = {}
        for s in self.spans.values():
            inv[s.entity] = inv.get(s.entity, 0) + 1
        return dict(sorted(inv.items(), key=lambda kv: (-kv[1], kv[0])))

    # -- edição -----------------------------------------------------------
    def _novo_id(self) -> str:
        return f"s{len(self.spans) + 1}_{secrets.token_hex(3)}"

    def alternar(self, span_id: str, ativo: bool) -> SpanUI:
        s = self.spans[span_id]
        s.ativo = ativo
        self._invalidar()
        logger.info("sessao %s: span %s ativo=%s", self.doc_id, span_id, ativo)
        return s

    def adicionar_por_termo(self, termo: str) -> list[SpanUI]:
        """Cria um span para **cada** ocorrência literal de ``termo``.

        É o caminho determinístico do chat: o usuário aponta o que faltou e o
        backend encontra todas as ocorrências, sem modelo nenhum no meio. Se
        uma ocorrência já estiver coberta por span ativo, ela é ignorada — não
        adianta empilhar tarja sobre tarja.
        """
        termo = termo.strip()
        if len(termo) < 2:
            raise ValueError("termo curto demais")

        cobertos = {(s.start, s.end) for s in self.spans.values()}
        criados: list[SpanUI] = []
        texto = self.tm.text
        pos = texto.find(termo)
        while pos != -1:
            fim = pos + len(termo)
            if (pos, fim) not in cobertos and self.tm.rects_for(pos, fim):
                sid = self._novo_id()
                self.spans[sid] = SpanUI(
                    id=sid,
                    entity=MANUAL,
                    score=1.0,
                    start=pos,
                    end=fim,
                    valor=texto[pos:fim],
                    origem="usuario",
                )
                criados.append(self.spans[sid])
            pos = texto.find(termo, pos + 1)

        self._invalidar()
        logger.info(
            "sessao %s: termo adicionado, %d ocorrencias", self.doc_id, len(criados)
        )
        return criados

    def aplicar_perfil(self, perfil: PerfilPolitica) -> None:
        validar_perfil(perfil, config.ENTIDADES_ATIVAS)
        self.perfil = perfil
        self._invalidar()
        logger.info("sessao %s: perfil %r aplicado", self.doc_id, perfil.nome)

    def _invalidar(self) -> None:
        """Qualquer edição derruba a aprovação.

        Sem isso, o usuário aprovaria, mexeria nas tarjas e baixaria um arquivo
        que não corresponde ao que ele viu aprovado. É o modo de falha mais
        fácil de introduzir numa tela assim.
        """
        if self.aprovada or self.redigido:
            logger.info("sessao %s: aprovacao invalidada por edicao", self.doc_id)
        self.aprovada = False
        self.relatorio = None
        if self.redigido and self.redigido.exists():
            self.redigido.unlink()
        self.redigido = None

    # -- produção do arquivo ----------------------------------------------
    def aprovar(self) -> dict:
        """Redige de verdade, verifica de verdade, e só então libera.

        A ordem importa: se ``verify`` reprovar, o arquivo redigido é apagado.
        Um PDF que falhou a verificação não pode ficar em disco esperando
        alguém baixá-lo por outro caminho.
        """
        ativos = self.spans_ativos()
        saida = self.pasta / "redigido.pdf"

        doc = fitz.open(str(self.original))
        try:
            tm = build_text_map(doc)
            res = redact_document(doc, tm, [s.para_span() for s in ativos], saida)
        finally:
            doc.close()

        rel = verify(saida, res.valores)

        self.relatorio = {
            "spans_redigidos": res.spans_redigidos,
            "retangulos": res.retangulos,
            "spans_sem_retangulo": len(res.spans_sem_retangulo),
            "saneamento": res.saneamento,
            "verificacao_ok": rel.ok,
            "vetores": rel.vetores_executados,
            "valores_checados": rel.valores_checados,
            # Os vetores em que houve vazamento, sem o valor vazado — dizer
            # "vazou no vetor X" e o rotulo basta para agir; repetir o valor
            # aqui o copiaria para mais um artefato.
            "vazamentos": sorted({leak.vetor for leak in rel.leaks}),
            "total_vazamentos": len(rel.leaks),
        }

        if rel.ok:
            self.aprovada = True
            self.redigido = saida
        else:
            self.aprovada = False
            self.redigido = None
            saida.unlink(missing_ok=True)
            logger.error(
                "sessao %s: verificacao REPROVOU, %d ocorrencias em %s",
                self.doc_id,
                len(rel.leaks),
                self.relatorio["vazamentos"],
            )

        logger.info(
            "sessao %s: aprovacao %s, %d spans",
            self.doc_id,
            "ok" if rel.ok else "REPROVADA",
            res.spans_redigidos,
        )
        return self.relatorio

    @property
    def pode_baixar(self) -> bool:
        return bool(
            self.aprovada
            and self.redigido
            and self.redigido.exists()
            and self.relatorio
            and self.relatorio.get("verificacao_ok")
        )

    # -- serialização para a tela -----------------------------------------
    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "nome_arquivo": self.nome_arquivo,
            "paginas": self.paginas,
            "spans": [self.span_dict(s) for s in self.spans.values()],
            "inventario": self.inventario(),
            "perfil": self.perfil.to_dict(),
            "entidades_ativas": list(config.ENTIDADES_ATIVAS),
            "aprovada": self.aprovada,
            "pode_baixar": self.pode_baixar,
            "relatorio": self.relatorio,
        }

    def span_dict(self, s: SpanUI) -> dict:
        return {
            "id": s.id,
            "entity": s.entity,
            "score": round(s.score, 3),
            "valor": s.valor,
            "origem": s.origem,
            "ativo": s.ativo,
            "sera_tarjado": s.ativo and self.operador_de(s.entity) == TARJA,
            "rects": [
                {
                    "pagina": pno,
                    "x0": r.x0,
                    "y0": r.y0,
                    "x1": r.x1,
                    "y1": r.y1,
                }
                for pno, r in self.tm.rects_for(s.start, s.end)
            ],
        }


class Sessoes:
    """Registro em memória, com expiração e apagamento explícito.

    O original em claro fica em disco durante a revisão — não há como mostrar
    duas versões lado a lado sem isso. O que dá para garantir é que ele não
    fica *depois*: TTL, ``DELETE`` explícito, e varredura na subida.
    """

    def __init__(self, raiz: Path, ttl: float = TTL_PADRAO) -> None:
        self.raiz = Path(raiz)
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self._itens: dict[str, Sessao] = {}
        self._lock = threading.Lock()
        self.limpar_orfaos()

    def limpar_orfaos(self) -> int:
        """Apaga pastas de sessão de execuções anteriores.

        Um crash não pode deixar documento em claro em disco indefinidamente.
        """
        n = 0
        for pasta in self.raiz.iterdir() if self.raiz.exists() else []:
            if pasta.is_dir() and pasta.name not in self._itens:
                shutil.rmtree(pasta, ignore_errors=True)
                n += 1
        if n:
            logger.info("removidas %d pastas de sessao orfas", n)
        return n

    def expirar(self) -> int:
        agora = time.time()
        with self._lock:
            vencidas = [
                k for k, s in self._itens.items() if agora - s.criada_em > self.ttl
            ]
        for k in vencidas:
            self.remover(k)
        return len(vencidas)

    def criar(self, nome_arquivo: str, dados: bytes) -> Sessao:
        doc_id = secrets.token_urlsafe(9)
        pasta = self.raiz / doc_id
        pasta.mkdir(parents=True, exist_ok=True)
        original = pasta / "original.pdf"
        original.write_bytes(dados)

        doc = fitz.open(str(original))
        try:
            tm = build_text_map(doc)
            paginas = [
                {
                    "numero": i,
                    "largura": doc.load_page(i).rect.width,
                    "altura": doc.load_page(i).rect.height,
                }
                for i in range(doc.page_count)
            ]
        finally:
            doc.close()

        sessao = Sessao(
            doc_id=doc_id,
            pasta=pasta,
            original=original,
            nome_arquivo=nome_arquivo,
            tm=tm,
            paginas=paginas,
        )
        with self._lock:
            self._itens[doc_id] = sessao
        logger.info(
            "sessao %s criada: %d paginas, %d caracteres",
            doc_id,
            len(paginas),
            len(tm.text),
        )
        return sessao

    def obter(self, doc_id: str) -> Sessao | None:
        with self._lock:
            return self._itens.get(doc_id)

    def remover(self, doc_id: str) -> bool:
        with self._lock:
            sessao = self._itens.pop(doc_id, None)
        if not sessao:
            return False
        shutil.rmtree(sessao.pasta, ignore_errors=True)
        logger.info("sessao %s removida, arquivos apagados", doc_id)
        return True


def perfil_padrao() -> PerfilPolitica:
    """Perfil inicial: tarja o que a Fase 0 tarjava, mantém o resto.

    Espelha ``config.ENTIDADES_REDIGIDAS`` — em documento público o nome do
    órgão e a data do ato costumam ser justamente o que precisa permanecer
    legível, então `ORGANIZATION`, `LOCATION` e `DATE_TIME` nascem em `manter`.
    """
    regras = {
        e: (TARJA if e in config.ENTIDADES_REDIGIDAS else MANTER)
        for e in config.ENTIDADES_ATIVAS
    }
    return PerfilPolitica(
        nome="padrao",
        descricao="tarja identificadores e nomes; preserva órgão, local e data",
        padrao=TARJA,
        regras=regras,
    )
