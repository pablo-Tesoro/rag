"""Loaders: turn a corpus file into a `ParsedDocument` (numbered sections of blocks).

Rules shared by both formats:
- A section starts at a numbered heading ("3.1 Título"). Unnumbered text before the first
  numbered heading is boilerplate (title, "documento ficticio" notice) and is not indexed;
  the document title is added to every chunk header anyway.
- Tables are kept as rows so they can stay whole.
"""

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pdfplumber
from pdfplumber.page import Page

from bank_assistant.ingestion.documents import (
    ParsedDocument,
    Section,
    TableBlock,
    TextBlock,
)
from bank_assistant.ingestion.metadata import SourceDocument, load_markdown

# --------------------------------------------------------------------------- Markdown

_MD_HEADING = re.compile(r"^#{2,6}\s+(\d+(?:\.\d+)*)\.?\s+(.+?)\s*$")
_MD_TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}")


def parse_markdown(body: str) -> list[Section]:
    sections: list[Section] = []
    paragraph: list[str] = []
    table: list[str] = []

    def flush() -> None:
        if not sections:  # preamble: dropped
            paragraph.clear()
            table.clear()
            return
        if paragraph:
            sections[-1].blocks.append(TextBlock("\n".join(paragraph)))
            paragraph.clear()
        if table:
            sections[-1].blocks.append(_markdown_table(table))
            table.clear()

    for raw in body.splitlines():
        line = raw.rstrip()
        heading = _MD_HEADING.match(line)
        if heading:
            flush()
            sections.append(Section(number=heading.group(1), title=heading.group(2)))
        elif line.startswith("|"):
            if paragraph:
                flush()
            table.append(line)
        elif not line.strip():
            flush()
        else:
            if table:
                flush()
            paragraph.append(line.strip())
    flush()
    return sections


def _markdown_table(lines: list[str]) -> TableBlock:
    rows = [
        tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        for line in lines
        if not _MD_TABLE_SEPARATOR.match(line)
    ]
    return TableBlock(header=rows[0], rows=tuple(rows[1:]))


# -------------------------------------------------------------------------------- PDF

_PDF_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+([A-ZÁÉÍÓÚÑ].*)$")
# Page bands (in points) where running headers and footers live; excluded from the body.
HEADER_BAND = 36
FOOTER_BAND = 60
# A vertical gap larger than this between two lines starts a new paragraph.
PARAGRAPH_GAP = 5.0
# A line is a heading candidate only if its font is clearly bigger than the body text.
HEADING_SIZE_RATIO = 1.15


@dataclass
class _Item:
    top: float
    kind: str  # "heading" | "line" | "table"
    text: str = ""
    bottom: float = 0.0
    table: TableBlock | None = None
    number: str = ""


def parse_pdf(path: str) -> list[Section]:
    sections: list[Section] = []
    paragraph: list[str] = []
    last_bottom: float | None = None
    last_emitted: str | None = None  # kind of the last element added, to detect continuations

    def flush_paragraph() -> None:
        if paragraph and sections:
            sections[-1].blocks.append(TextBlock(" ".join(paragraph)))
        paragraph.clear()

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            last_bottom = None
            for item in _page_items(page):
                if item.kind == "heading":
                    flush_paragraph()
                    sections.append(Section(number=item.number, title=item.text))
                    last_emitted = "heading"
                elif item.kind == "table" and item.table is not None:
                    flush_paragraph()
                    if sections:
                        _append_table(sections[-1], item.table, continuing=last_emitted == "table")
                    last_emitted = "table"
                else:
                    if last_bottom is not None and item.top - last_bottom > PARAGRAPH_GAP:
                        flush_paragraph()
                    paragraph.append(item.text)
                    last_emitted = "line"
                last_bottom = item.bottom if item.kind == "line" else None
        flush_paragraph()
    return sections


def _append_table(section: Section, table: TableBlock, *, continuing: bool) -> None:
    """Stitch a table that continues from the previous page (same header, nothing between)."""
    previous = section.blocks[-1] if section.blocks else None
    if continuing and isinstance(previous, TableBlock) and previous.header == table.header:
        section.blocks[-1] = TableBlock(previous.header, previous.rows + table.rows)
    else:
        section.blocks.append(table)


def _page_items(page: Page) -> Iterator[_Item]:
    body = page.crop((0, HEADER_BAND, page.width, page.height - FOOTER_BAND))
    tables = body.find_tables()
    boxes = [table.bbox for table in tables]
    lines = [
        line
        for line in body.extract_text_lines(return_chars=True)
        if not any(_inside(line, box) for box in boxes)
    ]
    body_size = _body_font_size(lines)

    items = [_line_item(line, body_size) for line in lines]
    for table in tables:
        rows = [tuple(_clean_cell(cell) for cell in row) for row in table.extract()]
        if rows:
            block = TableBlock(header=rows[0], rows=tuple(rows[1:]))
            items.append(_Item(top=table.bbox[1], kind="table", table=block))
    yield from sorted(items, key=lambda item: item.top)


def _line_item(line: dict[str, Any], body_size: float) -> _Item:
    text = str(line["text"]).strip()
    size = max(float(char["size"]) for char in line["chars"])
    heading = _PDF_HEADING.match(text)
    if heading and size >= body_size * HEADING_SIZE_RATIO:
        return _Item(
            top=line["top"], kind="heading", number=heading.group(1), text=heading.group(2)
        )
    return _Item(top=line["top"], bottom=line["bottom"], kind="line", text=text)


def _body_font_size(lines: list[dict[str, Any]]) -> float:
    sizes = Counter(round(float(char["size"]), 1) for line in lines for char in line["chars"])
    return sizes.most_common(1)[0][0] if sizes else 0.0


def _inside(line: dict[str, Any], box: tuple[float, float, float, float]) -> bool:
    middle = (float(line["top"]) + float(line["bottom"])) / 2
    return box[1] <= middle <= box[3]


def _clean_cell(cell: str | None) -> str:
    return " ".join((cell or "").split())


# ---------------------------------------------------------------------------- facade


def load_document(source: SourceDocument) -> ParsedDocument:
    if source.kind == "markdown":
        metadata, body = load_markdown(source.path)
        sections = parse_markdown(body)
    else:
        metadata = source.metadata
        sections = parse_pdf(str(source.path))
    # Sections without blocks (e.g. "3." followed directly by "3.1") are kept: their
    # titles are part of the heading path of their subsections.
    return ParsedDocument(metadata=metadata, sections=sections)
