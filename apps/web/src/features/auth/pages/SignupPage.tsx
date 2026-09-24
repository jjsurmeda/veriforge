import { Mail, UserPlus } from 'lucide-react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { signupAuthSignupPost } from '../../../generated/sdk.gen'
import { setAccessToken } from '../../../lib/auth'
import { AuthShell } from '../components/AuthShell'

interface ApiErrorBody {
  error_code?: string
  message?: string
}

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
      const { data, error: apiError } = await signupAuthSignupPost({
        body: { email: String(form.get('email')), password: String(form.get('password')) },
      })
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
    <AuthShell
      title="Create your account"
      description="Start a private evidence workspace in less than a minute."
      footer={
        <Link to="/login" className="rounded-md font-medium text-primary transition-colors duration-180 hover:text-primary-strong focus-visible:outline-2 focus-visible:outline-primary">
          Already have an account
        </Link>
      }
    >
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-3">
        <label className="relative block">
          <Mail size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <input
            name="email"
            aria-label="Email"
            type="email"
            required
            autoComplete="email"
            placeholder="Email"
            className="h-11 w-full rounded-lg border border-border bg-background pl-10 pr-3 text-sm text-foreground placeholder:text-muted-foreground/70 transition-[border-color,box-shadow] duration-180 hover:border-primary/40 focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25"
          />
        </label>
        <label className="relative block">
          <UserPlus size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <input
            name="password"
            aria-label="Password"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            placeholder="Password (8+ characters)"
            className="h-11 w-full rounded-lg border border-border bg-background pl-10 pr-3 text-sm text-foreground placeholder:text-muted-foreground/70 transition-[border-color,box-shadow] duration-180 hover:border-primary/40 focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25"
          />
        </label>
        {error && <p role="alert" className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-on-primary shadow-sm transition-[background-color,transform,box-shadow] duration-180 hover:-translate-y-0.5 hover:bg-primary-strong hover:shadow-md active:translate-y-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transform-none motion-reduce:transition-none"
        >
          <UserPlus size={16} aria-hidden="true" />
          {busy ? 'Creating account…' : 'Sign up'}
        </button>
      </form>
    </AuthShell>
  )
}
