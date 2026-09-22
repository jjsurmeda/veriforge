import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { resetPasswordAuthResetPasswordPost } from '../../../generated/sdk.gen'

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
    <main className="flex min-h-screen items-center justify-center bg-ink text-paper">
      <div className="w-80 rounded border border-mist bg-graphite p-6">
        <h1 className="font-display text-xl">Choose a new password</h1>
        <form onSubmit={(e) => void onSubmit(e)} className="mt-4 flex flex-col gap-3">
          <input
            name="password"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            placeholder="New password (8+ characters)"
            className="rounded border border-mist bg-ink px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ember"
          />
          {error && <p className="text-sm text-rust">{error}</p>}
          <button
            type="submit"
            className="rounded border border-mist py-2 text-sm hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
          >
            Reset password
          </button>
        </form>
        <div className="mt-4 text-xs text-paper/50">
          <Link to="/login" className="hover:text-paper">
            Back to sign in
          </Link>
        </div>
      </div>
    </main>
  )
}
