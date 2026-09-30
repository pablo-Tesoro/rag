import pytest

from bank_assistant.ingestion.documents import ParsedDocument, Section, TableBlock, TextBlock
from bank_assistant.ingestion.loaders import load_document, parse_markdown, parse_pdf
from bank_assistant.ingestion.metadata import discover_corpus
from tests.helpers import DATA_DIR

MARKDOWN = """# Título del documento

> Documento ficticio: este preámbulo no se indexa.

## 1. Objeto

Primer párrafo
que ocupa dos líneas.

Segundo párrafo.

## 2. Tabla

| Código | Importe |
|---|---|
| A-1 | 1,00 € |
| A-2 | 2,00 € |

Texto tras la tabla.

## 3. Padre

### 3.1 Hijo

- punto uno
- punto dos
"""


def test_markdown_sections_blocks_and_tables() -> None:
    sections = parse_markdown(MARKDOWN)

    assert [s.number for s in sections] == ["1", "2", "3", "3.1"]
    assert sections[0].blocks == [
        TextBlock("Primer párrafo\nque ocupa dos líneas."),
        TextBlock("Segundo párrafo."),
    ]
    table = sections[1].blocks[0]
    assert isinstance(table, TableBlock)
    assert table.header == ("Código", "Importe")
    assert table.rows == (("A-1", "1,00 €"), ("A-2", "2,00 €"))
    assert sections[1].blocks[1] == TextBlock("Texto tras la tabla.")
    assert sections[2].blocks == []  # parent with no own content
    assert sections[3].blocks == [TextBlock("- punto uno\n- punto dos")]


def test_markdown_preamble_is_not_indexed() -> None:
    all_text = " ".join(
        block.text
        for s in parse_markdown(MARKDOWN)
        for block in s.blocks
        if isinstance(block, TextBlock)
    )
    assert "preámbulo" not in all_text


@pytest.fixture(scope="module")
def catalog() -> list[Section]:
    return parse_pdf(str(DATA_DIR / "corpus" / "NOR-002_catalogo-productos-financiacion.pdf"))


def test_pdf_headings_become_sections(catalog: list[Section]) -> None:
    sections = catalog

    assert [s.number for s in sections] == ["1", "2", "3", "4", "5"]
    assert sections[1].title == "Préstamos personales"


def test_pdf_table_split_across_pages_is_stitched_back(catalog: list[Section]) -> None:
    tables = [b for b in catalog[3].blocks if isinstance(b, TableBlock)]

    assert len(tables) == 1
    assert [row[0] for row in tables[0].rows] == ["LIN-PYM-12", "PRE-PYM-60"]


def test_pdf_wrapped_table_cells_are_joined(catalog: list[Section]) -> None:
    table = next(b for b in catalog[1].blocks if isinstance(b, TableBlock))

    assert table.header[4] == "Comisión de apertura"
    assert table.rows[1][:4] == ("PRS-CONS-36", "Préstamo Consumo 36", "36 meses", "7,45 %")


def test_pdf_running_footer_and_title_are_dropped(catalog: list[Section]) -> None:
    text = " ".join(
        b.text if isinstance(b, TextBlock) else b.to_markdown() for s in catalog for b in s.blocks
    )

    assert "Página" not in text
    assert "Documento ficticio" not in text


def test_every_corpus_document_loads_with_numbered_sections() -> None:
    for source in discover_corpus(DATA_DIR / "corpus"):
        document = load_document(source)
        assert isinstance(document, ParsedDocument)
        assert document.sections[0].number == "1", source.metadata.id
        assert any(s.blocks for s in document.sections)


def test_heading_path_includes_parent_sections() -> None:
    source = next(s for s in discover_corpus(DATA_DIR / "corpus") if s.metadata.id == "NOR-001")
    document = load_document(source)
    section = next(s for s in document.sections if s.number == "3.1")

    assert document.heading_path(section) == (
        "3. Descubiertos y posiciones deudoras > 3.1 Comisión de descubierto (COM-DES-004)"
    )
