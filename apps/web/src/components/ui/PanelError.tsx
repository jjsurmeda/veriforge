import type { ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

/** The counterpart to `PanelEmpty`: a read that failed. Same scale, an alert
 *  role — but it names what could not be read instead of claiming the thing
 *  is empty. A dead API must never render as an empty corpus, and the
 *  icon-plus-sentence keeps the state off colour alone.
 *
 *  `compact` is the rail version (the 280px chat sidebar): left-aligned and
 *  tight, because the design system centres only for empty and auth states,
 *  and a centred block that size crowds a navigation list. */
export function PanelError({
  icon,
  title,
  hint,
  action,
  compact = false,
}: {
  icon?: ReactNode
  title: string
  hint: string
  action?: ReactNode
  compact?: boolean
}) {
  if (compact) {
    return (
      <div role="alert" className="px-1 py-4 text-left">
        <p className="flex items-start gap-2 text-xs font-medium text-fg">
          <AlertTriangle
            size={14}
            strokeWidth={1.75}
            className="mt-0.5 shrink-0 text-danger"
            aria-hidden="true"
          />
          <span className="min-w-0">{title}</span>
        </p>
        <p className="mt-1 pl-6 text-2xs leading-4 text-fg-muted">{hint}</p>
        {action && <div className="mt-2 pl-6">{action}</div>}
      </div>
    )
  }
  return (
    <div role="alert" className="flex flex-col items-center px-4 py-10 text-center">
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-raised text-danger">
        {icon ?? <AlertTriangle size={18} strokeWidth={1.75} aria-hidden="true" />}
      </span>
      <p className="mt-3 text-sm font-medium text-fg">{title}</p>
      <p className="mt-1 max-w-[34ch] text-xs leading-5 text-fg-muted">{hint}</p>
      {action && <div className="mt-4 w-full">{action}</div>}
    </div>
  )
}