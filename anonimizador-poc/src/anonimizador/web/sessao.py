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
import re
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
from ..pseudonimo import pseudonimizar_texto, tokens_de
from ..spans import Span, resolver_sobreposicoes
from ..verifier import verify, verify_texto

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
    nota: str | None = None

    # Decisão do usuário sobre **este** trecho, em três estados:
    #
    #   None   segue a política da entidade (o padrão)
    #   True   tarja, mesmo que a política da classe diga para manter
    #   False  não tarja, mesmo que a política da classe diga para tarjar
    #
    # Era um booleano com padrão `True`, e `sera_tarjado` era
    # `ativo AND política == tarja` — duas chaves em série. O efeito é que,
    # quando a política da entidade é `manter`, a chave do span perde toda a
    # autoridade: clicar no retângulo alternava `ativo` sem mudar nada na
    # tela. Num documento com 31 datas detectadas e preservadas por política,
    # eram 31 retângulos tracejados em que clicar não fazia efeito nenhum.
    #
    # Com três estados, o clique sempre tem consequência visível, e a
    # intenção explícita sobre um trecho vence o padrão da classe.
    ativo: bool | None = None

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
    # Artefato de texto pseudonimizado. Independente do PDF: tem gate próprio
    # (`verify_texto`), e a mesma edição invalida os dois.
    texto_pseudo: Path | None = None
    relatorio_texto: dict | None = None

    # -- política ---------------------------------------------------------
    def operador_de(self, entidade: str) -> str:
        if entidade == MANUAL:
            # O usuário apontou explicitamente. A política de entidades não
            # tem jurisdição sobre isso — ela descreve classes detectadas.
            return TARJA
        return self.perfil.operador_de(entidade)

    def sera_tarjado(self, s: SpanUI) -> bool:
        """Único lugar que decide se um trecho vai virar tarja.

        A decisão explícita sobre o trecho vence o padrão da classe. Sem essa
        precedência, desligar `DATE_TIME` inteiro tornaria impossível tarjar
        *uma* data específica — e o inverso também: com a classe ligada, não
        haveria como poupar um caso pontual.
        """
        if s.ativo is not None:
            return s.ativo
        return self.operador_de(s.entity) == TARJA

    def spans_ativos(self) -> list[SpanUI]:
        """Os spans que de fato serão tarjados."""
        return [s for s in self.spans.values() if self.sera_tarjado(s)]

    def inventario(self) -> dict[str, int]:
        """Contagem por entidade, **incluindo as que não apareceram**.

        Listar só o que foi detectado transforma duas coisas muito diferentes
        na mesma ausência na tela: "procurei CPF e não há nenhum neste
        documento" e "não sei procurar CPF". O usuário não tem como
        distinguir, e a leitura natural da tela é a segunda.

        Com a contagem zero explícita, o ponto cego fica visível. É o mesmo
        princípio do `report.md`: o número que não existe precisa aparecer
        como zero, não como silêncio.
        """
        inv: dict[str, int] = {e: 0 for e in config.ENTIDADES_ATIVAS}
        for s in self.spans.values():
            inv[s.entity] = inv.get(s.entity, 0) + 1
        # Detectadas primeiro, por volume; as zeradas depois, em ordem
        # alfabética, para não competirem por atenção com o que importa.
        return dict(
            sorted(inv.items(), key=lambda kv: (kv[1] == 0, -kv[1], kv[0]))
        )

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
        backend encontra todas as ocorrências, sem modelo nenhum no meio.

        **Ocorrência já coberta por tarja ativa é ignorada.** A checagem tem
        de ser por *sobreposição*, não por igualdade de fronteiras: tarjar
        ``Leonardo`` num documento onde o detector já marcou
        ``Leonardo Guerra`` criava um segundo retângulo por cima do primeiro.
        Os dois ficavam pretos e empilhados, o clique acertava só o de cima, e
        a tarja continuava lá — o usuário concluía, com razão, que não dava
        para desligá-la.
        """
        termo = termo.strip()
        if len(termo) < 2:
            raise ValueError("termo curto demais")

        # Só spans que de fato produzirão tarja bloqueiam. Se o usuário
        # desligou um span e depois pediu o termo, a intenção explícita dele
        # vale mais que a proposta desligada do detector.
        ativos = [(s.start, s.end) for s in self.spans_ativos()]

        def sobreposto(ini: int, fim: int) -> bool:
            return any(ini < b and a < fim for a, b in ativos)

        criados: list[SpanUI] = []
        texto = self.tm.text
        for ini, fim in self._ocorrencias(termo, texto):
            if not sobreposto(ini, fim) and self.tm.rects_for(ini, fim):
                sid = self._novo_id()
                self.spans[sid] = SpanUI(
                    id=sid,
                    entity=MANUAL,
                    score=1.0,
                    start=ini,
                    end=fim,
                    valor=texto[ini:fim],
                    origem="usuario",
                )
                criados.append(self.spans[sid])

        self._invalidar()
        logger.info(
            "sessao %s: termo adicionado, %d ocorrencias", self.doc_id, len(criados)
        )
        return criados

    def _conferir_intervalo(self, inicio: int, fim: int, texto: str) -> tuple[int, int]:
        """Confere que o intervalo aponta mesmo para o texto que o cliente viu.

        Os offsets vêm do navegador, e há uma diferença real entre os dois
        lados: o JavaScript conta comprimento em unidades UTF-16, o Python em
        code points. Um caractere fora do BMP num documento faz as duas
        contagens divergirem, e a partir dali os offsets escorregam.

        O modo de falha disso é o pior possível num redator: tarjar o trecho
        **errado**, sem erro nenhum, cobrindo texto inocente e deixando o dado
        pessoal à mostra. Ninguém perceberia até alguém ler o PDF final.

        Por isso o servidor não confia no offset: ele confere. Batendo, usa.
        Não batendo, procura o texto reivindicado numa janela ao redor e se
        corrige. Não achando, recusa em vez de adivinhar.
        """
        def normal(s: str) -> str:
            return " ".join(s.split())

        alvo = normal(texto)
        if not alvo:
            return inicio, fim

        if normal(self.tm.text[inicio:fim]) == alvo:
            return inicio, fim

        # Escorregou. Procura perto de onde o cliente disse que estava —
        # limitar a janela evita casar com outra ocorrência do outro lado do
        # documento, que seria uma correção pior que o erro.
        janela = 500
        ini_busca = max(0, inicio - janela)
        trecho = self.tm.text[ini_busca:min(len(self.tm.text), fim + janela)]
        for a, b in self._ocorrencias(alvo, trecho):
            logger.warning(
                "sessao %s: offset do cliente escorregou %d caracteres, corrigido",
                self.doc_id,
                abs((ini_busca + a) - inicio),
            )
            return ini_busca + a, ini_busca + b

        raise ValueError(
            "a seleção não corresponde ao documento; tente selecionar de novo"
        )

    def adicionar_intervalo(
        self, inicio: int, fim: int, texto: str = ""
    ) -> SpanUI:
        """Tarja **exatamente** os caracteres ``[inicio, fim)``.

        É o caminho da seleção com o mouse, e é deliberadamente diferente de
        ``adicionar_por_termo``:

        * **selecionar** é apontar *esta* ocorrência. O usuário marcou um
          trecho específico na tela e espera que só ele seja coberto.
        * **digitar** é descrever um valor. Aí faz sentido pegar todas as
          ocorrências, porque o usuário não tem como caçar cada uma.

        Tratar os dois igual — como fazíamos, mandando a seleção para a busca
        textual — dá o resultado errado nos dois sentidos: seleciona-se um
        nome numa cláusula e o documento inteiro fica tarjado; e um trecho que
        aparece uma vez só chega ao servidor como texto, sujeito a não casar
        por espaçamento.

        Com offsets não há busca nenhuma: o intervalo já é a resposta.
        """
        n = len(self.tm.text)
        if not (0 <= inicio < fim <= n):
            raise ValueError("intervalo fora do documento")

        inicio, fim = self._conferir_intervalo(inicio, fim, texto)

        # Seleção com o mouse quase sempre pega espaço nas pontas; tarjá-lo
        # cobriria vizinhança à toa.
        while inicio < fim and self.tm.text[inicio].isspace():
            inicio += 1
        while fim > inicio and self.tm.text[fim - 1].isspace():
            fim -= 1
        if fim - inicio < 1:
            raise ValueError("seleção vazia")

        if any(inicio < s.end and s.start < fim for s in self.spans_ativos()):
            raise ValueError("esse trecho já está coberto por uma tarja ativa")

        if not self.tm.rects_for(inicio, fim):
            raise ValueError("seleção sem região visível no documento")

        sid = self._novo_id()
        self.spans[sid] = SpanUI(
            id=sid,
            entity=MANUAL,
            score=1.0,
            start=inicio,
            end=fim,
            valor=self.tm.text[inicio:fim],
            origem="usuario",
        )
        self._invalidar()
        logger.info(
            "sessao %s: intervalo tarjado, %d caracteres", self.doc_id, fim - inicio
        )
        return self.spans[sid]

    @staticmethod
    def _ocorrencias(termo: str, texto: str) -> list[tuple[int, int]]:
        """Onde ``termo`` aparece, tolerando diferença de espaçamento.

        Busca literal não serve aqui, e o motivo aparece assim que alguém
        seleciona um trecho na tela: o que a pessoa vê como
        ``Maria Fernanda da Mata`` numa linha só pode estar no texto extraído
        como ``Maria Fernanda\\nda Mata``, porque o PDF quebrou a linha ali. O
        ``find`` não acha, a tela responde "nenhuma ocorrência", e o usuário
        conclui — com razão — que o botão não funciona.

        Qualquer sequência de espaço em branco no termo casa com qualquer
        sequência de espaço em branco no texto. O resto é comparado
        literalmente: isto continua sendo busca exata, não difusa. Um termo
        errado não passa a casar com nada parecido.
        """
        partes = [re.escape(p) for p in termo.split() if p]
        if not partes:
            return []
        padrao = re.compile(r"\s+".join(partes))
        return [(m.start(), m.end()) for m in padrao.finditer(texto)]

    def remover_span(self, span_id: str) -> None:
        """Apaga um span que o usuário criou.

        Desligar não basta. Um termo digitado errado — ``a``, ou um trecho
        curto que casa em cinquenta lugares — enche a tela de retângulos que o
        usuário precisa desligar um a um. Apagar é a operação que ele quer, e
        só existe para spans de origem ``usuario``: remover uma proposta do
        detector esconderia dele que aquilo foi detectado.
        """
        s = self.spans.get(span_id)
        if s is None:
            raise KeyError(span_id)
        if s.origem != "usuario":
            raise ValueError(
                "só é possível apagar trecho adicionado por você; "
                "para ignorar uma proposta do detector, desligue-a"
            )
        del self.spans[span_id]
        self._invalidar()
        logger.info("sessao %s: span %s removido", self.doc_id, span_id)

    def remover_manuais(self) -> int:
        """Apaga todos os trechos adicionados à mão. O desfazer do campo."""
        ids = [k for k, s in self.spans.items() if s.origem == "usuario"]
        for k in ids:
            del self.spans[k]
        if ids:
            self._invalidar()
        logger.info("sessao %s: %d spans manuais removidos", self.doc_id, len(ids))
        return len(ids)

    def aplicar_perfil(self, perfil: PerfilPolitica) -> None:
        """Aplica a política e **devolve a classe alterada ao padrão dela**.

        Sem isso a caixa de seleção da entidade deixaria de ser confiável:
        desmarcá-la ainda deixaria tarjados os trechos daquela classe que o
        usuário tinha ligado um a um antes, e a contagem na lateral
        contradiria o que a tela mostra.

        A regra fica assim: a caixa define o padrão da classe e zera as
        exceções; o clique no retângulo cria uma exceção a partir daí.
        """
        validar_perfil(perfil, config.ENTIDADES_ATIVAS)

        mudaram = {
            e
            for e in config.ENTIDADES_ATIVAS
            if self.perfil.operador_de(e) != perfil.operador_de(e)
        }
        for s in self.spans.values():
            if s.entity in mudaram and s.origem != "usuario":
                s.ativo = None

        self.perfil = perfil
        self._invalidar()
        logger.info("sessao %s: perfil %r aplicado", self.doc_id, perfil.nome)

    def _invalidar(self) -> None:
        """Qualquer edição derruba a aprovação.

        Sem isso, o usuário aprovaria, mexeria nas tarjas e baixaria um arquivo
        que não corresponde ao que ele viu aprovado. É o modo de falha mais
        fácil de introduzir numa tela assim.
        """
        if self.aprovada or self.redigido or self.texto_pseudo:
            logger.info("sessao %s: aprovacao invalidada por edicao", self.doc_id)
        self.aprovada = False
        self.relatorio = None
        if self.redigido and self.redigido.exists():
            self.redigido.unlink()
        self.redigido = None

        # O texto pseudonimizado é um entregável como o PDF, e a mesma regra
        # vale: quem editou depois de gerar não pode baixar o que foi gerado
        # antes da edição.
        self.relatorio_texto = None
        if self.texto_pseudo and self.texto_pseudo.exists():
            self.texto_pseudo.unlink()
        self.texto_pseudo = None

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

        # A dissecação precisa acontecer **antes** de apagar o arquivo: ela
        # reabre o PDF reprovado para descobrir se cada valor ainda aparece no
        # texto extraído. Sem isso, a tela só consegue dizer "reprovou", que é
        # exatamente a mensagem que não deixa ninguém agir.
        ocorrencias = self._dissecar(rel.leaks, saida)

        self.relatorio = {
            "spans_redigidos": res.spans_redigidos,
            "retangulos": res.retangulos,
            "spans_sem_retangulo": len(res.spans_sem_retangulo),
            "saneamento": res.saneamento,
            "verificacao_ok": rel.ok,
            "vetores": rel.vetores_executados,
            "valores_checados": rel.valores_checados,
            "vazamentos": sorted({leak.vetor for leak in rel.leaks}),
            "total_vazamentos": len(rel.leaks),
            "ocorrencias": ocorrencias,
        }

        if rel.ok:
            self.aprovada = True
            self.redigido = saida
        else:
            self.aprovada = False
            self.redigido = None
            saida.unlink(missing_ok=True)
            # Log sem valor: tipo de objeto e vetor bastam para diagnosticar,
            # e não copiam dado pessoal para mais um artefato com retenção
            # própria.
            logger.error(
                "sessao %s: verificacao REPROVOU, %d ocorrencia(s); %s",
                self.doc_id,
                len(rel.leaks),
                "; ".join(
                    f"{o['vetor']}:{o['objeto']}"
                    + (" (visivel no texto)" if o["visivel_no_texto"] else "")
                    for o in ocorrencias
                ),
            )

        logger.info(
            "sessao %s: aprovacao %s, %d spans",
            self.doc_id,
            "ok" if rel.ok else "REPROVADA",
            res.spans_redigidos,
        )
        return self.relatorio

    def gerar_texto_pseudonimizado(self) -> dict:
        """Produz o texto com tokens no lugar dos valores, e verifica.

        Espelha ``aprovar()`` de propósito, inclusive no que parece detalhe:
        se a verificação reprovar, o arquivo é apagado. Um artefato que falhou
        o gate não pode ficar em disco esperando alguém alcançá-lo por outro
        caminho — vale para o texto exatamente como vale para o PDF.

        Usa os mesmos spans que virariam tarja. A política não muda; muda o
        que preenche o buraco em cada artefato — retângulo preto no PDF, token
        no texto. É por isso que isto não é um operador novo de ``politica.py``
        e ``validar_perfil`` continua recusando ``pseudonimo``: enquanto não
        existir escritor de token no PDF, liberar o operador deixaria um perfil
        pedir pseudônimo e receber tarja, sem aviso.
        """
        ativos = [s.para_span() for s in self.spans_ativos()]

        # Spans ativos podem se sobrepor: basta desligar um span detectado,
        # marcar um trecho manual dentro dele e religar o detectado. O caminho
        # do PDF tolera isso desenhando dois retângulos; a substituição em
        # texto produziria um token dentro do outro. `resolver_sobreposicoes`
        # é a peça determinística que já existe para essa decisão — sem
        # `texto`, para não redecidir rótulo que o usuário pode ter editado.
        disjuntos = resolver_sobreposicoes(ativos)

        res = pseudonimizar_texto(self.tm.text, disjuntos)
        tokens = tokens_de(res.substituicoes)

        saida = self.pasta / "pseudonimizado.txt"
        rel = verify_texto(res.texto, res.valores, tokens, caminho=str(saida))

        self.relatorio_texto = {
            "spans_substituidos": len(res.substituicoes),
            "tokens_distintos": len(tokens),
            "spans_descartados_por_sobreposicao": len(ativos) - len(disjuntos),
            "caracteres": len(res.texto),
            "verificacao_ok": rel.ok,
            "vetores": rel.vetores_executados,
            "valores_checados": rel.valores_checados,
            "vazamentos": sorted({leak.vetor for leak in rel.leaks}),
            "total_vazamentos": len(rel.leaks),
            # Token não é dado pessoal: pode ser nomeado, e é a única coisa
            # que torna um descarte silencioso diagnosticável.
            "tokens_ausentes": sorted(
                leak.valor for leak in rel.leaks if leak.vetor == "token-ausente"
            ),
        }

        if rel.ok:
            saida.write_text(res.texto, encoding="utf-8")
            self.texto_pseudo = saida
        else:
            self.texto_pseudo = None
            saida.unlink(missing_ok=True)
            # Sem valor de PII: vetor e contagem bastam para diagnosticar.
            logger.error(
                "sessao %s: texto pseudonimizado REPROVOU, %d ocorrencia(s) em %s",
                self.doc_id,
                len(rel.leaks),
                ", ".join(sorted({leak.vetor for leak in rel.leaks})) or "-",
            )

        logger.info(
            "sessao %s: texto pseudonimizado %s, %d substituicoes, %d tokens",
            self.doc_id,
            "ok" if rel.ok else "REPROVADO",
            len(res.substituicoes),
            len(tokens),
        )
        return self.relatorio_texto

    @property
    def pode_baixar_texto(self) -> bool:
        return bool(
            self.texto_pseudo
            and self.texto_pseudo.exists()
            and self.relatorio_texto
            and self.relatorio_texto.get("verificacao_ok")
        )

    def _dissecar(self, leaks: list, caminho_redigido: Path) -> list[dict]:
        """Traduz cada vazamento em algo sobre o que dá para agir.

        Um vazamento tem duas naturezas muito diferentes, e a tela precisa
        distingui-las porque o conserto é outro:

        * **visível no texto extraído** — a string que mandamos tarjar aparece
          em algum lugar que qualquer copiar-colar alcança. Quase sempre é
          outra ocorrência do mesmo valor que o detector não marcou. O usuário
          conserta em um clique, tarjando todas as ocorrências.

        * **só na estrutura** — o valor não sai por extração de texto, mas
          sobrevive num objeto do PDF: aparência de campo de formulário,
          XObject que a redação não alcançou, metadados. Isso não é erro de
          detecção e o usuário não conserta sozinho — é defeito do redator.

        Chamar as duas de "vazou" e apagar o arquivo, como fazíamos, é
        tecnicamente correto e praticamente inútil.
        """
        if not leaks:
            return []

        texto_final = ""
        try:
            d = fitz.open(str(caminho_redigido))
            try:
                texto_final = "\n".join(
                    d.load_page(i).get_text() for i in range(d.page_count)
                )
            finally:
                d.close()
        except Exception:  # noqa: BLE001
            logger.exception("sessao %s: falha ao reabrir o PDF reprovado", self.doc_id)

        por_valor: dict[str, dict] = {}
        for leak in leaks:
            item = por_valor.setdefault(
                leak.valor,
                {
                    "valor": leak.valor,
                    "vetor": leak.vetor,
                    "vetores": [],
                    "objeto": "",
                    "visivel_no_texto": leak.valor in texto_final,
                    "ocorrencias_no_texto": texto_final.count(leak.valor),
                },
            )
            if leak.vetor not in item["vetores"]:
                item["vetores"].append(leak.vetor)
            # O detalhe do vetor `streams` carrega o tipo do objeto; é a
            # informação que diz *onde* consertar.
            if leak.vetor == "streams" and "em " in leak.detalhe and not item["objeto"]:
                item["objeto"] = leak.detalhe.split("em ", 1)[1]

        return sorted(
            por_valor.values(),
            key=lambda x: (not x["visivel_no_texto"], x["valor"]),
        )

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
            "pode_baixar_texto": self.pode_baixar_texto,
            "relatorio_texto": self.relatorio_texto,
        }

    def span_dict(self, s: SpanUI) -> dict:
        return {
            "id": s.id,
            "entity": s.entity,
            "score": round(s.score, 3),
            "valor": s.valor,
            "origem": s.origem,
            "ativo": s.ativo,
            "nota": s.nota,
            "sera_tarjado": self.sera_tarjado(s),
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
