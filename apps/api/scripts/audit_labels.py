"""Label audit for every eval item (testing.md: "Test data is audited like
code").

Takes a set file and the corpus it is scored against, and for each item
records the proof that its label is right, or the finding that it is wrong:

- `answer` / `library` items: the query that finds the answering passage
  (hits > 0) and the passage quoted, plus where each accepted `mention`
  string is actually attested in the corpus.
- `not_in_sources` items: the zero-hit queries over **every chunk the test
  user can retrieve**, with the false hits spot-read and named.
- every item: the second-referent check (KI-27) — does the corpus support a
  second valid answer?

The rule this script exists to enforce: **a label that contradicts the
corpus is a test bug — fix the item, never the pipeline.** Nothing here
compares an item against what the pipeline answered; the pipeline is not
consulted.

Usage:

    uv run python scripts/audit_labels.py ../../evals/acceptance/books.json
    uv run python scripts/audit_labels.py ../../evals/seed/items.json --write-back

The scoring core (`audit_items`) is pure: it takes a `Corpus` of passages and
returns an `AuditReport`, so it is unit-testable without a database. Only
`corpus_from_db` touches Postgres.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --------------------------------------------------------------------------
# Tokenisation
# --------------------------------------------------------------------------

_LATIN = re.compile(r"[^\W\d_]+", re.UNICODE)
# A number is a token. `[^\W\d_]` excludes digits, so without this second pass
# every figure in the corpus was invisible to the audit and
# `answer_not_in_corpus` fired on each item whose answer *is* a number — which
# is most of a specification. Scanned in one pass with the words so the stream
# keeps its order: the phrase "1 640" must match "1 640" and not a "1" and a
# "640" that happen to sit in the same chunk.
_WORD_OR_DIGIT = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)
# CJK has no word boundaries. Character bigrams are the standard cheap
# approximation and are what a BM25 index over Chinese or Japanese text
# degenerates to anyway.
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
_CJK_RUN = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]+")

# Question words and the other glue that carries no retrievable content. A
# should-abstain proof that rests on "who" or "what" is not a proof.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "for",
        "from",
        "had",
        "has",
        "have",
        "having",
        "he",
        "her",
        "here",
        "hers",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "our",
        "out",
        "she",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "under",
        "until",
        "up",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "after",
        "again",
        "against",
        "all",
        "also",
        "am",
        "any",
        "because",
        "before",
        "below",
        "between",
        "both",
        "during",
        "each",
        "few",
        "further",
        "here",
        "itself",
        "just",
        "more",
        "most",
        "no",
        "nor",
        "not",
        "now",
        "only",
        "other",
        "over",
        "same",
        "too",
        "very",
    ]
)

QUOTE_CHARS = 400


def normalise(text: str) -> str:
    """Casefold and strip accents, so "Hôpital" and "hopital" are one token."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    """Latin words plus CJK bigrams, casefolded and accent-stripped.

    Single letters are still dropped: they carry no content. Digits are kept
    whatever their length — see `_WORD_OR_DIGIT`.
    """
    lowered = normalise(text)
    cjk_runs = _CJK_RUN.findall(lowered)
    # CJK characters match `[^\W\d_]` too, so they would be emitted a third
    # time as one whole "word". Strip them from the Latin pass first.
    latin_only = _CJK.sub(" ", lowered)
    tokens = [t for t in _WORD_OR_DIGIT.findall(latin_only) if len(t) > 1 or t.isdigit()]
    for run in cjk_runs:
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def stem(document_name: str) -> str:
    """A document name without its file suffix.

    "Pride and Prejudice.txt" -> "pride and prejudice". The corpus names its
    documents with their filenames, but an eval item names the work, so the
    two have to meet somewhere.
    """
    return normalise(Path(document_name).stem)


def content_terms(question: str) -> list[str]:
    """The retrievable content of a question, glue removed, longest first.

    Order matters for the abstention proof: the first term is the one the
    item is really about, and it is the one the corpus must not attest.
    """
    tokens = [t for t in tokenize(question) if t not in STOPWORDS]
    return sorted(set(tokens), key=lambda t: (-len(t), t))


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Passage:
    """One retrievable chunk. `document` is the document's human name."""

    document: str
    ord: int
    text: str


@dataclass
class Corpus:
    """Everything the test user can retrieve, searchable offline.

    Built once, then queried per item: the whole point is that a label is
    proven against *every* chunk in scope, not against what retrieval
    happened to rank.
    """

    passages: list[Passage] = field(default_factory=list)

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[str, int, str]]) -> Corpus:
        return cls([Passage(document=d, ord=o, text=t) for d, o, t in rows])

    def __post_init__(self) -> None:
        self._tokens: list[list[str]] = [tokenize(p.text) for p in self.passages]
        df: Counter[str] = Counter()
        for tokens in self._tokens:
            df.update(set(tokens))
        total = max(len(self.passages), 1)
        # BM25 rarity weight. Used only for ranking, never for deciding
        # whether a term is "distinctive" — a fixed rarity threshold gives a
        # different answer on a 7-passage fixture than on the books corpus.
        self._idf: dict[str, float] = {
            token: math.log(1 + total / count) for token, count in df.items()
        }

    def idf(self, token: str) -> float:
        """Rarity weight, floored so an unknown token still counts a little."""
        return self._idf.get(token, math.log(1 + max(len(self.passages), 1)))

    def __len__(self) -> int:
        return len(self.passages)

    def documents(self) -> set[str]:
        return {p.document for p in self.passages}

    def passages_containing(self, needle: str) -> list[Passage]:
        """Every passage whose token sequence holds `needle`'s.

        Matched on **token boundaries**, not as a raw substring. A zero-hit
        proof that reports `%van%` x1015 because "relevant" contains "van",
        and `%ahab%` x129 for a book that is not in the corpus, is worse than
        no proof at all — it manufactures false hits and hides the real ones.
        """
        wanted = tokenize(needle)
        if not wanted:
            return []
        if len(wanted) == 1:
            only = wanted[0]
            if _CJK.fullmatch(only):
                # A lone CJK character is never a token of a longer run, since
                # those tokenize to bigrams ('この髪' -> 'この', 'の髪'). An
                # item that names a single kanji — 髪, in 羅生門's "この髪を
                # 抜いてな" — would otherwise read as absent from a corpus that
                # contains it, which is the opposite of a proof.
                return [
                    p
                    for p, tokens in zip(self.passages, self._tokens, strict=True)
                    if any(only in token for token in tokens)
                ]
            return [
                p for p, tokens in zip(self.passages, self._tokens, strict=True) if only in tokens
            ]
        span = len(wanted)
        return [
            p
            for p, tokens in zip(self.passages, self._tokens, strict=True)
            if any(tokens[i : i + span] == wanted for i in range(len(tokens) - span + 1))
        ]

    def rank(self, question: str, *, top_k: int = 3) -> list[tuple[Passage, float]]:
        """BM25 over the question's content terms. Returns [] at zero hits."""
        terms = content_terms(question)
        if not terms:
            return []
        k1, b = 1.5, 0.75
        avg_len = sum(len(t) for t in self._tokens) / max(len(self._tokens), 1)
        scores: list[tuple[float, int]] = []
        for index, tokens in enumerate(self._tokens):
            counts = Counter(tokens)
            length = len(tokens) or 1
            score = 0.0
            for term in terms:
                freq = counts.get(term, 0)
                if not freq:
                    continue
                denom = freq + k1 * (1 - b + b * length / max(avg_len, 1e-9))
                score += self.idf(term) * freq * (k1 + 1) / denom
            if score > 0:
                scores.append((score, index))
        scores.sort(key=lambda pair: (-pair[0], pair[1]))
        return [(self.passages[index], score) for score, index in scores[:top_k]]


def quote_around(passage: Passage, terms: Sequence[str], *, width: int = QUOTE_CHARS) -> str:
    """A readable window of the passage around the best term match."""
    low = normalise(passage.text)
    first = min(
        (low.find(t) for t in terms if len(t) > 1 and low.find(t) >= 0),
        default=-1,
    )
    if first < 0:
        return passage.text[:width].replace("\n", " ").strip()
    start = max(0, first - width // 3)
    return passage.text[start : start + width].replace("\n", " ").strip()


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------

ANSWER_EXPECTS = frozenset({"answer", "library"})
ABSTAIN_EXPECTS = frozenset({"not_in_sources"})

FINDING_CODES = (
    "answer_not_in_corpus",  # a mention the item demands is nowhere in scope
    "answer_query_no_hit",  # the question retrieves nothing at all
    "underdetermined_source",  # mentions span documents and no `cite` pins one
    "abstain_false_hit",  # the question's rarest term IS attested in the corpus
)


@dataclass
class Finding:
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass
class ItemAudit:
    item_id: str
    expect: str
    question: str
    proof: str
    hits: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.item_id,
            "expect": self.expect,
            "hits": self.hits,
            "ok": self.ok,
            "findings": [f.as_dict() for f in self.findings],
            "proof": self.proof,
        }


def _question_of(item: dict[str, Any]) -> str:
    """The turn that carries the label — the last one for multi-turn items."""
    if "turns" in item:
        return str(item["turns"][-1])
    return str(item["question"])


def _expect_of(item: dict[str, Any]) -> str:
    if "expect" in item:
        return str(item["expect"])
    return "not_in_sources" if item.get("should_abstain") else "answer"


def _mentions_of(item: dict[str, Any]) -> list[str]:
    return [str(m) for m in item.get("mention", [])]


def _alt_mentions_of(item: dict[str, Any]) -> list[str]:
    return [str(m) for m in item.get("alt_mention", [])]


def audit_items(
    items: Sequence[dict[str, Any]],
    corpus: Corpus,
    *,
    abstain_term_limit: int = 12,
) -> list[ItemAudit]:
    """Audit every item against `corpus`. Pure — no database, no provider.

    `abstain_term_limit` caps how many of a question's terms the zero-hit
    proof enumerates, longest first: the rarest and longest term is what the
    item is about, and a 40-term dump of every question word is not a proof.
    """
    audits: list[ItemAudit] = []
    for item in items:
        question = _question_of(item)
        expect = _expect_of(item)
        mentions = _mentions_of(item)
        terms = content_terms(question)
        ranked = corpus.rank(question)
        findings: list[Finding] = []
        # A `library` item names a document ("Pride and Prejudice"), but the
        # corpus's documents are named with a suffix ("Pride and Prejudice.txt")
        # and an accent-bearing title ("Noli Me Tangere"). Compare on the
        # normalised stem, or the rule never fires and every library item is
        # reported as demanding a string the corpus cannot produce.
        document_names = {normalise(stem(d)) for d in corpus.documents()}

        if expect in ANSWER_EXPECTS:
            attested: list[tuple[str, Passage]] = []
            missing: list[str] = []
            for mention in mentions:
                found = corpus.passages_containing(mention)
                # A `library` item names a document, so the document name is a
                # legitimate attestation even with no passage repeating it.
                if not found and normalise(mention) in document_names:
                    continue
                if found:
                    attested.append((mention, found[0]))
                else:
                    missing.append(mention)
            # `alt_mention` is the same value written another way — "6400" for
            # the corpus's "6,400", "Soreheim" for "Sørheim". It has to be a
            # *spelling* of something the item already accepts, not a new fact:
            # an alt string the corpus never attests and whose mention-list twin
            # is also unattested would let an item smuggle in a second, unchecked
            # answer, which is the defect `answer_not_in_corpus` exists to catch.
            alt = _alt_mentions_of(item)
            unattested_alts = [
                a
                for a in alt
                if not corpus.passages_containing(a)
                and normalise(a) not in document_names
                and not any(corpus.passages_containing(m) for m in mentions)
            ]
            if unattested_alts:
                findings.append(
                    Finding(
                        "alt_mention_unattested",
                        f"alt_mention {unattested_alts!r} is accepted by the item but the "
                        "corpus attests neither it nor any `mention` string, so it is a second "
                        "unchecked answer rather than a spelling of an attested one. Add the "
                        "value to `mention`.",
                    )
                )
            # Every mention is unattested but an alt_mention spelled it a way
            # the corpus uses: report the alts instead of the misses.
            if missing and not attested and any(corpus.passages_containing(a) for a in alt):
                missing = []
            if missing:
                findings.append(
                    Finding(
                        "answer_not_in_corpus",
                        f"{len(missing)}/{len(mentions)} accepted mention(s) are attested "
                        f"nowhere in the {len(corpus)}-passage scope: {missing!r}. The item "
                        "demands a string the corpus cannot produce.",
                    )
                )
            if not ranked:
                findings.append(
                    Finding(
                        "answer_query_no_hit",
                        f"the question itself retrieves nothing over {len(corpus)} passages "
                        f"(content terms: {terms!r}).",
                    )
                )
            # The second-referent check (KI-27). What the script can honestly decide is
            # narrower than "is this ambiguous": it cannot read the passages
            # and tell that the corpus answers the question two ways. What it
            # CAN see is whether the item pins the source at all. Mentions
            # attested in several documents, with no `cite` list to say which
            # document the answer must come from, leave the item satisfied by
            # a passage from the wrong book — that is the mechanism behind
            # KI-36, where the cite check alone was too weak. So this is a
            # finding about the item's checks, and the cross-document map goes
            # in the proof for a human to judge the KI-27 question.
            source_documents = sorted({p.document for _, p in attested})
            if (
                len(attested) > 1
                and len(source_documents) > 1
                and not item.get("cite")
                and expect != "library"
            ):
                # A `library` item is *supposed* to name every document in the
                # library, so "the accepted mentions span five documents" is the
                # item working correctly, not a finding. Without the exemption
                # the rule reported a correct answer as a defect, which is worse
                # than not having the rule: it teaches a reader to ignore it.
                findings.append(
                    Finding(
                        "underdetermined_source",
                        f"accepted mentions are attested in {len(source_documents)} documents "
                        f"({source_documents!r}) and the item declares no `cite`, so nothing "
                        "stops a passage from the wrong book satisfying it. Name the source, or "
                        "check whether the corpus answers this two ways (KI-27).",
                    )
                )
            proof = _proof_answer(item, expect, ranked, attested, corpus, terms)
            hits = len(ranked)

        elif expect in ABSTAIN_EXPECTS:
            # Every content term, longest first, capped. No IDF floor: a fixed
            # rarity threshold means a different answer on a 7-passage fixture
            # than on 10,733 books passages, and a term the audit silently
            # skipped is a term nobody spot-reads. The finding below picks the
            # specific one by hit count instead.
            checked = terms[:abstain_term_limit]
            per_term: dict[str, list[Passage]] = {t: corpus.passages_containing(t) for t in checked}
            false_hits = {t: ps for t, ps in per_term.items() if ps}
            # The rarest attested term is the one worth a human's time. A
            # should-abstain item asks about something the corpus does not
            # have, so the signal that the label may be wrong is that the
            # question's most corpus-specific content term IS attested.
            #
            # "Most specific" means the *rarest attested* term, not merely any
            # attested term. Co-occurrence does not rescue it either:
            # 'sherlock' and 'holmes' co-occur in every passage that carries
            # either, which says the corpus owns a book about Holmes and
            # nothing about whether it holds the Afghanistan deduction.
            # Spot-reads after this rule fired on the books corpus:
            #   'afghanistan' x1 -> Watson's own "camp life in Afghanistan",
            #                        a statement of the fact but not of how
            #                        Holmes deduced it (a real question);
            #   'australia' x3   -> Alice asking "is this New Zealand or
            #                        Australia?" (false hit);
            #   'whale' x3       -> Frankenstein's whalers (false hit);
            #   'harriet' x3     -> Pride and Prejudice (false hit).
            # Four flags on fourteen items, each a note in the item's proof
            # once a human has read it — the prompt's "false hits spot-read
            # and noted".
            attested_terms = {t: ps for t, ps in false_hits.items() if ps}
            if attested_terms:
                # `content_terms` is already longest-first, so among equal
                # hit counts the first minimum is the most corpus-identifying
                # term available — no separate tie-break needed.
                rarest = min(attested_terms, key=lambda t: len(attested_terms[t]))
                findings.append(
                    Finding(
                        "abstain_false_hit",
                        f"the question's most corpus-specific term {rarest!r} is attested in "
                        f"{len(attested_terms[rarest])} passage(s) of "
                        f"{sorted({p.document for p in attested_terms[rarest]})!r}. Spot-read "
                        "before trusting the label.",
                    )
                )

            proof = _proof_abstain(question, checked, per_term, len(corpus))
            hits = len(corpus.rank(question))
        else:
            proof = (
                f"Class {expect!r} is checked against the run's behaviour, not against a "
                f"corpus passage, so no hit proof applies ({len(corpus)} passages in scope)."
            )
            hits = len(corpus.rank(question))

        audits.append(
            ItemAudit(
                item_id=str(item.get("id", question[:40])),
                expect=expect,
                question=question,
                proof=proof,
                hits=hits,
                findings=findings,
            )
        )
    return audits


def _proof_answer(
    item: dict[str, Any],
    expect: str,
    ranked: list[tuple[Passage, float]],
    attested: list[tuple[str, Passage]],
    corpus: Corpus,
    terms: Sequence[str],
) -> str:
    scope_size = len(corpus)
    parts = [
        f"Audited by scripts/audit_labels.py over all {scope_size} passages the test user can "
        f"retrieve (testing.md: 'Test data is audited like code'). Expect {expect!r}."
    ]
    if ranked:
        passage, score = ranked[0]
        parts.append(
            f"Query {_question_of(item)!r} (content terms {list(terms)!r}) hits "
            f"{len(ranked)}+ passages; top hit {passage.document!r} ord {passage.ord} "
            f'(score {score:.2f}): "{quote_around(passage, terms)}"'
        )
    else:
        parts.append(f"Query {_question_of(item)!r} hits 0 passages.")
    for mention, passage in attested[:6]:
        others = sorted({p.document for p in corpus.passages_containing(mention)})
        parts.append(
            f"mention {mention!r} attested at {passage.document!r} ord {passage.ord}: "
            f'"{quote_around(passage, [mention])}" (attested in {len(others)} document(s)'
            + (f": {others!r}" if len(others) > 1 else "")
            + ")"
        )
    if not attested and item.get("mention"):
        parts.append("Item declares no `mention` list, so the answer text is unchecked.")
    reference = item.get("reference_answer")
    if reference:
        parts.append(f"reference_answer: {reference}")
    return " ".join(parts)


def _proof_abstain(
    question: str, checked: Sequence[str], per_term: dict[str, list[Passage]], scope_size: int
) -> str:
    parts = [
        f"Audited by scripts/audit_labels.py over all {scope_size} passages the test user can "
        "retrieve. Expect not_in_sources, so every content term must be absent (or spot-read "
        "and named as a false hit)."
    ]
    parts.append(f"Question {question!r}")
    for term in checked:
        passages = per_term.get(term, [])
        if not passages:
            parts.append(f"{term!r}: 0 hits")
            continue
        documents = sorted({p.document for p in passages})
        parts.append(
            f"{term!r}: {len(passages)} hit(s) in {documents!r} — SPOT-READ: "
            + " | ".join(
                f'{p.document!r} ord {p.ord}: "{quote_around(p, [term], width=180)}"'
                for p in passages[:3]
            )
        )
    return " ".join(parts)


@dataclass
class AuditReport:
    set_name: str
    corpus_description: str
    scope_size: int
    audits: list[ItemAudit] = field(default_factory=list)

    def findings(self) -> list[tuple[str, Finding]]:
        return [(a.item_id, f) for a in self.audits for f in a.findings]

    def summary(self) -> dict[str, Any]:
        by_code: Counter[str] = Counter(f.code for _, f in self.findings())
        return {
            "set": self.set_name,
            "corpus": self.corpus_description,
            "passages_in_scope": self.scope_size,
            "items": len(self.audits),
            "clean": sum(1 for a in self.audits if a.ok),
            "findings": dict(sorted(by_code.items())),
            "total_findings": sum(by_code.values()),
        }


# --------------------------------------------------------------------------
# Loading a corpus from the database
# --------------------------------------------------------------------------


def corpus_from_db(
    database_url: str,
    *,
    user_email: str | None = None,
    collection: str | None = None,
) -> tuple[Corpus, str]:
    """Every chunk a fresh test user can retrieve, read straight out of SQL.

    Deliberately not the retrieval stack: the audit asks what the corpus
    *contains*, so it reads the same rows `retrieval/filters.py::build_scope`
    would admit (a shared collection, or one the user owns) and scores them
    offline. Retrieval ranking is the pipeline's business, not the label's.

    `collection` narrows to one collection by name. That is the right scope for
    a set with its own corpus: the seed items are about `eval-seed-corpus`,
    and auditing them over everything a shared user can retrieve would report
    the books' contents as evidence about the AW-2000 manual.
    """
    import asyncio

    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _load() -> list[tuple[str, int, str]]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as conn:
                user_clause = ""
                collection_clause = ""
                params: dict[str, Any] = {}
                if user_email:
                    user_clause = " OR col.owner_id = (SELECT id FROM users WHERE email = :e)"
                    params["e"] = user_email
                if collection:
                    collection_clause = " AND col.name = :c"
                    params["c"] = collection
                result = await conn.execute(
                    sa_text(
                        "SELECT d.name, ch.ord, ch.text FROM chunks ch "  # noqa: S608
                        "JOIN documents d ON d.id = ch.document_id "
                        "JOIN collections col ON col.id = d.collection_id "
                        "WHERE d.status = 'ready' "
                        f"AND (col.visibility = 'shared'{user_clause}{collection_clause}) "
                        "ORDER BY d.name, ch.ord"
                    ),
                    params,
                )
                return [(row[0], int(row[1]), row[2]) for row in result]
        finally:
            await engine.dispose()

    rows = asyncio.run(_load())
    parts = ["every visibility='shared' collection (what a fresh test user sees)"]
    if user_email:
        parts[0] = f"shared collections + collections owned by {user_email}"
    if collection:
        parts.append(f"narrowed to the {collection!r} collection")
    return Corpus.from_rows(rows), ", ".join(parts)


def corpus_from_files(directory: Path) -> Corpus:
    """A corpus built straight from the set's own markdown files.

    For a set whose corpus is not in a database — the counterfactual set ships
    its documents in the repo — this is the corpus the ingest pipeline would
    produce: `ingest.chunk.chunk_document` is the production chunker, so the
    passages audited here are the passages that would be retrievable. Nothing is
    embedded, so the audit needs no database, no provider and no credits.
    """
    from ingest.chunk import chunk_document

    rows: list[tuple[str, int, str]] = []
    for path in sorted(directory.glob("*.md")):
        for section in chunk_document(path.read_text(encoding="utf-8"), []):
            drafts = list(section.children)
            if drafts:
                for draft in drafts:
                    rows.append((path.name, draft.ord, draft.text))
            else:
                rows.append((path.name, section.ord, section.text))
    return Corpus.from_rows(rows)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def load_set(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def write_back(path: Path, audits: Sequence[ItemAudit]) -> int:
    """Stamp each audited item's `proof` into the set file, in place.

    Only fills a missing or empty `proof`: a hand-written proof from a human
    (outside-whitman-lilacs) is never overwritten, because it carries the
    spot-read notes only that person can make.
    """
    payload = load_set(path)
    by_id = {a.item_id: a for a in audits}
    written = 0
    for item in payload["items"]:
        audit = by_id.get(str(item.get("id")))
        if audit is None:
            continue
        if item.get("proof"):
            continue
        item["proof"] = audit.proof
        written += 1
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return written


def print_report(report: AuditReport) -> None:
    summary = report.summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print()
    for audit in report.audits:
        mark = "ok  " if audit.ok else "FLAG"
        print(f"{mark} {audit.item_id:<28} {audit.expect:<15} hits={audit.hits}")
        for finding in audit.findings:
            print(f"       [{finding.code}] {finding.detail}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit eval item labels against their corpus.")
    parser.add_argument("set_file", type=Path)
    parser.add_argument(
        "--user",
        default=None,
        help="also include collections this user owns (default: shared collections only, "
        "which is what a freshly signed-up test user retrieves)",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="audit against one collection by name (default: everything a test user can "
        "retrieve). Use it for a set with its own corpus.",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help="audit against the markdown files in this directory instead of the database, "
        "using the production chunker. For a set whose corpus ships in the repo.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="defaults to $DATABASE_URL",
    )
    parser.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    parser.add_argument(
        "--write-back",
        action="store_true",
        help="stamp the generated proof into the set file (never overwrites a hand-written proof)",
    )
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="exit 1 when any item carries a finding. A spot-read finding is "
        "recorded in the item, not fixed away, so this is for CI over a set "
        "whose items are all annotated.",
    )
    args = parser.parse_args(argv)

    import os

    payload = load_set(args.set_file)
    if args.corpus_dir is not None:
        corpus = corpus_from_files(args.corpus_dir)
        description = (
            f"the {len(list(args.corpus_dir.glob('*.md')))} markdown files in {args.corpus_dir}"
        )
    else:
        database_url = args.database_url or os.environ.get("DATABASE_URL")
        if not database_url:
            raise SystemExit("set DATABASE_URL, pass --database-url, or pass --corpus-dir")
        corpus, description = corpus_from_db(
            database_url, user_email=args.user, collection=args.collection
        )
    audits = audit_items(payload["items"], corpus)
    report = AuditReport(
        set_name=str(payload.get("dataset") or args.set_file.stem),
        corpus_description=description,
        scope_size=len(corpus),
        audits=audits,
    )
    print_report(report)
    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "summary": report.summary(),
                    "items": [a.as_dict() for a in report.audits],
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nreport: {args.out}")
    if args.write_back:
        written = write_back(args.set_file, audits)
        print(f"proof written to {written} item(s) in {args.set_file}")
    # A finding is not a crash: the audit reports, a human fixes the label.
    if args.require_clean and report.findings():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
