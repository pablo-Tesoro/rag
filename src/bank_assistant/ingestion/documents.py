"""Structural representation of a parsed document: numbered sections made of blocks.

Both loaders (Markdown and PDF) produce this shape, so chunking does not care about the
source format. Tables are kept as rows, not as flattened text, so the chunker can keep them
whole or, if one is too big, split it by rows repeating the header.
"""

from dataclasses import dataclass, field

from bank_assistant.ingestion.metadata import DocumentMetadata


@dataclass(frozen=True)
class TextBlock:
    text: str


@dataclass(frozen=True)
class TableBlock:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def to_markdown(self, rows: tuple[tuple[str, ...], ...] | None = None) -> str:
        body = self.rows if rows is None else rows
        lines = [
            "| " + " | ".join(self.header) + " |",
            "|" + "---|" * len(self.header),
        ]
        lines.extend("| " + " | ".join(row) + " |" for row in body)
        return "\n".join(lines)


Block = TextBlock | TableBlock


@dataclass
class Section:
    number: str  # "3.1"
    title: str
    blocks: list[Block] = field(default_factory=list)

    @property
    def parent_numbers(self) -> list[str]:
        """Ancestor section numbers, outermost first: "3.1.2" -> ["3", "3.1"]."""
        parts = self.number.split(".")
        return [".".join(parts[:i]) for i in range(1, len(parts))]


@dataclass(frozen=True)
class ParsedDocument:
    metadata: DocumentMetadata
    sections: list[Section]

    def heading_path(self, section: Section) -> str:
        """Human-readable breadcrumb, e.g. "3. Descubiertos > 3.1 Comisión de descubierto"."""
        titles = {s.number: s.title for s in self.sections}
        crumbs = [_label(n, titles[n]) for n in section.parent_numbers if n in titles]
        crumbs.append(_label(section.number, section.title))
        return " > ".join(crumbs)


def _label(number: str, title: str) -> str:
    # "3. Tarjetas" for top-level sections, "3.1 Comisión de descubierto" for subsections.
    return f"{number}. {title}" if "." not in number else f"{number} {title}"
