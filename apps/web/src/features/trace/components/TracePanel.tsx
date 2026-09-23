import type { Decision, StepCompleted, StepStarted } from '../../../generated/types.gen'

interface Props {
  steps: Array<StepStarted | StepCompleted>
  decisions: Decision[]
  thinking: string
  streaming: boolean
}

function StepRow({ step }: { step: StepStarted | StepCompleted }) {
  const isCompleted = step.type === 'step.completed'
  return (
    <li className="flex items-baseline justify-between gap-2 py-0.5 text-xs">
      <span className="text-paper/80">{step.label}</span>
      <span className="text-paper/40">
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
    <li className="border-l border-mist/40 py-1 pl-3">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-medium text-paper/90">{decision.name}</span>
        <span className="flex items-baseline gap-2 text-paper/50">
          <span>{decision.engine}</span>
          <span>{decision.latency_ms} ms</span>
        </span>
      </div>
      <div className="mt-0.5 text-xs text-paper/70">
        {valueLabel}
        {probability !== null && probability !== undefined && (
          <span className="ml-2 text-paper/40">p={probability.toFixed(2)}</span>
        )}
      </div>
      {decision.reasoning && (
        <details className="mt-1 text-xs text-paper/50">
          <summary className="cursor-pointer hover:text-paper/70">reasoning</summary>
          <p className="mt-1 whitespace-pre-wrap">{decision.reasoning}</p>
        </details>
      )}
    </li>
  )
}

export function TracePanel({ steps, decisions, thinking, streaming }: Props) {
  return (
    <aside className="flex w-80 flex-col border-l border-mist bg-graphite/60 text-paper">
      <header className="border-b border-mist px-4 py-3">
        <h2 className="text-sm font-medium text-paper/90">Trace</h2>
        {streaming && <p className="mt-0.5 text-xs text-paper/50">live</p>}
      </header>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {thinking.length > 0 && (
          <section>
            <details>
              <summary className="cursor-pointer text-xs font-medium text-paper/70 hover:text-paper">
                Thinking
              </summary>
              <p className="mt-2 whitespace-pre-wrap text-xs text-paper/60">{thinking}</p>
            </details>
          </section>
        )}
        {steps.length > 0 && (
          <section>
            <h3 className="text-xs font-medium uppercase tracking-wide text-paper/50">
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
            <h3 className="text-xs font-medium uppercase tracking-wide text-paper/50">
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
          <p className="text-xs text-paper/40">
            Decisions and reasoning stream here while a run is in flight.
          </p>
        )}
      </div>
    </aside>
  )
}
