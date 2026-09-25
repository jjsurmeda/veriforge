import { Mail, Send } from 'lucide-react'
import { useState } from 'react'

import { forgotPasswordAuthForgotPasswordPost } from '../../../generated/sdk.gen'
import { AuthShell } from '../components/AuthShell'

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false)
  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    await forgotPasswordAuthForgotPasswordPost({ body: { email: String(form.get('email')) } })
    setSent(true)
  }

  return (
    <AuthShell title="Reset password" description="We will send a secure reset link if an account matches that address." footer={<a href="/login" className="rounded-md font-medium text-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent">Back to sign in</a>}>
      {sent ? <div className="rounded-lg border border-success/30 bg-success-soft px-3 py-3 text-sm leading-6 text-success">If an account exists for that address, a reset link is on its way. (Local dev: the link is logged by the API instead of emailed.)</div> : <form onSubmit={(event) => void onSubmit(event)} className="space-y-4">
        <label className="relative block"><Mail size={16} strokeWidth={1.75} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-hidden="true" /><input name="email" aria-label="Email" type="email" required autoComplete="email" placeholder="Email" className="h-11 w-full rounded-lg border border-border bg-background pl-10 pr-3 text-sm text-foreground placeholder:text-muted-foreground transition-colors duration-150 hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent" /></label>
        <button type="submit" className="pressable inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-on-primary hover:bg-primary-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"><Send size={16} strokeWidth={1.75} aria-hidden="true" />Send reset link</button>
      </form>}
    </AuthShell>
  )
}
