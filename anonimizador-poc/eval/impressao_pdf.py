"""Prova de que o caminho do PDF nao mudou.

Nao e um teste — e um instrumento de comparacao entre duas revisoes do
codigo. Usa spans fixos e nenhum modelo, para o resultado depender so do
redator e do saneamento.

NAO compara bytes. Medido em 2026-09-05: a saida do PyMuPDF nao e
byte-deterministica nem para o mesmo codigo rodado duas vezes — o `/ID` do
trailer varia por execucao. Comparar bytes daria "mudou" sempre, o que e
ruido, nao sinal.

Compara o que o criterio de aceite realmente queria dizer: o conteudo
observavel do arquivo redigido — texto extraido, paginas, retangulos,
saneamento e resultado da verificacao.
"""
import hashlib
import json
import sys

import fitz

sys.path.insert(0, "/app/src")

from anonimizador.layout import build_text_map
from anonimizador.pdf_redactor import redact_document
from anonimizador.spans import Span
from anonimizador.verifier import verify

LINHAS = [
    "CONTRATO DE PRESTACAO DE SERVICOS",
    "Contratante: Mariana Aparecida Souza, CPF 529.982.247-25,",
    "residente na Rua das Flores, 100, CEP 01310-100, Sao Paulo.",
    "Contato: mariana.souza@exemplo.com.br, telefone (11) 98765-4321.",
]
ALVOS = [
    ("Mariana Aparecida Souza", "PERSON"),
    ("529.982.247-25", "CPF"),
    ("01310-100", "CEP"),
    ("mariana.souza@exemplo.com.br", "EMAIL"),
]

entrada = "/tmp/ref-entrada.pdf"
saida = "/tmp/ref-saida.pdf"

pdf = fitz.open()
page = pdf.new_page()
y = 64
for linha in LINHAS:
    page.insert_text((56, y), linha, fontname="helv", fontsize=9)
    y += 13
pdf.set_metadata({})
pdf.save(entrada, garbage=4, deflate=True)
pdf.close()

doc = fitz.open(entrada)
try:
    tm = build_text_map(doc)
    spans = []
    for valor, ent in ALVOS:
        pos = tm.text.find(valor)
        assert pos != -1, valor
        spans.append(Span(start=pos, end=pos + len(valor), entity=ent, score=0.99))
    res = redact_document(doc, tm, spans, saida)
finally:
    doc.close()

rel = verify(saida, res.valores)

out = fitz.open(saida)
try:
    texto = "\n".join(out.load_page(p).get_text() for p in range(out.page_count))
    paginas = out.page_count
finally:
    out.close()

impressao = {
    "texto_extraido": texto,
    "paginas": paginas,
    "spans_redigidos": res.spans_redigidos,
    "retangulos": res.retangulos,
    "sem_retangulo": len(res.spans_sem_retangulo),
    "saneamento": res.saneamento,
    "verificacao_ok": rel.ok,
    "vetores": rel.vetores_executados,
    "valores_checados": rel.valores_checados,
    "vazamentos": len(rel.leaks),
}
serial = json.dumps(impressao, sort_keys=True, ensure_ascii=False)
print(json.dumps(impressao, sort_keys=True, ensure_ascii=False, indent=2))
print("impressao=" + hashlib.sha256(serial.encode()).hexdigest())
