"""Geração do corpus sintético com gabarito exato.

O ponto delicado de qualquer avaliação de detecção de PII é o gabarito. Anotar
PDFs prontos à mão é lento e impreciso; o caminho correto é o inverso — gerar o
texto **junto com** os rótulos e só então renderizar o PDF. O gabarito nasce
exato, por construção, e não por anotação.

Duas disciplinas que o gerador respeita e das quais depende a validade dos
números:

* **Nenhum valor de PII é quebrado entre linhas.** A quebra é feita entre
  segmentos, nunca dentro de um. Se um valor atravessasse a quebra, o
  reconhecedor não teria como acertá-lo e o eval mediria o gerador, não o
  detector.
* **Semente fixa.** O corpus inteiro é reprodutível: dois runs geram os mesmos
  50 documentos, então uma variação de métrica é sempre variação do código.

Nenhum número aqui tem vínculo com pessoa real. Os identificadores têm
checksum válido — sem isso não exercitariam os reconhecedores — mas são
construídos por gerador pseudoaleatório semeado.
"""

from __future__ import annotations

import argparse
import json
import random
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
from faker import Faker

from anonimizador import fakes

# --------------------------------------------------------------------------
# Estrutura
# --------------------------------------------------------------------------
Segmento = tuple[str, str | None]  # (texto, rótulo ou None)

LARGURA_LINHA = 92
# Largura util de cada coluna na secao de duas colunas.
LARGURA_COLUNA = 42
# Separador entre celulas de uma mesma linha de tabela no texto-fonte.
SEPARADOR_CELULA = "   "
NOVA_LINHA = "\n"
MARGEM_X = 56
MARGEM_Y = 64
ALTURA_LINHA = 13
FONTE = "helv"
CORPO = 9


def _normalizar_segmentos(item: object) -> list[Segmento]:
    """Aceita "texto", ("texto", "ROTULO") ou uma lista dos dois e devolve
    sempre uma lista de segmentos.

    Uma celula ou linha de coluna pode misturar rotulado e nao rotulado
    (``["CPF ", (valor, "CPF")]``), entao a normalizacao precisa descer ate o
    segmento — normalizar so o nivel de cima deixava a string crua passar.
    """
    if isinstance(item, str):
        return [(item, None)]
    if isinstance(item, tuple):
        return [item]  # type: ignore[list-item]
    return [(x, None) if isinstance(x, str) else x for x in item]  # type: ignore[union-attr]


@dataclass
class Bloco:
    """Unidade de layout. O tipo decide como o bloco e escrito no PDF **e** em
    que ordem ele entra no texto-fonte.

    Tres tipos, escolhidos porque sao os que exercitam `layout.py`:

    * ``corpo``   - paragrafos de largura cheia. O caso facil, ja coberto.
    * ``tabela``  - varias celulas na mesma linha visual, em x distintos. Forca
      `rects_for` a agrupar por linha sem transformar a linha inteira num unico
      retangulo, o que apagaria o texto entre as celulas.
    * ``colunas`` - duas colunas independentes na mesma pagina.
    """

    tipo: str = "corpo"
    linhas: list[list[Segmento]] = field(default_factory=list)
    celulas: list[list[list[Segmento]]] = field(default_factory=list)   # [linha][coluna]
    colunas: list[list[list[Segmento]]] = field(default_factory=list)   # [coluna][linha]
    x: list[float] = field(default_factory=list)


@dataclass
class Documento:
    doc_id: str
    genero: str
    blocos: list[Bloco] = field(default_factory=list)

    def _corpo(self) -> Bloco:
        if not self.blocos or self.blocos[-1].tipo != "corpo":
            self.blocos.append(Bloco("corpo"))
        return self.blocos[-1]

    def add(self, *segmentos: Segmento | str) -> None:
        linha: list[Segmento] = []
        for s in segmentos:
            linha.append((s, None) if isinstance(s, str) else s)
        self._corpo().linhas.append(linha)

    def blank(self) -> None:
        self._corpo().linhas.append([])

    def add_tabela(self, x: list[float], linhas: list[list]) -> None:
        norm = [[_normalizar_segmentos(c) for c in linha] for linha in linhas]
        self.blocos.append(Bloco("tabela", celulas=norm, x=list(x)))

    def add_colunas(self, x: list[float], colunas: list[list]) -> None:
        norm = [[_normalizar_segmentos(ln) for ln in coluna] for coluna in colunas]
        self.blocos.append(Bloco("colunas", colunas=norm, x=list(x)))

    @property
    def linhas(self) -> list[list[Segmento]]:
        """Compatibilidade: so as linhas de corpo, para quem quer o fluxo."""
        return [ln for b in self.blocos if b.tipo == "corpo" for ln in b.linhas]


def montar_texto(doc: Documento) -> tuple[str, list[dict]]:
    """Concatena os blocos e devolve (texto, gabarito) com offsets exatos.

    A ordem aqui e a **ordem logica de leitura humana**: numa secao de duas
    colunas, a coluna da esquerda inteira e so depois a da direita. O PyMuPDF
    devolve essas mesmas paginas em ordem de varredura (esquerda-1, direita-1,
    esquerda-2, ...), e essa divergencia e deliberada: `align.py` reprojeta o
    gabarito no texto extraido, e o detector passa a ser medido exatamente sob
    a degradacao de contexto que um PDF de duas colunas causa na vida real.
    """
    partes: list[str] = []
    gabarito: list[dict] = []
    pos = 0

    def escrever(segmentos: list[Segmento], sufixo: str) -> None:
        nonlocal pos
        for texto, rotulo in segmentos:
            if rotulo:
                gabarito.append(
                    {"label": rotulo, "value": texto, "start": pos, "end": pos + len(texto)}
                )
            partes.append(texto)
            pos += len(texto)
        partes.append(sufixo)
        pos += len(sufixo)

    for bloco in doc.blocos:
        if bloco.tipo == "corpo":
            for linha in bloco.linhas:
                escrever(linha, NOVA_LINHA)
        elif bloco.tipo == "tabela":
            for linha in bloco.celulas:
                for i, celula in enumerate(linha):
                    ultimo = i == len(linha) - 1
                    escrever(celula, NOVA_LINHA if ultimo else SEPARADOR_CELULA)
        elif bloco.tipo == "colunas":
            for coluna in bloco.colunas:
                for linha in coluna:
                    escrever(linha, NOVA_LINHA)

    return "".join(partes), gabarito


def _refluir(linhas: list[list[Segmento]], largura: int) -> list[list[Segmento]]:
    """Reflui para caber na largura **sem partir nenhum segmento**."""
    saida: list[list[Segmento]] = []
    for linha in linhas:
        if not linha:
            saida.append([])
            continue
        atual: list[Segmento] = []
        usada = 0
        for texto, rotulo in linha:
            if atual and usada + len(texto) > largura:
                saida.append(atual)
                atual, usada = [], 0
                texto = texto.lstrip()
            atual.append((texto, rotulo))
            usada += len(texto)
        if atual:
            saida.append(atual)
    return saida


def quebrar_linhas(doc: Documento) -> Documento:
    """Aplica o refluxo a cada bloco, com a largura do seu regime de layout."""
    novo = Documento(doc.doc_id, doc.genero)
    for bloco in doc.blocos:
        if bloco.tipo == "corpo":
            novo.blocos.append(Bloco("corpo", linhas=_refluir(bloco.linhas, LARGURA_LINHA)))
        elif bloco.tipo == "colunas":
            novo.blocos.append(
                Bloco(
                    "colunas",
                    colunas=[_refluir(c, LARGURA_COLUNA) for c in bloco.colunas],
                    x=list(bloco.x),
                )
            )
        else:
            # Celulas de tabela nao refluem: sao valores curtos de campo, e
            # quebra-las partiria justamente o identificador que queremos medir.
            novo.blocos.append(bloco)
    return novo


# --------------------------------------------------------------------------
# Gêneros documentais
# --------------------------------------------------------------------------
def _pessoa(fake: Faker, rng: random.Random) -> dict:
    return {
        "nome": fake.name(),
        "cpf": fakes.fake_cpf(rng),
        "rg": fakes.fake_rg_sp(rng),
        "cep": fakes.fake_cep(rng),
        "tel": fakes.fake_telefone(rng),
        "email": fake.email(),
        "logradouro": f"{fake.street_name()}, {rng.randint(1, 4000)}",
        "cidade": fake.city(),
        "nascimento": fake.date_of_birth(minimum_age=21, maximum_age=78).strftime("%d/%m/%Y"),
    }


# --------------------------------------------------------------------------
# Anexos de layout — o que faz o corpus sair do caso facil
# --------------------------------------------------------------------------
# A primeira rodada do eval usou 50 documentos de uma pagina, uma coluna, sem
# tabela. Ela media `layout.py` no cenario mais benigno possivel. Os anexos
# abaixo existem para exercitar os tres casos que o goal aponta como risco:
# multiplas paginas, celulas lado a lado na mesma linha visual, e duas colunas
# independentes.
X_TABELA_3 = [MARGEM_X, MARGEM_X + 190.0, MARGEM_X + 330.0]
X_COLUNAS_2 = [MARGEM_X, MARGEM_X + 268.0]


def _prosa(doc: Documento, texto: str) -> None:
    """Adiciona prosa ja quebrada em linhas.

    `_refluir` nunca parte um segmento — e essa e a garantia de que nenhum
    valor de PII atravessa uma quebra de linha. O efeito colateral e que um
    paragrafo inteiro passado como um unico segmento viraria uma linha so,
    estourando a pagina. Por isso a prosa entra pre-quebrada.
    """
    for linha in textwrap.wrap(texto, LARGURA_LINHA):
        doc.add(linha)


def _tabela_pessoas(
    doc: Documento, fake: Faker, rng: random.Random, titulo: str, n: int
) -> None:
    """Tabela de N pessoas: nome, CPF e nascimento em celulas lado a lado.

    Cada celula e uma chamada propria de `insert_text` na mesma altura. E o
    caso que obriga `rects_for` a agrupar por linha visual sem engolir o
    espaco entre colunas.
    """
    doc.blank()
    doc.add(titulo)
    linhas: list[list] = [["Nome", "CPF", "Nascimento"]]
    for _ in range(n):
        nome = fake.name()
        linhas.append(
            [
                [(nome, "PERSON")],
                [(fakes.fake_cpf(rng), "CPF")],
                [(fake.date_of_birth(minimum_age=1, maximum_age=70).strftime("%d/%m/%Y"),
                  "DATE_TIME")],
            ]
        )
    doc.add_tabela(X_TABELA_3, linhas)


def _colunas_pessoas(
    doc: Documento, fake: Faker, rng: random.Random,
    titulo_esq: str, titulo_dir: str, n: int
) -> None:
    """Duas colunas independentes, cada uma com nomes e identificadores.

    O PyMuPDF devolve a pagina em ordem de varredura, entao no texto extraido
    a linha da esquerda e a da direita se alternam. E exatamente a degradacao
    de contexto que um PDF de duas colunas causa num detector real, e e por
    isso que este bloco esta aqui.
    """
    doc.blank()
    doc.add(f"{titulo_esq} / {titulo_dir}")

    def coluna(titulo: str) -> list[list]:
        linhas: list[list] = [titulo]
        for _ in range(n):
            linhas.append([(fake.name(), "PERSON")])
            linhas.append(["CPF ", (fakes.fake_cpf(rng), "CPF")])
            linhas.append(["Tel. ", (fakes.fake_telefone(rng), "TELEFONE")])
            linhas.append([""])
        return linhas

    doc.add_colunas(X_COLUNAS_2, [coluna(titulo_esq), coluna(titulo_dir)])


def _clausulas(doc: Documento, fake: Faker, n: int, prefixo: str) -> None:
    """Volume de prosa para o documento passar de uma pagina."""
    for i in range(n):
        doc.blank()
        doc.add(f"{prefixo} {i + 1}.")
        _prosa(doc, " ".join(fake.paragraph(nb_sentences=5) for _ in range(2)))


def gerar_contrato(doc: Documento, fake: Faker, rng: random.Random) -> None:
    empresa = fake.company()
    cnpj = fakes.fake_cnpj(rng)
    p = _pessoa(fake, rng)

    doc.add("CONTRATO DE PRESTAÇÃO DE SERVIÇOS")
    doc.blank()
    doc.add("CONTRATANTE: ", (empresa, "ORGANIZATION"), ", pessoa jurídica de direito privado, ")
    doc.add("inscrita no CNPJ/MF sob o nº ", (cnpj, "CNPJ"), ", com sede na ",
            (f"Rua {p['logradouro']}", "ENDERECO"), ", CEP ", (p["cep"], "CEP"), ".")
    doc.blank()
    doc.add("CONTRATADO(A): ", (p["nome"], "PERSON"), ", brasileiro(a), portador(a) da cédula ")
    doc.add("de identidade RG nº ", (p["rg"], "RG"), ", inscrito(a) no CPF sob o nº ",
            (p["cpf"], "CPF"), ", ")
    doc.add("residente e domiciliado(a) em ", (p["cidade"], "LOCATION"),
            ", telefone ", (p["tel"], "TELEFONE"), ", ")
    doc.add("e-mail ", (p["email"], "EMAIL"), ".")
    doc.blank()
    doc.add("CLÁUSULA PRIMEIRA — DO OBJETO. O presente instrumento tem por objeto a prestação ")
    doc.add("de serviços técnicos especializados, na forma e condições aqui ajustadas.")
    doc.blank()
    doc.add("CLÁUSULA SEGUNDA — DO PAGAMENTO. Pelos serviços, a CONTRATANTE pagará o valor ")
    doc.add(f"mensal de R$ {rng.randint(2, 40) * 1000:,}".replace(",", ".") + ",00, ")
    doc.add("mediante depósito em conta de titularidade de ", (p["nome"], "PERSON"), ".")
    doc.blank()
    testemunha = fake.name()
    doc.add("Testemunha: ", (testemunha, "PERSON"), ", CPF ", (fakes.fake_cpf(rng), "CPF"), ".")

    _clausulas(doc, fake, 11, "CLAUSULA")
    _tabela_pessoas(doc, fake, rng, "QUADRO DE INTERVENIENTES", 6)
    _colunas_pessoas(doc, fake, rng, "TESTEMUNHAS", "PROCURADORES", 3)


def gerar_peticao(doc: Documento, fake: Faker, rng: random.Random) -> None:
    p = _pessoa(fake, rng)
    processo = fakes.fake_processo_cnj(rng)
    re_empresa = fake.company()
    cnpj = fakes.fake_cnpj(rng)
    adv = fake.name()

    doc.add("EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A) JUIZ(A) DE DIREITO DA ")
    doc.add(f"{rng.randint(1, 12)}ª VARA CÍVEL DA COMARCA DE ", (fake.city(), "LOCATION"))
    doc.blank()
    doc.add("Autos nº ", (processo, "PROCESSO_CNJ"))
    doc.blank()
    doc.add((p["nome"], "PERSON"), ", brasileiro(a), inscrito(a) no CPF sob o nº ",
            (p["cpf"], "CPF"), ", ")
    doc.add("portador(a) do RG nº ", (p["rg"], "RG"), ", nascido(a) em ",
            (p["nascimento"], "DATE_TIME"), ", ")
    doc.add("residente na ", (f"Avenida {p['logradouro']}", "ENDERECO"), ", CEP ",
            (p["cep"], "CEP"), ", ")
    doc.add("endereço eletrônico ", (p["email"], "EMAIL"), ", vem, por seu advogado que esta ")
    doc.add("subscreve, ", (adv, "PERSON"), ", propor a presente AÇÃO DE INDENIZAÇÃO em face de ")
    doc.add((re_empresa, "ORGANIZATION"), ", inscrita no CNPJ sob o nº ", (cnpj, "CNPJ"), ", ")
    doc.add("pelos fatos e fundamentos a seguir expostos.")
    doc.blank()
    doc.add("DOS FATOS. A parte autora firmou com a ré contrato de adesão, tendo sido ")
    doc.add("surpreendida com cobranças indevidas em sua fatura.")
    doc.blank()
    doc.add("Requer a intimação pelo telefone ", (p["tel"], "TELEFONE"), ".")

    _clausulas(doc, fake, 11, "DOS FUNDAMENTOS —")
    _colunas_pessoas(doc, fake, rng, "ROL DE TESTEMUNHAS", "LITISCONSORTES", 3)
    _tabela_pessoas(doc, fake, rng, "RELAÇÃO DE INTIMANDOS", 6)


def gerar_prontuario(doc: Documento, fake: Faker, rng: random.Random) -> None:
    p = _pessoa(fake, rng)
    cns = fakes.fake_cns(rng)
    medico = fake.name()

    doc.add("PRONTUÁRIO DE ATENDIMENTO AMBULATORIAL")
    doc.add("Unidade: ", (f"UBS {fake.last_name()}", "ORGANIZATION"),
            " — Município: ", (fake.city(), "LOCATION"))
    doc.blank()
    doc.add("Paciente: ", (p["nome"], "PERSON"))
    doc.add("Cartão Nacional de Saúde (CNS): ", (cns, "CNS"))
    doc.add("CPF: ", (p["cpf"], "CPF"), "   Data de nascimento: ",
            (p["nascimento"], "DATE_TIME"))
    doc.add("Endereço: ", (f"Rua {p['logradouro']}", "ENDERECO"), " — CEP ", (p["cep"], "CEP"))
    doc.add("Telefone de contato: ", (p["tel"], "TELEFONE"))
    doc.blank()
    doc.add("EVOLUÇÃO CLÍNICA. Paciente comparece à consulta de retorno referindo melhora ")
    doc.add("parcial do quadro. Mantida a conduta terapêutica anterior, com reavaliação ")
    doc.add("em 30 dias. Solicitados exames laboratoriais de rotina.")
    doc.blank()
    doc.add("Responsável técnico: ", (medico, "PERSON"), " — CRM ",
            f"{rng.randint(10000, 199999)}")
    doc.add("Contato institucional: ", (fake.email(), "EMAIL"))

    _tabela_pessoas(doc, fake, rng, "ACOMPANHANTES AUTORIZADOS", 6)
    _clausulas(doc, fake, 11, "EVOLUÇÃO —")
    _colunas_pessoas(doc, fake, rng, "EQUIPE ASSISTENCIAL", "CONTATOS DE EMERGÊNCIA", 3)


def gerar_rh(doc: Documento, fake: Faker, rng: random.Random) -> None:
    p = _pessoa(fake, rng)
    empresa = fake.company()

    doc.add("FICHA DE REGISTRO DE EMPREGADO")
    doc.add("Empregador: ", (empresa, "ORGANIZATION"), " — CNPJ ",
            (fakes.fake_cnpj(rng), "CNPJ"))
    doc.blank()
    doc.add("Nome do empregado: ", (p["nome"], "PERSON"))
    doc.add("CPF: ", (p["cpf"], "CPF"), "   RG: ", (p["rg"], "RG"))
    doc.add("PIS/PASEP: ", (fakes.fake_pis(rng), "PIS_PASEP"))
    doc.add("Título de eleitor: ", (fakes.fake_titulo_eleitor(rng), "TITULO_ELEITOR"))
    doc.add("CNH nº ", (fakes.fake_cnh(rng), "CNH"), " — categoria ",
            rng.choice(["AB", "B", "D"]))
    doc.add("Data de nascimento: ", (p["nascimento"], "DATE_TIME"))
    doc.add("Endereço residencial: ", (f"Rua {p['logradouro']}", "ENDERECO"),
            " — CEP ", (p["cep"], "CEP"))
    doc.add("Telefone: ", (p["tel"], "TELEFONE"), "   E-mail: ", (p["email"], "EMAIL"))
    doc.blank()
    doc.add("Cargo: ", fake.job(), "   Admissão: ",
            (fake.date_this_decade().strftime("%d/%m/%Y"), "DATE_TIME"))
    doc.add(f"Remuneração mensal: R$ {rng.randint(2, 30) * 1000:,}".replace(",", ".") + ",00")
    doc.blank()
    doc.add("Declaro serem verdadeiras as informações prestadas.")
    doc.add("Assinatura do empregado: ", (p["nome"], "PERSON"))

    _tabela_pessoas(doc, fake, rng, "DEPENDENTES DECLARADOS", 6)
    _clausulas(doc, fake, 11, "CLAUSULA CONTRATUAL")
    _colunas_pessoas(doc, fake, rng, "CONTATOS DE EMERGÊNCIA", "REFERÊNCIAS PROFISSIONAIS", 3)


def gerar_oficio(doc: Documento, fake: Faker, rng: random.Random) -> None:
    p = _pessoa(fake, rng)
    orgao = f"Secretaria Municipal de {fake.word().capitalize()}"

    doc.add(f"OFÍCIO Nº {rng.randint(10, 999)}/{rng.randint(2023, 2026)} — ", (orgao, "ORGANIZATION"))
    doc.add("Processo administrativo nº ", (fakes.fake_processo_cnj(rng), "PROCESSO_CNJ"))
    doc.blank()
    doc.add("Ao Senhor(a) ", (p["nome"], "PERSON"))
    doc.add("Matrícula funcional: ", f"{rng.randint(100000, 999999)}",
            "   CPF: ", (p["cpf"], "CPF"))
    doc.add("Endereço: ", (f"Avenida {p['logradouro']}", "ENDERECO"), " — CEP ",
            (p["cep"], "CEP"))
    doc.blank()
    doc.add("Assunto: solicitação de documentação complementar.")
    doc.blank()
    doc.add("Senhor(a) Servidor(a),")
    doc.add("Comunicamos que, nos termos da legislação vigente, faz-se necessária a ")
    doc.add("apresentação de documentação complementar no prazo de 15 (quinze) dias.")
    doc.blank()
    doc.add("Dúvidas podem ser encaminhadas para ", (fake.email(), "EMAIL"), " ou pelo ")
    doc.add("telefone ", (fakes.fake_telefone(rng, celular=False), "TELEFONE"), ".")
    doc.blank()
    doc.add("Atenciosamente,")
    doc.add((fake.name(), "PERSON"), " — Chefe de Gabinete")

    _clausulas(doc, fake, 11, "ANEXO —")
    _colunas_pessoas(doc, fake, rng, "SERVIDORES NOTIFICADOS", "SUPLENTES", 3)
    _tabela_pessoas(doc, fake, rng, "RELAÇÃO NOMINAL", 6)


GERADORES = {
    "contrato": gerar_contrato,
    "peticao": gerar_peticao,
    "prontuario": gerar_prontuario,
    "rh": gerar_rh,
    "oficio": gerar_oficio,
}


# --------------------------------------------------------------------------
# Renderização
# --------------------------------------------------------------------------
def renderizar(doc: Documento, caminho: Path) -> None:
    """Escreve uma chamada de ``insert_text`` por celula visual.

    Renderizar celula a celula (em vez de usar caixa de texto com refluxo
    automatico) e o que garante que a estrutura do PDF corresponda a estrutura
    do gabarito. Cada bloco tem seu regime:

    * ``corpo``   - uma chamada por linha, em MARGEM_X;
    * ``tabela``  - N chamadas na mesma altura, uma por coluna;
    * ``colunas`` - as duas colunas avancam em paralelo na mesma altura, e a
      quebra de pagina leva as duas juntas.
    """
    pdf = fitz.open()
    page = pdf.new_page()
    altura_util = page.rect.height - MARGEM_Y
    estado = {"page": page, "y": MARGEM_Y}

    def nova_pagina_se_preciso() -> None:
        if estado["y"] > altura_util:
            estado["page"] = pdf.new_page()
            estado["y"] = MARGEM_Y

    def escrever(x: float, texto: str) -> None:
        if texto:
            estado["page"].insert_text(
                (x, estado["y"]), texto, fontname=FONTE, fontsize=CORPO
            )

    for bloco in doc.blocos:
        if bloco.tipo == "corpo":
            for linha in bloco.linhas:
                nova_pagina_se_preciso()
                escrever(MARGEM_X, "".join(t for t, _ in linha))
                estado["y"] += ALTURA_LINHA

        elif bloco.tipo == "tabela":
            for linha in bloco.celulas:
                nova_pagina_se_preciso()
                for x, celula in zip(bloco.x, linha):
                    escrever(x, "".join(t for t, _ in celula))
                estado["y"] += ALTURA_LINHA

        elif bloco.tipo == "colunas":
            altura = max((len(c) for c in bloco.colunas), default=0)
            for i in range(altura):
                nova_pagina_se_preciso()
                for x, coluna in zip(bloco.x, bloco.colunas):
                    if i < len(coluna):
                        escrever(x, "".join(t for t, _ in coluna[i]))
                estado["y"] += ALTURA_LINHA

        estado["y"] += ALTURA_LINHA  # respiro entre blocos

    # Metadados propositalmente poluídos: parte do que a Fase 0 precisa provar
    # é que o saneamento os remove. Um PDF de teste "limpo" não testaria nada.
    pdf.set_metadata(
        {
            "title": f"{doc.genero} {doc.doc_id}",
            "author": next(
                (t for linha in doc.linhas for t, r in linha if r == "PERSON"), "desconhecido"
            ),
            "subject": "documento sintético de avaliação — Fase 0",
            "keywords": "teste, sintetico",
        }
    )
    pdf.save(str(caminho), garbage=4, deflate=True)
    pdf.close()


def gerar_corpus(destino: Path, n: int, semente: int) -> dict:
    destino.mkdir(parents=True, exist_ok=True)
    rng = random.Random(semente)
    fake = Faker("pt_BR")
    Faker.seed(semente)

    generos = list(GERADORES)
    indice = []

    for i in range(n):
        genero = generos[i % len(generos)]
        doc_id = f"{genero}-{i:03d}"
        d = Documento(doc_id, genero)
        GERADORES[genero](d, fake, rng)
        d = quebrar_linhas(d)

        texto, gabarito = montar_texto(d)
        caminho_pdf = destino / f"{doc_id}.pdf"
        renderizar(d, caminho_pdf)

        (destino / f"{doc_id}.json").write_text(
            json.dumps(
                {
                    "doc_id": doc_id,
                    "genero": genero,
                    "pdf": caminho_pdf.name,
                    "source_text": texto,
                    "gold": gabarito,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        indice.append({"doc_id": doc_id, "genero": genero, "entidades": len(gabarito)})

    resumo = {
        "n": n,
        "semente": semente,
        "generos": {g: sum(1 for x in indice if x["genero"] == g) for g in generos},
        "entidades_total": sum(x["entidades"] for x in indice),
        "documentos": indice,
    }
    (destino / "index.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return resumo


def main() -> None:
    ap = argparse.ArgumentParser(description="Gera o corpus sintético da Fase 0")
    ap.add_argument("--out", default="eval/datasets", type=Path)
    ap.add_argument("--n", default=50, type=int)
    ap.add_argument("--seed", default=20260829, type=int)
    args = ap.parse_args()

    resumo = gerar_corpus(args.out, args.n, args.seed)
    print(f"corpus gerado em {args.out}")
    print(f"  documentos : {resumo['n']}")
    print(f"  por gênero : {resumo['generos']}")
    print(f"  entidades  : {resumo['entidades_total']}")


if __name__ == "__main__":
    main()
