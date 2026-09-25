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
    const { error: apiError } = await resetPasswordAuthResetPasswordPost({ body: { token, password: String(form.get('password')) } })
    if (apiError) {
      setError('Reset link is invalid or expired')
      return
    }
    void navigate({ to: '/login' })
  }

  return (
    <AuthShell title="Choose a new password" description="Use at least eight characters, then return to your workspace." footer={<Link to="/login" className="rounded-md font-medium text-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent">Back to sign in</Link>}>
      <form onSubmit={(event) => void onSubmit(event)} className="space-y-4">
        <label className="relative block"><KeyRound size={16} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" /><input name="password" aria-label="New password" type="password" required minLength={8} autoComplete="new-password" placeholder="New password (8+ characters)" className="h-11 w-full rounded-lg border border-border bg-background pl-10 pr-3 text-sm text-foreground placeholder:text-muted-foreground transition-colors duration-150 hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent" /></label>
        {error && <p role="alert" className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}
        <button type="submit" className="pressable inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-on-primary hover:bg-primary-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"><ShieldCheck size={16} strokeWidth={1.75} aria-hidden="true" />Reset password</button>
      </form>
    </AuthShell>
  )
}
