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
    <AuthShell
      title="Reset password"
      description="We will send a secure reset link if an account matches that address."
      footer={
        <a href="/login" className="rounded-md font-medium text-primary transition-colors duration-180 hover:text-primary-strong focus-visible:outline-2 focus-visible:outline-primary">
          Back to sign in
        </a>
      }
    >
      {sent ? (
        <div className="rounded-lg border border-success/30 bg-success-soft px-3 py-3 text-sm leading-6 text-success">
          If an account exists for that address, a reset link is on its way. (Local dev: the link is logged by the API instead of emailed.)
        </div>
      ) : (
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
          <button
            type="submit"
            className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-on-primary shadow-sm transition-[background-color,transform,box-shadow] duration-180 hover:-translate-y-0.5 hover:bg-primary-strong hover:shadow-md active:translate-y-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transform-none motion-reduce:transition-none"
          >
            <Send size={16} aria-hidden="true" />
            Send reset link
          </button>
        </form>
      )}
    </AuthShell>
  )
}
