import { useNavigate } from '@tanstack/react-router'
import { LogOut, ShieldCheck, UserRound } from 'lucide-react'

import { useMe } from '../features/auth/hooks/useMe'
import { useQuota } from '../features/chat/hooks/useQuota'
import { logout } from '../lib/auth'
import { queryClient } from '../lib/queryClient'
import { formatCredits } from '../lib/format'
import { useTheme, ThemeToggle } from './ThemeToggle'
import {
  Menu,
  MenuContent,
  MenuItemWithIcon,
  MenuRadioGroup,
  MenuRadioItemWithCheck,
  MenuTrigger,
} from './ui/primitives'

function initialsFor(email: string): string {
  const local = email.split('@')[0] ?? email
  return local.slice(0, 2).toUpperCase()
}

export function ProfileMenu({ side = 'top', align = 'start', collapsed = false }: { side?: 'top' | 'right' | 'bottom'; align?: 'start' | 'center' | 'end'; collapsed?: boolean }) {
  const me = useMe()
  const quota = useQuota()
  const { theme, setTheme } = useTheme()
  const navigate = useNavigate()
  const user = me.data
  const windows = quota.data ? [
    { label: '5h', remaining: quota.data.remaining_5h, limit: quota.data.limit_5h, reset: quota.data.reset_at_5h },
    { label: 'month', remaining: quota.data.remaining_month, limit: quota.data.limit_month, reset: quota.data.reset_at_month },
  ] : []
  const credits = quota.data?.remaining_5h ?? 0

  const onLogout = async () => {
    await logout()
    queryClient.clear()
    void navigate({ to: '/login' })
  }

  const trigger = (
    <MenuTrigger asChild>
      <button
        type="button"
        aria-label="Profile menu"
        title="Profile menu"
        className={collapsed ? 'inline-flex size-7 items-center justify-center rounded-full border border-border bg-raised text-[10px] font-semibold text-fg transition-colors hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring' : 'flex min-h-12 w-full items-center gap-2 rounded-lg px-2 text-left hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'}
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-raised text-[10px] font-semibold text-fg">{user ? initialsFor(user.email) : <UserRound size={14} aria-hidden="true" />}</span>
        {!collapsed && user && <span className="min-w-0 flex-1"><span className="block truncate text-xs font-medium text-fg">{user.email}</span><span className="block truncate text-[0.65rem] text-fg-muted">Free plan · {formatCredits(credits)} credits</span></span>}
      </button>
    </MenuTrigger>
  )

  return (
    <Menu>
      {trigger}
      <MenuContent side={side} align={align} className="w-70">
        <div className="border-b border-border px-2.5 pb-3 pt-2">
          <p className="truncate text-sm font-medium text-fg">{user?.email ?? 'Profile loading'}</p>
          <p className="mt-0.5 font-mono text-[0.65rem] uppercase tracking-[0.1em] text-fg-muted">{user?.role ?? '—'}</p>
        </div>
        <div className="border-b border-border px-2.5 py-3">
          <div className="mb-2 flex items-center justify-between"><span className="text-xs font-medium text-fg">Credits</span>{quota.data?.blocked && <span className="font-mono text-[0.65rem] text-danger">limit reached</span>}</div>
          {quota.isPending ? <p className="text-xs text-fg-muted">Loading quota…</p> : !quota.data ? <p className="text-xs text-fg-muted">Quota unavailable</p> : <div className="space-y-2.5">{windows.map((window) => <div key={window.label} role="group" aria-label={`${window.label} quota`}><div className="mb-1 flex justify-between text-[0.68rem] text-fg-muted"><span>{window.label}</span><span className="font-mono tabular-nums">{formatCredits(window.remaining)} / {formatCredits(window.limit)}</span></div><div className="h-1 overflow-hidden rounded-full bg-raised"><div className="h-full rounded-full bg-fg-strong" style={{ width: `${window.limit > 0 ? Math.min(100, Math.max(0, window.remaining / window.limit * 100)) : 0}%` }} /></div><p className="mt-1 text-[0.62rem] text-fg-subtle">Resets {new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(window.reset))}</p></div>)}</div>}
        </div>
        <div className="border-b border-border px-2.5 py-2.5"><p className="mb-1.5 px-1 text-[0.65rem] font-medium uppercase tracking-[0.1em] text-fg-subtle">Theme</p><MenuRadioGroup value={theme}><MenuRadioItemWithCheck value="light" onSelect={() => setTheme('light')}>Light</MenuRadioItemWithCheck><MenuRadioItemWithCheck value="dark" onSelect={() => setTheme('dark')}>Dark</MenuRadioItemWithCheck><MenuRadioItemWithCheck value="system" onSelect={() => setTheme('system')}>System</MenuRadioItemWithCheck></MenuRadioGroup></div>
        <div className="border-b border-border px-2.5 py-2.5"><ThemeToggle /></div>
        {user?.role === 'admin' && <MenuItemWithIcon onSelect={() => void navigate({ to: '/admin' })}><ShieldCheck size={15} aria-hidden="true" />Admin console</MenuItemWithIcon>}
        <MenuItemWithIcon className="text-danger" onSelect={() => void onLogout()}><LogOut size={15} aria-hidden="true" />Log out</MenuItemWithIcon>
      </MenuContent>
    </Menu>
  )
}

export function QuotaBadge({ className = '', side = 'top', align = 'start' }: { className?: string; side?: 'top' | 'right' | 'bottom'; align?: 'start' | 'center' | 'end' }) {
  const quota = useQuota()
  const { data } = quota
  return (
    <div className={className}>
      <Menu>
        <MenuTrigger asChild>
          <button type="button" aria-label="Credit quota details" className="inline-flex h-8 items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 text-xs text-fg-muted transition-colors hover:border-border-strong hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"><span className="font-medium">Credits</span><span className="font-mono text-[0.68rem] tabular-nums">{data ? formatCredits(data.remaining_5h) : '—'}</span></button>
        </MenuTrigger>
        <MenuContent side={side} align={align} className="w-70">
          <div className="px-2.5 py-2"><p className="text-xs font-medium text-fg">Credits</p>{quota.isPending ? <p className="mt-2 text-xs text-fg-muted">Loading…</p> : !data ? <p className="mt-2 text-xs text-fg-muted">Unavailable</p> : <div className="mt-2 space-y-2">{[5, 'month'].map((key) => { const label = key === 5 ? '5h' : 'month'; const remaining = key === 5 ? data.remaining_5h : data.remaining_month; const limit = key === 5 ? data.limit_5h : data.limit_month; const reset = key === 5 ? data.reset_at_5h : data.reset_at_month; return <div key={label} role="group" aria-label={`${label} quota`}><div className="flex justify-between text-[0.68rem] text-fg-muted"><span>{label}</span><span>{formatCredits(remaining)} / {formatCredits(limit)}</span></div><div className="mt-1 h-1 rounded-full bg-raised"><div className="h-full rounded-full bg-fg-strong" style={{ width: `${limit > 0 ? Math.min(100, remaining / limit * 100) : 0}%` }} /></div><p className="mt-1 text-[0.62rem] text-fg-subtle">Resets {new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(reset))}</p></div> })}</div>}{data?.blocked && <p className="mt-2 text-xs text-danger">limit reached</p>}</div>
        </MenuContent>
      </Menu>
    </div>
  )
}
