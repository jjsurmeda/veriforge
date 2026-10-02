from __future__ import annotations

import re
from dataclasses import dataclass

import litellm

SECTION_TOKENS = 2000
# Round 2 (KI-12): sentence-aware children of about 250–300 tokens with
# 15% whole-sentence overlap replace the 500-token character windows —
# a quote no longer sits buried at a chunk's tail (TRD §9.1 step 4,
# amended 2026-09-29).
CHILD_TOKENS = 300
CHILD_OVERLAP_TOKENS = 45
ENCODING_MODEL = "gpt-4o-mini"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

# Plain-text heading promotion (TRD §9.1 step 4, amended): plain text and
# PDF-derived markdown carry no `#` headings, so chapter markers in several
# languages, standalone roman numerals and conservative short title lines
# are promoted. Only blank-surrounded standalone lines qualify, and never
# the document's first content line (that is a title, not a section).
_CHAPTER_RE = re.compile(
    r"^(?:CHAPTER|Chapter|CAPÍTULO|Capítulo|CHAPITRE|Chapitre|Kapitel|KAPANATA|Kabanata)"
    r"\s+(?:[0-9]+|[IVXLCDM]+|[ivxlcdm]+|primero|Primero)\b.{0,70}$"
)
_CJK_CHAPTER_RE = re.compile(r"^第[0-9０-９一二三四五六七八九十百千萬零〇两兩]+[回章].{0,60}$")
_ROMAN_RE = re.compile(r"^(?:[IVXLCDM]+|[ivxlcdm]+)[.:=]?$")
# Gutenberg metadata keys ("Author: …", "Language: …") are catalog data,
# not document structure.
_METADATA_RE = re.compile(
    r"^(?:Author|Title|Language|Credits|Translator|Posting [Dd]ate|Release [Dd]ate|"
    r"Last [Uu]pdated|Other information|ISBN|Editor)\s*:"
)

# Sentence boundaries, language-neutral. Latin terminals (. ! ?) need
# following whitespace (so "3.14" and filenames never split); CJK terminals
# (。！？) do not. Closing quotes/brackets belong to the sentence (." 「。」).
_ABBREVIATIONS = ("Mr.", "Mrs.", "Dr.", "Sr.", "Sra.", "M.", "Mme.", "St.")
_CLOSERS = "\"'”’»›）)】〕]」』"
_SENT_BOUNDARY = re.compile(
    r"([.!?])([" + re.escape(_CLOSERS) + r"]*)(\s+)"
    r"|([。！？])([" + re.escape(_CLOSERS) + r"]*)"
)

# TRD §11 layer 2: any literal `<source ...>` / `</source>` inside chunk
# text must be escaped so the generator's structural delimiter cannot be
# forged by an attacker-controlled document. HTML-escape the angle
# brackets; the original text is preserved for readers (renderers decode).
_SOURCE_TAG_RE = re.compile(r"</?source\b", re.IGNORECASE)


def escape_source_tags(text: str) -> str:
    return _SOURCE_TAG_RE.sub(lambda m: m.group(0).replace("<", "&lt;").replace(">", "&gt;"), text)


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


@dataclass(frozen=True)
class _Unit:
    """An indivisible stretch of text: a paragraph that fits the limit, a
    sentence, or a hard-split piece of an oversized sentence."""

    start: int
    end: int
    tokens: int


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
    previous_tail = ""
    for index, (heading_path, text) in enumerate(sections):
        children = _children(text, page_texts, overlap_prefix=previous_tail)
        previous_tail = _tail_text(text)
        drafts.append(
            SectionDraft(
                heading_path=heading_path,
                ord=index,
                text=text,
                tokens=_tokens(text),
                children=children,
            )
        )
    return drafts


def _promoted_heading(
    line: str, prev_blank: bool, next_blank: bool, saw_content: bool
) -> str | None:
    stripped = line.strip()
    # Old Gutenberg files wrap headings in =…= ("=XXVII.="); unwrap them.
    if len(stripped) >= 3 and stripped.startswith("=") and stripped.endswith("="):
        stripped = stripped[1:-1].strip()
    if not prev_blank or not next_blank or not stripped or len(stripped) > 80:
        return None
    if _METADATA_RE.match(stripped):
        return None
    # Chapter markers and standalone roman numerals are unambiguous; the
    # short-title heuristic below is not, so it may not fire on the
    # document's first content line (a title, not a section).
    if _CHAPTER_RE.match(stripped) or _CJK_CHAPTER_RE.match(stripped) or _ROMAN_RE.match(stripped):
        return stripped
    if (
        saw_content
        and len(stripped) <= 60
        and len(stripped.split()) <= 12
        and not line[:1].isspace()
        and stripped[0] not in "-*>|~`[\"'“”「『(〔"
        and stripped[-1] not in "\"'”’」』)】〔"
        and "|" not in stripped
        and not re.match(r"\d+[.)]\s", stripped)
        and stripped[-1] not in ".!?…:;,。！？；："
        and not stripped.islower()
        and re.search(r"[\wÀ-ɏぁ-ゟ゠-ヿ一-鿿]", stripped)
    ):
        return stripped
    return None


def _blocks(markdown: str) -> list[_Block]:
    path: list[str] = []
    pending: list[str] = []
    blocks: list[_Block] = []
    saw_content = False

    def flush() -> None:
        text = "\n".join(pending).strip()
        pending.clear()
        if not text:
            return
        for part in re.split(r"\n\s*\n", text):
            part = part.strip()
            if part:
                blocks.append(_Block(" > ".join(path), escape_source_tags(part)))

    lines = markdown.split("\n")
    prev_blank = True
    for index, line in enumerate(lines):
        next_blank = index + 1 >= len(lines) or not lines[index + 1].strip()
        match = _HEADING_RE.match(line)
        promoted = None if match else _promoted_heading(line, prev_blank, next_blank, saw_content)
        if match is not None:
            flush()
            level = len(match.group(1))
            path = [*path[: level - 1], match.group(2).strip()]
        elif promoted is not None:
            flush()
            path = [promoted]
        else:
            pending.append(line)
            if line.strip():
                saw_content = True
        prev_blank = not line.strip()
    flush()
    return blocks


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    pos = 0
    separators: list[re.Match[str] | None] = [*re.finditer(r"\n[ \t]*\n", text), None]
    for separator in separators:
        end = separator.start() if separator else len(text)
        part = text[pos:end]
        if part.strip():
            lead = len(part) - len(part.lstrip())
            trail = len(part) - len(part.rstrip())
            spans.append((pos + lead, end - trail))
        pos = separator.end() if separator else len(text)
    return spans


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENT_BOUNDARY.finditer(text):
        if match.group(1) is not None:
            end = match.end(2)
            terminal = match.start(1)
            word_start = max(text.rfind(" ", 0, terminal), text.rfind("\n", 0, terminal)) + 1
            if text[word_start : terminal + 1] in _ABBREVIATIONS:
                continue
        else:
            end = match.end(5)
        if text[start:end].strip():
            spans.append((start, end))
        start = end
    if text[start:].strip():
        spans.append((start, len(text)))
    return spans


def _char_pieces(text: str, start: int, end: int, limit: int) -> list[_Unit]:
    pieces: list[_Unit] = []
    pos = start
    while pos < end:
        cut = _max_end(text, pos, limit)
        if cut <= pos:
            cut = min(pos + 1, end)
        pieces.append(_Unit(pos, cut, _tokens(text[pos:cut])))
        pos = cut
    return pieces


def _hard_split(text: str, start: int, end: int, limit: int) -> list[_Unit]:
    """Oversized sentence: word boundaries, or characters when a single
    word (CJK, unbroken strings) still exceeds the limit."""
    words = [(m.start() + start, m.end() + start) for m in re.finditer(r"\S+", text[start:end])]
    if len(words) < 2:
        return _char_pieces(text, start, end, limit)
    counts = [_tokens(text[s:e]) for s, e in words]
    pieces: list[_Unit] = []
    i = 0
    while i < len(words):
        if counts[i] > limit:
            pieces.extend(_char_pieces(text, words[i][0], words[i][1], limit))
            i += 1
            continue
        used, j = counts[i], i + 1
        while j < len(words) and used + counts[j] <= limit:
            used += counts[j]
            j += 1
        pieces.append(_Unit(words[i][0], words[j - 1][1], used))
        i = j
    return pieces


def _units(text: str, limit: int) -> list[_Unit]:
    """Recursive cut: whole paragraphs, else whole sentences, else
    hard-split pieces — every unit is at most `limit` tokens."""
    units: list[_Unit] = []
    for p_start, p_end in _paragraph_spans(text):
        para_tokens = _tokens(text[p_start:p_end])
        if para_tokens <= limit:
            units.append(_Unit(p_start, p_end, para_tokens))
            continue
        for s_start, s_end in _sentence_spans(text[p_start:p_end]):
            sent_start, sent_end = p_start + s_start, p_start + s_end
            sent_tokens = _tokens(text[sent_start:sent_end])
            if sent_tokens <= limit:
                units.append(_Unit(sent_start, sent_end, sent_tokens))
            else:
                units.extend(_hard_split(text, sent_start, sent_end, limit))
    return units


def _pack_windows(units: list[_Unit], limit: int) -> list[tuple[int, int]]:
    """Greedy [start, end) unit ranges, each within `limit` tokens."""
    windows: list[tuple[int, int]] = []
    i = 0
    while i < len(units):
        used, j = units[i].tokens, i + 1
        while j < len(units) and used + units[j].tokens <= limit:
            used += units[j].tokens
            j += 1
        windows.append((i, j))
        i = j
    return windows


def _tail_units(units: list[_Unit], window: tuple[int, int]) -> int:
    """Index of the first unit of `window`'s trailing-sentence overlap, or
    the window's end when no whole unit fits the budget."""
    start, end = window
    total, first = 0, end
    for index in range(end - 1, start, -1):
        if total + units[index].tokens > CHILD_OVERLAP_TOKENS:
            break
        total += units[index].tokens
        first = index
    return first


def _tail_text(text: str) -> str:
    """The section's trailing whole sentences within the overlap budget —
    the next section's first child starts with them."""
    units = _units(text, CHILD_TOKENS)
    if not units:
        return ""
    first = _tail_units(units, (0, len(units)))
    if first >= len(units):
        return ""
    return text[units[first].start : units[-1].end].strip()


def _children(text: str, page_texts: list[str], overlap_prefix: str = "") -> list[ChunkDraft]:
    if _tokens(text) <= CHILD_TOKENS and not overlap_prefix:
        return [ChunkDraft(ord=0, page=_page_for_text(text, page_texts), text=text)]

    units = _units(text, CHILD_TOKENS)
    if not units:
        return [ChunkDraft(ord=0, page=_page_for_text(text, page_texts), text=text.strip())]
    windows = _pack_windows(units, CHILD_TOKENS)
    starts = [window[0] for window in windows]
    for k in range(1, len(windows)):
        starts[k] = min(starts[k], _tail_units(units, windows[k - 1]))

    drafts: list[ChunkDraft] = []
    ends = [w[1] for w in windows]
    for k, (start, end) in enumerate(zip(starts, ends, strict=True)):
        core = text[units[start].start : units[end - 1].end].strip()
        child_text = f"{overlap_prefix}\n{core}" if k == 0 and overlap_prefix else core
        page_source = core if k == 0 and overlap_prefix else child_text
        if child_text:
            page = _page_for_text(page_source, page_texts)
            drafts.append(ChunkDraft(ord=len(drafts), page=page, text=child_text))
    return drafts


def _split_to_limit(text: str, limit: int) -> list[str]:
    units = _units(text, limit)
    if not units:
        return []
    pieces: list[str] = []
    for start, end in _pack_windows(units, limit):
        pieces.append(text[units[start].start : units[end - 1].end])
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
