import datetime as dt
from itertools import pairwise

import pytest

from bank_assistant.ingestion.chunking import Chunk, ChunkConfig, chunk_document
from bank_assistant.ingestion.documents import ParsedDocument, Section, TableBlock, TextBlock
from bank_assistant.ingestion.loaders import load_document
from bank_assistant.ingestion.metadata import DocumentMetadata, DocumentStatus, discover_corpus
from tests.fakes import whitespace_token_count as count
from tests.helpers import DATA_DIR

META = DocumentMetadata(
    id="NOR-900",
    title="Documento",
    version="1.0",
    date=dt.date(2025, 1, 1),
    status=DocumentStatus.CURRENT,
    groups=frozenset({"todos"}),
)


def _doc(*sections: Section) -> ParsedDocument:
    return ParsedDocument(metadata=META, sections=list(sections))


def _sentences(n: int, words: int = 8) -> str:
    return " ".join(f"Frase {i} " + " ".join(["palabra"] * (words - 2)) + "." for i in range(n))


def _chunks(doc: ParsedDocument, max_tokens: int, overlap: int = 0) -> list[Chunk]:
    return chunk_document(doc, count, ChunkConfig(max_tokens=max_tokens, overlap_tokens=overlap))


def test_small_sections_become_one_chunk_each_and_never_mix() -> None:
    doc = _doc(
        Section("1", "Uno", [TextBlock("Texto uno.")]),
        Section("2", "Dos", [TextBlock("Texto dos.")]),
    )

    chunks = _chunks(doc, max_tokens=100)

    assert [(c.section, c.content) for c in chunks] == [("1", "Texto uno."), ("2", "Texto dos.")]
    assert [c.chunk_id for c in chunks] == ["NOR-900#000", "NOR-900#001"]


def test_header_is_indexed_but_not_part_of_the_cited_content() -> None:
    doc = _doc(Section("1", "Objeto", [TextBlock("Cuerpo.")]))

    (chunk,) = _chunks(doc, max_tokens=100)

    assert chunk.search_text.startswith("Documento (NOR-900, versión 1.0, vigente)\n1. Objeto\n\n")
    assert chunk.search_text.endswith("Cuerpo.")
    assert chunk.content == "Cuerpo."


def test_sections_without_content_produce_no_chunk() -> None:
    doc = _doc(Section("3", "Padre"), Section("3.1", "Hijo", [TextBlock("Contenido.")]))

    (chunk,) = _chunks(doc, max_tokens=100)

    assert chunk.section == "3.1"
    assert chunk.heading_path == "3. Padre > 3.1 Hijo"


def test_every_chunk_respects_the_token_limit() -> None:
    doc = _doc(Section("1", "Largo", [TextBlock(_sentences(40))]))

    chunks = _chunks(doc, max_tokens=60, overlap=10)

    assert len(chunks) > 1
    assert all(c.token_count <= 60 for c in chunks)


def test_long_prose_is_split_with_sentence_overlap() -> None:
    doc = _doc(Section("1", "Largo", [TextBlock(_sentences(20))]))

    chunks = _chunks(doc, max_tokens=60, overlap=10)

    for previous, current in pairwise(chunks):
        last_sentence = previous.content.split(". ")[-1]
        assert current.content.startswith(last_sentence.rstrip(".")), "overlap missing"


def test_no_text_is_lost_when_splitting() -> None:
    text = _sentences(25)
    doc = _doc(Section("1", "Largo", [TextBlock(text)]))

    chunks = _chunks(doc, max_tokens=60, overlap=10)

    for sentence in text.split(". "):
        assert any(sentence.rstrip(".") in c.content for c in chunks)


def test_a_table_that_fits_is_never_split() -> None:
    table = TableBlock(("Código", "Importe"), tuple((f"C-{i}", f"{i},00 €") for i in range(5)))
    doc = _doc(Section("2", "Tabla", [TextBlock(_sentences(3)), table]))

    chunks = _chunks(doc, max_tokens=60)

    tables = [c for c in chunks if "| Código | Importe |" in c.content]
    assert len(tables) == 1
    assert all(f"C-{i}" in tables[0].content for i in range(5))


def test_an_oversized_table_is_split_by_rows_repeating_the_header() -> None:
    table = TableBlock(("Código", "Importe"), tuple((f"C-{i}", f"{i},00 €") for i in range(30)))
    doc = _doc(Section("2", "Tabla", [table]))

    chunks = _chunks(doc, max_tokens=50)

    assert len(chunks) > 1
    assert all(c.content.startswith("| Código | Importe |\n|---|---|") for c in chunks)
    rows = [line for c in chunks for line in c.content.splitlines()[2:]]
    assert rows == [f"| C-{i} | {i},00 € |" for i in range(30)]


def test_overlap_must_be_smaller_than_the_limit() -> None:
    with pytest.raises(ValueError):
        ChunkConfig(max_tokens=50, overlap_tokens=50)


def test_real_corpus_chunks_are_complete_and_bounded() -> None:
    config = ChunkConfig(max_tokens=200, overlap_tokens=30)
    for source in discover_corpus(DATA_DIR / "corpus"):
        document = load_document(source)
        chunks = chunk_document(document, count, config)

        assert all(c.token_count <= config.max_tokens for c in chunks), source.metadata.id
        sections_with_content = {s.number for s in document.sections if s.blocks}
        assert {c.section for c in chunks} == sections_with_content
        for section in document.sections:
            for block in section.blocks:
                if isinstance(block, TableBlock):
                    for row in block.rows:  # no table row is ever lost
                        assert any(
                            row[0] in c.content for c in chunks if c.section == section.number
                        )
