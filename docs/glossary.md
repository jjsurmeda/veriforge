# Glossary

Terms used across the PRD/TRD and the codebase. Alphabetical.

**Abstention** — The graph explicitly declining to answer when retrieved
evidence is insufficient, stating what was found and what's missing,
instead of generating an unsupported answer.

**Circuit breaker** — The rule that switches `DecisionEngine` calls from
Jev to the LLM fallback for a cooldown period after repeated Jev failures.

**Claim** — One atomic, extracted factual statement from a generated
answer, each carrying its own citation IDs and verdict.

**Complexity (decision)** — The Jev/fallback decision that routes an Auto
question to single-hop or multi-hop retrieval.

**Conflict check** — The step that detects when top retrieved chunks from
different documents or source types disagree, and triggers disclosure of
both sides with the source-priority rule applied.

**Context precision / recall** — Eval metrics for whether retrieved chunks
are relevant (precision) and whether all needed evidence was retrieved
(recall), scored by an LLM judge against a reference answer.

**Credits** — The cost-weighted unit quotas are measured in. One credit is
roughly one reference-model (Haiku-class) input token; see TRD §14 for the
formula.

**DecisionEngine** — The interface every routing/classification/scoring/
verification decision goes through. Two implementations: Jev (primary) and
an LLM fallback with the same question schema.

**Faithfulness** — The share of a message's factual claims verified as
supported (partial counts half). See also *minimum claim support*.

**Hop** — One retrieve-and-extract cycle in multi-hop (Deep) retrieval.
Deep mode runs up to 4 hops or stops at its credit budget.

**Jev** — TypeSafe AI's System One model, accessed via OpenRouter. Returns
typed, calibrated decisions (probabilities, choices, scores) rather than
free text; used for every decision in the graph.

**Minimum claim support** — The lowest per-claim support probability in a
message. The revision pass triggers on this, not on the mean faithfulness
score, so one bad claim can't hide among good ones.

**Multi-query** — Running the rewritten question plus 2–3 generated
variants through retrieval in parallel and fusing the results, used in
Auto single-hop.

**Noul** — A Jev question type: a single yes/no question answered with a
calibrated probability.

**Choice** — A Jev question type: a question answered by picking one of up
to 255 labelled options, each with a probability.

**Score** — A Jev question type: a question answered with a numeric value
in a defined range.

**RRF (Reciprocal Rank Fusion)** — The method used to merge vector-search
and BM25-search result lists into one ranked list before reranking.

**RunBus** — The interface decoupling a run's execution from the API
process serving its SSE stream, so any process can stream or cancel any
run. Default implementation is Postgres `LISTEN/NOTIFY`; see ADR-001.

**Sanitizer** — The per-chunk and per-web-page Jev check for injected
instructions in retrieved content, run before that content reaches the
generator.

**Shadow mode** — Running a sample of decisions on both Jev and the LLM
fallback simultaneously (without using the fallback's answer) to measure
agreement, logged to `decision_shadow`.

**Small-to-big retrieval** — Expanding a matched 500-token child chunk to
its neighbouring chunks or parent section before it's sent to the
generator, so the model sees more context than it matched on.

**Sufficiency** — The Jev decision (`sufficient`) that decides whether
retrieved evidence is enough to answer, gating the retry loop (single-hop)
or the hop controller (multi-hop).

**Verdict** — A claim's outcome after review: supported, partial,
unsupported, or contradicted.