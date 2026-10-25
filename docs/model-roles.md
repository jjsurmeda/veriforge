# Which model runs which stage

State on 2026-10-25, read from the code and from the seeded `model_roles` table. The code is the
source of truth; if this page and `scripts/seed_models.py` disagree, the seed wins. To see what a
running database uses: `select role, model_id from model_roles order by role;`.

## How a model is chosen

- **Roles.** Every LLM call carries a role (`generator`, `planner`, `rewriter`, ...). The `model_roles`
  table binds a role to a catalogue model, and the admin **Roles** page edits it. New runs use the
  change; runs in flight do not.
- **Resolution.** `providers/llm.py` asks the run's usage context for the model bound to the call's
  role (`UsageContext.resolve_model`). A role with no binding runs on the model the caller named.
- **Generator exception.** The composer's model picker wins for the `generator` role; the binding is
  only the default for a chat that has not picked one.
- **Decisions are separate.** Routing, classification, scoring and verification go through
  `DecisionEngine` (ADR-005), not through these roles. The primary provider is Jev
  (`decision_engine` role, `typesafe/jev-1.13` through OpenRouter System One). If Jev fails or its
  circuit breaker opens, the LLM judge in the `decision_fallback` role answers instead.
- **Everything goes through OpenRouter.** LiteLLM with the `openrouter/` prefix; embeddings and Jev
  use the same key. No provider is called directly.

## Defaults

| Role | Default model | Notes |
| --- | --- | --- |
| `decision_engine` | `typesafe/jev-1.13` | Jev; never rebound by the seed |
| `generator` | `deepseek/deepseek-v4-pro` | ADR-007; list price $0.955 / $1.911 per 1M tokens in / out |
| `planner`, `rewriter`, `claim_extractor`, `suggester`, `titler`, `small`, `decision_fallback` | `openai/gpt-4o-mini` | `DEFAULT_MODEL_ID`; the model the eval baselines were measured on |
| `async_judge` | `anthropic/claude-haiku-4.5` | seeded once, never overwritten by a reseed; see below |

`rewriter` falls back to `small` if it has no binding. On a transient failure of a call,
`llm_fallback_model` (`openai/gpt-4o-mini`) is tried once.

## Stage by stage

| Stage | What it does | Model |
| --- | --- | --- |
| Greeting fast path | a fixed allowlist of short greetings skips ingress | no model; the generator receives only the canonical phrase |
| Ingress | injection, jailbreak, PII and off-topic checks; intent, source, complexity, risk, lexical weight | **Jev** |
| Rewrite | resolves follow-ups into a standalone question | `rewriter` |
| Query variants | alternative search phrasings (Auto) | `rewriter` |
| Query embedding | vector for hybrid search | `openai/text-embedding-3-large` (`embedding_model` setting) |
| Hybrid search, fusion | Postgres vector and keyword search, RRF | no model |
| Rerank | orders passages and grades answer containment | **Jev** by default; a registry (`retrieval.reranker` setting, admin picker) can select Cohere, NVIDIA or others |
| Sanitize | drops passages that carry instructions | **Jev** |
| Evidence floor | blocks generation when the best passages are weak | arithmetic over the rerank grades |
| Entity guard | every named entity must appear in a passing passage | **Jev** |
| Conflict check | do two passages contradict (Auto) | **Jev** |
| Plan, follow-up question (Deep) | splits the question, writes the next hop's question | `planner` |
| Controller (Deep) | search again or answer | **Jev** |
| Generate | writes the cited answer | `generator` |
| Abstain, chit-chat, Library reply | short replies; an English abstain is a fixed template with no call | `generator` |
| IsUse | does the answer address the question, from these sources | **Jev** |
| Output guard | leak and unsafe-output check | **Jev** |
| Claim extraction | splits the answer into claims | `claim_extractor` |
| Claim verdict | is each claim supported by its passages | **Jev** |
| Revision pass | rewrites after review | `rewriter` |
| Suggested follow-ups, starter questions | next questions for the user | `suggester` |
| Chat title | names the chat | `titler` |
| Document summaries (ingest) | section summaries for new documents | the run's `small` model (`summariser` is a job label, not a bound role) |
| Async quality judge | context precision and answer relevance, pushed to Langfuse after a run | `async_judge` |

## The async judge

`graph/async_scoring.py` scores a run after it completes: context precision, answer relevance, and
context recall when a reference answer exists. It never blocks delivery and never gates anything.

- **Model.** Haiku 4.5 by default (`ASYNC_JUDGE_MODEL_ID` in `config.py`). Change it on the Roles page;
  with no binding it still runs on Haiku.
- **Cost.** About $0.007 per judged run in the 2026-10-25 measurement, more than the generator's
  share of the same runs. `trace_sample_rate` (admin Settings, 0 to 1) sets the fraction of runs that
  are judged. Local work and eval recheck runs use 1.0; the deployed value is 0.1 (KI-94).

## Cost figures

- The generator price constants are the OpenRouter list price. Across 53 billed calls the bill came
  to 0.98x of it; single runs ranged from 0.77x to 1.12x because OpenRouter routes the model to
  different providers (KI-90, ADR-007).
- Jev is priced near zero in the catalogue; its real cost comes from OpenRouter generation records.
  Decision-layer cost and latency against the LLM judge are in
  [`benchmarks/decision-layer.md`](benchmarks/decision-layer.md).

## Not covered

Jev's three question types and each decision's thresholds are in TRD §8. How the eval harness picks
models (it pins `gpt-4o-mini` for the small roles) is in `apps/api/evals/runner.py`. A stage added
after the date above is not in the table until someone adds it.
