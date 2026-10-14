import { LogIn, Mail, PlayCircle, UserRound } from 'lucide-react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { loginAuthLoginPost, startDemoAuthDemoPost } from '../../../generated/sdk.gen'
import { setAccessToken } from '../../../lib/auth'
import { AuthShell } from '../components/AuthShell'
import { TourQuestionList } from '../components/TourQuestionList'

interface ApiErrorBody { error_code?: string; message?: string }

export function LoginPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [demoBusy, setDemoBusy] = useState(false)

  // Item 4. No credential, an ephemeral account on the seeded demo plan. The
  // errors are spelled out rather than folded into the sign-in message: this
  // is the one button on the page that a rate limit can refuse, and "Try again"
  // would be the one thing that does not help.
  const onDemo = async () => {
    setDemoBusy(true)
    setError(null)
    try {
      const { data, error: apiError } = await startDemoAuthDemoPost()
      if (apiError || !data) {
        const code = (apiError as ApiErrorBody | undefined)?.error_code
        setError(
          code === 'rate_limited'
            ? 'The demo has been started a few times from this network. Try again in an hour.'
            : code === 'demo_unavailable'
              ? 'The demo is not set up on this deployment yet.'
              : // KI-63: the demo is off by default, so "Try the demo" is
                // the first button a visitor presses on a deployment whose
                // operator has not turned it on. "Could not start the demo"
                // reads as a broken product; these two say what is actually
                // true and what, if anything, the visitor can do about it.
                code === 'demo_disabled'
                ? 'The demo is not available right now.'
                : code === 'demo_capacity'
                  ? 'The demo is full for today. Try again tomorrow.'
                  : 'Could not start the demo. Try again.',
        )
        return
      }
      setAccessToken(data.access_token)
      void navigate({ to: '/' })
    } catch {
      setError('Could not reach the server. Check your connection and try again.')
    } finally {
      setDemoBusy(false)
    }
  }

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
    } catch {
      // A rejected request (offline, CORS, a thrown transport error) has no
      // { error } to read, so it used to clear `busy` and vanish silently.
      // The inputs are uncontrolled, so the entered values survive the
      // re-render and the user can just press Sign in again.
      setError('Could not reach the server. Check your connection and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell title="Welcome back" description="Sign in to continue building answers you can inspect." footer={<div className="flex justify-center gap-4"><Link to="/signup" className="rounded-md font-medium text-fg hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring">Create account</Link><Link to="/forgot-password" className="rounded-md text-fg-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring">Forgot password</Link></div>}>
      <form onSubmit={(event) => void onSubmit(event)} className="space-y-4">
        <label className="relative block"><Mail size={16} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" aria-hidden="true" /><input name="email" aria-label="Email" type="email" required autoComplete="email" placeholder="Email" className="h-11 w-full rounded-lg border border-border bg-main pl-10 pr-3 text-sm text-fg placeholder:text-fg-muted transition-colors duration-150 hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring" /></label>
        <label className="relative block"><UserRound size={16} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" aria-hidden="true" /><input name="password" aria-label="Password" type="password" required autoComplete="current-password" placeholder="Password" className="h-11 w-full rounded-lg border border-border bg-main pl-10 pr-3 text-sm text-fg placeholder:text-fg-muted transition-colors duration-150 hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring" /></label>
        {error && <p role="alert" className="rounded-lg border border-border/30 bg-raised px-3 py-2 text-sm text-danger">{error}</p>}
        <button type="submit" disabled={busy} className="pressable inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-fg-strong px-4 text-sm font-semibold text-on-strong hover:bg-fg-strong disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"><LogIn size={16} strokeWidth={1.75} aria-hidden="true" />{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>

      {/* Secondary action, one below the form (design-system.md §6: one
          primary action; the demo is the way in without an account, not the
          way most people arrive). */}
      <div className="mt-4 border-t border-border pt-4">
        <button
          type="button"
          onClick={() => void onDemo()}
          disabled={demoBusy}
          className="pressable inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-border bg-surface px-4 text-sm font-medium text-fg transition-colors duration-150 hover:bg-raised disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          <PlayCircle size={16} strokeWidth={1.75} aria-hidden="true" />
          {demoBusy ? 'Starting the demo…' : 'Try the demo'}
        </button>
        <TourQuestionList />
      </div>
    </AuthShell>
  )
}
