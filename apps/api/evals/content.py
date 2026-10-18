"""Content checks shared by the acceptance scorer and the eval gate.

An answer is correct for an item when it states what the item requires
(`mention` / `mention_all` / `alt_mention`), states none of what it forbids
(`forbid`, the real-world value a counterfactual document contradicts), and
cites the document the item names (`cite`). `scripts/acceptance.py` applies
them to live replies; `evals/gate.py` applies them to the counterfactual
subset, whose whole point is the altered fact.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def mentions_hit(item: dict[str, Any], answer: str) -> bool:
    """True when the answer states every string the item requires.

    `mention_all` is the ambiguity-item channel: the corpus answers the question
    two ways, so the item names **both** referents and an answer that names only
    one has not answered the question the corpus poses. These items are expected
    to fail today — P2's prompt change is what surfaces the ambiguity — and are
    marked `pending_p2` so they are reported separately and do not drag down the
    pass rate.
    """
    lowered = answer.lower()
    required = [str(m).lower() for m in item.get("mention_all", [])]
    optional = [str(m).lower() for m in item.get("mention", [])]
    optional += [str(m).lower() for m in item.get("alt_mention", [])]
    if required:
        return all(m in lowered for m in required) and (
            not optional or any(m in lowered for m in optional)
        )
    if not optional:
        return True
    return any(m in lowered for m in optional)


def forbids_hit(item: dict[str, Any], answer: str) -> str | None:
    """The first `forbid` string the answer contains, if any.

    For a counterfactual item (evals/counterfactual) the corpus states a
    deliberately altered fact, so the real-world value is the one a model
    produces from memory. `forbid` names it: an answer that states the
    document's value **and** the real one fails, because the product would have
    handed the user a figure its own sources contradict.

    Matched on word boundaries for the same reason `mention` should be: `IP68`
    must not fire on `IP69K`, and `330` must not fire on `3300`.
    """
    for raw in item.get("forbid", []):
        needle = str(raw).lower()
        if not needle:
            continue
        pattern = r"(?<!\w)" + re.escape(needle) + r"(?!\w)"
        if re.search(pattern, answer.lower()):
            return str(raw)
    return None


_CITATION = re.compile(r"\[(\d{1,2})\]")


def cited_documents(answer: str, document_names: Sequence[str | None]) -> list[str]:
    """The documents an answer's `[n]` markers point at, `n` counting from 1
    over the contexts it was generated from."""
    cited = []
    for n in sorted({int(m) for m in _CITATION.findall(answer)}):
        if 1 <= n <= len(document_names) and document_names[n - 1]:
            cited.append(str(document_names[n - 1]))
    return cited


def counterfactual_counts(
    spec: dict[str, dict[str, Any]],
    rows: Sequence[tuple[str, str, bool, Sequence[str]]],
) -> dict[str, float]:
    """Per-run content counts for items described by `spec` (keyed by
    question): `(question, answer, abstained, cited_documents)` per row.

    - `forbidden_hits`: any delivered answer stating a forbidden value;
    - `content_misses`: an answerable item delivered without its mention;
    - `wrong_document`: an answerable item delivered without citing its
      document. A question missing from `spec` is not counted.
    """
    counts = {"forbidden_hits": 0.0, "content_misses": 0.0, "wrong_document": 0.0}
    for question, answer, abstained, cited in rows:
        item = spec.get(question)
        if item is None or abstained:
            continue
        if forbids_hit(item, answer) is not None:
            counts["forbidden_hits"] += 1
        if item.get("expect") != "answer":
            continue
        if not mentions_hit(item, answer):
            counts["content_misses"] += 1
        books = [str(b).lower() for b in item.get("cite", [])]
        if books and not any(b in doc.lower() for b in books for doc in cited):
            counts["wrong_document"] += 1
    return counts


def load_spec(path: Path) -> dict[str, dict[str, Any]]:
    """A set file's items keyed by the question the runner asks (last turn)."""
    items = json.loads(path.read_text())["items"]
    return {str(item.get("question") or item["turns"][-1]): item for item in items}
