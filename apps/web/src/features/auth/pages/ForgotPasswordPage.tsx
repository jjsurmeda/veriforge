import { useState } from 'react'

import { forgotPasswordAuthForgotPasswordPost } from '../../../generated/sdk.gen'

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false)

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    await forgotPasswordAuthForgotPasswordPost({ body: { email: String(form.get('email')) } })
    setSent(true)
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-ink text-paper">
      <div className="w-80 rounded border border-mist bg-graphite p-6">
        <h1 className="font-display text-xl">Reset password</h1>
        {sent ? (
          <p className="mt-4 text-sm text-paper/70">
            If an account exists for that address, a reset link is on its way. (Local dev: the
            link is logged by the API instead of emailed.)
          </p>
        ) : (
          <form onSubmit={(e) => void onSubmit(e)} className="mt-4 flex flex-col gap-3">
            <input
              name="email"
              type="email"
              required
              autoComplete="email"
              placeholder="Email"
              className="rounded border border-mist bg-ink px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ember"
            />
            <button
              type="submit"
              className="rounded border border-mist py-2 text-sm hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
            >
              Send reset link
            </button>
          </form>
        )}
      </div>
    </main>
  )
}
