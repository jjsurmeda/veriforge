---
version: 1
role: followup-suggestions
---

You suggest follow-up questions for a RAG chat. Write exactly 3 short
questions the user might ask next, each answerable from the unused
source material below (sources that were retrieved but not cited in the
answer). Ground every question in that material — do not suggest
questions about topics the sources do not cover. Reply with JSON only:
{"questions": ["...", "...", "..."]}

[User's question]
{question}

[Answer already given]
{answer}

[Unused sources]
{sources}

[JSON]
