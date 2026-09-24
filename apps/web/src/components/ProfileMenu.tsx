import { useState, type FocusEvent } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { LogOut, ShieldCheck, UserRound } from 'lucide-react'

import { useMe } from '../features/auth/hooks/useMe'
import { logout } from '../lib/auth'
import { queryClient } from '../lib/queryClient'

function initialsFor(email: string): string {
  const local = email.split('@')[0] ?? email
  return local.slice(0, 2).toUpperCase()
}

export function ProfileMenu() {
  const me = useMe()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)

  const closeOnBlur = (event: FocusEvent<HTMLDivElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false)
  }

  const onLogout = async () => {
    await logout()
    queryClient.clear()
    void navigate({ to: '/login' })
  }

  if (!me.data) {
    return (
      <span
        className="inline-flex size-9 items-center justify-center rounded-full border border-border bg-surface-muted/60 text-muted-foreground"
        aria-label="Profile loading"
      >
        <UserRound size={16} aria-hidden="true" />
      </span>
    )
  }

  return (
    <div className="relative" onFocus={closeOnBlur} onBlur={closeOnBlur}>
      <button
        type="button"
        aria-label="Profile menu"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false)
        }}
        className="inline-flex size-9 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-primary shadow-sm transition-[box-shadow,transform] duration-180 hover:-translate-y-0.5 hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transform-none motion-reduce:transition-none"
      >
        {initialsFor(me.data.email)}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Profile"
          className="absolute right-0 top-[calc(100%+0.5rem)] z-50 w-64 rounded-xl border border-border bg-surface/90 p-3 shadow-lg backdrop-blur"
        >
          <div className="mb-3 flex items-center gap-3 border-b border-border/70 pb-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-primary">
              {initialsFor(me.data.email)}
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-foreground">{me.data.email}</p>
              <p className="font-mono text-[0.65rem] uppercase tracking-[0.1em] text-muted-foreground">
                {me.data.role}
              </p>
            </div>
          </div>
          {me.data.role === 'admin' && (
            <button
              type="button"
              onClick={() => void navigate({ to: '/admin' })}
              className="mb-1 flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-foreground transition-colors duration-150 hover:bg-primary-soft hover:text-primary focus-visible:outline-2 focus-visible:outline-primary"
            >
              <ShieldCheck size={15} aria-hidden="true" />
              Admin console
            </button>
          )}
          <button
            type="button"
            onClick={() => void onLogout()}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm text-danger transition-colors duration-150 hover:bg-danger-soft focus-visible:outline-2 focus-visible:outline-danger"
          >
            <LogOut size={15} aria-hidden="true" />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
