import { Mail, UserPlus } from 'lucide-react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { signupAuthSignupPost } from '../../../generated/sdk.gen'
import { setAccessToken } from '../../../lib/auth'
import { AuthShell } from '../components/AuthShell'

interface ApiErrorBody { error_code?: string; message?: string }

export function SignupPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy(true)
    setError(null)
    try {
      const { data, error: apiError } = await signupAuthSignupPost({ body: { email: String(form.get('email')), password: String(form.get('password')) } })
      if (apiError || !data) {
        setError((apiError as ApiErrorBody | undefined)?.message ?? 'Signup failed')
        return
      }
      setAccessToken(data.access_token)
      void navigate({ to: '/' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell title="Create your account" description="Start a private evidence workspace in less than a minute." footer={<Link to="/login" className="rounded-md font-medium text-fg hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring">Already have an account</Link>}>
      <form onSubmit={(event) => void onSubmit(event)} className="space-y-4">
        <label className="relative block"><Mail size={16} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" aria-hidden="true" /><input name="email" aria-label="Email" type="email" required autoComplete="email" placeholder="Email" className="h-11 w-full rounded-lg border border-border bg-main pl-10 pr-3 text-sm text-fg placeholder:text-fg-muted transition-colors duration-150 hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring" /></label>
        <label className="relative block"><UserPlus size={16} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" aria-hidden="true" /><input name="password" aria-label="Password" type="password" required minLength={8} autoComplete="new-password" placeholder="Password (8+ characters)" className="h-11 w-full rounded-lg border border-border bg-main pl-10 pr-3 text-sm text-fg placeholder:text-fg-muted transition-colors duration-150 hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring" /></label>
        {error && <p role="alert" className="rounded-lg border border-border/30 bg-raised px-3 py-2 text-sm text-danger">{error}</p>}
        <button type="submit" disabled={busy} className="pressable inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-fg-strong px-4 text-sm font-semibold text-on-strong hover:bg-fg-strong disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"><UserPlus size={16} strokeWidth={1.75} aria-hidden="true" />Sign up</button>
      </form>
    </AuthShell>
  )
}
