import { useState } from 'react'
import { AlertTriangle, Check, ChevronDown, ChevronRight, Info, Sparkles, X } from 'lucide-react'

import type { Decision } from '../../../generated/types.gen'
import {
  decisionLabel,
  decisionOutcome,
  decisionStageLabel,
  groupDecisions,
  probabilityOf,
  type DecisionGroup,
  type OutcomeTone,
} from '../decisionMeta'

function engineLabel(engine: Decision['engine']): string {
  return engine === 'jev' ? 'Jev' : 'fallback'
}

function EngineBadge({ engine }: { engine: Decision['engine'] }) {
  const fallback = engine === 'fallback'
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 font-mono text-[0.6rem] ${
        fallback
          ? 'border-warning/30 bg-warning-soft text-warning'
          : 'border-accent/25 bg-accent-soft text-accent'
      }`}
      title={fallback ? 'Jev unavailable — answered by LLM fallback' : undefined}
    >
      {fallback ? <AlertTriangle size={10} aria-hidden="true" /> : <Sparkles size={10} aria-hidden="true" />}
      {engineLabel(engine)}
    </span>
  )
}

function Outcome({ label, tone }: { label: string; tone: OutcomeTone }) {
  const toneClass = {
    neutral: 'text-muted-foreground',
    success: 'text-success',
    warning: 'text-warning',
    danger: 'text-danger',
  }[tone]
  const Icon = tone === 'success' ? Check : tone === 'danger' ? X : tone === 'warning' ? AlertTriangle : Info
  return (
    <span className={`inline-flex items-center gap-1 text-[0.65rem] font-medium ${toneClass}`}>
      <Icon size={11} aria-hidden="true" />
      {label}
    </span>
  )
}

function Reasoning({ reasoning }: { reasoning: string | null | undefined }) {
  if (!reasoning) return null
  return (
    <details className="mt-1 text-xs text-muted-foreground">
      <summary className="cursor-pointer hover:text-foreground">reasoning</summary>
      <p className="mt-1 whitespace-pre-wrap">{reasoning}</p>
    </details>
  )
}

function NoulRow({ decision, stage }: { decision: Decision; stage: string | null }) {
  const probability = probabilityOf(decision)
  const threshold = decision.threshold
  const width = Math.max(0, Math.min(100, (probability ?? 0) * 100))
  const thresholdPosition = threshold === null || threshold === undefined
    ? null
    : Math.max(0, Math.min(100, threshold * 100))
  const outcome = decisionOutcome(decision)
  const label = decisionLabel(decision.name, stage)
  const meterLabel = threshold === null || threshold === undefined
    ? `${label} probability ${(probability ?? 0).toFixed(2)}`
    : `${label} probability ${(probability ?? 0).toFixed(2)}, threshold ${threshold.toFixed(2)}`

  return (
    <li className="space-y-1.5 py-2">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium text-foreground">{label}</span>
        <EngineBadge engine={decision.engine} />
      </div>
      <div className="flex items-center gap-2">
        <div
          className="relative h-2 min-w-0 flex-1 overflow-visible rounded-full bg-surface-muted"
          role="meter"
          aria-label={meterLabel}
          aria-valuemin={0}
          aria-valuemax={1}
          aria-valuenow={probability ?? 0}
        >
          <div className="h-full rounded-full bg-accent" style={{ width: `${width}%` }} />
          {thresholdPosition !== null && (
            <span
              className="absolute -top-1 bottom-[-4px] border-l-2 border-foreground"
              style={{ left: `${thresholdPosition}%` }}
              aria-hidden="true"
            />
          )}
        </div>
        <span className="w-9 text-right font-mono text-[0.65rem] text-foreground">{(probability ?? 0).toFixed(2)}</span>
        <Outcome label={outcome.label} tone={outcome.tone} />
      </div>
      <Reasoning reasoning={decision.reasoning} />
    </li>
  )
}

function ChoiceRow({ decision, stage }: { decision: Decision; stage: string | null }) {
  const spread = Object.entries(decision.probabilities ?? {}).sort(([, left], [, right]) => right - left)
  const winner = String(decision.value)
  const winnerProbability = decision.probabilities?.[winner] ?? decision.probability
  return (
    <li className="space-y-1.5 py-2">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium text-foreground">{decisionLabel(decision.name, stage)}</span>
        <EngineBadge engine={decision.engine} />
      </div>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-xs">
        <span className="font-medium text-foreground">{winner}</span>
        {winnerProbability !== null && winnerProbability !== undefined && (
          <span className="font-mono text-muted-foreground">{(winnerProbability * 100).toFixed(0)}%</span>
        )}
      </div>
      {spread.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-[0.65rem] text-muted-foreground">
          {spread.map(([option, probability]) => (
            <span key={option}>
              {option} {(probability * 100).toFixed(0)}%
            </span>
          ))}
        </div>
      )}
      <Reasoning reasoning={decision.reasoning} />
    </li>
  )
}

function ScoreRow({ decision }: { decision: Decision }) {
  const value = typeof decision.value === 'number' ? decision.value : Number(decision.value)
  const lexical = decision.name === 'lexical_weight' && Number.isFinite(value)
  const vector = lexical ? Math.max(0, Math.min(1, 1 - value)) : null
  return (
    <li className="space-y-1.5 py-2">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium text-foreground">{decisionLabel(decision.name)}</span>
        <EngineBadge engine={decision.engine} />
      </div>
      <div className="font-mono text-xs text-foreground">{Number.isFinite(value) ? value.toFixed(2) : decision.value}</div>
      {lexical && vector !== null && (
        <div className="font-mono text-[0.65rem] text-muted-foreground">
          BM25 {(value * 100).toFixed(0)}% / vector {(vector * 100).toFixed(0)}%
        </div>
      )}
      <Reasoning reasoning={decision.reasoning} />
    </li>
  )
}

function GenericRow({ decision, stage }: { decision: Decision; stage: string | null }) {
  const outcome = decisionOutcome(decision)
  return (
    <li className="space-y-1 py-2">
      <div className="flex items-center justify-between gap-2 text-xs">
        <span className="font-medium text-foreground">{decisionLabel(decision.name, stage)}</span>
        <span className="flex items-center gap-2">
          <Outcome label={outcome.label} tone={outcome.tone} />
          <EngineBadge engine={decision.engine} />
        </span>
      </div>
      <div className="font-mono text-xs text-muted-foreground">{String(decision.value)}</div>
      <Reasoning reasoning={decision.reasoning} />
    </li>
  )
}

function DecisionValueRow({ decision, stage }: { decision: Decision; stage: string | null }) {
  if (decision.name === 'lexical_weight') return <ScoreRow decision={decision} />
  if (decision.probabilities) return <ChoiceRow decision={decision} stage={stage} />
  if (decision.probability !== null && decision.probability !== undefined) {
    return <NoulRow decision={decision} stage={stage} />
  }
  if (decision.threshold !== null && decision.threshold !== undefined) {
    return <NoulRow decision={decision} stage={stage} />
  }
  return <GenericRow decision={decision} stage={stage} />
}

function isDynamicDecision(decision: Decision): boolean {
  return decision.stage === 'claim_verdict' || decision.name.startsWith('chunk_injection_')
}

function DynamicSummary({
  decisions,
  stage,
}: {
  decisions: Decision[]
  stage: string | null
}) {
  const [expanded, setExpanded] = useState(false)
  const labels = new Set(decisions.map((decision) => decisionLabel(decision.name, decision.stage ?? stage)))
  const label = labels.size === 1 ? [...labels][0] : 'Dynamic checks'
  return (
    <li className="py-1">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-xs text-foreground transition-colors duration-150 hover:bg-surface-muted focus-visible:outline-2 focus-visible:outline-accent motion-reduce:transition-none"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className="inline-flex items-center gap-1.5">
          {expanded ? <ChevronDown size={13} aria-hidden="true" /> : <ChevronRight size={13} aria-hidden="true" />}
          {decisions.length} {label}
        </span>
        <span className="font-mono text-[0.65rem] text-muted-foreground">show details</span>
      </button>
      {expanded && (
        <ul className="mt-1 border-l border-border pl-2">
          {decisions.map((decision, index) => (
            <DecisionValueRow key={`${decision.name}-${index}`} decision={decision} stage={decision.stage ?? stage} />
          ))}
        </ul>
      )}
    </li>
  )
}

function DecisionGroupSection({ group }: { group: DecisionGroup }) {
  const dynamic = group.decisions.filter(isDynamicDecision)
  const ordinary = group.decisions.filter((decision) => !isDynamicDecision(decision))
  const maxLatency = Math.max(0, ...group.decisions.map((decision) => decision.latency_ms))
  const questionCount = group.decisions[0]?.batch_size ?? group.decisions.length
  const engines = [...new Set(group.decisions.map((decision) => decision.engine))]
  const callLabel = engines.length === 1 ? `1 ${engineLabel(engines[0])} call` : `${engines.length} engines`

  return (
    <section className="rounded-lg border border-border bg-surface">
      <header className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 border-b border-border px-3 py-2">
        <h3 className="text-xs font-semibold text-foreground">{decisionStageLabel(group.stage)}</h3>
        <span className="font-mono text-[0.6rem] text-muted-foreground">
          {callLabel} · {questionCount} questions · {maxLatency} ms
        </span>
      </header>
      <ul className="divide-y divide-border/70 px-3">
        {ordinary.map((decision, index) => (
          <DecisionValueRow key={`${decision.name}-${index}`} decision={decision} stage={decision.stage ?? group.stage} />
        ))}
        {dynamic.length > 0 && <DynamicSummary decisions={dynamic} stage={group.stage} />}
      </ul>
    </section>
  )
}

export function DecisionTimeline({ decisions }: { decisions: Decision[] }) {
  if (decisions.length === 0) return null
  return (
    <div className="space-y-3">
      {groupDecisions(decisions).map((group) => (
        <DecisionGroupSection key={group.key} group={group} />
      ))}
    </div>
  )
}

export function DecisionSummary({ decisions }: { decisions: Decision[] }) {
  if (decisions.length === 0) return null
  const jevCount = decisions.filter((decision) => decision.engine === 'jev').length
  const slowestCall = Math.max(
    0,
    ...groupDecisions(decisions).map((group) => Math.max(...group.decisions.map((decision) => decision.latency_ms))),
  )
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-border bg-surface-muted px-2.5 py-2 font-mono text-[0.65rem] text-muted-foreground">
      <span>{decisions.length} decisions</span>
      <span aria-hidden="true">·</span>
      <span>Jev {jevCount}/{decisions.length}</span>
      <span aria-hidden="true">·</span>
      <span>slowest call {slowestCall} ms</span>
    </div>
  )
}
