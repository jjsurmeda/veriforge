import { AlertTriangle, Check, Info, ShieldCheck, X } from 'lucide-react'

import type { Decision } from '../../../generated/types.gen'
import { evidenceGates, type EvidenceGate, type GateState } from '../evidenceGates'
import { EngineBadge } from './DecisionTimeline'

/** design-system.md §2: a status colour may be a 6px dot or a text label, never
 *  an ambient fill, and PRODUCT.md requires a shape beside every verdict. Each
 *  state therefore carries its own icon — the shape is what distinguishes
 *  "cleared" from "blocked" when the colour does not. */
function StateIcon({ state }: { state: GateState }) {
  const Icon = state === 'cleared' ? Check : state === 'blocked' ? X : state === 'disclosed' ? AlertTriangle : Info
  return <Icon size={12} strokeWidth={2} aria-hidden="true" />
}

const TONE_CLASS: Record<EvidenceGate['tone'], string> = {
  neutral: 'text-fg-muted',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
}

function GateRow({ gate }: { gate: EvidenceGate }) {
  const value = gate.value ?? 0
  const width = Math.max(0, Math.min(100, value * 100))
  const mark = gate.threshold === null ? null : Math.max(0, Math.min(100, gate.threshold * 100))
  const meterLabel =
    gate.threshold === null
      ? `${gate.label} value ${value.toFixed(2)}, no threshold recorded`
      : `${gate.label} value ${value.toFixed(2)}, threshold ${gate.threshold.toFixed(2)}, ${gate.label2}`
  return (
    <li className="space-y-1.5 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-fg">{gate.label}</span>
        <span className="flex items-center gap-1.5">
          <EngineBadge engine={gate.engine} />
          <span className={`inline-flex items-center gap-1 text-2xs font-medium ${TONE_CLASS[gate.tone]}`}>
            <StateIcon state={gate.state} />
            {gate.label2}
          </span>
        </span>
      </div>
      <div className="flex items-center gap-2">
        <div
          className="relative h-2 min-w-0 flex-1 overflow-visible rounded-full bg-sidebar"
          role="meter"
          aria-label={meterLabel}
          aria-valuemin={0}
          aria-valuemax={1}
          aria-valuenow={value}
        >
          <div className="h-full rounded-full bg-fg-strong" style={{ width: `${width}%` }} />
          {mark !== null && (
            <span
              className="absolute -top-1 bottom-[-4px] border-l-2 border-border"
              style={{ left: `${mark}%` }}
              aria-hidden="true"
            />
          )}
        </div>
        <span className="w-9 text-right font-mono text-2xs tabular-nums text-fg">{value.toFixed(2)}</span>
        {gate.threshold !== null && (
          <span className="w-12 text-right font-mono text-2xs tabular-nums text-fg-muted">
            vs {gate.threshold.toFixed(2)}
          </span>
        )}
      </div>
      {gate.perPassage && gate.sample > 1 && (
        <p className="font-mono text-2xs text-fg-muted">best of {gate.sample} passages</p>
      )}
    </li>
  )
}

/** Lane E item 1: the answer to "why did it answer, or why did it decline",
 *  as one row per gate with the value it produced, the floor it was compared
 *  against, a verdict and the engine that produced the number. Reads the
 *  `decision` events the run already publishes (no new event type), so it
 *  works for a finished run replayed from the bus as well as a live stream. */
export function EvidenceGateCard({ decisions }: { decisions: Decision[] }) {
  const gates = evidenceGates(decisions)
  if (gates.length === 0) return null
  return (
    <section id="evidence-gates" aria-labelledby="evidence-gates-heading" className="rounded-lg border border-border bg-surface">
      <header className="flex items-center gap-2 border-b border-border px-3 py-2">
        <ShieldCheck size={13} strokeWidth={1.75} className="text-fg" aria-hidden="true" />
        <h3 id="evidence-gates-heading" className="text-xs font-semibold text-fg">
          Evidence gates
        </h3>
      </header>
      <ul className="divide-y divide-border/70">
        {gates.map((gate) => (
          <GateRow key={gate.key} gate={gate} />
        ))}
      </ul>
    </section>
  )
}