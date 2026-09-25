import { Check, CircleX, LoaderCircle } from 'lucide-react'

const LIVE_STATUSES = new Set(['queued', 'parsing', 'embedding'])

export function StatusChip({ status }: { status: string }) {
  if (LIVE_STATUSES.has(status))
    return <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-raised px-1.5 py-0.5 text-[0.65rem] font-medium text-fg-muted"><LoaderCircle size={11} strokeWidth={1.75} className="animate-spin" aria-hidden="true" />{status}</span>
  if (status === 'ready')
    return <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-raised px-1.5 py-0.5 text-[0.65rem] font-medium text-success"><Check size={11} strokeWidth={1.75} aria-hidden="true" />ready</span>
  return <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-raised px-1.5 py-0.5 text-[0.65rem] font-medium text-danger"><CircleX size={11} strokeWidth={1.75} aria-hidden="true" />{status}</span>
}
