"""Tests for scripts/audit_labels.py (P1b item 1).

testing.md: "Test data is audited like code." These pin the two failures the
audit exists to catch — an item that demands a string the corpus cannot
produce, and an item whose corpus answers two ways (KI-27) — plus the
zero-hit proof for should-abstain items.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.audit_labels import (
    Corpus,
    audit_items,
    content_terms,
    quote_around,
    tokenize,
    write_back,
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_labels.py"


@pytest.fixture
def corpus() -> Corpus:
    """A tiny corpus with two documents, one of which names two referents."""
    return Corpus.from_rows(
        [
            (
                "Pride and Prejudice.txt",
                0,
                "Walt Whitman has a fine distinction between "
                "loving by allowance and loving with personal love.",
            ),
            (
                "Pride and Prejudice.txt",
                1,
                "Elizabeth Bennet is the protagonist, and her "
                "sister Jane is the elder, married to Mr Bingley.",
            ),
            (
                "frankeNstein.txt",
                0,
                "Victor Frankenstein wanders at the entrance of the cemetery at Geneva.",
            ),
        ]
    )


def test_answer_item_proof_quotes_the_answering_passage(corpus: Corpus) -> None:
    items = [
        {
            "id": "wen",
            "turns": ["What does Whitman say about loving by allowance?"],
            "expect": "answer",
            "mention": ["allowance"],
        }
    ]
    audit = audit_items(items, corpus)[0]
    assert audit.hits > 0, "the question must retrieve the passage"
    assert "Pride and Prejudice.txt" in audit.proof
    assert "allowance" in audit.proof
    assert audit.findings == []


def test_answer_item_demanding_an_unattested_mention_is_flagged(corpus: Corpus) -> None:
    """The KI-36 shape: a correct-sounding item whose mention is not in the corpus."""
    items = [
        {
            "id": "fact-bad",
            "turns": ["Who is Weena in The Time Machine?"],
            "expect": "answer",
            "mention": ["Eloi"],
        }
    ]
    audit = audit_items(items, corpus)[0]
    codes = [f.code for f in audit.findings]
    assert "answer_not_in_corpus" in codes, "an unattested mention must be a finding"
    finding = next(f for f in audit.findings if f.code == "answer_not_in_corpus")
    assert "Eloi" in finding.detail


def test_item_whose_mentions_span_documents_and_pin_no_source_is_flagged(
    corpus: Corpus,
) -> None:
    """KI-27/KI-36: nothing stops a passage from the wrong book satisfying it."""
    items = [
        {
            "id": "amb",
            "turns": ["Who is the elder Bennet sister?"],
            "expect": "answer",
            "mention": ["Jane", "Victor"],
        }
    ]
    audit = audit_items(items, corpus)[0]
    assert "underdetermined_source" in [f.code for f in audit.findings]
    # The cross-document map goes in the proof too, so a human can judge the
    # KI-27 question the script cannot decide: each mention names the document
    # that attests it, which here are two different books.
    assert "'Jane' attested at 'Pride and Prejudice.txt'" in audit.proof
    assert "'Victor' attested at 'frankeNstein.txt'" in audit.proof


def test_cite_list_clears_the_underdetermined_source_finding(corpus: Corpus) -> None:
    items = [
        {
            "id": "pinned",
            "turns": ["Who is the elder Bennet sister?"],
            "expect": "answer",
            "mention": ["Jane", "Victor"],
            "cite": ["Pride and Prejudice"],
        }
    ]
    audit = audit_items(items, corpus)[0]
    assert "underdetermined_source" not in [f.code for f in audit.findings]


def test_substring_matching_is_not_used_for_term_proofs() -> None:
    """'ahab' must not match inside 'ahead'; a false-hit proof built on
    substring hits manufactures hits that are not in the corpus."""
    corpus = Corpus.from_rows([("noli.txt", 0, "Look ahead, she said, and go behind.")])
    assert corpus.passages_containing("ahab") == []
    assert len(corpus.passages_containing("ahead")) == 1


def test_a_multi_word_needle_must_appear_in_order() -> None:
    """'the allowance Whitman' must not match a passage that has all three
    words in some other order — an unordered match invents a quote."""
    corpus = Corpus.from_rows(
        [("a.txt", 0, "Whitman is mentioned in the margin, and allowance is a separate note.")]
    )
    assert corpus.passages_containing("the allowance Whitman") == []
    assert len(corpus.passages_containing("Whitman is mentioned")) == 1


def test_a_lone_cjk_character_is_found_inside_a_bigram() -> None:
    """'この髪を抜いてな' tokenizes to the bigrams 'この' and 'の髪', so the
    single kanji 髪 is not a token of that passage. An item naming one kanji
    must still find it, or a proof reports the corpus missing what it holds."""
    corpus = Corpus.from_rows(
        [("羅生門.txt", 0, "「この髪を抜いてな、この女の髪を抜いてな」と女は言った。")]
    )
    assert len(corpus.passages_containing("髪")) == 1
    assert len(corpus.passages_containing("女の髪")) == 1
    assert corpus.passages_containing(" Donaldson") == []


def test_a_needle_may_not_span_a_token_boundary() -> None:
    """Matching "grandfather" against 'grand father' is a real false hit: OCR
    and line-wrapped text split hyphenated and compound words across chunks,
    so a zero-hit proof built on joined-text search invents the corpus."""
    corpus = Corpus.from_rows([("kafka.txt", 0, "His grand father kept the shop.")])
    assert corpus.passages_containing("grandfather") == []
    assert len(corpus.passages_containing("grand father")) == 1


def test_a_glue_word_hit_is_not_chosen_as_the_specific_term() -> None:
    """The finding names the RAREST attested term, not the most frequent one.

    'end' appears in every passage and 'rhododendron' in two; the question is
    about the festival, so the proof has to lead a human to the festival. If
    the rule reported the most-hit term instead, every finding on a large
    corpus would point at ordinary English.
    """
    corpus = Corpus.from_rows(
        [("a.txt", i, "at the end of the day they end it") for i in range(40)]
        + [("b.txt", i, "about Rhododendron Festival planning") for i in range(2)]
    )
    items = [
        {
            "id": "outside-festival",
            "turns": ["When is the Rhododendron Festival held?"],
            "expect": "not_in_sources",
        }
    ]
    audit = audit_items(items, corpus)[0]
    assert [f.code for f in audit.findings] == ["abstain_false_hit"]
    assert "rhododendron" in audit.findings[0].detail


def test_an_item_with_no_attested_term_is_never_flagged() -> None:
    """Every content term absent is the proof the item wants. Nothing to
    spot-read, so nothing to flag — the clean case must stay clean."""
    corpus = Corpus.from_rows([("a.txt", 0, "unrelated prose about a gate and a garden")])
    items = [
        {
            "id": "outside-lilacs",
            "turns": ["What does the Kestrel Bridge span?"],
            "expect": "not_in_sources",
        }
    ]
    audit = audit_items(items, corpus)[0]
    assert audit.findings == [], audit.findings
    assert "0 hits" in audit.proof


def test_the_rarest_term_wins_even_when_a_commoner_one_is_more_specific_to_read() -> None:
    """Ties on hit count break on term length, so the reported term is the
    most corpus-identifying one available.

    The tie-break is `content_terms` being longest-first, which is why this
    fixture puts the longer rare term first rather than relying on a separate
    comparison: with 'reichenbach' (10) and 'moriarty' (8) both at one hit,
    the reported term must be the longer one and never 'holmes' (2 hits).
    """
    corpus = Corpus.from_rows(
        [
            ("a.txt", 0, "Holmes and Moriarty at the Reichenbach Falls"),
            ("b.txt", 0, "more prose about Holmes, and more about Holmes"),
        ]
    )
    items = [
        {
            "id": "outside-moriarty",
            "turns": ["Who is Professor Moriarty at the Reichenbach Falls?"],
            "expect": "not_in_sources",
        }
    ]
    audit = audit_items(items, corpus)[0]
    assert [f.code for f in audit.findings] == ["abstain_false_hit"]
    detail = audit.findings[0].detail
    # 'reichenbach' and 'moriarty' tie at one hit each, so the longer term
    # wins; 'holmes' appears in both passages and loses on hit count.
    assert "reichenbach" in detail
    assert "moriarty" not in detail
    assert "holmes" not in detail


def test_a_corpus_that_owns_a_book_about_a_character_still_needs_reading() -> None:
    """The case the rule is honest about: 'sherlock'/'holmes'/'watson' are all
    attested in the Holmes corpus, so the item IS flagged — and the finding
    says only 'spot-read before trusting the label', not 'the label is
    wrong'. Deciding it is a human's job, and the finding must not pretend
    otherwise."""
    corpus = Corpus.from_rows(
        [
            (
                "The Adventures of Sherlock Holmes.txt",
                index,
                "Sherlock Holmes and Watson were in a case, and Holmes spoke",
            )
            for index in range(6)
        ]
        + [("Other.txt", 0, "an unrelated chapter about a garden and a gate")]
    )
    items = [
        {
            "id": "outside-study-in-scarlet",
            "turns": ["How does Sherlock Holmes figure out Watson had been in Afghanistan?"],
            "expect": "not_in_sources",
        }
    ]
    audit = audit_items(items, corpus)[0]
    assert [f.code for f in audit.findings] == ["abstain_false_hit"]
    assert "Spot-read" in audit.findings[0].detail


def test_a_corpus_wide_word_is_never_the_term_reported() -> None:
    """'end' in every passage says nothing about whether the corpus covers
    this question, so it must never be the term a finding names."""
    # 'end' hits every passage; 'captain', 'whale' and 'ahab' hit one each.
    # The tie on one hit is broken on term length, so 'captain' is reported —
    # a corpus-wide word never is, however many passages carry it.
    corpus = Corpus.from_rows(
        [("a.txt", i, "at the end of the road they end the long day") for i in range(6)]
        + [("a.txt", 6, "and once, a Captain Ahab sailed after a whale")]
    )
    items = [
        {
            "id": "outside-glue",
            "turns": ["What does Captain Ahab do at the end of the whale chase?"],
            "expect": "not_in_sources",
        }
    ]
    audit = audit_items(items, corpus)[0]
    assert [f.code for f in audit.findings] == ["abstain_false_hit"]
    assert "captain" in audit.findings[0].detail
    assert "end" not in audit.findings[0].detail
    # The prompt asks for false hits "spot-read and noted": the evidence and
    # the verdict to read have to be in the proof, not only in the finding.
    assert "SPOT-READ" in audit.proof
    assert "end" in audit.proof  # still noted, just not reported


def test_answer_question_with_no_retrievable_term_is_flagged(corpus: Corpus) -> None:
    items = [{"id": "void", "turns": ["What is"], "expect": "answer"}]
    audit = audit_items(items, corpus)[0]
    assert "answer_query_no_hit" in [f.code for f in audit.findings]


def test_library_item_is_proven_by_the_document_name(corpus: Corpus) -> None:
    """A `library` item names a document, so the name is the attestation.

    The point of the case: the mention string appears in NO passage of the
    document ("frankeNstein.txt" holds a Victor Frankenstein passage, but the
    title itself is never repeated in the text). Without the document-name
    rule this item is reported as demanding a string the corpus cannot
    produce, which is a false finding on every `library` item in the set.
    """
    items = [
        {
            "id": "library-list",
            "turns": ["what books do we have?"],
            "expect": "library",
            "mention": ["Noli Me Tangere"],
        }
    ]
    corpus = Corpus.from_rows(
        [("Noli Me Tangere.txt", 0, "prose about the books this garden has, and a garden")]
    )
    audit = audit_items(items, corpus)[0]
    assert audit.findings == [], audit.findings


def test_tokenizer_handles_cjk_and_accents() -> None:
    assert tokenize("Hôpital") == ["hopital"]
    # CJK bigrams, not whitespace-delimited words and not the whole run:
    # 西遊記 yields 西遊 / 遊記, never the three-character "word".
    assert tokenize("西遊記") == ["西遊", "遊記"]
    assert tokenize("贾宝玉") == ["贾宝", "宝玉"]
    # A single kana is emitted whole — Japanese has no bigram-only rule.
    assert tokenize("ひ") == ["ひ"]
    # Terms are longest-first (that is the order the abstention proof reads),
    # and accents are stripped: "Misérables" -> "miserables".
    assert content_terms("Who is Cosette in Les Misérables?") == ["miserables", "cosette", "les"]
    assert "cosette" in tokenize("Who is Cosette in Les Misérables?")


def test_quote_around_centres_on_the_matched_term(corpus: Corpus) -> None:
    passage = corpus.passages[0]
    quoted = quote_around(passage, ["allowance"], width=60)
    assert "allowance" in quoted.lower()


def test_write_back_never_overwrites_a_hand_written_proof(tmp_path: Path) -> None:
    """outside-whitman-lilacs carries a human spot-read; the script must not clobber it."""
    set_file = tmp_path / "set.json"
    set_file.write_text(
        json.dumps(
            {
                "dataset": "x",
                "items": [
                    {"id": "kept", "turns": ["q"], "expect": "answer", "proof": "by hand"},
                    {"id": "filled", "turns": ["q"], "expect": "answer"},
                ],
            }
        ),
        encoding="utf-8",
    )
    corpus = Corpus.from_rows([("d.txt", 0, "some passage")])
    audits = audit_items(json.loads(set_file.read_text())["items"], corpus)
    assert write_back(set_file, audits) == 1
    payload = json.loads(set_file.read_text())
    assert payload["items"][0]["proof"] == "by hand"
    assert payload["items"][1]["proof"].startswith("Audited by scripts/audit_labels.py")


def test_cli_flags_a_mislabelled_item_from_a_synthetic_set(tmp_path: Path) -> None:
    """End to end over the real CLI, without a database."""
    set_file = tmp_path / "books.json"
    set_file.write_text(
        json.dumps(
            {
                "dataset": "synthetic",
                "items": [
                    {
                        "id": "wrong",
                        "turns": ["What is the warranty period in Geneva?"],
                        "expect": "answer",
                        "mention": ["lifetime warranty"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(set_file),
            "--database-url",
            "postgresql+asyncpg://nobody@127.0.0.1:1/none",
        ],
        capture_output=True,
        text=True,
    )
    # No database is reachable, so the run fails before auditing — which is
    # itself worth pinning: the CLI must not report "0 findings" on a corpus
    # it never loaded.
    assert proc.returncode != 0
    assert "0 findings" not in proc.stdout
