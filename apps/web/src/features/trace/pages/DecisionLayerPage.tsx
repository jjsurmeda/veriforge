import { useNavigate } from '@tanstack/react-router'
import { ArrowLeft } from 'lucide-react'

import { DecisionLayerPanel } from '../components/DecisionLayerPanel'

/** Lane E item 3: the decision layer for the demo role.
 *
 *  A page rather than a Trace tab because the numbers describe the whole
 *  deployment, not one run — the trace is per-run, and putting deployment
 *  totals inside a run's trace would invite the reader to treat them as that
 *  run's. Read-only throughout: the panel this renders has no control that
 *  writes, and the one control it has (the window select) only changes the
 *  query. */
export function DecisionLayerPage() {
  const navigate = useNavigate()
  return (
    <div className="h-full overflow-y-auto bg-main text-fg">
      <header className="border-b border-border bg-sidebar px-5 py-4 sm:px-8">
        <div className="mx-auto flex max-w-5xl items-center gap-3">
          <button
            type="button"
            onClick={() => void navigate({ to: '/' })}
            className="icon-button size-8"
            aria-label="Back to chats"
          >
            <ArrowLeft size={16} strokeWidth={1.75} aria-hidden="true" />
          </button>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-muted">Read-only</p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight text-fg">Decision layer</h1>
          </div>
        </div>
      </header>
      <div className="mx-auto max-w-5xl px-5 py-6 sm:px-8">
        <p className="mb-5 max-w-[62ch] text-sm leading-6 text-fg-muted">
          Every gate, routing choice and reviewer verdict in Veriforge goes through one decision engine, with
          Jev as the primary answerer and an LLM fallback behind a circuit breaker. These are the live
          numbers behind that: which engine answered, how long it took, and where the two disagreed.
        </p>
        <DecisionLayerPanel />
      </div>
    </div>
  )
}