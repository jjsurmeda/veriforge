# Product

## Register

product

## Users

Engineers and architects evaluating a RAG system, alongside people using the workbench to ask questions from their documents. They work in long, evidence-heavy sessions and need to inspect how an answer was formed, not just read a polished result.

## Product Purpose

Veriforge turns retrieved evidence into verified answers. It makes trust visible while an answer is forming: provenance, retrieval decisions, reviewer verdicts, conflicts, abstentions, and quotas remain inspectable. Success means a user can understand what supports a claim, what remains uncertain, and what action to take next without leaving the workbench.

## Brand Personality

Forensic, precise, grounded. The interface should feel like a calm instrument panel: matter-of-fact, technically literate, and confident only when the evidence earns it.

## Anti-references

Avoid generic AI SaaS aesthetics, cream-and-terracotta or near-black-and-acid palettes, decorative dashboards, card stacks that obscure the workbench, ambient confidence badges, and motion that exists only to make a page feel busy.

## Design Principles

- Show the evidence trail while trust is still forming; never perform certainty before verification.
- Treat sources, scores, and verdicts as material with provenance, not decoration.
- Prefer dense, scannable instrument controls and plain user-facing language over decorative hierarchy.
- Use progressive disclosure: keep the transcript calm while allowing the trace, sources, metrics, and reviewer detail to be inspected on demand.
- Make state unmistakable with semantic colour plus shape, text, and accessible focus affordances.

## Accessibility & Inclusion

Target WCAG 2.1 AA contrast in both themes. Verdict colour is always paired with shape or text. Every interactive control has a visible Ember 2px keyboard focus ring, and `prefers-reduced-motion` removes nonessential transitions while preserving state changes. Tables, metrics, and charts have text equivalents, and controls remain usable by keyboard and assistive technology.
