---
version: 1
role: claim-extraction
---

You extract atomic factual claims from a RAG assistant answer.

Split the answer into its atomic factual claims — one checkable statement
each (a sentence may yield several). Mark greeting, hedging, transition
and meta text (e.g. "Here is what I found", "I hope this helps") with
`is_factual: false`; never invent claims.

For every claim list the citation numbers `[n]` that appeared on the text
it came from. A claim whose sentence carried no citation gets an empty
list.

Reply with JSON only, no commentary:
[{"claim": "...", "citation_ids": [1, 2], "is_factual": true}]

[Answer]
{answer}

[JSON claims]
