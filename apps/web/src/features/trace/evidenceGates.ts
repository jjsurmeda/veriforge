import type { Decision } from '../../generated/types.gen'
import { probabilityOf, type OutcomeTone } from './decisionMeta'

/** How a gate read, in the shape the design system asks for: a state name and
 *  a tone. The row always renders the label as text and a distinct icon per
 *  state, so the verdict never depends on colour alone (PRODUCT.md,
 *  design-system.md §2). */
export type GateState = 'cleared' | 'blocked' | 'disclosed' | 'observed'

export interface EvidenceGate {
  key: string
  label: string
  /** The gate's own number, or null when the event carried none. */
  value: number | null
  /** The floor the value was compared against, from the event. */
  threshold: number | null
  state: GateState
  label2: string
  tone: OutcomeTone
  engine: Decision['engine']
  /** How many checks this row folds together. Meaningful only for the
   *  per-passage families; for sufficiency and relevance a count above one
   *  means "the run retried", not "N measurements". */
  sample: number
  perPassage: boolean
}

/** One row per gate, in the order the run applied them: sufficiency, then
 *  relevance, then entity match, then conflict. Every gate here is a
 *  "cleared means the run continued" check except conflict, which clears when
 *  the sources agree — so its own label and shape carry that distinction
 *  rather than a shared pass/fail. */
const GATES = [
  { key: 'sufficient', label: 'Sufficiency', match: (name: string) => name === 'sufficient' },
  { key: 'relevance', label: 'Relevance', match: (name: string) => name === 'relevance' },
  { key: 'entity', label: 'Entity match', match: (name: string) => name.startsWith('entity_') },
  {
    key: 'conflict',
    label: 'Conflict',
    match: (name: string) => name === 'conflict' || name.startsWith('conflict_'),
  },
] as const

/** Cleared / blocked wording per gate, in the design system's plain voice. */
const VERDICT_TEXT: Record<string, { cleared: string; blocked: string }> = {
  sufficient: { cleared: 'answered', blocked: 'too little evidence' },
  relevance: { cleared: 'on topic', blocked: 'off topic' },
  entity: { cleared: 'matched', blocked: 'no passage matches' },
  conflict: { cleared: 'sources agree', blocked: 'disclosed' },
}

const TONES: Record<GateState, OutcomeTone> = {
  cleared: 'success',
  blocked: 'danger',
  disclosed: 'warning',
  observed: 'neutral',
}

function stateFor(key: string, value: number | null, threshold: number | null): GateState {
  if (threshold === null || value === null) return 'observed'
  const cleared = value >= threshold
  // The conflict gate inverts: a high value means two sources disagreed and
  // the run said so, which is the disclosure working, not the gate failing.
  if (key === 'conflict') return cleared ? 'disclosed' : 'cleared'
  return cleared ? 'cleared' : 'blocked'
}

export function evidenceGates(decisions: Decision[]): EvidenceGate[] {
  const gates: EvidenceGate[] = []
  for (const gate of GATES) {
    const matches = decisions.filter((decision) => gate.match(decision.name))
    if (matches.length === 0) continue
    // A run can publish several of these: one rewrite + retry for the
    // single-valued gates, one Noul per passage for entity, one per candidate
    // pair for conflict. For the per-passage families the row shows the best
    // check, because that is the one that decided the gate — any passage
    // clearing the floor is a match, and the conflict that gets disclosed is
    // the most severe pair, not the last pair asked about. For sufficiency and
    // relevance the last decision is the one the run acted on.
    const byValue = matches.reduce((top, decision) =>
      (probabilityOf(decision) ?? -1) > (probabilityOf(top) ?? -1) ? decision : top,
    )
    const perPassage = gate.key === 'entity' || gate.key === 'conflict'
    const chosen = perPassage ? byValue : matches[matches.length - 1]
    const threshold = chosen.threshold ?? null
    const value = probabilityOf(chosen)
    const state = stateFor(gate.key, value, threshold)
    const text = VERDICT_TEXT[gate.key]
    gates.push({
      key: gate.key,
      label: gate.label,
      value,
      threshold,
      state,
      label2: state === 'observed' ? 'no threshold' : text[state === 'disclosed' ? 'blocked' : state],
      tone: TONES[state],
      engine: chosen.engine,
      sample: matches.length,
      perPassage,
    })
  }
  return gates
}

/** The gate that stopped the run, or null when nothing did. Ordered the same
 *  way the pipeline applies them, so the message names the first gate to fail
 *  rather than whichever happens to sit last in the event list. */
export function failedGate(decisions: Decision[]): EvidenceGate | null {
  return evidenceGates(decisions).find((gate) => gate.state === 'blocked') ?? null
}