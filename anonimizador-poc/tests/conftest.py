import random
from pathlib import Path

import pytest


@pytest.fixture
def rng():
    return random.Random(20260829)


@pytest.fixture
def tmp_pdf(tmp_path: Path):
    """Fábrica de PDFs de teste a partir de uma lista de linhas."""
    import fitz

    def _criar(linhas, nome="teste.pdf", metadata=None):
        pdf = fitz.open()
        page = pdf.new_page()
        y = 64
        for linha in linhas:
            page.insert_text((56, y), linha, fontname="helv", fontsize=9)
            y += 13
        if metadata:
            pdf.set_metadata(metadata)
        caminho = tmp_path / nome
        pdf.save(str(caminho), garbage=4, deflate=True)
        pdf.close()
        return caminho

    return _criar
