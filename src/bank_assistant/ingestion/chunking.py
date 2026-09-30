"""Structure-aware chunking.

Rules (each one is there for a reason that the evals can show):
1. A chunk never crosses a section boundary, so every chunk has exactly one
   `(document, section)` label and citations are precise.
2. Blocks (paragraphs, tables) are packed greedily up to `max_tokens`, measured with the
   embedding model's own tokenizer: a chunk longer than the model's window would be
   silently truncated when embedded.
3. Tables stay whole. Only a table that alone exceeds the limit is split, by rows, and every
   piece repeats the header row so it can still be read on its own.
4. When prose continues in a new chunk of the same section, the new chunk starts with the
   last sentences of the previous one (about `overlap_tokens`), so a fact that straddles
   the boundary is retrievable from either side.
5. Every chunk starts with a contextual header (document title, id, version, status and
   heading path). It is embedded and indexed with the body: "límites" in the title helps
   a chunk that only contains a table of numbers.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from bank_assistant.ingestion.documents import ParsedDocument, Section, TableBlock

TokenCounter = Callable[[str], int]

# Bump when the chunking logic changes: it is part of the index fingerprint, so every
# document gets re-chunked on the next ingestion.
CHUNKER_VERSION = "1"

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?;])\s+|\n+")


@dataclass(frozen=True)
class ChunkConfig:
    max_tokens: int = 380
    overlap_tokens: int = 60

    def __post_init__(self) -> None:
        if not 0 <= self.overlap_tokens < self.max_tokens:
            raise ValueError("overlap_tokens must be >= 0 and smaller than max_tokens")


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    ordinal: int
    section: str
    section_title: str
    heading_path: str
    content: str  # the body, shown to the model and cited
    search_text: str  # header + body: what gets embedded and indexed
    token_count: int

    @property
    def chunk_id(self) -> str:
        return f"{self.doc_id}#{self.ordinal:03d}"


def chunk_header(document: ParsedDocument, section: Section) -> str:
    meta = document.metadata
    return (
        f"{meta.title} ({meta.id}, versión {meta.version}, {meta.status.value})\n"
        f"{document.heading_path(section)}\n\n"
    )


def chunk_document(
    document: ParsedDocument, count_tokens: TokenCounter, config: ChunkConfig
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in document.sections:
        if not section.blocks:
            continue
        header = chunk_header(document, section)
        budget = config.max_tokens - count_tokens(header)
        if budget <= config.overlap_tokens:
            raise ValueError(f"max_tokens too small for the header of {document.metadata.id}")
        for body in _section_bodies(section, count_tokens, budget, config.overlap_tokens):
            chunks.append(
                Chunk(
                    doc_id=document.metadata.id,
                    ordinal=len(chunks),
                    section=section.number,
                    section_title=section.title,
                    heading_path=document.heading_path(section),
                    content=body,
                    search_text=header + body,
                    token_count=count_tokens(header + body),
                )
            )
    return chunks


def _section_bodies(
    section: Section, count_tokens: TokenCounter, budget: int, overlap: int
) -> list[str]:
    bodies: list[str] = []
    parts: list[str] = []  # blocks of the chunk being built, joined by blank lines

    def fits(candidate: list[str]) -> bool:
        return count_tokens("\n\n".join(candidate)) <= budget

    def close() -> str:
        """Emit the current chunk; return the overlap tail to seed the next one."""
        tail = _tail(parts[-1], count_tokens, overlap) if parts else ""
        if parts:
            bodies.append("\n\n".join(parts))
            parts.clear()
        return tail

    for block in section.blocks:
        if isinstance(block, TableBlock):
            rendered = block.to_markdown()
            if not fits([rendered]):  # rule 3: only oversized tables are split
                close()
                bodies.extend(_split_table(block, count_tokens, budget))
            elif fits([*parts, rendered]):
                parts.append(rendered)
            else:
                close()  # a table starts its own chunk, no prose overlap needed
                parts.append(rendered)
            continue

        text = block.text
        if fits([*parts, text]):
            parts.append(text)
            continue
        tail = close() if parts else ""
        if fits([tail, text] if tail else [text]):
            parts.extend([tail, text] if tail else [text])
            continue

        # The paragraph does not fit even on its own: pack it sentence by sentence.
        current = tail
        for sentence in _sentences(text, count_tokens, budget):
            candidate = f"{current} {sentence}".strip()
            if fits([*parts, candidate]):
                current = candidate
                continue
            parts.append(current)
            tail = close()
            current = f"{tail} {sentence}".strip()
            if not fits([current]):
                current = sentence
        if current:
            parts.append(current)
    close()
    return bodies


def _is_prose(text: str) -> bool:
    return not text.startswith("|")


def _sentences(text: str, count_tokens: TokenCounter, budget: int) -> list[str]:
    """Split into sentences; a sentence longer than the budget is split by words."""
    pieces: list[str] = []
    for sentence in filter(None, (s.strip() for s in _SENTENCE_BOUNDARY.split(text))):
        if count_tokens(sentence) <= budget:
            pieces.append(sentence)
            continue
        words: list[str] = []
        for word in sentence.split():
            if words and count_tokens(" ".join([*words, word])) > budget:
                pieces.append(" ".join(words))
                words = []
            words.append(word)
        if words:
            pieces.append(" ".join(words))
    return pieces


def _tail(text: str, count_tokens: TokenCounter, overlap: int) -> str:
    """Last whole sentences of `text` adding up to at most `overlap` tokens."""
    if overlap == 0 or not _is_prose(text):
        return ""
    tail: list[str] = []
    for sentence in reversed([s for s in _SENTENCE_BOUNDARY.split(text) if s.strip()]):
        if count_tokens(" ".join([sentence, *tail])) > overlap:
            break
        tail.insert(0, sentence.strip())
    return " ".join(tail)


def _split_table(table: TableBlock, count_tokens: TokenCounter, budget: int) -> list[str]:
    pieces: list[str] = []
    rows: list[tuple[str, ...]] = []
    for row in table.rows:
        if rows and count_tokens(table.to_markdown((*rows, row))) > budget:
            pieces.append(table.to_markdown(tuple(rows)))
            rows = []
        rows.append(row)
    if rows:
        pieces.append(table.to_markdown(tuple(rows)))
    return pieces
