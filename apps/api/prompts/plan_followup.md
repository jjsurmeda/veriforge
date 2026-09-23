---
version: 1
role: deep-planner-followup
---

The original plan's sub-questions have all been answered but the notes
gathered so far are not enough to answer the original question. Write
ONE more sub-question that targets exactly what is missing.

Rules:
- Do not repeat a sub-question already answered below.
- Target the specific gap, not the whole original question again.
- Reply with JSON only, no commentary, no markdown fences:
  {"question": "..."}

[Original question]
{question}

[Notes gathered so far]
{notes}

[Next sub-question JSON]
