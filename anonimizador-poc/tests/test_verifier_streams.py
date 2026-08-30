"""A busca de forma numérica não pode inventar identificadores.

Contexto. O `verify` procura um valor em dez vetores, e um deles são os
streams descomprimidos do PDF — binário de fonte, imagem, coordenadas. Para
achar um CPF que ressurgiu como ``52998224725`` onde foi tarjado como
``529.982.247-25``, a busca precisa comparar formas só-dígitos.

A implementação original fazia isso apagando **todo** caractere não-dígito do
palheiro. Num vetor binário isso cola dígitos que nunca estiveram juntos, e o
gate passa a reprovar redação correta. Um gate que dá alarme falso é um gate
que as pessoas aprendem a ignorar — e aí ele não protege mais nada.

A correção apaga apenas os separadores que ocorrem *dentro* de um
identificador brasileiro. Estes testes fixam os dois lados dessa fronteira,
porque errar para qualquer lado é grave:

* apagar de menos → deixa de achar vazamento real (falha de segurança);
* apagar de mais  → reprova documento íntegro (falha de produto).
"""

import fitz
import pytest

from anonimizador.verifier import _procurar, _variantes, verify

CPF = "529.982.247-25"
DIGITOS = "52998224725"


def _agulhas(*valores):
    return {v: _variantes(v) for v in valores}


# --------------------------------------------------------------------------
# Continua achando o que precisa achar
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "palheiro",
    [
        "o valor 529.982.247-25 aparece aqui",   # forma original
        "o valor 52998224725 aparece aqui",      # só dígitos
        "o valor 529 982 247 25 aparece aqui",   # separado por espaço
        "o valor 529-982-247-25 aparece aqui",   # separado por hífen
        "o valor 529/982/247/25 aparece aqui",   # separado por barra
        "(529) 982 247-25",                      # parênteses, como telefone
    ],
)
def test_acha_identificador_em_qualquer_pontuacao(palheiro):
    achados = _procurar(_agulhas(CPF), palheiro, "teste")
    assert achados, f"deixou de achar em {palheiro!r} — vazamento real passaria"


def test_acha_valor_de_texto_com_espacamento_diferente():
    achados = _procurar(_agulhas("Ana Souza"), "nome:  Ana   Souza  aqui", "teste")
    assert achados


# --------------------------------------------------------------------------
# Para de achar o que nunca esteve lá
# --------------------------------------------------------------------------
def test_nao_cola_digitos_atraves_de_letras():
    """O caso que reprovava documento íntegro.

    Bytes de um stream de fonte: os dígitos existem, mas separados por
    caracteres que não são separadores de identificador. Colá-los fabrica um
    CPF que não está no documento e não é recuperável por ninguém.
    """
    palheiro = "5a2b9c9d8e2f2g4h7i2j5k"
    assert not _procurar(_agulhas(CPF), palheiro, "teste")


def test_nao_cola_digitos_atraves_de_quebra_de_objeto():
    # Fim de um stream encostando no começo de outro. A concatenação era feita
    # pelo próprio verificador; a sequência nunca existiu em lugar nenhum.
    palheiro = "endstream 529 obj\x00\x01\x02 982247 endobj 25 stream"
    assert not _procurar(_agulhas(CPF), palheiro, "teste")


def test_nao_cola_digitos_atraves_de_operadores_pdf():
    palheiro = "BT /F1 529 Tf 982 247 Td (x) Tj 25 TL ET"
    assert not _procurar(_agulhas(CPF), palheiro, "teste")


# --------------------------------------------------------------------------
# O gate ponta a ponta, sobre um PDF de verdade
# --------------------------------------------------------------------------
def test_pdf_redigido_aprova(tmp_pdf, tmp_path):
    """Redação correta tem de passar. É o caso que estava reprovando."""
    from anonimizador.layout import build_text_map
    from anonimizador.pdf_redactor import redact_document
    from anonimizador.spans import Span

    entrada = tmp_pdf(
        [
            "OFICIO 123/2026",
            f"Interessado: Ana Souza, CPF {CPF}.",
            "Assunto: solicitacao de certidao.",
        ]
    )
    saida = tmp_path / "redigido.pdf"

    doc = fitz.open(str(entrada))
    try:
        tm = build_text_map(doc)
        pos = tm.text.find(CPF)
        assert pos != -1
        res = redact_document(
            doc, tm, [Span(pos, pos + len(CPF), "CPF", 1.0)], saida
        )
    finally:
        doc.close()

    rel = verify(saida, res.valores)
    assert rel.ok, f"reprovou redacao correta: {[str(x) for x in rel.leaks]}"


def test_pdf_com_valor_sobrevivente_reprova(tmp_pdf, tmp_path):
    """E vazamento real tem de continuar reprovando.

    O mesmo CPF em duas linhas; só a primeira é tarjada. A segunda sobrevive
    e o gate precisa pegá-la — se este teste passar a falhar, a correção
    afrouxou o verificador.
    """
    from anonimizador.layout import build_text_map
    from anonimizador.pdf_redactor import redact_document
    from anonimizador.spans import Span

    entrada = tmp_pdf(
        [
            f"Interessado: Ana Souza, CPF {CPF}.",
            f"Confirmacao do CPF {CPF} para o cadastro.",
        ]
    )
    saida = tmp_path / "redigido.pdf"

    doc = fitz.open(str(entrada))
    try:
        tm = build_text_map(doc)
        pos = tm.text.find(CPF)
        res = redact_document(
            doc, tm, [Span(pos, pos + len(CPF), "CPF", 1.0)], saida
        )
    finally:
        doc.close()

    rel = verify(saida, res.valores)
    assert not rel.ok, "deixou passar um CPF que sobreviveu no texto"
    assert any(lk.vetor.startswith("texto") for lk in rel.leaks)


def test_acha_valor_escrito_em_hexadecimal(tmp_path):
    """A cegueira que este teste fecha.

    O PyMuPDF — e vários outros geradores — escreve texto no content stream
    como ``[<435046203532392e...>] TJ``, não como ``(CPF 529.982...)``. A
    busca literal não via nada disso, e o verificador devolvia "aprovado"
    sobre um objeto onde o valor está perfeitamente recuperável por quem
    souber ler hexadecimal.
    """
    caminho = tmp_path / "com_valor.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((56, 72), f"CPF {CPF}", fontname="helv", fontsize=11)
    doc.save(str(caminho))
    doc.close()

    rel = verify(caminho, [CPF])
    de_stream = [lk for lk in rel.leaks if lk.vetor == "streams"]
    assert de_stream, "nao achou o valor escrito em hexadecimal no content stream"


def test_leak_de_stream_diz_o_tipo_do_objeto(tmp_path):
    """O achado precisa dizer *onde* está, não só que existe.

    "Vazou em streams" não permite agir. O número do xref e o tipo do objeto
    — conteúdo de página, aparência de formulário, fonte — é o que aponta o
    conserto.
    """
    caminho = tmp_path / "com_valor.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((56, 72), f"CPF {CPF}", fontname="helv", fontsize=11)
    doc.save(str(caminho))
    doc.close()

    rel = verify(caminho, [CPF])
    de_stream = [lk for lk in rel.leaks if lk.vetor == "streams"]
    assert de_stream
    assert "xref" in de_stream[0].detalhe
    assert "em " in de_stream[0].detalhe


def test_hex_nao_inventa_vazamento_em_binario(tmp_path):
    """A tradução de hex não pode criar alarme falso.

    Bytes de imagem contêm sequências que *parecem* string hexadecimal entre
    `<` e `>`. Traduzi-las produz texto aleatório, e texto aleatório não pode
    casar com um valor real — mas a checagem tem de existir, porque este é o
    modo de falha que a correção anterior acabou de tirar do sistema.
    """
    import random

    caminho = tmp_path / "ruido.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((56, 72), "documento sem PII", fontname="helv", fontsize=11)
    rnd = random.Random(3)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    for _ in range(9000):
        pix.set_pixel(
            rnd.randrange(200),
            rnd.randrange(200),
            (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)),
        )
    page.insert_image(fitz.Rect(56, 100, 256, 300), pixmap=pix)
    doc.save(str(caminho), garbage=4, deflate=True)
    doc.close()

    rel = verify(caminho, [CPF, "Ana Souza", "01310-100"])
    assert rel.ok, f"alarme falso sobre binario: {[str(x) for x in rel.leaks]}"
