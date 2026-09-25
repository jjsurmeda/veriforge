import { useState, type FocusEvent } from 'react'
import { ChevronDown, Coins, ShieldCheck } from 'lucide-react'

import { ProfileMenu } from './ProfileMenu'
import { ThemeToggle } from './ThemeToggle'
import { useQuota } from '../features/chat/hooks/useQuota'
import { formatCredits } from '../lib/format'

function quotaPercent(remaining: number, limit: number): number {
  if (limit <= 0) return 0
  return Math.min(100, Math.max(0, (remaining / limit) * 100))
}

function resetLabel(value: string): string {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(value))
}

export function QuotaBadge({ className = '' }: { className?: string }) {
  const quota = useQuota()
  const [open, setOpen] = useState(false)

  const closeOnBlur = (event: FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false)
  }

  if (quota.isPending) {
    return (
      <div
        className={`inline-flex h-9 items-center gap-2 rounded-full border border-border bg-surface px-3 text-xs text-muted-foreground ${className}`}
        aria-label="Credit quota loading"
      >
        <Coins size={14} strokeWidth={1.75} aria-hidden="true" />
        <span className="hidden font-medium sm:inline">Credits —</span>
      </div>
    )
  }

  if (!quota.data) {
    return (
      <div
        className={`inline-flex h-9 items-center gap-2 rounded-full border border-border bg-surface px-3 text-xs text-muted-foreground ${className}`}
        aria-label="Credit quota unavailable"
      >
        <Coins size={14} strokeWidth={1.75} aria-hidden="true" />
        <span className="hidden font-medium sm:inline">Credits —</span>
      </div>
    )
  }

  const windows = [
    { label: '5h', remaining: quota.data.remaining_5h, limit: quota.data.limit_5h, reset: quota.data.reset_at_5h },
    {
      label: 'month',
      remaining: quota.data.remaining_month,
      limit: quota.data.limit_month,
      reset: quota.data.reset_at_month,
    },
  ]
  const fiveHourPercent = quotaPercent(windows[0].remaining, windows[0].limit)

  return (
    <div className={`relative ${className}`} onFocus={closeOnBlur} onBlur={closeOnBlur}>
      <button
        type="button"
        aria-label="Credit quota details"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false)
        }}
        className="inline-flex h-9 items-center gap-2 rounded-full border border-border bg-surface px-3 text-xs text-foreground transition-[background-color,border-color,color] duration-150 ease-out hover:border-border-strong hover:bg-surface-hover active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent motion-reduce:transform-none"
      >
        <Coins size={14} strokeWidth={1.75} className={quota.data.blocked ? 'text-danger' : 'text-accent'} aria-hidden="true" />
        <span className="hidden font-medium sm:inline">Credits</span>
        <span className="hidden font-mono text-[0.7rem] tabular-nums text-muted-foreground sm:inline">
          {formatCredits(quota.data.remaining_5h)}
        </span>
        <ChevronDown
          size={13}
          strokeWidth={1.75}
          className={`text-muted-foreground transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Credit quota details"
          className="absolute bottom-[calc(100%+0.5rem)] left-1/2 z-50 w-72 -translate-x-1/2 rounded-xl border border-border bg-surface-raised p-3 shadow-lg lg:bottom-auto lg:left-auto lg:right-0 lg:top-[calc(100%+0.5rem)] lg:translate-x-0"
        >
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-semibold text-foreground">Credit quota</p>
              <p className="font-mono text-[0.65rem] text-muted-foreground">live balance</p>
            </div>
            {quota.data.blocked && <span className="font-mono text-[0.65rem] text-danger">limit reached</span>}
          </div>
          <div className="space-y-3">
            {windows.map((window, index) => {
              const percent = quotaPercent(window.remaining, window.limit)
              return (
                <div key={window.label} role="group" aria-label={`${window.label} quota`}>
                  <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[0.7rem]">
                    <span className="font-medium text-foreground">{window.label}</span>
                    <span className="font-mono tabular-nums text-muted-foreground">
                      {formatCredits(window.remaining)} / {formatCredits(window.limit)}
                    </span>
                  </div>
                  <div className="h-1 overflow-hidden rounded-full bg-border">
                    <div
                      className={`h-full rounded-full ${index === 0 ? 'bg-accent' : 'bg-muted-foreground'}`}
                      style={{ width: `${percent}%` }}
                    />
                  </div>
                  <p className="mt-1 font-mono text-[0.62rem] text-muted-foreground">
                    resets {resetLabel(window.reset)}
                  </p>
                </div>
              )
            })}
          </div>
          <div className="mt-3 flex items-center justify-between border-t border-border pt-2 font-mono text-[0.62rem] text-muted-foreground">
            <span>5h window</span>
            <span className="tabular-nums">{Math.round(fiveHourPercent)}% available</span>
          </div>
        </div>
      )}
    </div>
  )
}

export function AppHeader() {
  return (
    <header className="z-30 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-surface-muted px-3 sm:px-5">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-accent">
          <ShieldCheck size={17} strokeWidth={1.75} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <p className="truncate font-display text-sm font-semibold tracking-tight text-foreground">Veriforge</p>
          <p className="hidden truncate text-[0.65rem] text-muted-foreground sm:block">Evidence workbench</p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
        <QuotaBadge />
        <ThemeToggle />
        <ProfileMenu />
      </div>
    </header>
  )
}
