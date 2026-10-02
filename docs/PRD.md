# Veriforge — Product Requirements Document (PRD)

*Companion to `TRD.md`. See `docs/adr/` for architectural decisions and
`docs/glossary.md` for terminology.*

## Revision v3 — aligned to the built architecture, OKF added (2026-10-02)

v3 aligns the requirements with the architecture as built (through `d36a034`)
and adds OKF (Google's Open Knowledge Format v0.2) import and export to v1.
It was reviewed independently twice (`docs/reviews/2026-10-02-0400-…`,
`…-0420-…`) and approved by the owner on 2026-10-02.

| # | Change | Why |
| --- | --- | --- |
| 1 | **CH-5 redefined:** continuous progress, plus separate targets for answers, declines and held answers, measured client-side | The 3 s target predated Auto's verification stages. The three reply paths differ: answers 7.8 s p50, declines 12.8 s, held answers after review. ADR-003. |
| 2 | **CH-2 / CH-3 aligned:** Auto is single-hop; Fast has no abstention or sanitizer | That is how they're built |
| 3 | **TR-4 describes the built mechanism** (two evidence checks, one retry, no citations, the question's language), with the P2 answerability target marked | D2 relevance gate, KI-25, KI-29 |
| 4 | **TR-5 clarified; TR-8 added** (ambiguity disclosure) | KI-34, KI-27 |
| 5 | **The Jev reranker moves to v1; NVIDIA is dev-only** | `1ba8f3f`, KI-28 |
| 6 | **OKF import and export (§4.7)** | Owner decision; ADR-004 |
| 7 | **Quality targets defined, sized and tied to a harness** across four corpora, including a counterfactual set | Measured performance; the books are known to the models |

## Revision v2 — changes to reach 9/10

Version 2 closes the nine gaps found in the v1 review. The architecture is
unchanged; every fix lands inside an existing build slice and adds about
two days of work.

| # | Gap in v1 | Fix in v2 | Slice |
| --- | --- | --- | --- |
| 1 | Weak evidence still produced an answer | Explicit abstention branch: says what was found, what is missing, and offers Web or Deep mode. Abstention is an eval metric. | 4 |
| 2 | Faithfulness was a lenient average of sentence-level claims | LLM claim extraction; uncited factual claims count as unsupported; two scores: faithfulness (share supported) and minimum claim support. Revision triggers on the minimum. | 6 |
| 3 | Retrieval returned bare chunks | Small-to-big context expansion, multi-query in Auto single-hop, query-aware BM25/vector fusion weights chosen by Jev. | 3–4 |
| 4 | Unverified answer shown first, then rewritten | Risk-based delivery: low-risk answers stream then get annotated; high-risk or borderline answers show a verifying state and deliver the reviewed answer. | 6 |
| 5 | Prompt-injection defense was classifier-only | Structural defense first (delimited source blocks, tool-less generator, sources-are-data policy), Jev sanitizer second. | 4 |
| 6 | No rule when documents and web disagree | Source-priority rule (user documents outrank web by default, admin-configurable) and explicit conflict disclosure with both citations. | 4 |
| 7 | Tables and scanned pages degraded silently | Ingestion detects table-heavy and low-text pages and flags them in the Sources UI; OCR adapter in v1.1. | 2 |
| 8 | Ingestion could starve live chat on one box | Worker concurrency cap, batched embeddings, retrieval statement timeout, chat-priority scheduling. | 2 |
| 9 | Eval thresholds had no data at start | Hand-labeled seed set of 50 questions (10+ should abstain) ships with slice 3. | 3 |

Also added: query-embedding and web-result caching, rolling summaries for
long chats, parallel retrieval for independent Deep-mode sub-questions,
and an AGPL licence note for pg_search.

---

## 1. Overview, goals and non-goals

We are building Veriforge, a multi-user RAG chatbot that answers from
uploaded documents and the web, adapts its retrieval strategy per
question, and shows its reasoning, evidence and scores as it works. It is
a Loop Engineering showcase built production-shaped: visible internals,
real accounts and quotas, and a hosting bill of about $39 per month.

**Problem.** Most RAG demos hide how answers are produced, cannot say when
they do not know, and give no measure of whether citations support the
text. Teams evaluating RAG cannot see retrieval quality, latency or cost
per answer.

**Goals**

1. Answer grounded questions over a user's documents and the web with
   inline citations.
2. Adapt automatically: choose sources and single-hop or multi-hop
   retrieval per question, with manual override.
3. Make trust measurable: per-claim verification, faithfulness scores, and
   explicit abstention when evidence is weak.
4. Make the pipeline visible: streamed plan, decisions with
   probabilities, retrieval scores, latency, tokens and context use.
5. Run multi-user with per-user credit limits per rolling 5 hours and per
   month.
6. Stay cheap: one small AWS instance, usage-based costs capped by
   quotas.

**Non-goals for v1**

- OCR of scanned documents (v1.1).
- Team workspaces, sharing chats between users, or collaborative editing.
- Agent tool use beyond retrieval and web search (no code execution, no
  actions on external systems).
- Mobile apps; the web app is responsive only.
- High availability or multi-region deployment.

## 2. Users and user stories

Three roles use the product: end users who ask questions, admins who
configure it, and anonymous visitors who try the read-only demo.

| Persona | Who | What they need |
| --- | --- | --- |
| Knowledge user | Engineer or analyst asking questions over their own documents | Fast, cited answers; control over sources; trust signals |
| RAG evaluator | Developer or architect studying how RAG works (Loop Engineering audience) | Full visibility of the pipeline, scores and costs; mode comparison |
| Admin | Operator of the deployment | Providers, models, thresholds, quotas, users, evals |
| Demo visitor | Anyone with the public link | Try the product on a preloaded corpus with no sign-up |

**Key user stories**

- As a user, I upload PDFs and ask a question, and get an answer with
  numbered citations I can hover to see the source passage and page.
- As a user, I leave the mode on Auto and the system decides whether to
  use my documents, the web or both, and whether one retrieval pass is
  enough.
- As a user, I switch to Deep for a complex question and watch the plan,
  each hop and each decision stream in the Trace panel.
- As a user, when my documents do not contain the answer, I am told so
  plainly, shown what was found, and offered to search the web.
- As a user, I can stop a running answer and keep the partial text.
- As a user, I see how many credits I have left in the current 5-hour
  window and this month, and when they reset.
- As a user, I click a suggested follow-up question to continue.
- As an admin, I change which model powers each step, adjust guardrail
  thresholds, and see the effect on an eval run before rolling it out.
- As an admin, I set quota plans and override limits for a specific user.
- As an evaluator, I compare Auto, Fast and Deep on the same dataset for
  faithfulness, latency and cost.

## 3. Scope and release phases

v1 ships everything in the original brief plus the v2 quality fixes; OCR
follows in v1.1.

| Phase | Contents |
| --- | --- |
| v1 | Auth (email/password, Google), chat and history, Auto/Fast/Deep modes, Upload/Web/Both sources, hybrid retrieval with filters and the **Jev reranker**, Jev decision layer with LLM fallback, guardrails, reviewer and faithfulness, abstention, citations, trace panel, metrics, suggested questions, cancel, quotas, admin pages, eval page, demo corpus and demo account, **OKF bundle import and OKF export of verified answers (§4.7)**, AWS deployment |
| v1.1 | OCR adapter (Mistral OCR or Textract) behind an admin toggle |
| Later | Team workspaces and shared chats; scheduled eval runs; OKF sync from a remote catalogue; Stage 2 infrastructure (ECS, dedicated database host) |

**Supported inputs in v1:** PDF, DOCX, MD, TXT and HTML up to 20 MB per
file, and **OKF bundles** (a `.zip` of markdown concepts; limits in OK-0).
Scanned pages are detected and flagged but not read until v1.1.

## 4. Functional requirements

Requirements are grouped by area and numbered for traceability to the TRD
and tests. All are v1 unless marked.

### 4.1 Chat and modes

| ID | Requirement |
| --- | --- |
| CH-1 | Composer offers two toggles, both off by default: **Deep search** (off = Auto mode, on = Deep mode) and **Web search** (off = documents only, on = documents and web). Fast mode remains an API/eval option, not a composer control. |
| CH-2 | Auto is **single-hop**: one retrieval with several query phrasings and at most one rewrite + retry (the source is set by the Web search toggle). Each decision and its probability appear in the trace. Multi-hop is Deep only (CH-4). *(v3)* |
| CH-3 | Fast mode forces single-hop with no plan and no retry. It has **no abstention, sanitizer or ingress guardrail**, and review runs after delivery. API/eval option only (CH-1). *(v3)* |
| CH-4 | Deep mode forces multi-hop: plan, sub-questions, up to 4 hops or the credit budget, whichever comes first. |
| CH-5 | Answers stream token by token. All times are **client-side, from send**; server-side `run_events` give the per-stage breakdown. **Progress:** the trace updates at least every 2 s until the first answer token or the decline, and long stages publish sub-steps. **Single-pass answers:** first token ≤ 5 s p50 / ≤ 8 s p95 (*provisional, P3 exit*). **Declines:** delivered ≤ 10 s p95 (*provisional, P3 exit*). **Held answers** (TR-6): *TBD at P3, from ≥ 10 held runs*. **Fast:** first token ≤ 2 s p50. All targets hold with OKF in scope. A provisional target is changed only by an owner-approved entry in ADR-003. *(v3)* |
| CH-6 | A Stop button cancels the run; partial text is saved with a Cancelled label and used credits are charged. |
| CH-7 | Follow-up questions use chat history; long chats are summarised so context stays within the model window. |
| CH-8 | Users pick the answer model from models the admin enabled; the choice persists per chat. |
| CH-9 | Three suggested follow-up questions appear under each answer; starter questions appear in an empty chat, generated from the chat's sources (or the Library when the chat has none). |
| CH-10 | Users rate answers thumbs up or down with an optional comment. |

### 4.2 Trust: citations, faithfulness, abstention, conflicts

| ID | Requirement |
| --- | --- |
| TR-1 | Every factual claim carries a numbered citation; hovering shows the passage, document, page, rerank score and support probability. |
| TR-2 | Each claim gets a verdict: supported, partial, unsupported or contradicted. Citation chips are coloured green, amber or red. |
| TR-3 | Each answer shows faithfulness (share of claims supported) and minimum claim support. |
| TR-4 | In Auto, the system retrieves once and, if the evidence is weak, rewrites and retries **once**. It abstains when **either** check fails: **sufficiency** (do the passages together answer the question?) or **answerability** (does any passage contain the answer, or, for a summary question, do the passages cover the subject?). **Until P2, answerability is the Jev relevance floor** (`rerank_abstain`). It applies only when Jev reranks; otherwise sufficiency alone applies. When the generated reply itself declines, the run is recorded as an abstention and its citations are dropped (P2). An abstention states what was found and what is missing, **carries no citations**, is written in the question's language, and offers Web or Deep. Fast mode doesn't abstain (CH-3). *(v3)* |
| TR-5 | When sources conflict, the answer says so and cites **the passages on each side of the conflict**; user documents outrank web by default. *(v3: today's side assignment is a midpoint split and doesn't meet this, KI-34.)* |
| TR-6 | Low-risk answers stream first and are annotated after review. High-risk or borderline answers show a verifying state and deliver the reviewed version. |
| TR-7 | If the reviewer revises an answer, the UI labels it and offers a diff against the original draft. |
| TR-8 | When the sources support more than one answer (for example, two people who are each "the master"), the answer names each one and how it fits, instead of picking one. Prompt change, gated by the eval set, with at least 3 ambiguity items in acceptance first. *(v3)* |

### 4.3 Sources

| ID | Requirement |
| --- | --- |
| SR-1 | Each chat has its own sources, uploaded from the composer or the right panel's Sources tab and deleted with the chat. Admins manage a Shared library (admin-only page) that every chat also searches; users see it read-only in the Sources tab. Users never manage collections (ADR-002). |
| SR-2 | Drag-and-drop upload with per-file ingestion status (queued, parsing, embedding, ready, failed). An OKF bundle shows per-concept status, with rejected and skipped concepts listed with their reason. *(v3)* |
| SR-3 | Document viewer shows chunks, pages and metadata; users edit tags and delete or re-index documents. |
| SR-4 | Pages that look scanned or table-heavy are flagged with a warning icon. |
| SR-5 | Web results used in a chat are listed as temporary sources; users can pin one into the chat's sources. |
| SR-6 | Metadata filters (source type, **format (file/OKF)**, document, tag, date range, file type; **for OKF: concept type, status, verification**) are available in the API and the composer. Filters only narrow results. *(v3: composer UI not built yet.)* |
| SR-7 | Multilingual documents and questions are supported *(added 2026-09-29, round 2)*: chunking, embeddings and answers work beyond English; the answer follows the language of the user's question. |

### 4.4 Transparency and metrics

| ID | Requirement |
| --- | --- |
| TX-1 | A Trace panel streams the plan, each step, each decision with probabilities, and native model reasoning in a collapsible block. |
| TX-2 | A Sources tab lists retrieved chunks with vector, BM25, fusion and rerank scores, and marks chunks dropped by the sanitizer. |
| TX-3 | A Metrics tab shows a latency waterfall by stage. |
| TX-4 | Each answer footer shows faithfulness, total latency, tokens in and out, credits used and context used vs model window. |
| TX-5 | Opening an old chat replays its full trace. |
| TX-6 | A usage page shows the user's credits over time, faithfulness trend and latency p50 and p95. |

### 4.5 Accounts and quotas

| ID | Requirement |
| --- | --- |
| AC-1 | Sign up and sign in with email and password or Google; password reset by email. |
| AC-2 | Roles: user and admin. A read-only demo account uses the shared demo corpus. |
| AC-3 | Each user has a credit limit per rolling 5 hours and per calendar month, set by plan with per-user overrides. |
| AC-4 | Credits are cost-weighted by model price and count all internal calls. |
| AC-5 | The composer shows remaining credits in both windows and the next reset time. |
| AC-6 | At the limit, new questions are blocked with a clear message and countdown. |

### 4.6 Admin

| ID | Requirement |
| --- | --- |
| AD-1 | Providers: add, edit, test and disable LLM providers (OpenRouter, Anthropic, OpenAI) with encrypted keys. |
| AD-2 | Models: catalogue with prices, context window and capabilities; enable or disable per model. |
| AD-3 | Model roles: assign a model to each role (planner, generator, rewriter, claim extractor, suggester, decision engine, decision fallback). |
| AD-4 | Retrieval settings: top-k values, fusion constant, **reranker (Jev, Cohere, off; NVIDIA dev-only)**, hop and retry limits, **the sufficiency and relevance/answerability thresholds with per-format overrides (OKF)**, **OKF link-expansion limits, deprecated-concept exclusion, and trust ordering**. Fast mode always uses a provider reranker. *(v3)* |
| AD-5 | Guardrails: toggle, threshold and action (block, warn, redact) per check, with thresholds per decision engine. |
| AD-6 | Plans and quotas, and user management (role, override, disable). |
| AD-7 | Evals: datasets (hand-written, synthetic with approval, harvested from rated chats), runs against a settings version, diff vs baseline. |
| AD-8 | System: web search provider and keys, source-priority rule, Jev engine mode (auto, Jev only, fallback only), shadow-mode sample rate, trace sampling. |
| AD-9 | Settings are versioned; any change can be rolled back. All admin actions are audit-logged. |

### 4.7 OKF: Open Knowledge Format *(v3)*

A bundle is a folder of markdown concept files:
- YAML frontmatter: a required `type`, plus `title`, `description`,
  `resource` and `tags`
- links between files
- v0.2 trust signals: `sources`, `generated`, `verified` (`{by, at}`),
  `status` (draft/stable/deprecated) and `stale_after`

Veriforge reads and writes the format; search stays one hybrid search.

| ID | Requirement |
| --- | --- |
| OK-0 | **Bundle handling** (the trust boundary):<ul><li>compressed ≤ 20 MB, **uncompressed ≤ 100 MB**, ≤ 2,000 concepts; archive entries with absolute paths or `..` are rejected (zip-slip)</li><li>`resource` is stored as text and **never fetched**</li><li>spec-reserved `.md` files are skipped, not rejected</li><li>a concept's identity is **(bundle, bundle-relative path)**, not its content hash (a migration for OKF documents), so identical or moved concepts don't collide</li><li>re-uploading a bundle **syncs** it: changed concepts are replaced, and concepts missing from the new upload are retired</li><li>replaced and retired concepts become **non-searchable versions that keep their chunks**, so old chats' citations still resolve (TX-5, TR-1)</li><li>a link resolves by bundle-relative path **within its own bundle**; a link to another bundle resolves only by the target's `resource` identifier, and only if that bundle is in the chat's scope</li></ul> |
| OK-1 | A user uploads a bundle as chat sources, and an admin uploads one to the Shared library. Each concept becomes a source document (`format = okf`), searched in the same hybrid search as every other document. The library intent counts or groups concepts per bundle; it doesn't list every concept. |
| OK-2 | Frontmatter becomes metadata and **never enters passage text**. Server-derived attributes (`status`, `verified`, `stale`) may appear as attributes on the source wrapper the generator sees. A concept with invalid YAML or no `type` is rejected with a reason; the rest of the bundle ingests. |
| OK-3 | In Auto, passages from concepts that a retrieved concept links to directly may be added to the evidence: **one hop**, bounded by an admin limit, within the chat's scope. In Deep, the **controller's DecisionEngine `Choice` gains a `follow_link` option** (TRD §8). Linked passages pass the same sanitizer as retrieved ones. **In Auto, linked passages are added only after both evidence gates have passed.** They can't turn a decline into an answer, the gates keep their calibration, and the reviewer still verifies every claim drawn from them. |
| OK-4 | **A link never widens access.** A link whose target is outside the chat's scope, doesn't exist, or is excluded (for example `deprecated`) is shown identically as "link not followed", using only the link text from the user's own source. There's no reason distinction and no target title, so the trace can't reveal whether something exists elsewhere. Covered by an ownership test. |
| OK-5 | Trust signals:<ul><li>`deprecated` concepts are excluded by a **server-side default inside scope** (admin setting, not a client filter that could widen results)</li><li>concepts past `stale_after` show a "stale" badge</li><li>an admin may enable trust ordering, which changes **ordering only** and is applied **after the top-k cut and after the evidence gates**, so it can never change which passages the gates see</li><li>while the default exclusion is on, a `status = deprecated` filter returns nothing; filters only narrow</li><li>the Sources panel and citation hover show status and who verified the concept</li></ul> |
| OK-6 | When concepts conflict, TR-5's disclosure applies, and status breaks the tie by default (via OK-2's wrapper attributes). **Depends on KI-34.** |
| OK-7 | **Export:** a reviewed answer downloads as an OKF concept.<ul><li>`sources` = its citations</li><li>`generated` = model and run</li><li>`verified` records the **actual** verdict engine (`agent/jev-…` or `agent/fallback-…`)</li><li>a human verification is an **explicit "Verify" action**, separate from thumbs-up, recorded with a stable pseudonymous id</li><li>`status`: `draft` until human-verified, then `stable`</li></ul> |
| OK-8 | Exported concepts re-import as valid OKF and keep their trust signals. |
| OK-9 | Multilingual concepts follow SR-7. |
| OK-10 | Ingestion runs **one job per bundle**: embeddings batched across concepts, one starter-question job per bundle, not per concept. |

## 5. Non-functional requirements and success metrics

v1 is accepted when the targets below hold. *(v3: targets defined per corpus and tied to the harness that measures them; current measurements are tracked in the production plan, not here.)*

**Acceptance corpora:**
- books (multilingual fiction)
- product manuals (AW-2000)
- an OKF bundle
- a **counterfactual corpus**: realistic documents with deliberately altered
  facts, so answers must come from the documents, not model memory

**Item counts:** each corpus has **≥ 20 answerable and ≥ 20 should-abstain
items** (160+ across 4 corpora). Every label is proven against the corpus by
a scripted check: a hit search for answer items, a zero-hit search for
should-abstain items.

**Two tiers of runs, to fit the budget:**
- **Per phase (gate):** fast20 plus a ~10-item stratified subset per corpus,
  one run, about $0.6 per phase.
- **At milestones only** (P2 exit, OKF exit, P8): the full sets, **2 runs**,
  in parallel on isolated stacks. About $2.6 and about 40 min wall clock per
  milestone, about $8 over v1.

**Measurement setup:**
- Eval corpora move out of the Shared library in P5 (KI-24). The books status
  cells below were measured **in Shared** and are re-baselined after the move.
- Latency is measured locally until slice 9, then **re-measured on the
  deployed stack** (P8), which is authoritative.

| Area | Target | Measured by |
| --- | --- | --- |
| Faithfulness | ≥ 0.90 mean per corpus | eval runner, per corpus |
| Minimum claim support | ≥ 0.6 on ≥ 95% of answers | eval runner summary (`min_support` field to add) |
| Decline accuracy | ≥ 90% of should-abstain item-runs end as a **clean decline** (abstained, no citations), per corpus | milestone full sets, 2 runs |
| **Confident wrong answer** | A reply to a should-abstain item that **asserts an answer**: it doesn't say the sources lack it. (A prose "not in the sources" reply with citations is an unclean decline, counted against decline accuracy, not here.) Target: **≤ 1 per 100** should-abstain item-runs, and **no item twice**. | milestone full sets, scorer's `says_not_in_sources` |
| False abstention | ≤ 5% of answerable items, **including broad/summary questions** | acceptance-style set |
| Grounding | ≥ 95% of counterfactual answers follow the document, not the real-world fact | counterfactual set with fact checks |
| Context recall | ≥ 0.85 per corpus | eval runner (needs reference contexts) |
| Progress | no trace gap > 2 s before the first token or decline | `run_events` gaps |
| Latency, answers | first token ≤ 5 s p50 / ≤ 8 s p95, client-side (*provisional, P3*) | acceptance `ttft_ms`; `run_events` per stage |
| Latency, declines | delivered ≤ 10 s p95, client-side (*provisional, P3*) | acceptance; `run_events` |
| Latency, held answers | *TBD at P3, from ≥ 10 held runs* | acceptance; `run_events` |
| Latency, Fast | first token ≤ 2 s p50 | `run_events`, Fast eval |
| Latency, Deep | complete ≤ 30 s p50 incl. OKF traversal, on ≥ 10 Deep items per corpus | Deep eval set (to add) |
| OKF ingestion | 500-concept bundle searchable ≤ 10 min (*provisional, OKF O2*) | ingestion timing |
| OKF expansion | ≤ 500 ms p50 added to Auto, A/B with OKF in vs out of scope | timed `okf_expand` stage |
| Security | ownership filter on every retrieval and every followed link; no existence oracle (OK-4); encrypted provider keys; no secrets in the repo or images | tests (P5); security review |
| Cost | AWS infrastructure ≤ $45 per month at Stage 1; usage bounded by quotas; usage per answer reported, including OKF expansion and ingestion | AWS billing; metrics (P7) |
| Decision layer | Jev ingress call ≤ 600 ms p95; fallback share ≤ 5% of decisions in normal operation | (unchanged from v2) |
| Ingestion | A 50-page text PDF is ready in ≤ 2 min; ingestion never raises chat p95 latency by more than 20% | (unchanged from v2) |
| Availability | Single-box best effort; restore from backup in ≤ 30 min (RPO 24 h) | (unchanged from v2) |
| Accessibility | WCAG 2.1 AA for colour contrast and keyboard navigation; verdicts never conveyed by colour alone | (unchanged from v2) |

**Product success signals after launch:** share of answers rated
thumbs-up ≥ 80%, abstentions that lead to a Web or Deep retry ≥ 30%, and
demo visitors who sign up ≥ 10%.