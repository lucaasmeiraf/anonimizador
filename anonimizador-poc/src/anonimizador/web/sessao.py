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
from ..pdf_redactor import PseudonimoImpossivelNoPDF, medir_token, redact_document
from ..politica import (
    MANTER,
    OPERADORES_QUE_REMOVEM,
    PSEUDONIMO,
    TARJA,
    PerfilPolitica,
    validar_perfil,
)
from ..pseudonimo import AlocadorDeToken, pseudonimizar_texto, tokens_de
from ..spans import Span, resolver_sobreposicoes
from ..verifier import (
    SEPARADORES_DE_ID,
    _normalizar as _normalizar_verificacao,
    _variantes,
    verify,
    verify_texto,
)

logger = logging.getLogger(__name__)

# Rótulo dos spans que o usuário adicionou à mão. Não é entidade detectável:
# existe para separar, no relatório e na auditoria, o que o pipeline achou do
# que a pessoa apontou.
MANUAL = "MANUAL"

TTL_PADRAO = 2 * 60 * 60  # 2 h

# Limiar da conferência de pré-envio. Mais baixo que o `SCORE_THRESHOLD` de
# 0.35 da detecção normal, e a razão é que a conta de custo se inverte: no
# fluxo normal, falso positivo custa trabalho de revisão; antes de um envio
# externo, falso positivo custa recusar um envio seguro, e falso negativo
# custa mandar um nome real para um terceiro, sem desfazer.
LIMIAR_PRE_ENVIO = 0.20


def _preparar_paginas(textos: list[str]) -> list[tuple[str, str]]:
    """Cada página nas duas formas em que a verificação procura: espaço
    colapsado, e sem os separadores de identificador."""
    return [(_normalizar_verificacao(t), SEPARADORES_DE_ID.sub("", t)) for t in textos]


def _contar_por_pagina(paginas: list[tuple[str, str]], valor: str) -> dict[int, int]:
    """Página (1-based) -> quantas vezes ``valor`` aparece nela, em qualquer
    forma de ``_variantes``. Só as páginas em que aparece.

    É a busca do ``verify`` feita por página: a mesma régua que reprova o
    arquivo é a que diz ao usuário onde procurar.

    **O maior número entre as formas, não o da primeira que casa.** Parar na
    primeira contava 1 para ``18/02/2026`` numa página que também tem
    ``18.02.2026``: a forma literal casava uma vez e a de dígitos — que pega as
    duas, porque os separadores saem — nunca era consultada. A tela diria "1"
    e a verificação acharia 2, que é o defeito que esta contagem existe para
    evitar. Somar as formas contaria a mesma ocorrência duas vezes.
    """
    achado: dict[int, int] = {}
    for numero, (texto_norm, texto_ids) in enumerate(paginas, 1):
        n = max(
            (
                (texto_ids if forma.isdigit() else texto_norm).count(forma)
                for forma in _variantes(valor)
            ),
            default=0,
        )
        if n:
            achado[numero] = n
    return achado


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
    # Trilha de auditoria dos envios externos. Metadado apenas — sem conteúdo
    # enviado, sem resposta recebida. Não é apagada por `_invalidar`: o envio
    # aconteceu, e editar o documento depois não o desfaz.
    envios: list[dict] = field(default_factory=list)
    # Cresce a cada edição (`_invalidar`). A pré-verificação roda em segundo
    # plano enquanto o usuário continua editando; o número diz a que estado
    # da proposta um resultado se refere, e a tela descarta o que chegou
    # atrasado em vez de mostrar pendência de uma versão que já não existe.
    versao: int = 0
    # O que o PDF de origem tem e a redação vai perder — assinatura, links,
    # sumário. Contagem e booleano, nunca conteúdo: serve para a tela avisar
    # no momento de exportar só o que se aplica a *este* arquivo.
    caracteristicas: dict = field(default_factory=dict)
    # Último resultado da pré-verificação, com a versão a que se refere.
    _previa: tuple[int, dict] | None = field(default=None, repr=False)
    # Alocador de token **da sessão**, não de cada artefato.
    #
    # Criar um por chamada faria o mesmo nome virar `[P-7F3A]` no PDF e
    # `[P-2C81]` no texto, para o mesmo documento e a mesma pessoa. Quem
    # recebesse os dois arquivos não teria como saber que falam do mesmo ator
    # — que é exatamente a propriedade pela qual o token existe. Um alocador
    # por sessão dá determinismo entre os dois entregáveis.
    #
    # Continua sendo intradocumento: a sessão é um documento, morre com ele, e
    # nada é gravado em disco. A proibição da seção 0 do `goal-fase-2.md` é
    # reaproveitar entre documentos, e isso segue valendo.
    _alocador: AlocadorDeToken | None = field(default=None, repr=False)

    # -- política ---------------------------------------------------------
    def operador_de(self, entidade: str) -> str:
        if entidade == MANUAL:
            # O usuário apontou explicitamente, e a política de entidades não
            # tem jurisdição sobre isso — ela descreve classes detectadas.
            #
            # O que ela não decide é **se** o trecho sai; o **como** segue o
            # padrão do documento. Sem isso, num documento em modo token o
            # trecho apontado à mão viraria barra preta enquanto todo o resto
            # vira token — e o PDF discordaria do texto pseudonimizado, que
            # tokeniza tudo o que está ativo.
            padrao = self.perfil.padrao
            return padrao if padrao in OPERADORES_QUE_REMOVEM else TARJA
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
        # `OPERADORES_QUE_REMOVEM`, e nao `== TARJA`: com `pseudonimo`
        # liberado, comparar com um operador so faria o span cair fora da
        # lista de ativos — e o valor ficaria no PDF. O nome do metodo e
        # anterior ao segundo operador; o que ele responde e "este trecho sai
        # do documento?", verdade para os dois.
        return self.operador_de(s.entity) in OPERADORES_QUE_REMOVEM

    def spans_ativos(self) -> list[SpanUI]:
        """Os spans cujo valor sai do documento — por tarja ou por token."""
        return [s for s in self.spans.values() if self.sera_tarjado(s)]

    def operador_do_span(self, s: SpanUI) -> str:
        """Qual operador se aplica a **este** trecho, não à classe dele.

        A diferença aparece quando o usuário liga à mão um trecho de uma classe
        que está em ``manter``: a política decidiu "não mexer" e foi vencida
        pela decisão explícita. Ela decidiu o *se*, e perdeu; o *como* não é
        dela, e segue o padrão do documento.

        Sem isto, num documento em modo token esse trecho viraria barra preta
        no meio de um texto de códigos — e o PDF discordaria do texto
        pseudonimizado, que tokeniza tudo o que está ativo.
        """
        op = self.operador_de(s.entity)
        if op in OPERADORES_QUE_REMOVEM:
            return op
        padrao = self.perfil.padrao
        return padrao if padrao in OPERADORES_QUE_REMOVEM else TARJA

    @property
    def alocador(self) -> AlocadorDeToken:
        if self._alocador is None:
            self._alocador = AlocadorDeToken()
        return self._alocador

    def _tokens_do_pdf(self, ativos: list[SpanUI]) -> tuple[dict, int, dict]:
        """Token de cada span cujo operador é `pseudonimo` **e em que ele cabe**.

        Devolve ``(tokens, sem_token_por_sobreposicao, sem_espaco)``, este
        último contando por entidade os trechos que ficaram em tarja porque o
        token não cabia na caixa do valor.

        **Não cabe → tarja, decidido pelo usuário em 2026-09-23.** Antes o
        documento inteiro era reprovado (A4 do `goal-fase-2.md`), e a tela não
        oferecia saída: um documento comum tem CEP e data, e `[CEP-2C81]` ocupa
        48,0pt onde o CEP deixa 43,0pt. O valor sai do documento do mesmo jeito
        — o que se perde é só a legibilidade de "quem é quem" naquele trecho.

        O que o A4 protegia continua protegido: nada é escrito encolhido nem
        por cima do vizinho. E a troca não é silenciosa — a contagem vai para o
        relatório e para a tela, por entidade, e a pré-visualização desenha
        tarja exatamente onde o PDF terá tarja. A medida é
        ``pdf_redactor.medir_token``, a mesma que o redator usa; por isso a
        exceção dele continua lá como trava e não dispara neste caminho.

        Devolve também quantos ficaram sem token por sobreposição. Spans ativos
        podem se sobrepor — basta desligar um detectado, marcar um trecho
        manual dentro dele e religar o detectado. Dois tokens sobrepostos
        escreveriam um por cima do outro na página, e ``resolver_sobreposicoes``
        é a peça determinística que o caminho de texto já usa para essa mesma
        decisão.

        O span que perde a disputa **não fica sem tratamento**: ele continua na
        lista de ativos e recebe tarja. O valor sai do documento de qualquer
        forma; o que ele não recebe é o token. A contagem vai para o relatório
        porque uma substituição a menos que o pedido não pode ser silenciosa.
        """
        alvos = [s for s in ativos if self.operador_do_span(s) == PSEUDONIMO]
        if not alvos:
            return {}, 0, {}

        disjuntos = resolver_sobreposicoes([s.para_span() for s in alvos])
        tokens: dict[tuple[int, int], str] = {}
        sem_espaco: dict[str, int] = {}
        for sp in disjuntos:
            # O token é alocado mesmo quando não vai para o PDF: o texto
            # pseudonimizado usa o mesmo alocador e vai precisar dele.
            token = self.alocador.token_de(sp.entity, self.tm.text[sp.start:sp.end])
            rects = self.tm.rects_for(sp.start, sp.end)
            # Sem caixa o redator registra `spans_sem_retangulo`; aqui não há
            # o que medir, e o token segue para ele tratar.
            if rects and not medir_token(token, rects[0][1])[2]:
                sem_espaco[sp.entity] = sem_espaco.get(sp.entity, 0) + 1
                continue
            tokens[(sp.start, sp.end)] = token
        return tokens, len(alvos) - len(disjuntos), sem_espaco

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

    def alternar_iguais(self, span_id: str, ativo: bool) -> int:
        """O clique individual, aplicado a todo trecho com o **mesmo valor**.

        "Não anonimizar nenhuma igual": o revisor decide sobre um nome, não
        sobre cada aparição dele. Fazer isso pelo navegador — um PATCH por
        trecho — deixaria a regra de o que conta como "igual" morando na tela.
        Aqui ela é uma só: mesmo texto, com o espaçamento colapsado (a mesma
        tolerância de ``_ocorrencias``), de qualquer classe.

        Só propostas do detector. Trecho apontado à mão tem desfazer próprio,
        que é apagar (``remover_span``); desligar deixaria um retângulo que
        ninguém propôs.
        """
        alvo = self.spans[span_id]
        chave = " ".join(alvo.valor.split())
        ids = [
            k for k, s in self.spans.items()
            if s.origem != "usuario" and " ".join(s.valor.split()) == chave
        ]
        for k in ids:
            self.spans[k].ativo = ativo
        if ids:
            self._invalidar()
        logger.info(
            "sessao %s: %d trecho(s) iguais a %s -> ativo=%s",
            self.doc_id, len(ids), span_id, ativo,
        )
        return len(ids)

    def mudar_entidade(self, span_id: str, entidade: str) -> SpanUI:
        """Corrige o rótulo de um trecho detectado.

        Rótulo errado tem consequência: define o prefixo do código (`[P-…]`
        para pessoa, `[ORG-…]` para órgão) e a política que se aplica. O caso
        comum é o de 2026-09-23: o nome de uma empresa detectado como
        ``PERSON`` virou código de pessoa.

        **O efeito visível não muda com o rótulo.** Se o trecho ia sair do
        documento e a classe nova está em ``manter``, ele continua saindo — a
        decisão vira explícita no trecho. Corrigir um rótulo não pode ser um
        jeito escondido de desligar uma tarja; para isso existe "não
        anonimizar".
        """
        if entidade not in config.ENTIDADES_ATIVAS:
            raise ValueError(f"entidade desconhecida: {entidade}")
        s = self.spans[span_id]
        if s.origem == "usuario":
            raise ValueError("trecho apontado à mão não tem classe detectada")
        antes = self.sera_tarjado(s)
        s.entity = entidade
        if self.sera_tarjado(s) != antes:
            s.ativo = antes
        self._invalidar()
        logger.info("sessao %s: span %s -> %s", self.doc_id, span_id, entidade)
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

    def alternar_manuais(self, ativo: bool) -> int:
        """Liga ou desliga de uma vez todos os trechos apontados à mão.

        Existe porque a caixa de `MANUAL` na lista não podia funcionar pelo
        caminho do perfil: `MANUAL` não é entidade de política — é origem —, e
        `validar_perfil` recusa regra para ela, com razão. A caixa governa o
        padrão de uma classe detectada, e trecho apontado à mão não tem classe.

        Então o lote usa o mesmo caminho do clique individual: mexe em
        ``ativo``, não na política. A regra de que a decisão explícita vence o
        padrão da classe continua inteira — desligar em lote também é decisão
        explícita.

        **Desligar não é apagar.** ``remover_manuais`` remove os trechos da
        proposta; aqui o retângulo continua na tela, tracejado, e o revisor
        segue enxergando o que apontou e resolveu não usar.
        """
        ids = [k for k, s in self.spans.items() if s.origem == "usuario"]
        for k in ids:
            self.spans[k].ativo = ativo
        if ids:
            self._invalidar()
        logger.info(
            "sessao %s: %d trecho(s) manuais -> ativo=%s", self.doc_id, len(ids), ativo
        )
        return len(ids)

    def remover_manuais(self) -> int:
        """Apaga todos os trechos adicionados à mão. O desfazer do campo."""
        ids = [k for k, s in self.spans.items() if s.origem == "usuario"]
        for k in ids:
            del self.spans[k]
        if ids:
            self._invalidar()
        logger.info("sessao %s: %d spans manuais removidos", self.doc_id, len(ids))
        return len(ids)

    def alternar_entidade(self, entidade: str, ligar: bool) -> None:
        """A caixa da classe no inventário: liga ou desliga a classe inteira.

        Existe porque ``aplicar_perfil`` só zera as exceções das classes cuja
        regra **mudou** — e desmarcar uma classe que já está em ``manter`` não
        muda regra nenhuma. Relatado em 2026-09-23: o revisor ligou à mão um
        trecho de ``LOCATION`` (classe em ``manter``), desmarcou a caixa, e
        nada aconteceu — a exceção sobrevivia, o trecho continuava ligado, e a
        caixa continuava marcada porque conta os trechos ligados.

        Aqui a intenção é explícita e não depende de diferença de regra: a
        caixa define o padrão da classe e **sempre** zera as exceções dela.
        Trecho apontado à mão fica de fora — ele não tem classe, e tem a sua
        própria caixa (``alternar_manuais``).
        """
        if entidade not in config.ENTIDADES_ATIVAS:
            raise ValueError(f"entidade desconhecida: {entidade}")

        atual = self.perfil.operador_de(entidade)
        if not ligar:
            op = MANTER
        elif atual in OPERADORES_QUE_REMOVEM:
            op = atual
        else:
            padrao = self.perfil.padrao
            op = padrao if padrao in OPERADORES_QUE_REMOVEM else TARJA

        novo = PerfilPolitica.from_dict(
            {**self.perfil.to_dict(), "nome": "personalizado",
             "regras": {**self.perfil.regras, entidade: op}}
        )
        validar_perfil(novo, config.ENTIDADES_ATIVAS)

        for s in self.spans.values():
            if s.entity == entidade and s.origem != "usuario":
                s.ativo = None
        self.perfil = novo
        self._invalidar()
        logger.info("sessao %s: classe %s -> %s", self.doc_id, entidade, op)

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
        self.versao += 1
        self._previa = None
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
    def _redigir_e_verificar(self, ativos: list[SpanUI], saida: Path) -> dict:
        """Redige em ``saida``, verifica e disseca. Não decide nada sobre o
        arquivo: quem chama decide se ele fica, e quem pode alcançá-lo.

        Existe para que a aprovação e a pré-verificação rodem **o mesmo**
        código. Uma pré-verificação com heurística própria mais barata
        reintroduziria o defeito que ela veio resolver: a tela dizendo "1
        ocorrência tarjada" para um termo manual enquanto a verificação de
        verdade acha 2. A busca do termo é literal; o ``verify`` procura também
        variantes (só dígitos, sem espaço) e em mais de um extrator — qualquer
        diferença entre os dois caminhos vira surpresa no fim.
        """
        tokens, sem_token, sem_espaco = self._tokens_do_pdf(ativos)

        doc = fitz.open(str(self.original))
        try:
            tm = build_text_map(doc)
            # Token que não cabe já saiu de `tokens` e vai em tarja, contado em
            # `sem_espaco` — decidido **antes**, com a mesma medida do redator,
            # e não capturando a exceção dele. Por isso
            # `PseudonimoImpossivelNoPDF` continua subindo sem captura: se ela
            # disparar aqui, as duas medições discordaram, e isso é defeito, não
            # documento difícil. `app.py` a traduz em 422.
            res = redact_document(
                doc, tm, [s.para_span() for s in ativos], saida, tokens=tokens
            )
        finally:
            doc.close()

        rel = verify(saida, res.valores, tokens=res.tokens_escritos)

        # A dissecação precisa acontecer **antes** de apagar o arquivo: ela
        # reabre o PDF reprovado para descobrir se cada valor ainda aparece no
        # texto extraído. Sem isso, a tela só consegue dizer "reprovou", que é
        # exatamente a mensagem que não deixa ninguém agir.
        ocorrencias = self._dissecar(rel.leaks, saida)

        return {
            "spans_redigidos": res.spans_redigidos,
            "retangulos": res.retangulos,
            "tokens_escritos": len(res.tokens_escritos),
            "spans_sem_token_por_sobreposicao": sem_token,
            # Entidade -> trechos que pediam token e saíram em tarja porque o
            # token não cabia. Entidade e contagem, nunca o valor.
            "tarja_por_falta_de_espaco": sem_espaco,
            "spans_sem_retangulo": len(res.spans_sem_retangulo),
            "saneamento": res.saneamento,
            "verificacao_ok": rel.ok,
            "vetores": rel.vetores_executados,
            "valores_checados": rel.valores_checados,
            "vazamentos": sorted({leak.vetor for leak in rel.leaks}),
            "total_vazamentos": len(rel.leaks),
            "ocorrencias": ocorrencias,
        }

    def aprovar(self) -> dict:
        """Redige de verdade, verifica de verdade, e só então libera.

        A ordem importa: se ``verify`` reprovar, o arquivo redigido é apagado.
        Um PDF que falhou a verificação não pode ficar em disco esperando
        alguém baixá-lo por outro caminho.
        """
        ativos = self.spans_ativos()
        saida = self.pasta / "redigido.pdf"
        self.relatorio = self._redigir_e_verificar(ativos, saida)
        ok = self.relatorio["verificacao_ok"]
        ocorrencias = self.relatorio["ocorrencias"]

        if ok:
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
                self.relatorio["total_vazamentos"],
                "; ".join(
                    f"{o['vetor']}:{o['objeto']}"
                    + (" (visivel no texto)" if o["visivel_no_texto"] else "")
                    for o in ocorrencias
                ),
            )

        logger.info(
            "sessao %s: aprovacao %s, %d spans",
            self.doc_id,
            "ok" if ok else "REPROVADA",
            self.relatorio["spans_redigidos"],
        )
        return self.relatorio

    def preverificar(self) -> dict:
        """A verificação da aprovação, rodada **antes** de o usuário aprovar.

        Sem isto a verificação só acontecia no clique final e reprovava no pior
        momento: o usuário apontava um termo, a tela dizia "1 ocorrência
        tarjada", e só na geração descobria que sobravam 2. Agora a tela roda
        isto a cada edição e mostra a pendência enquanto ele ainda está
        revisando.

        É ``_redigir_e_verificar`` inteiro — os mesmos vetores, a mesma busca
        por variante —, e não uma aproximação: a contagem que a tela mostra
        tem de ser a que a aprovação vai encontrar.

        **O arquivo nunca é entregável.** Nasce com nome sorteado na pasta da
        sessão, nenhuma rota o alcança, e é apagado antes de retornar, passe ou
        não. Esta função não toca ``aprovada``, ``redigido`` nem
        ``relatorio``: aprovar continua sendo um ato explícito, que refaz tudo
        do zero. O resultado é guardado por ``versao`` e cai a cada edição.
        """
        versao = self.versao
        if self._previa and self._previa[0] == versao:
            return self._previa[1]

        # `list(...)` antes de iterar: a pré-verificação roda enquanto o
        # usuário segue editando, e iterar o dict vivo pode encontrá-lo
        # mudando de tamanho no meio.
        ativos = [s for s in list(self.spans.values()) if self.sera_tarjado(s)]
        base = {"versao": versao, "valores_ativos": len(ativos)}
        if not ativos:
            resultado = {**base, "ok": True, "total_vazamentos": 0,
                         "vazamentos": [], "ocorrencias": [], "vetores": []}
            self._previa = (versao, resultado)
            return resultado

        saida = self.pasta / f"previa-{secrets.token_hex(6)}.pdf"
        try:
            rel = self._redigir_e_verificar(ativos, saida)
        except PseudonimoImpossivelNoPDF as exc:
            # A mesma trava da aprovação: as duas medidas de largura
            # discordaram. A mensagem carrega token e larguras, não o valor.
            return {**base, "ok": False, "erro": str(exc), "total_vazamentos": 0,
                    "vazamentos": [], "ocorrencias": [], "vetores": []}
        finally:
            saida.unlink(missing_ok=True)

        resultado = {
            **base,
            "ok": rel["verificacao_ok"],
            "total_vazamentos": rel["total_vazamentos"],
            "vazamentos": rel["vazamentos"],
            "vetores": rel["vetores"],
            "valores_checados": rel["valores_checados"],
            "ocorrencias": rel["ocorrencias"],
            "tarja_por_falta_de_espaco": rel["tarja_por_falta_de_espaco"],
        }
        # Só guarda se ninguém editou enquanto rodava; senão o resultado já
        # nasceu velho e a próxima chamada precisa refazer.
        if self.versao == versao:
            self._previa = (versao, resultado)
        logger.info(
            "sessao %s: pre-verificacao v%d %s, %d ocorrencia(s)",
            self.doc_id,
            versao,
            "ok" if resultado["ok"] else "PENDENTE",
            resultado["total_vazamentos"],
        )
        return resultado

    def contar_termo(self, termo: str) -> dict:
        """Quantas vezes ``termo`` aparece, pelas duas réguas, **sem** criar nada.

        Duas contagens porque elas respondem perguntas diferentes, e a
        diferença entre elas é exatamente o que a tela precisa mostrar antes
        do clique:

        * ``novas`` — quantas ``adicionar_por_termo`` vai marcar: ocorrências
          literais (tolerando espaçamento) ainda não cobertas e com região
          visível na página.
        * ``no_texto`` — quantas a verificação vai procurar: a busca por
          variante do ``verify`` (só dígitos, sem espaço) sobre o texto de
          cada página. Uma data ``18/02/2026`` casa também ``18.02.2026``.

        Quando ``no_texto`` passa de ``novas + ja_cobertas``, marcar o termo
        não basta, e a tela diz isso antes — em vez de a verificação dizer no
        fim.
        """
        termo = termo.strip()
        if len(termo) < 2:
            raise ValueError("termo curto demais")

        ativos = [(s.start, s.end) for s in self.spans_ativos()]
        novas = ja_cobertas = sem_regiao = 0
        paginas: set[int] = set()
        for ini, fim in self._ocorrencias(termo, self.tm.text):
            if any(ini < b and a < fim for a, b in ativos):
                ja_cobertas += 1
                continue
            rects = self.tm.rects_for(ini, fim)
            if not rects:
                sem_regiao += 1
                continue
            novas += 1
            paginas.update(pno + 1 for pno, _ in rects)

        return {
            "novas": novas,
            "ja_cobertas": ja_cobertas,
            "sem_regiao": sem_regiao,
            "paginas": sorted(paginas),
            "no_texto": sum(self._contar_no_original(termo).values()),
        }

    def _contar_no_original(self, valor: str) -> dict[int, int]:
        """Página (1-based) -> ocorrências de ``valor`` no PDF **original**,
        com a busca por variante da verificação. Ver ``_dissecar``."""
        doc = fitz.open(str(self.original))
        try:
            textos = [doc.load_page(i).get_text() for i in range(doc.page_count)]
        finally:
            doc.close()
        return _contar_por_pagina(_preparar_paginas(textos), valor)

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

        # O alocador da sessão, não um novo: é o que faz o mesmo valor
        # receber o mesmo token no texto e no PDF.
        res = pseudonimizar_texto(self.tm.text, disjuntos, self.alocador)
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

    def conferir_antes_do_envio(self, detectar) -> list[dict]:
        """Roda a detecção **de novo**, sobre o texto já pseudonimizado.

        Exigência do `goal-fase-3.md` §2, opção (b): antes de qualquer envio a
        um serviço externo, procurar no texto de saída o que deveria ter saído
        dele. É barato e pega o caso "sobrou uma ocorrência" — que é
        exatamente o defeito que o dublê de teste reproduziu e que a detecção
        real também comete, medida em cerca de 1 documento a cada 50.

        O limiar é mais baixo de propósito. Na detecção normal, 0.35 descarta
        padrão numérico cru sem âncora, porque falso positivo custa trabalho
        de revisão. Aqui a conta inverte: o custo de um falso positivo é
        recusar um envio que era seguro, e o custo de um falso negativo é
        mandar um nome real para um terceiro, sem desfazer. Vale errar para o
        lado de recusar.

        ``detectar`` recebe ``(texto, limiar)`` e devolve spans — injetado em
        vez de importado para esta regra ser testável sem carregar 1 GB de
        pesos.

        Devolve **entidade e posição, nunca o valor.** Um achado aqui é sinal
        de PII que sobreviveu; copiá-lo para a resposta da API ou para o log
        criaria uma segunda cópia do dado exatamente no momento em que
        descobrimos que ele não deveria estar em lugar nenhum.
        """
        if not self.pode_baixar_texto:
            raise RuntimeError("texto pseudonimizado ausente ou reprovado")

        texto = self.texto_pseudo.read_text(encoding="utf-8")
        achados = []
        for span in detectar(texto, LIMIAR_PRE_ENVIO):
            # Só conta o que a política mandava substituir. `ORGANIZATION`
            # nasce em `manter` porque a LAI cobra que o órgão do ato continue
            # legível — encontrá-lo aqui é o sistema funcionando, não falha.
            if self.operador_de(span.entity) not in OPERADORES_QUE_REMOVEM:
                continue
            achados.append(
                {"entidade": span.entity, "inicio": span.start, "fim": span.end}
            )
        return achados

    def registrar_envio(self, destino: str, resultado: dict) -> dict:
        """Trilha de auditoria do que saiu da máquina.

        Sem isto o envio externo é um caminho sem dono: ninguém consegue dizer
        depois o que foi mandado, para onde e quando. Registra metadado —
        contagem, modelo, duração — e **nada** do conteúdo enviado ou
        recebido.
        """
        registro = {
            "quando": time.time(),
            "destino": destino,
            "modelo": resultado.get("modelo"),
            "caracteres_enviados": resultado.get("caracteres_enviados"),
            "tokens_prompt": resultado.get("tokens_prompt"),
            "tokens_saida": resultado.get("tokens_saida"),
            "duracao_s": resultado.get("duracao_s"),
        }
        self.envios.append(registro)
        logger.info(
            "sessao %s: enviado a %s (%s), %s caracteres",
            self.doc_id,
            destino,
            registro["modelo"],
            registro["caracteres_enviados"],
        )
        return registro

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

        # Por página, e não o texto inteiro concatenado: "1 ocorrência legível"
        # sem dizer onde deixava o usuário caçando o valor num documento de
        # dezenas de páginas. O caso típico é o mesmo valor tarjado na página
        # 1 e não reconhecido na 7 — o detector classificou o contexto de outro
        # jeito —, e a página é exatamente o que falta para achá-lo.
        textos_pagina: list[str] = []
        try:
            d = fitz.open(str(caminho_redigido))
            try:
                textos_pagina = [
                    d.load_page(i).get_text() for i in range(d.page_count)
                ]
            finally:
                d.close()
        except Exception:  # noqa: BLE001
            logger.exception("sessao %s: falha ao reabrir o PDF reprovado", self.doc_id)

        # A mesma busca por variantes que o `verify` usa. Comparar literal aqui
        # era um defeito com consequência direta: medido em 2026-09-05, um CNPJ
        # tarjado numa passagem sobrevivia noutra escrito só com dígitos
        # (`Chave PIX: 61904327000118`). O `verify` o encontrava pela variante
        # numérica e reprovava — certo —, mas a dissecação procurava a forma
        # literal com pontuação, não achava, e classificava como "só na
        # estrutura do PDF".
        #
        # A classificação errada manda o usuário para o caminho oposto do
        # conserto: ela diz "defeito do redator, você não conserta sozinho",
        # quando a verdade era "outra ocorrência, tarje todas em um clique".
        paginas_norm = _preparar_paginas(textos_pagina)

        por_valor: dict[str, dict] = {}
        for leak in leaks:
            por_pagina = _contar_por_pagina(paginas_norm, leak.valor)
            ocorrencias = sum(por_pagina.values())
            item = por_valor.setdefault(
                leak.valor,
                {
                    "valor": leak.valor,
                    "vetor": leak.vetor,
                    "vetores": [],
                    "objeto": "",
                    "visivel_no_texto": ocorrencias > 0,
                    "ocorrencias_no_texto": ocorrencias,
                    "paginas": sorted(por_pagina),
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
        # O mesmo plano que `aprovar` vai usar: a pré-visualização mostra
        # token onde o PDF terá token, e tarja onde ele não cabe.
        tokens, _, _ = self._tokens_do_pdf(self.spans_ativos())
        return {
            "doc_id": self.doc_id,
            "nome_arquivo": self.nome_arquivo,
            "paginas": self.paginas,
            "spans": [self.span_dict(s, tokens) for s in self.spans.values()],
            "inventario": self.inventario(),
            "perfil": self.perfil.to_dict(),
            "entidades_ativas": list(config.ENTIDADES_ATIVAS),
            "aprovada": self.aprovada,
            "pode_baixar": self.pode_baixar,
            "relatorio": self.relatorio,
            "pode_baixar_texto": self.pode_baixar_texto,
            "relatorio_texto": self.relatorio_texto,
            "envios": self.envios,
            "versao": self.versao,
            "caracteristicas": self.caracteristicas,
        }

    def _fragmento(self, s: SpanUI) -> bool:
        t = self.tm.text
        corta_inicio = 0 < s.start < len(t) and t[s.start - 1].isalnum() and t[s.start].isalnum()
        corta_fim = 0 < s.end < len(t) and t[s.end - 1].isalnum() and t[s.end].isalnum()
        return corta_inicio or corta_fim

    def span_dict(self, s: SpanUI, tokens: dict | None = None) -> dict:
        # Token que este trecho terá **no PDF**. Nulo quando sai em tarja —
        # por política ou porque o token não cabe. Token não é dado pessoal:
        # é sorteado, e mostrá-lo é o que deixa o revisor ver antes o que vai
        # receber.
        token = (tokens or {}).get((s.start, s.end))
        pediu_token = self.sera_tarjado(s) and self.operador_do_span(s) == PSEUDONIMO
        return {
            "id": s.id,
            "entity": s.entity,
            "score": round(s.score, 3),
            "valor": s.valor,
            "origem": s.origem,
            "ativo": s.ativo,
            "nota": s.nota,
            "sera_tarjado": self.sera_tarjado(s),
            # Qual dos dois operadores se aplica a este trecho. A tela precisa
            # distinguir "vai sumir" de "vira token" — são promessas
            # diferentes para quem assina embaixo.
            #
            # `operador_do_span` e não `operador_de`: para um trecho ligado à
            # mão numa classe em `manter`, o segundo responderia "manter", que
            # é justamente o que não vai acontecer com ele.
            "operador": self.operador_do_span(s),
            "token": token,
            # Pediu token e não vai receber. Quase sempre é falta de espaço;
            # o caso raro é ter perdido a disputa de sobreposição para outro
            # trecho — nos dois o valor sai, em tarja.
            "sem_token": bool(pediu_token and token is None),
            # Começa ou termina no meio de uma palavra ("RO" dentro de
            # "RODOVIÁRIA"). Fato sobre o texto, não decisão: a tela decide o
            # que fazer com ele, e nunca esconde um trecho que vai sair do PDF.
            "fragmento": self._fragmento(s),
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
            caracteristicas = _caracteristicas(doc)
        finally:
            doc.close()

        sessao = Sessao(
            doc_id=doc_id,
            pasta=pasta,
            original=original,
            nome_arquivo=nome_arquivo,
            tm=tm,
            paginas=paginas,
            caracteristicas=caracteristicas,
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


def _caracteristicas(doc: fitz.Document) -> dict:
    """O que a redação vai tirar do arquivo além dos dados marcados.

    A lista de avisos era fixa e ficava num acordeão no rodapé — "assinatura
    digital é invalidada" aparecia para todo documento, inclusive os que não
    têm assinatura, e ninguém a lia. Com isto a tela avisa, na hora de
    exportar, só o que se aplica a este arquivo.

    ``get_sigflags``: -1 sem formulário, 0 formulário sem campo de assinatura,
    1 ou mais há campo de assinatura (3 = assinado). Campo vazio também conta:
    o aviso é sobre o que a remoção de texto destrói, e um campo preparado
    para assinatura é parte do fluxo que o cliente pode esperar preservado.
    """
    try:
        assinatura = doc.get_sigflags() > 0
    except Exception:  # noqa: BLE001 — PDF estranho não pode derrubar o upload
        assinatura = False
    links = 0
    for pagina in doc:
        links += len(pagina.get_links())
    return {
        "assinatura": assinatura,
        "links": links,
        "marcadores": len(doc.get_toc(simple=True)),
        "anexos": doc.embfile_count(),
    }


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
