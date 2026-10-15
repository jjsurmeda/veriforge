"""Summarisation (TRD §9.1 step 6): one summary per section, one per document.

Built on the small model, in the ingest pipeline, for **new** documents. The 32
documents already in the corpus are covered by `scripts/backfill_summaries.py`,
which is resumable and does not re-embed any chunk.

**The document summary is built from the section summaries, not from the
text.** Summarising 2,000 tokens of a chapter costs several times what
summarising a section's 300 does, it is a second copy of material that already
has a summary, and the question a document summary has to answer — "what is
this book about" — wants the arc across sections rather than a detailed recap
of whichever section went first.

Everything is a single batched `complete` call per document, both levels, so a
new upload costs one extra round trip rather than 1,723. The call is optional
in the sense that a summarisation failure must not fail an ingest: the document
is already indexed and usable without summaries, and the backfill will pick it
up. That is a deliberate asymmetry — an index that only half-exists is the
normal state of a resumable backfill, and one that made the document unreadable
until it completed would be worse.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from config import get_settings

logger = logging.getLogger(__name__)

#: The role summaries are written under, so they get their own output cap and
#: their own usage line. A section summary is ~80 words; six of them plus a
#: document summary fit inside the rewriter's 2,048 comfortably, and a role of
#: its own means a summarisation failure is attributable in the usage ledger.
SUMMARY_ROLE = "summariser"

#: Cap on the characters of section text handed to the summariser. A section is
#: already capped at 2,000 tokens by the chunker; this is the cheap guard that
#: stops one pathological section from being the whole prompt.
SECTION_INPUT_CHARS = 6_000

#: Cap on section summaries handed to the document summary. Thirty-two covers
#: every book in this corpus's largest section count with room, and the point
#: of the cap is that a 400-section technical manual does not produce a prompt
#: the small model cannot hold.
DOCUMENT_INPUT_SECTIONS = 32

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class SummaryError(Exception):
    """The summariser returned something unusable."""


@dataclass(frozen=True)
class SectionSummary:
    """One section's summary, ready to be written."""

    section_ord: int
    heading_path: str
    text: str


@dataclass(frozen=True)
class DocumentSummaries:
    """Everything one document needs: one summary per section, plus one for the
    document itself."""

    sections: list[SectionSummary]
    document: str


def build_summary_prompt(
    *, document_title: str, sections: list[tuple[int, str, str]]
) -> str:
    """One prompt, both levels, one call.

    `sections` is `(ord, heading_path, text)`. The JSON object it asks for has
    one key per section's `ord` and a `document` key, which is why this returns
    a single string rather than a section prompt and a document prompt: two
    prompts means two calls, two chances to fail, and a document summary that
    is not in step with its sections.
    """
    lines = [
        "You write short reference summaries for a document search index.",
        "Write each summary as plain prose. Do not address the reader, do not "
        "ask questions, and do not mention that a summary is being written.",
        "",
        f"[document]\n{document_title}",
        "",
        "[sections]",
    ]
    included = sections[:DOCUMENT_INPUT_SECTIONS]
    for ord_, heading_path, text in included:
        lines.append(f"--- section {ord_} ---")
        if heading_path:
            lines.append(heading_path)
        lines.append(text[:SECTION_INPUT_CHARS])
        lines.append("")
    lines.append(
        "Respond with a single JSON object and nothing else, of the form:"
    )
    lines.append(
        '{"sections": {"<section ord>": "<one paragraph, 40-80 words>"}, '
        '"document": "<one paragraph, 60-120 words: what this document is and '
        'the arc it follows>"}'
    )
    lines.append(
        f"Include a key for each of the {len(included)} section numbers above, "
        "and no others. Ground every statement in the text you were given."
    )
    return "\n".join(lines)


def parse_summaries(raw: str, sections: list[tuple[int, str, str]]) -> DocumentSummaries:
    """The model's reply into rows, or a named failure.

    Two things it refuses to do rather than guess at: a section with no summary
    (one missing section is a gap in the index that would otherwise be silent),
    and a document with no summary (the whole point of the second level).
    """
    text = raw.strip()
    fenced = _FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SummaryError(f"summariser returned non-JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SummaryError("summariser returned non-object JSON")
    by_ord = payload.get("sections")
    if not isinstance(by_ord, dict):
        raise SummaryError("summariser returned no sections object")
    out: list[SectionSummary] = []
    for ord_, heading_path, _text in sections[:DOCUMENT_INPUT_SECTIONS]:
        value = by_ord.get(str(ord_))
        if not isinstance(value, str) or not value.strip():
            raise SummaryError(f"summariser returned no summary for section {ord_}")
        out.append(
            SectionSummary(section_ord=ord_, heading_path=heading_path, text=value.strip())
        )
    document = payload.get("document")
    if not isinstance(document, str) or not document.strip():
        raise SummaryError("summariser returned no document summary")
    return DocumentSummaries(sections=out, document=document.strip())


async def summarise_document(
    *,
    document_title: str,
    sections: list[tuple[int, str, str]],
    complete_fn: Callable[..., Awaitable[str]],
) -> DocumentSummaries:
    """Both levels of one document's summaries, in one call."""
    if not sections:
        raise SummaryError(f"{document_title!r} has no sections to summarise")
    raw = await complete_fn(
        litellm_model=get_settings().small_model,
        messages=[
            {
                "role": "system",
                "content": build_summary_prompt(
                    document_title=document_title, sections=sections
                ),
            }
        ],
        metadata={"job": "summarise", "role": SUMMARY_ROLE},
        temperature=0,
    )
    return parse_summaries(raw, sections)
