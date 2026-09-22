# Veriforge — Product Requirements Document (PRD)

*Companion to `TRD.md`. See `docs/adr/` for architectural decisions and
`docs/glossary.md` for terminology.*

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
| v1 | Auth (email/password, Google), chat and history, Auto/Fast/Deep modes, Upload/Web/Both sources, hybrid retrieval with filters and rerank, Jev decision layer with LLM fallback, guardrails, reviewer and faithfulness, abstention, citations, trace panel, metrics, suggested questions, cancel, quotas, admin pages, eval page, demo corpus and demo account, AWS deployment |
| v1.1 | OCR adapter (Mistral OCR or Textract) behind an admin toggle; Jev-as-reranker A/B experiment |
| Later | Team workspaces and shared chats; answer export; scheduled eval runs; Stage 2 infrastructure (ECS, dedicated database host) |

**Supported inputs in v1:** PDF, DOCX, MD, TXT and HTML up to 20 MB per
file. Scanned pages are detected and flagged but not read until v1.1.

## 4. Functional requirements

Requirements are grouped by area and numbered for traceability to the TRD
and tests. All are v1 unless marked.

### 4.1 Chat and modes

| ID | Requirement |
| --- | --- |
| CH-1 | Composer offers mode Auto (default), Fast and Deep, and source Auto (default), Upload, Web and Both. |
| CH-2 | Auto mode decides source and single-hop vs multi-hop per question; the decision and its probability appear in the trace. |
| CH-3 | Fast mode forces single-hop with no plan and no retry loop; review runs after delivery. |
| CH-4 | Deep mode forces multi-hop: plan, sub-questions, up to 4 hops or the credit budget, whichever comes first. |
| CH-5 | Answers stream token by token; time to first token for Auto single-hop is under 3 s at p50. |
| CH-6 | A Stop button cancels the run; partial text is saved with a Cancelled label and used credits are charged. |
| CH-7 | Follow-up questions use chat history; long chats are summarised so context stays within the model window. |
| CH-8 | Users pick the answer model from models the admin enabled; the choice persists per chat. |
| CH-9 | Three suggested follow-up questions appear under each answer; starter questions appear in an empty chat, generated per collection. |
| CH-10 | Users rate answers thumbs up or down with an optional comment. |

### 4.2 Trust: citations, faithfulness, abstention, conflicts

| ID | Requirement |
| --- | --- |
| TR-1 | Every factual claim carries a numbered citation; hovering shows the passage, document, page, rerank score and support probability. |
| TR-2 | Each claim gets a verdict: supported, partial, unsupported or contradicted. Citation chips are coloured green, amber or red. |
| TR-3 | Each answer shows faithfulness (share of claims supported) and minimum claim support. |
| TR-4 | When evidence is insufficient after retries, the system abstains: states what was found and what is missing, and offers Web or Deep. |
| TR-5 | When sources conflict, the answer says so and cites both sides; user documents outrank web by default. |
| TR-6 | Low-risk answers stream first and are annotated after review. High-risk or borderline answers show a verifying state and deliver the reviewed version. |
| TR-7 | If the reviewer revises an answer, the UI labels it and offers a diff against the original draft. |

### 4.3 Sources

| ID | Requirement |
| --- | --- |
| SR-1 | Users create private collections and attach one or more to a chat; admins publish shared collections. |
| SR-2 | Drag-and-drop upload with per-file ingestion status (queued, parsing, embedding, ready, failed). |
| SR-3 | Document viewer shows chunks, pages and metadata; users edit tags and delete or re-index documents. |
| SR-4 | Pages that look scanned or table-heavy are flagged with a warning icon. |
| SR-5 | Web results used in a chat are listed as temporary sources; users can pin one into a collection. |
| SR-6 | Metadata filters (collection, source type, document, tag, date range, file type) are available in the composer. |

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
| AD-4 | Retrieval settings: top-k values, fusion constant, rerank on or off, hop and retry limits, sufficiency and abstention thresholds. |
| AD-5 | Guardrails: toggle, threshold and action (block, warn, redact) per check, with thresholds per decision engine. |
| AD-6 | Plans and quotas, and user management (role, override, disable). |
| AD-7 | Evals: datasets (hand-written, synthetic with approval, harvested from rated chats), runs against a settings version, diff vs baseline. |
| AD-8 | System: web search provider and keys, source-priority rule, Jev engine mode (auto, Jev only, fallback only), shadow-mode sample rate, trace sampling. |
| AD-9 | Settings are versioned; any change can be rolled back. All admin actions are audit-logged. |

## 5. Non-functional requirements and success metrics

v1 is accepted when the seed eval set meets the quality targets below on
the production box. Latency targets are measured from AWS Singapore.

| Area | Target |
| --- | --- |
| Faithfulness (seed set, Auto) | ≥ 0.90 mean; minimum claim support ≥ 0.6 on ≥ 95% of answers |
| Abstention | ≥ 80% correct abstentions on should-abstain questions; ≤ 10% false abstentions |
| Context recall (seed set) | ≥ 0.85 |
| Latency, Auto single-hop | First token ≤ 3 s p50, ≤ 5 s p95 |
| Latency, Fast | First token ≤ 2 s p50 |
| Latency, Deep | Complete ≤ 30 s p50 |
| Decision layer | Jev ingress call ≤ 600 ms p95; fallback share ≤ 5% of decisions in normal operation |
| Ingestion | A 50-page text PDF is ready in ≤ 2 min; ingestion never raises chat p95 latency by more than 20% |
| Availability | Single-box best effort; restore from backup in ≤ 30 min (RPO 24 h) |
| Security | Server-side ownership filter on every retrieval; encrypted provider keys; no secrets in the repo or images |
| Cost | AWS infrastructure ≤ $45 per month at Stage 1; usage bounded by quotas |
| Accessibility | WCAG 2.1 AA for colour contrast and keyboard navigation; verdicts never conveyed by colour alone |

**Product success signals after launch:** share of answers rated
thumbs-up ≥ 80%, abstentions that lead to a Web or Deep retry ≥ 30%, and
demo visitors who sign up ≥ 10%.