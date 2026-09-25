import { ShieldCheck } from 'lucide-react'

import { ProfileMenu, QuotaBadge } from './ProfileMenu'

export { QuotaBadge } from './ProfileMenu'

export function AppHeader() {
  return (
    <header className="z-30 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-sidebar px-3 sm:px-5">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-fg">
          <ShieldCheck size={17} strokeWidth={1.75} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <p className="truncate font-display text-sm font-semibold tracking-tight text-fg">Veriforge</p>
          <p className="hidden truncate text-[0.65rem] text-fg-muted sm:block">Evidence workbench</p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
        <QuotaBadge side="bottom" align="end" />
        <ProfileMenu side="bottom" align="end" />
      </div>
    </header>
  )
}
