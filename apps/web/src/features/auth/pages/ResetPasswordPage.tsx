import { KeyRound, ShieldCheck } from 'lucide-react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { resetPasswordAuthResetPasswordPost } from '../../../generated/sdk.gen'
import { AuthShell } from '../components/AuthShell'

export function ResetPasswordPage({ token }: { token: string }) {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const { error: apiError } = await resetPasswordAuthResetPasswordPost({
      body: { token, password: String(form.get('password')) },
    })
    if (apiError) {
      setError('Reset link is invalid or expired')
      return
    }
    void navigate({ to: '/login' })
  }

  return (
    <AuthShell
      title="Choose a new password"
      description="Use at least eight characters, then return to your workspace."
      footer={
        <Link to="/login" className="rounded-md font-medium text-primary transition-colors duration-180 hover:text-primary-strong focus-visible:outline-2 focus-visible:outline-primary">
          Back to sign in
        </Link>
      }
    >
      <form onSubmit={(e) => void onSubmit(e)} className="space-y-3">
        <label className="relative block">
          <KeyRound size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
          <input
            name="password"
            aria-label="New password"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            placeholder="New password (8+ characters)"
            className="h-11 w-full rounded-lg border border-border bg-background pl-10 pr-3 text-sm text-foreground placeholder:text-muted-foreground/70 transition-[border-color,box-shadow] duration-180 hover:border-primary/40 focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/25"
          />
        </label>
        {error && <p role="alert" className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
        <button
          type="submit"
          className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-on-primary shadow-sm transition-[background-color,transform,box-shadow] duration-180 hover:-translate-y-0.5 hover:bg-primary-strong hover:shadow-md active:translate-y-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transform-none motion-reduce:transition-none"
        >
          <ShieldCheck size={16} aria-hidden="true" />
          Reset password
        </button>
      </form>
    </AuthShell>
  )
}
