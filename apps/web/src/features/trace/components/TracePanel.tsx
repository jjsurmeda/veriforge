import { useState } from 'react'
import { Activity, BarChart3, FileText } from 'lucide-react'

import { formatCredits } from '../../../lib/format'
import type {
  Decision,
  Metrics,
  RetrievedChunk,
  StepCompleted,
  StepStarted,
} from '../../../generated/types.gen'
import { SourcesTab } from './SourcesTab'

interface Props {
  steps: Array<StepStarted | StepCompleted>
  decisions: Decision[]
  thinking: string
  streaming: boolean
  chunks: RetrievedChunk[]
  metrics: Metrics | null
  hold: boolean
}

type Tab = 'trace' | 'sources' | 'metrics'

function StepRow({ step }: { step: StepStarted | StepCompleted }) {
  const isCompleted = step.type === 'step.completed'
  return (
    <li className="flex items-baseline justify-between gap-2 py-0.5 text-xs">
      <span className="text-foreground">{step.label}</span>
      <span className="text-muted-foreground">
        {isCompleted ? `${(step as StepCompleted).duration_ms} ms` : '…'}
      </span>
    </li>
  )
}

function DecisionRow({ decision }: { decision: Decision }) {
  const probability = decision.probability
  const valueLabel =
    typeof decision.value === 'number'
      ? decision.value.toFixed(2)
      : String(decision.value)
  return (
    <li className="border-l border-border py-1 pl-3">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-medium text-foreground">{decision.name}</span>
        <span className="flex items-baseline gap-2 text-muted-foreground">
          <span>{decision.engine}</span>
          <span>{decision.latency_ms} ms</span>
        </span>
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">
        {valueLabel}
        {probability !== null && probability !== undefined && (
          <span className="ml-2 text-muted-foreground">p={probability.toFixed(2)}</span>
        )}
      </div>
      {decision.reasoning && (
        <details className="mt-1 text-xs text-muted-foreground">
          <summary className="cursor-pointer hover:text-muted-foreground">reasoning</summary>
          <p className="mt-1 whitespace-pre-wrap">{decision.reasoning}</p>
        </details>
      )}
    </li>
  )
}

function WaterfallRow({ label, ms, max }: { label: string; ms: number; max: number }) {
  const width = max > 0 ? Math.max(2, Math.round((ms / max) * 100)) : 0
  return (
    <li className="py-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-foreground">{label}</span>
        <span className="font-mono text-muted-foreground">{ms} ms</span>
      </div>
      <div className="mt-0.5 h-1.5 w-full rounded-sm bg-surface-muted">
        <div className="h-1.5 rounded-sm bg-border-strong" style={{ width: `${width}%` }} />
      </div>
    </li>
  )
}

function MetricsTab({ metrics }: { metrics: Metrics | null }) {
  if (!metrics) {
    return <p className="text-xs text-muted-foreground">Metrics land when the run completes.</p>
  }
  const latency = Object.entries(metrics.latency_ms ?? {})
  const max = Math.max(1, ...latency.map(([, ms]) => ms))
  const total = latency.reduce((sum, [, ms]) => sum + ms, 0)
  return (
    <div className="space-y-4 text-xs">
      <section>
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Latency by stage
        </h3>
        <ul className="mt-1">
          {latency.map(([label, ms]) => (
            <WaterfallRow key={label} label={label} ms={ms} max={max} />
          ))}
        </ul>
        <p className="mt-1 font-mono text-muted-foreground">total {total} ms</p>
      </section>
      <section>
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Answer scores
        </h3>
        <ul className="mt-1 space-y-0.5 font-mono text-muted-foreground">
          <li>faithfulness {metrics.faithfulness !== null && metrics.faithfulness !== undefined ? metrics.faithfulness.toFixed(2) : '—'}</li>
          <li>min support {metrics.min_support !== null && metrics.min_support !== undefined ? metrics.min_support.toFixed(2) : '—'}</li>
        </ul>
      </section>
      <section>
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Usage</h3>
        <ul className="mt-1 space-y-0.5 font-mono text-muted-foreground">
          <li>tokens in {metrics.tokens_in}</li>
          <li>tokens out {metrics.tokens_out}</li>
           <li>credits {metrics.credits !== undefined ? formatCredits(metrics.credits) : '—'}</li>
          <li>
            context {metrics.context_used} / {metrics.context_window}
          </li>
        </ul>
      </section>
    </div>
  )
}

export function TracePanel({
  steps,
  decisions,
  thinking,
  streaming,
  chunks,
  metrics,
  hold,
}: Props) {
  const [tab, setTab] = useState<Tab>('trace')
  const tabs: Array<{ id: Tab; label: string; icon: React.ReactNode }> = [
    { id: 'trace', label: 'Trace', icon: <Activity size={13} aria-hidden="true" /> },
    { id: 'sources', label: `Sources${chunks.length > 0 ? ` (${chunks.length})` : ''}`, icon: <FileText size={13} aria-hidden="true" /> },
    { id: 'metrics', label: 'Metrics', icon: <BarChart3 size={13} aria-hidden="true" /> },
  ]
  return (
    <aside className="hidden w-80 shrink-0 flex-col border-l border-border bg-surface/80 text-foreground shadow-sm backdrop-blur-md lg:flex">
      <header className="border-b border-border bg-surface-muted/40 px-4 py-3 backdrop-blur-sm">
        <div className="flex items-center justify-between gap-2">
          <nav className="flex gap-1" aria-label="Trace tabs">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                aria-current={tab === t.id}
                className={`inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs transition-[color,background-color,transform] duration-180 focus-visible:outline-2 focus-visible:outline-primary motion-reduce:transition-none ${
                  tab === t.id ? 'bg-primary-soft font-medium text-primary' : 'text-muted-foreground hover:bg-surface-muted hover:text-foreground'
                }`}
              >
                {t.icon}
                {t.label}
              </button>
            ))}
          </nav>
          {streaming && <span className="inline-flex items-center gap-1.5 text-xs text-info"><span className="size-1.5 animate-pulse rounded-full bg-info" aria-hidden="true" />live</span>}
        </div>
        {hold && (
          <p className="mt-2 rounded-lg border border-warning/30 bg-warning-soft px-2.5 py-2 text-xs text-warning" role="status">
            Verifying… the reviewed answer lands when checks finish.
          </p>
        )}
      </header>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">

        {tab === 'trace' && (
          <>
            {thinking.length > 0 && (
              <section>
                <details>
                  <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
                    Thinking
                  </summary>
                  <p className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">{thinking}</p>
                </details>
              </section>
            )}
            {steps.length > 0 && (
              <section>
                <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Steps
                </h3>
                <ul className="mt-1">
                  {steps.map((step, i) => (
                    <StepRow key={i} step={step} />
                  ))}
                </ul>
              </section>
            )}
            {decisions.length > 0 && (
              <section>
                <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Decisions
                </h3>
                <ul className="mt-1 space-y-1">
                  {decisions.map((decision, i) => (
                    <DecisionRow key={i} decision={decision} />
                  ))}
                </ul>
              </section>
            )}
            {steps.length === 0 && decisions.length === 0 && thinking.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Decisions and reasoning stream here while a run is in flight.
              </p>
            )}
          </>
        )}
        {tab === 'sources' && <SourcesTab chunks={chunks} />}
        {tab === 'metrics' && <MetricsTab metrics={metrics} />}
      </div>
    </aside>
  )
}
