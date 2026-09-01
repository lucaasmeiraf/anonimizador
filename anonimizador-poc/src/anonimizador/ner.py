"""Camada de NER local — as três configurações comparadas na Fase 0.

1. ``spacy``            — ``pt_core_news_lg``, via o próprio NlpEngine do Presidio.
2. ``bert-lenerbr``     — BERT PT-BR ajustado em LeNER-Br (jurídico).
3. ``bertimbau-harem``  — BERTimbau-large ajustado em HAREM selective (geral).

O spaCy é carregado em **todas** as configurações, mesmo quando o NER vem de um
transformer: o Presidio usa os lemas do spaCy para o enriquecimento por
contexto (as palavras-âncora dos reconhecedores estruturados). Quando a
configuração ativa é um transformer, o NER do próprio spaCy é desligado para
não competir.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

from presidio_analyzer import EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngine, NlpEngineProvider

from . import config

logger = logging.getLogger(__name__)

# Rótulos do spaCy PT (treinado em WikiNER) para o vocabulário do Presidio.
_SPACY_MAP = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "ORG": "ORGANIZATION",
    "LOC": "LOCATION",
    "GPE": "LOCATION",
}

ENTIDADES_NER = ("PERSON", "ORGANIZATION", "LOCATION", "DATE_TIME")


def build_nlp_engine(usar_ner_do_spacy: bool) -> NlpEngine:
    """Monta o NlpEngine em PT.

    ``usar_ner_do_spacy=False`` mantém a tokenização e a lematização (de que o
    enriquecedor de contexto depende) mas descarta as entidades do spaCy.
    """
    labels_to_ignore = [] if usar_ner_do_spacy else list(_SPACY_MAP) + ["MISC"]

    conf = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": config.LANG, "model_name": "pt_core_news_lg"}],
        "ner_model_configuration": {
            "model_to_presidio_entity_mapping": _SPACY_MAP,
            "low_score_entity_names": [],
            "labels_to_ignore": labels_to_ignore,
        },
    }
    return NlpEngineProvider(nlp_configuration=conf).create_engine()


class TransformersNerRecognizer(EntityRecognizer):
    """Encapsula um pipeline de token-classification do Hugging Face.

    Duas decisões que importam:

    * **Janelamento próprio.** Os checkpoints são BERT, com teto de 512
      tokens. O pipeline de token-classification do HF não faz janela
      deslizante sozinho — ele trunca. Truncar significa que a partir da
      página 2 nada é detectado, o que num PoC de redação seria um vazamento
      silencioso. Fatiamos o texto em janelas com sobreposição, corrigimos os
      offsets e desduplicamos.
    * **Carga preguiçosa.** O modelo só é lido do disco no primeiro
      ``analyze``, para que instanciar o pipeline em testes não custe segundos.
    """

    def __init__(
        self,
        model_id: str,
        label_map: dict[str, str],
        supported_entities: Iterable[str] = ENTIDADES_NER,
        supported_language: str = "pt",
        device: str = "cpu",
        janela: int = 1200,
        sobreposicao: int = 200,
        score_minimo: float = 0.5,
        teto_tokens: int = 460,
        janela_minima: int = 120,
    ) -> None:
        self.model_id = model_id
        self.label_map = label_map
        self.device = device
        self.janela = janela
        self.sobreposicao = sobreposicao
        self.score_minimo = score_minimo
        # Teto de tokens por janela. O BERT aceita 512 posições contando os
        # tokens especiais; 460 deixa folga sem encolher a janela útil.
        self.teto_tokens = teto_tokens
        # Piso da subdivisão: abaixo disto paramos de dividir. Uma janela
        # minúscula custa uma inferência inteira e o contexto que sobra é
        # pequeno demais para o NER decidir bem.
        self.janela_minima = janela_minima
        self._pipe = None
        super().__init__(
            supported_entities=list(supported_entities),
            supported_language=supported_language,
            name=f"TransformersNer[{model_id}]",
        )

    # -- carga -------------------------------------------------------------
    def load(self) -> None:  # chamado pelo Presidio; a carga real é preguiçosa
        return None

    def _pipeline(self):
        if self._pipe is None:
            from transformers import (
                AutoModelForTokenClassification,
                AutoTokenizer,
                pipeline,
            )

            logger.info("carregando NER %s em %s", self.model_id, self.device)
            tok = AutoTokenizer.from_pretrained(self.model_id)
            mdl = AutoModelForTokenClassification.from_pretrained(self.model_id)
            self._pipe = pipeline(
                "token-classification",
                model=mdl,
                tokenizer=tok,
                aggregation_strategy="simple",
                device=0 if self.device.startswith("cuda") else -1,
            )
        return self._pipe

    # -- janelamento -------------------------------------------------------
    def _janelas(self, text: str) -> list[tuple[int, int]]:
        """Fatia em janelas com sobreposição, cortando em espaço quando dá.

        A sobreposição garante que uma entidade na fronteira de uma janela
        apareça inteira na janela seguinte.

        O corte é por **caractere**, e o teto do modelo é por **token**. Os dois
        não são proporcionais, e por isso o resultado passa por
        ``_caber_no_teto`` antes de ir para o modelo — ver o que aquilo conserta.
        """
        if len(text) <= self.janela:
            janelas = [(0, len(text))]
        else:
            janelas, ini = [], 0
            passo = self.janela - self.sobreposicao
            while ini < len(text):
                fim = min(ini + self.janela, len(text))
                if fim < len(text):
                    corte = text.rfind(" ", ini + passo // 2, fim)
                    if corte > ini:
                        fim = corte
                janelas.append((ini, fim))
                if fim >= len(text):
                    break
                ini = max(ini + 1, fim - self.sobreposicao)

        return self._caber_no_teto(text, janelas)

    # -- teto de tokens ----------------------------------------------------
    def _conta_tokens(self, trecho: str) -> int:
        tok = self._pipeline().tokenizer
        return len(tok(trecho, add_special_tokens=True, truncation=False)["input_ids"])

    def _caber_no_teto(
        self, text: str, janelas: list[tuple[int, int]]
    ) -> list[tuple[int, int]]:
        """Subdivide as janelas que estouram o teto de tokens do modelo.

        **O defeito que isto conserta.** A janela é medida em caracteres (1200)
        e o modelo tem teto em tokens (512). Os dois não são proporcionais:
        prosa comum cabe com folga — 1200 caracteres dão ~256 tokens —, mas
        texto denso em identificadores dá **648**. Um número como
        ``0000000-00.2026.8.26.0100`` vira uma dúzia de tokens; uma linha de
        tabela com processo, CPF, RG, telefone e CEP explode a conta.

        O que acontecia então: o ``pipe`` levantava ``RuntimeError`` (``tensor
        522 != 512``), o ``except`` do ``analyze`` engolia a janela inteira, e a
        detecção seguia **sem nenhum nome daquele trecho**. Medido: um bloco de
        1.294 caracteres com um nome no meio produzia 60 spans de
        identificadores e **zero** ``PERSON``. Nenhum erro chegava à tela.

        O usuário veria os CPFs tarjados e concluiria, com toda a razão
        aparente, que o documento não tem nomes. É o pior modo de falha deste
        sistema — falso silêncio — e aparecia justamente onde ele mais dói: em
        tabela de pessoas, que é o documento que mais carrega dado pessoal.

        A correção é por subdivisão, e não por reescrever o janelamento em
        tokens, de propósito: uma janela que já cabe sai daqui **idêntica**.
        Documento que funciona hoje produz exatamente as mesmas janelas, os
        mesmos spans e os mesmos números de avaliação. Só o caminho quebrado
        muda.
        """
        saida: list[tuple[int, int]] = []
        for ini, fim in janelas:
            saida.extend(self._dividir(text, ini, fim))
        return saida

    def _dividir(self, text: str, ini: int, fim: int) -> list[tuple[int, int]]:
        if fim - ini <= self.janela_minima:
            return [(ini, fim)]
        if self._conta_tokens(text[ini:fim]) <= self.teto_tokens:
            return [(ini, fim)]

        # Corta perto do meio, preferindo um espaço: partir no meio de um
        # identificador criaria dois fragmentos que não são nada.
        meio = (ini + fim) // 2
        corte = text.rfind(" ", ini + (fim - ini) // 4, meio + (fim - ini) // 4)
        if corte <= ini or corte >= fim:
            corte = meio

        # A sobreposição também vale aqui: sem ela, um nome exatamente sobre o
        # corte desapareceria — que é o mesmo defeito, em escala menor.
        recuo = min(self.sobreposicao, (fim - corte) // 2, (corte - ini) // 2)
        esquerda = self._dividir(text, ini, corte)
        direita = self._dividir(text, max(ini, corte - recuo), fim)
        return esquerda + direita

    # -- análise -----------------------------------------------------------
    def analyze(
        self,
        text: str,
        entities: list[str],
        nlp_artifacts=None,
    ) -> list[RecognizerResult]:
        if not text.strip():
            return []

        pipe = self._pipeline()
        brutos: list[tuple[int, int, str, float]] = []

        for ini, fim in self._janelas(text):
            trecho = text[ini:fim]
            try:
                saida = pipe(trecho)
            except Exception:  # noqa: BLE001 - uma janela ruim não derruba o doc
                logger.exception("falha do NER na janela %d:%d", ini, fim)
                continue

            for ent in saida:
                rotulo = self.label_map.get(ent["entity_group"])
                if not rotulo or (entities and rotulo not in entities):
                    continue
                score = float(ent["score"])
                if score < self.score_minimo:
                    continue
                s, e = self._aparar(text, ini + ent["start"], ini + ent["end"])
                if e > s:
                    brutos.append((s, e, rotulo, score))

        return [
            RecognizerResult(entity_type=r, start=s, end=e, score=sc,
                             analysis_explanation=None)
            for s, e, r, sc in self._desduplicar(brutos)
        ]

    @staticmethod
    def _aparar(text: str, start: int, end: int) -> tuple[int, int]:
        """Remove espaço e pontuação nas bordas do span.

        A estratégia de agregação ``simple`` frequentemente encosta um espaço
        ou uma vírgula no span. Isso não muda o F1 relaxado, mas destrói o F1
        estrito — e, na redação, engorda a tarja sem necessidade.
        """
        lixo = " \t\n\r.,;:()[]—-–"
        while start < end and text[start] in lixo:
            start += 1
        while end > start and text[end - 1] in lixo:
            end -= 1
        return start, end

    @staticmethod
    def _desduplicar(spans: list[tuple[int, int, str, float]]):
        """Funde spans idênticos ou contidos vindos de janelas vizinhas."""
        if not spans:
            return []
        spans = sorted(spans, key=lambda x: (x[0], -(x[1] - x[0]), -x[3]))
        saida: list[tuple[int, int, str, float]] = []
        for s, e, r, sc in spans:
            absorvido = False
            for i, (s2, e2, r2, sc2) in enumerate(saida):
                if r == r2 and s >= s2 and e <= e2:
                    saida[i] = (s2, e2, r2, max(sc, sc2))
                    absorvido = True
                    break
            if not absorvido:
                saida.append((s, e, r, sc))
        return saida


def build_ner_recognizer(cfg: config.NerConfig, device: Optional[str] = None):
    """Devolve o reconhecedor de NER da configuração, ou ``None`` para spaCy.

    No caso do spaCy o NER já vem embutido no NlpEngine e é exposto pelo
    ``SpacyRecognizer`` padrão do Presidio — não há reconhecedor extra a criar.
    """
    if cfg.tipo == "spacy":
        return None
    if cfg.tipo != "transformers":
        raise ValueError(f"tipo de NER desconhecido: {cfg.tipo}")
    return TransformersNerRecognizer(
        model_id=cfg.model_id,
        label_map=cfg.label_map,
        device=device or config.DEVICE,
    )
