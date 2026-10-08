import type { Decision } from '../../generated/types.gen'
import { failedGate, type EvidenceGate } from './evidenceGates'

export interface DeclineReason {
  /** One sentence naming the gate in plain words, e.g. "No retrieved passage
   *  is about the Kestrel K9." */
  sentence: string
  /** The gate this sentence is about, so the link and the card agree. */
  gate: EvidenceGate
}

/** The nouns a decline names: the thing the question asked about, and the
 *  thing the sources turned out to be about. Present on the retrieval event
 *  either way, so a decline that had nothing to retrieve still reads right. */
export interface DeclineNouns {
  entity?: string
  passage?: string
}

/** Pull the capitalised or code-shaped names out of a question, so the decline
 *  can say which one nothing was found about. Mirrors the backend's
 *  `named_entities` stop-word list (graph/auto.py) rather than inventing a
 *  second, looser one: a noun the gate never checked is a noun this sentence
 *  must not blame. */
const ENTITY_STOP = new Set([
  'Compare', 'How', 'What', 'Why', 'When', 'Where', 'Who', 'Which', 'Does',
  'Did', 'Can', 'Could', 'Should', 'Shall', 'May', 'Might', 'The', 'A', 'An',
  'This', 'That', 'These', 'Those', 'There', 'Here', 'It', 'I', 'You', 'We',
  'They', 'He', 'She', 'My', 'Your', 'Our', 'Their', 'In', 'On', 'At', 'For',
  'With', 'From', 'About', 'Into', 'Over', 'Under', 'Per', 'Also', 'Please',
  'Note', 'Hi', 'Hello', 'Thanks', 'Thank', 'Yes', 'No',
  'Quel', 'Quels', 'Qui', 'Quand', 'Comment', 'Pourquoi',
  'Wer', 'Was', 'Wie', 'Wann', 'Wo', 'Warum', 'Welche', 'Welcher', 'Welches',
])

// The same two patterns `named_entities` uses (graph/auto.py), copied rather
// than loosened: the sentence must name what the entity gate was actually
// asked about. A wider pattern here would let the copy blame a noun no gate
// ever checked, which is the one thing this sentence must not do.
const MODEL_CODE = /\b[A-Z]{1,4}-?\d{1,4}(?:[-/]\d{1,4})*\b/g
const CAPITALISED_NAME = /\b[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|the))*(?=\b)/g

/** Honorifics are not names. "Mr" reaches the entity gate as its own entity
 *  and the judge handles it fine, but "No retrieved passage is about Mr" is
 *  not a sentence anyone should read. */
const HONORIFIC = /^(?:Mr|Mrs|Ms|Dr|Prof|Sir|Lord|Lady)\.?$/

export function questionEntities(question: string): string[] {
  const codes: string[] = []
  const names: string[] = []
  for (const match of question.matchAll(MODEL_CODE)) codes.push(match[0])
  for (const match of question.matchAll(CAPITALISED_NAME)) {
    const value = match[0]
    if (ENTITY_STOP.has(value) || HONORIFIC.test(value)) continue
    // A name at the very start of a question is usually the sentence's first
    // word, not a subject: "Frankenstein warns…" over "In what ways do Victor
    // Frankenstein…". The backend makes the same call (graph/auto.py).
    if (match.index === 0) continue
    names.push(value)
  }
  // Names before codes, so "the Kestrel K9" is named as Kestrel rather than by
  // the suffix the code regex also matched. Both reached the gate; only one of
  // them is the thing a reader recognises as the subject.
  return [...new Set([...names, ...codes])]
}

/** Name the gate that stopped the run, in the design system's plain voice
 *  (design-system.md §8: plain, specific, no filler).
 *
 *  Each gate gets its own sentence because each one failed for a different
 *  reason, and a generic "insufficient evidence" is exactly what the trace
 *  exists to replace. The wording is about what the reader can check — the
 *  thing asked about, the passages retrieved — not about the model's
 *  confidence.
 *
 *  There is no conflict sentence, and that is deliberate rather than an
 *  omission: a conflict is a *disclosure* beside an answer (the run discloses
 *  and answers, graph/auto.py), so it never appears in the failed-gate set
 *  `failedGate` returns and cannot be the reason a run declined.
 */
function sentenceFor(gate: EvidenceGate, nouns: DeclineNouns): string {
  switch (gate.key) {
    case 'entity':
      return nouns.entity
        ? `No retrieved passage is about ${nouns.entity}.`
        : 'None of the retrieved passages is about the thing you asked about.'
    case 'relevance':
      return 'Nothing retrieved was close enough to the question to answer from.'
    case 'sufficient':
      return 'What was retrieved does not cover enough of the question to answer it.'
    default:
      return 'The retrieved sources do not contain enough evidence to answer this question.'
  }
}

/** The decline reason for a run, or null when nothing blocked it.
 *
 *  `declined` is a flag rather than the `abstain` event because the sentence
 *  has to work for a reopened message too, where the event is not in hand —
 *  only the persisted `status === "abstained"` and the replayed decisions are.
 *  Taking the event would have made this work live only, which is half the
 *  time a reader meets a decline.
 *
 *  Returns null rather than a guess when no gate blocked: a decline with no
 *  failed gate is a case the card cannot explain, and inventing a reason for
 *  it would be worse than showing none.
 */
export function declineReason(
  declined: boolean,
  decisions: Decision[],
  question: string | null | undefined,
  retrieved?: Array<{ document_name?: string | null; page?: number | null }>,
): DeclineReason | null {
  if (!declined) return null
  const gate = failedGate(decisions)
  if (!gate) return null
  const entities = questionEntities(question ?? '')
  const passage = retrieved?.find((chunk) => chunk.document_name)?.document_name ?? undefined
  return {
    sentence: sentenceFor(gate, { entity: entities[0], passage }),
    gate,
  }
}