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
MARGEM_X = 56
MARGEM_Y = 64
ALTURA_LINHA = 13
FONTE = "helv"
CORPO = 9


@dataclass
class Documento:
    doc_id: str
    genero: str
    linhas: list[list[Segmento]] = field(default_factory=list)

    def add(self, *segmentos: Segmento | str) -> None:
        linha: list[Segmento] = []
        for s in segmentos:
            linha.append((s, None) if isinstance(s, str) else s)
        self.linhas.append(linha)

    def blank(self) -> None:
        self.linhas.append([])


def montar_texto(doc: Documento) -> tuple[str, list[dict]]:
    """Concatena as linhas e devolve (texto, gabarito) com offsets exatos."""
    partes: list[str] = []
    gabarito: list[dict] = []
    pos = 0

    for linha in doc.linhas:
        for texto, rotulo in linha:
            if rotulo:
                gabarito.append(
                    {"label": rotulo, "value": texto, "start": pos, "end": pos + len(texto)}
                )
            partes.append(texto)
            pos += len(texto)
        partes.append("\n")
        pos += 1

    return "".join(partes), gabarito


def quebrar_linhas(doc: Documento) -> Documento:
    """Reflui as linhas para caber na página **sem partir nenhum segmento**."""
    novo = Documento(doc.doc_id, doc.genero)
    for linha in doc.linhas:
        if not linha:
            novo.blank()
            continue
        atual: list[Segmento] = []
        largura = 0
        for texto, rotulo in linha:
            if atual and largura + len(texto) > LARGURA_LINHA:
                novo.linhas.append(atual)
                atual, largura = [], 0
                texto = texto.lstrip()
            atual.append((texto, rotulo))
            largura += len(texto)
        if atual:
            novo.linhas.append(atual)
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
    """Escreve uma linha por chamada de ``insert_text``.

    Renderizar linha a linha (em vez de usar caixa de texto com refluxo
    automático) é o que garante que a estrutura do PDF corresponda à estrutura
    do gabarito.
    """
    pdf = fitz.open()
    page = pdf.new_page()
    y = MARGEM_Y
    altura_util = page.rect.height - MARGEM_Y

    for linha in doc.linhas:
        texto = "".join(t for t, _ in linha)
        if y > altura_util:
            page = pdf.new_page()
            y = MARGEM_Y
        if texto:
            page.insert_text((MARGEM_X, y), texto, fontname=FONTE, fontsize=CORPO)
        y += ALTURA_LINHA

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
