# Two-day private beta: RAG and Jev showcase

Owner decision 2026-10-05: **defer OKF** (O1–O5 and ADR-004 stay accepted but
unbuilt); focus on the RAG and the decision-model (Jev) showcase; give a
time-boxed share to UI polish. Supersedes the order in
`2026-10-02-0430-backend-prod-readiness-v3.md` for the next two days only; the
rest of that plan stands.

## Goal

An invite-only deployment on AWS Singapore (TRD §16 Stage 1, one t4g.medium)
where a visitor can *see how answers are formed and when the system declines*,
with the limits stated up front. Not full v1.

## Scope

**In:** deployment, latency quick wins, ops (traces, alarms, email, signup
control), answer-quality fixes (P2b-lite), and the showcase and UI lane.

**Out (post-launch):** OKF, auto-escalation to Deep, the Deep eval set, the
formal latency sign-off (ADR-003 stays provisional), a full security review,
human-label validation, further model work.

## Lanes (sub-agents in worktrees, parallel on day 1)

| Lane | Work | Needs |
| --- | --- | --- |
| **A. Deploy foundation** (long pole) | Production Dockerfiles (arm64), `compose.prod`, Caddy, a minimal CDK stack (EC2, S3, SSM secrets, CloudFront), backups, dry-run deploy | AWS account, domain |
| **B. Latency quick wins** | One batched embedding call, parallel searches, skip the retry when evidence is clearly absent, sub-steps for progress; measured against the gate | credit |
| **C. Ops** | Langfuse traces and stage spans (KI-21), CloudWatch alarms (errors, breaker open, credit floor), real email via SES (KI-35), signup gate (invite or domain allowlist) and throttling, admin bootstrap without a script | SES access |
| **D. Answer quality (P2b-lite)** | Books confident-wrong (`outside-holmes-boston`), broad-question answerability (`broad-alice`), entity-mismatch set wired into the gate | credit |
| **E. Showcase and UI polish** | see below; time-boxed to about 25% of the effort | none |

## Lane E: make the RAG and Jev legible

Anchored in `PRODUCT.md` and `docs/design-system.md` (forensic instrument
panel, evidence before certainty, no decorative dashboards). Polish, not
redesign.

1. **Evidence-gate card (KI-22, batch 1).** Per run in the Trace: each gate with
   its value, threshold and verdict (sufficiency, relevance, entity match),
   with the engine badge (Jev or fallback). Data already rides the `decision`
   events (`threshold` is set).
2. **"Why it declined".** The abstain message names the failed gate in plain
   words ("no passage mentions the Kestrel K9"), linked to the card.
3. **Decision-layer view for the demo role.** Read-only: Jev vs fallback share,
   breaker state, shadow-mode agreement, rerank latency. The admin panel
   exists; allow the demo role to read it.
4. **Demo mode.** A read-only demo account on the shared demo corpus (the
   books), with six guided starter questions that show each behaviour: a cited
   answer, an abstention, a conflict, an entity-mismatch decline, a
   multilingual answer, a Deep run. Eval corpora stay private.
5. **Latency waterfall (TX-3)** per run, with TTFT, from the stage timings.
6. **Polish pass, time-boxed.** Empty, loading and error states; both themes;
   keyboard focus; reduced motion; copy in the design-system voice; responsive
   check. Use the `impeccable` critique and audit passes. No new visual
   language.
7. **Capture.** Screenshots and a short demo recording for the showcase page.

## Day 2: deploy, verify, rehearse

1. Merge lanes one at a time, each through the gate.
2. Deploy; seed the demo corpus, the demo account and the admin.
3. Smoke test, and the eval gate against the deployed stack.
4. Backup, restore and rollback drill.
5. Load test: about 10 concurrent chats, quota correct under parallel runs.
6. Re-measure latency from Singapore; set the beta notice from the numbers.
7. Rehearse the six-question tour on the deployed stack; record it.
8. Go/no-go; invite the first users.

## Go/no-go

- Deployed stack passes the gate and the smoke test
- Restore works; rollback is documented as one command
- Traces arrive; a test alarm fires
- 10 concurrent chats with no failed runs or quota errors
- Confident-wrong ≤ 1 per 100 on the gate sets; faithfulness ≥ 0.90
- Latency near target, or the limits stated in the beta notice
- The tour works end to end on the deployed stack

## Risks

- First AWS deploy surprises: arm64 ParadeDB image, 4 GB RAM, TLS and DNS,
  **SES sandbox (production access can take about 24 h)**.
- Lane E touches `apps/web` and a few API surfaces; merge it last-but-one.
- If lane A slips, lanes B, D and E still ship locally and the beta moves to
  3–4 days. Don't rush the deploy.

## Needed from the owner

1. AWS account access (a scoped IAM role) and a domain with DNS.
2. OpenRouter top-up (about $20) and a separate production key with a cap.
3. SES production access requested today.
