import type { Decision } from '../../generated/types.gen'

export type OutcomeTone = 'neutral' | 'success' | 'warning' | 'danger'

export interface DecisionGroup {
  key: string
  stage: string | null
  decisions: Decision[]
}

export interface DecisionOutcome {
  label: string
  tone: OutcomeTone
}

const LABELS: Record<string, string> = {
  guard_injection: 'Injection',
  guard_jailbreak: 'Jailbreak',
  guard_pii: 'PII',
  off_topic: 'Off-topic',
  intent: 'Intent',
  source: 'Source',
  complexity: 'Complexity',
  risk: 'Risk',
  lexical_weight: 'Lexical weight',
  sufficient: 'Sufficient',
  relevance: 'Relevance',
  conflict: 'Conflict',
  controller: 'Controller',
  output_toxicity: 'Output toxicity',
  output_secrets: 'Output secrets',
}

const STAGE_LABELS: Record<string, string> = {
  ingress: 'Ingress',
  sanitize: 'Sanitiser',
  sufficient: 'Sufficiency',
  conflict: 'Conflict',
  controller: 'Controller',
  claim_verdict: 'Review',
  output_guard: 'Output guard',
}

export function decisionLabel(name: string, stage?: string | null): string {
  if (stage === 'claim_verdict' || name.startsWith('claim_')) return 'Claim verdicts'
  if (name.startsWith('chunk_injection_')) return 'Chunk checks'
  // One Noul per top-k passage (KI-54), so there are as many of these as
  // passages. The gate card folds them into a single "Entity match" row and
  // the timeline collapses them; naming the family once here is what makes
  // both read as one check instead of N.
  if (name.startsWith('entity_')) return 'Entity match'
  if (name.startsWith('conflict_')) return 'Conflict'
  return LABELS[name] ?? name
}

export function decisionStageLabel(stage: string | null | undefined): string {
  if (!stage) return 'Decisions'
  const known = STAGE_LABELS[stage]
  if (known) return known
  const parts = stage.split('_')
  return parts.map((part, index) => (index === 0 ? part.charAt(0).toUpperCase() + part.slice(1) : part)).join(' ')
}

export function groupDecisions(decisions: Decision[]): DecisionGroup[] {
  const groups = new Map<string, DecisionGroup>()
  for (const decision of decisions) {
    const key = decision.call_id
      ? `call:${decision.call_id}`
      : decision.stage
        ? `stage:${decision.stage}`
        : 'legacy'
    const existing = groups.get(key)
    if (existing) {
      existing.decisions.push(decision)
    } else {
      groups.set(key, { key, stage: decision.stage ?? null, decisions: [decision] })
    }
  }
  return [...groups.values()]
}

export function probabilityOf(decision: Decision): number | null {
  if (decision.probability !== null && decision.probability !== undefined) {
    return decision.probability
  }
  if (!decision.probabilities) {
    // A gate whose number is computed rather than asked for — the relevance
    // gate takes the max rerank score and publishes it as `value`, with no
    // `probability` — used to read as 0.00 here, because the only two sources
    // consulted were `probability` and `probabilities`. For a Noul-shaped
    // decision `value` IS the yes-probability (schemas/decisions.py), so this
    // is the real number rather than a fallback guess.
    return typeof decision.value === 'number' ? decision.value : null
  }
  const value = String(decision.value)
  const selected = decision.probabilities[value]
  if (selected !== undefined) return selected
  return Math.max(...Object.values(decision.probabilities))
}

export function decisionOutcome(decision: Decision): DecisionOutcome {
  const threshold = decision.threshold
  const probability = probabilityOf(decision)
  if (threshold === null || threshold === undefined) {
    if (decision.probabilities) return { label: 'choice', tone: 'neutral' }
    if (decision.name === 'lexical_weight') return { label: 'weight', tone: 'neutral' }
    return { label: 'observed', tone: 'neutral' }
  }

  const above = probability !== null && probability >= threshold
  if (decision.name === 'guard_injection' || decision.name === 'guard_jailbreak') {
    return above ? { label: 'block', tone: 'danger' } : { label: 'pass', tone: 'success' }
  }
  if (decision.name === 'guard_pii' || decision.name === 'off_topic') {
    return above ? { label: 'warn', tone: 'warning' } : { label: 'pass', tone: 'success' }
  }
  if (decision.name === 'output_toxicity') {
    return above ? { label: 'block', tone: 'danger' } : { label: 'pass', tone: 'success' }
  }
  if (decision.name === 'output_secrets') {
    return above ? { label: 'redact', tone: 'warning' } : { label: 'pass', tone: 'success' }
  }
  if (decision.name === 'sufficient') {
    return above ? { label: 'answer', tone: 'success' } : { label: 'retry', tone: 'warning' }
  }
  if (decision.name === 'conflict') {
    return above ? { label: 'disclose', tone: 'warning' } : { label: 'clear', tone: 'success' }
  }
  if (decision.name.startsWith('chunk_injection_')) {
    return above ? { label: 'drop', tone: 'danger' } : { label: 'keep', tone: 'success' }
  }
  if (decision.name === 'controller') {
    return above ? { label: 'sufficient', tone: 'success' } : { label: 'need more', tone: 'warning' }
  }
  return above ? { label: 'above threshold', tone: 'warning' } : { label: 'below threshold', tone: 'neutral' }
}
