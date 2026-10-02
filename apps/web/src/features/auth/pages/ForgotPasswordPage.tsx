import { Mail, Send } from 'lucide-react'
import { useState } from 'react'

import { forgotPasswordAuthForgotPasswordPost } from '../../../generated/sdk.gen'
import { AuthShell } from '../components/AuthShell'

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy(true)
    setError(null)
    try {
      const { error: apiError } = await forgotPasswordAuthForgotPasswordPost({
        body: { email: String(form.get('email')) },
      })
      if (apiError) {
        setError('We could not send a reset link just now. Try again in a moment.')
        return
      }
      // Only a real success gets the (deliberately generic) confirmation.
      setSent(true)
    } catch {
      setError('We could not send a reset link just now. Try again in a moment.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell title="Reset password" description="We will send a secure reset link if an account matches that address." footer={<a href="/login" className="rounded-md font-medium text-fg hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring">Back to sign in</a>}>
      {sent ? <div className="rounded-lg border border-border/30 bg-raised px-3 py-3 text-sm leading-6 text-success">If an account exists for that address, a reset link is on its way. (Local dev: the link is logged by the API instead of emailed.)</div> : <form onSubmit={(event) => void onSubmit(event)} className="space-y-4">
        <label className="relative block"><Mail size={16} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted" aria-hidden="true" /><input name="email" aria-label="Email" type="email" required autoComplete="email" placeholder="Email" className="h-11 w-full rounded-lg border border-border bg-main pl-10 pr-3 text-sm text-fg placeholder:text-fg-muted transition-colors duration-150 hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring" /></label>
        {error && <p role="alert" className="rounded-lg border border-border/30 bg-raised px-3 py-2 text-sm text-danger">{error}</p>}
        <button type="submit" disabled={busy} className="pressable inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-fg-strong px-4 text-sm font-semibold text-on-strong hover:bg-fg-strong disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"><Send size={16} strokeWidth={1.75} aria-hidden="true" />{busy ? 'Sending…' : 'Send reset link'}</button>
      </form>}
    </AuthShell>
  )
}
