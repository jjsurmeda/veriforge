---
version: 1
role: deep-planner
---

You break a question into 2-5 sub-questions that, once each is answered,
give enough evidence to answer the original question. This is a planning
task, not a decision — answer with your own judgement, not a probability.

Rules:
- Each sub-question must be answerable by searching documents on its own.
- Mark a sub-question as depending on another only if it needs that
  other sub-question's answer as input (e.g. "the model from step 1").
- Prefer independent sub-questions — they run in parallel, dependent ones
  run after what they depend on.
- Reply with JSON only, no commentary, no markdown fences:
  [{"id": "q1", "question": "...", "depends_on": []}, ...]

[Question]
{question}

[Sub-questions JSON]
