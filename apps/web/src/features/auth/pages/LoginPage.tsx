import { LogIn, Mail, UserRound } from 'lucide-react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { loginAuthLoginPost } from '../../../generated/sdk.gen'
import { setAccessToken } from '../../../lib/auth'
import { AuthShell } from '../components/AuthShell'

interface ApiErrorBody { error_code?: string; message?: string }

export function LoginPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy(true)
    setError(null)
    try {
      const { data, error: apiError } = await loginAuthLoginPost({ body: { email: String(form.get('email')), password: String(form.get('password')) } })
      if (apiError || !data) {
        setError((apiError as ApiErrorBody | undefined)?.message ?? 'Login failed')
        return
      }
      setAccessToken(data.access_token)
      void navigate({ to: '/' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell title="Welcome back" description="Sign in to continue building answers you can inspect." footer={<div className="flex justify-center gap-4"><Link to="/signup" className="rounded-md font-medium text-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent">Create account</Link><Link to="/forgot-password" className="rounded-md text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent">Forgot password</Link></div>}>
      <form onSubmit={(event) => void onSubmit(event)} className="space-y-4">
        <label className="relative block"><Mail size={16} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" /><input name="email" aria-label="Email" type="email" required autoComplete="email" placeholder="Email" className="h-11 w-full rounded-lg border border-border bg-background pl-10 pr-3 text-sm text-foreground placeholder:text-muted-foreground transition-colors duration-150 hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent" /></label>
        <label className="relative block"><UserRound size={16} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" /><input name="password" aria-label="Password" type="password" required autoComplete="current-password" placeholder="Password" className="h-11 w-full rounded-lg border border-border bg-background pl-10 pr-3 text-sm text-foreground placeholder:text-muted-foreground transition-colors duration-150 hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent" /></label>
        {error && <p role="alert" className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
        <button type="submit" disabled={busy} className="pressable inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-on-primary hover:bg-primary-strong disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"><LogIn size={16} strokeWidth={1.75} aria-hidden="true" />{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </AuthShell>
  )
}
