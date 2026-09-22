import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { loginAuthLoginPost } from '../../../generated/sdk.gen'
import { setAccessToken } from '../../../lib/auth'

interface ApiErrorBody {
  error_code?: string
  message?: string
}

export function LoginPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setBusy(true)
    setError(null)
    try {
      const { data, error: apiError } = await loginAuthLoginPost({
        body: { email: String(form.get('email')), password: String(form.get('password')) },
      })
      if (apiError || !data) {
        setError((apiError as ApiErrorBody | undefined)?.message ?? 'Login failed')
        return
      }
      setAccessToken(data.access_token)
      void navigate({ to: '/' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-ink text-paper">
      <div className="w-80 rounded border border-mist bg-graphite p-6">
        <h1 className="font-display text-xl">Veriforge</h1>
        <form onSubmit={(e) => void onSubmit(e)} className="mt-4 flex flex-col gap-3">
          <input
            name="email"
            type="email"
            required
            autoComplete="email"
            placeholder="Email"
            className="rounded border border-mist bg-ink px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ember"
          />
          <input
            name="password"
            type="password"
            required
            autoComplete="current-password"
            placeholder="Password"
            className="rounded border border-mist bg-ink px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-ember"
          />
          {error && <p className="text-sm text-rust">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="rounded border border-mist py-2 text-sm hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
          >
            Sign in
          </button>
        </form>
        <a
          href="/auth/google/login"
          className="mt-3 block rounded border border-mist py-2 text-center text-sm text-paper/70 hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
        >
          Continue with Google
        </a>
        <div className="mt-4 flex justify-between text-xs text-paper/50">
          <Link to="/signup" className="hover:text-paper">
            Create account
          </Link>
          <Link to="/forgot-password" className="hover:text-paper">
            Forgot password
          </Link>
        </div>
      </div>
    </main>
  )
}
