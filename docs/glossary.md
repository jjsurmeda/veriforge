# Glossary

Terms used across the PRD/TRD and the codebase. Alphabetical.

**Abstention** — The graph explicitly declining to answer when retrieved
evidence is insufficient, stating what was found and what's missing,
instead of generating an unsupported answer.

**Chat sources** — Documents uploaded into one chat. Stored in that chat's
hidden collection, searched only by that chat, deleted with it (ADR-002).

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

**Shared library** — Admin-managed documents that every chat searches in
addition to its own sources. Managed on the admin page; read-only for
users (ADR-002).

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

**Evidence floor** — The computed floor that decides whether the
retrieved evidence is clearly absent. It is the mean answer-containment grade
of the best three post-sanitize passages (`evidence_floor`); the default is
0.455 (ADR-006: it only removes clear misses, it is not a decline classifier).
Below the floor triggers one corrective retrieval, then abstains if still
below (Auto). Deep computes the same floor over its pooled hop passages
after the last hop and abstains directly — its corrective loop is the
controller's own hops, so there is no second check (R2b). Above the floor
the run generates, and IsUse decides. The named-entity guard
sits beside it.

**IsUse** — The post-generation usefulness check (Self-RAG's third
critique, realized; ADR-006). One `Noul` asked of every grounded Auto
answer after it generates, and of every Deep answer since R2b (R2b:
Deep runs are always held, so a fail declines without retraction):
*does this answer directly answer the question
asked, from these sources?* Below the `is_use` threshold (0.47) the
answer is replaced by the decline template and the run records an
abstention; a streamed answer is retracted first (`answer.retract`).
Calibrated on the probe: failing answers 0.09–0.37, answerables
0.56–0.93. A decision outage reads as a fail (KI-57, fail-closed).

**Stream line** — The delivery boundary for grounded Auto answers
(ADR-006 item 4): a rubric grade at or above it (0.60) streams before
review; below it the answer is held under the verifying step. Sits above
every recorded should-decline rubric reading (0.559) so streaming stays
clean; an `answer.retract` is its backstop.

**Verdict** — A claim's outcome after review: supported, partial,
unsupported, or contradicted.

## Providers, retrieval and modes

- **Decision provider** — a model behind the `DecisionProvider` interface that answers `Noul`, `Choice` and `Score` questions (Jev, an LLM judge, other decision models). Chosen per run.
- **Reranker** — reorders retrieved passages by whether they answer the question (Cohere, NVIDIA, Jev, LLM judge, or fused order for none).
- **Answer-containment rubric** — the rerank question "Does the passage contain the information needed to answer or verify the question?", graded off-topic / related / partly / fully.
- **Evidence check (corrective)** — Auto's single check that the reranked evidence answers the question; on failure it corrects the retrieval once before abstaining.
- **Entity guard** — rejects passages about a different named entity than the one asked about.
- **Section summary** — a summary of one document section (and one per document), indexed for gist questions.
- **Agent loop** — Deep mode's cycle: choose the next sub-question, retrieve, take notes, then search again or answer.
- **Comparison view** — one question replayed across chosen providers, side by side.

