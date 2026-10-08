import { ShieldAlert } from 'lucide-react'

import type { Decision } from '../../../generated/types.gen'
import { declineReason } from '../declineReason'

/** Item 2: the abstain message names the gate that stopped the run, in plain
 *  words, with a link that opens the gate card. The sentence is the
 *  user-facing half; the card is the evidence, one click away.
 *
 *  Renders nothing unless a gate actually blocked, so a decline the trace
 *  cannot explain does not get an invented reason — `declineReason` returns
 *  null in that case rather than guessing. */
export function DeclineReason({
  declined,
  decisions,
  question,
  retrieved,
  onShowGates,
}: {
  /** True when the message is an abstention, live or replayed. */
  declined: boolean
  decisions: Decision[]
  question?: string | null
  retrieved?: Array<{ document_name?: string | null; page?: number | null }>
  onShowGates?: () => void
}) {
  const reason = declineReason(declined, decisions, question, retrieved)
  if (!reason) return null
  return (
    <div className="mt-3 rounded-lg border border-warning/40 bg-raised px-3 py-2.5">
      <p className="flex items-start gap-2 text-xs leading-5 text-fg">
        <ShieldAlert
          size={13}
          strokeWidth={1.75}
          className="mt-0.5 shrink-0 text-warning"
          aria-hidden="true"
        />
        <span>
          <span className="text-fg-muted">Why it declined: </span>
          <span>{reason.sentence}</span>
        </span>
      </p>
      {onShowGates && (
        <button
          type="button"
          onClick={onShowGates}
          className="mt-2 inline-flex min-h-8 items-center gap-1.5 rounded-md px-1 text-xs text-fg-muted underline decoration-border underline-offset-2 transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
        >
          See the {reason.gate.label.toLowerCase()} gate
        </button>
      )}
    </div>
  )
}