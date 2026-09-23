from __future__ import annotations

import re
from dataclasses import dataclass

import litellm

SECTION_TOKENS = 2000
CHILD_TOKENS = 500
CHILD_OVERLAP_TOKENS = 75
ENCODING_MODEL = "gpt-4o-mini"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass(frozen=True)
class ChunkDraft:
    ord: int
    page: int | None
    text: str


@dataclass(frozen=True)
class SectionDraft:
    heading_path: str
    ord: int
    text: str
    tokens: int
    children: list[ChunkDraft]


@dataclass(frozen=True)
class _Block:
    heading_path: str
    text: str


def chunk_document(markdown: str, page_texts: list[str]) -> list[SectionDraft]:
    blocks = _blocks(markdown)
    if not blocks:
        return []

    sections: list[tuple[str, str]] = []
    current_path = blocks[0].heading_path
    current_text = ""
    for block in blocks:
        for piece in _split_to_limit(block.text, SECTION_TOKENS):
            if not current_text:
                current_path = block.heading_path
                current_text = piece
                continue
            candidate = f"{current_text}\n\n{piece}"
            if block.heading_path == current_path and _tokens(candidate) <= SECTION_TOKENS:
                current_text = candidate
            else:
                sections.append((current_path, current_text))
                current_path = block.heading_path
                current_text = piece
    if current_text:
        sections.append((current_path, current_text))

    drafts: list[SectionDraft] = []
    for index, (heading_path, text) in enumerate(sections):
        drafts.append(
            SectionDraft(
                heading_path=heading_path,
                ord=index,
                text=text,
                tokens=_tokens(text),
                children=_children(text, page_texts),
            )
        )
    return drafts


def _blocks(markdown: str) -> list[_Block]:
    path: list[str] = []
    pending: list[str] = []
    blocks: list[_Block] = []

    def flush() -> None:
        text = "\n".join(pending).strip()
        pending.clear()
        if not text:
            return
        for part in re.split(r"\n\s*\n", text):
            part = part.strip()
            if part:
                blocks.append(_Block(" > ".join(path), part))

    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if match is None:
            pending.append(line)
            continue
        flush()
        level = len(match.group(1))
        path = [*path[: level - 1], match.group(2).strip()]
    flush()
    return blocks


def _children(text: str, page_texts: list[str]) -> list[ChunkDraft]:
    if _tokens(text) <= CHILD_TOKENS:
        return [ChunkDraft(ord=0, page=_page_for_text(text, page_texts), text=text)]

    chunks: list[ChunkDraft] = []
    start = 0
    while start < len(text):
        end = _max_end(text, start, CHILD_TOKENS)
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(
                ChunkDraft(
                    ord=len(chunks), page=_page_for_text(chunk_text, page_texts), text=chunk_text
                )
            )
        if end >= len(text):
            break
        overlap = _suffix_len_within(text[start:end], CHILD_OVERLAP_TOKENS)
        start = max(start + 1, end - overlap)
    return chunks


def _split_to_limit(text: str, limit: int) -> list[str]:
    if _tokens(text) <= limit:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = _max_end(text, start, limit)
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end <= start:
            break
        start = end
    return pieces


def _max_end(text: str, start: int, limit: int) -> int:
    low = start + 1
    high = len(text)
    best = low
    while low <= high:
        mid = (low + high) // 2
        if _tokens(text[start:mid]) <= limit:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best


def _suffix_len_within(text: str, limit: int) -> int:
    low = 0
    high = len(text)
    best = 0
    while low <= high:
        mid = (low + high) // 2
        if _tokens(text[len(text) - mid :]) <= limit:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best


def _tokens(text: str) -> int:
    return int(litellm.token_counter(model=ENCODING_MODEL, text=text))


def _page_for_text(text: str, page_texts: list[str]) -> int | None:
    if not page_texts:
        return None
    haystack = "\n\n".join(page_texts)
    needle = text[:80].strip() or text.strip()
    offset = haystack.find(needle)
    if offset < 0:
        return None
    cursor = 0
    for page, page_text in enumerate(page_texts, start=1):
        page_end = cursor + len(page_text)
        if cursor <= offset <= page_end:
            return page
        cursor = page_end + 2
    return None
