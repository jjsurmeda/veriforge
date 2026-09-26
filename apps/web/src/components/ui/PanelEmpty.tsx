import type { ReactNode } from 'react'

/** The workspace panel's empty state, on the design-system.md §3 scale only:
 *  UI sans, body-small medium for the title, caption for the hint. No mono,
 *  no serif — the panel is chrome, not trace metadata. */
export function PanelEmpty({
  icon,
  title,
  hint,
  action,
}: {
  icon?: ReactNode
  title: string
  hint: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center px-4 py-10 text-center">
      {icon && (
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-raised text-fg-muted">
          {icon}
        </span>
      )}
      <p className="mt-3 text-sm font-medium text-fg">{title}</p>
      <p className="mt-1 max-w-[34ch] text-xs leading-5 text-fg-muted">{hint}</p>
      {action && <div className="mt-4 w-full">{action}</div>}
    </div>
  )
}
