import { useState, type FocusEvent } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { ChevronDown, Coins, LogOut, ShieldCheck } from 'lucide-react'

import { ThemeToggle } from './ThemeToggle'
import { useMe } from '../features/auth/hooks/useMe'
import { useQuota } from '../features/chat/hooks/useQuota'
import { logout } from '../lib/auth'
import { formatCredits } from '../lib/format'
import { queryClient } from '../lib/queryClient'

function quotaPercent(remaining: number, limit: number): number {
  if (limit <= 0) return 0
  return Math.min(100, Math.max(0, (remaining / limit) * 100))
}

function resetLabel(value: string): string {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(value))
}

function QuotaBadge() {
  const quota = useQuota()
  const [open, setOpen] = useState(false)

  const closeOnBlur = (event: FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false)
  }

  if (quota.isPending) {
    return (
      <div
         className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-surface-muted/60 px-2 text-xs text-muted-foreground sm:px-3"
        aria-label="Credit quota loading"
      >
        <Coins size={14} aria-hidden="true" />
         <span className="hidden font-mono sm:inline">Credits —</span>
      </div>
    )
  }

  if (!quota.data) {
    return (
      <div
         className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-surface-muted/60 px-2 text-xs text-muted-foreground sm:px-3"
        aria-label="Credit quota unavailable"
      >
        <Coins size={14} aria-hidden="true" />
         <span className="hidden font-mono sm:inline">Credits —</span>
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
    <div
       className="relative"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={closeOnBlur}
      onBlur={closeOnBlur}
    >
      <button
        type="button"
        aria-label="Credit quota details"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false)
        }}
         className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-surface-muted/60 px-2 text-xs text-foreground transition-[background-color,border-color,box-shadow] duration-180 hover:border-primary/35 hover:bg-primary-soft/60 hover:shadow-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transition-none sm:px-3"
      >
        <Coins size={14} className={quota.data.blocked ? 'text-danger' : 'text-primary'} aria-hidden="true" />
         <span className="hidden font-medium sm:inline">Credits</span>
         <span className="hidden font-mono text-[0.7rem] text-muted-foreground sm:inline">
          {formatCredits(quota.data.remaining_5h)}
        </span>
        <ChevronDown
          size={13}
          className={`text-muted-foreground transition-transform duration-180 ${open ? 'rotate-180' : ''} motion-reduce:transition-none`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Credit quota details"
          className="absolute right-0 top-[calc(100%+0.5rem)] z-50 w-72 rounded-xl border border-border bg-surface p-3 shadow-lg"
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
                    <span className="font-mono text-muted-foreground">
                      {formatCredits(window.remaining)} / {formatCredits(window.limit)}
                    </span>
                  </div>
                  <div className="h-1 overflow-hidden rounded-full bg-border">
                    <div
                      className={`h-full rounded-full ${index === 0 ? 'bg-primary' : 'bg-secondary'}`}
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
          <div className="mt-3 flex items-center justify-between border-t border-border/70 pt-2 font-mono text-[0.62rem] text-muted-foreground">
            <span>5h window</span>
            <span>{Math.round(fiveHourPercent)}% available</span>
          </div>
        </div>
      )}
    </div>
  )
}

export function AppHeader() {
  const navigate = useNavigate()
  const me = useMe()

  const onLogout = async () => {
    await logout()
    queryClient.clear()
    void navigate({ to: '/login' })
  }

  return (
    <header className="z-30 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-surface/95 px-3 shadow-sm backdrop-blur sm:px-5">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
          <ShieldCheck size={17} aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <p className="truncate font-display text-sm font-semibold tracking-tight text-foreground">Veriforge</p>
          <p className="hidden truncate font-mono text-[0.6rem] uppercase tracking-[0.12em] text-muted-foreground sm:block">
            Evidence workbench
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
        {me.data?.role === 'admin' && (
          <button
            type="button"
            onClick={() => void navigate({ to: '/admin' })}
            className="hidden h-9 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-muted-foreground transition-[color,background-color] duration-180 hover:bg-primary-soft hover:text-primary focus-visible:outline-2 focus-visible:outline-primary md:inline-flex"
          >
            <ShieldCheck size={14} aria-hidden="true" />
            Admin
          </button>
        )}
        <QuotaBadge />
        <ThemeToggle />
        <button
          type="button"
          aria-label="Sign out"
          title="Sign out"
          onClick={() => void onLogout()}
          className="inline-flex size-9 items-center justify-center rounded-lg text-muted-foreground transition-[color,background-color,transform] duration-180 hover:bg-danger-soft hover:text-danger active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger motion-reduce:transition-none"
        >
          <LogOut size={16} aria-hidden="true" />
        </button>
      </div>
    </header>
  )
}
