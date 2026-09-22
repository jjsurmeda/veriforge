// Access token lives in memory only (TRD §11); the refresh token rides in an
// httpOnly cookie the browser sends on credentials:'include' calls.

let accessToken: string | null = null
let refreshFlight: Promise<boolean> | null = null

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export async function refreshSession(): Promise<boolean> {
  if (refreshFlight) return refreshFlight
  refreshFlight = (async () => {
    try {
      const response = await fetch('/auth/refresh', {
        method: 'POST',
        credentials: 'include',
      })
      if (!response.ok) {
        accessToken = null
        return false
      }
      const body = (await response.json()) as { access_token: string }
      accessToken = body.access_token
      return true
    } catch {
      return false
    } finally {
      refreshFlight = null
    }
  })()
  return refreshFlight
}

export async function ensureSession(): Promise<boolean> {
  if (accessToken) return true
  return refreshSession()
}

export async function authedFetch(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const attempt = () => {
    // The generated client hands us a fully-built Request (no init), so seed
    // headers from it before adding Authorization — replacing them wholesale
    // drops Content-Type and the API can't parse JSON bodies.
    const headers = new Headers(
      init?.headers ?? (input instanceof Request ? input.headers : undefined),
    )
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
    return fetch(input, { ...init, headers, credentials: 'include' })
  }
  let response = await attempt()
  if (response.status === 401 && accessToken && (await refreshSession())) {
    response = await attempt()
  }
  return response
}

export async function logout(): Promise<void> {
  try {
    await fetch('/auth/logout', { method: 'POST', credentials: 'include' })
  } finally {
    accessToken = null
  }
}
