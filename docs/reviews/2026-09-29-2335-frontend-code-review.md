# Frontend code review

Reviewed 2026-09-29. Scope: `apps/web` React/TypeScript application, including its API-facing hooks and test configuration. This was a read-only review; no frontend code or tests were changed.

## Findings

### P1 — New-chat flows can silently lose queued files and navigate after failed API operations

Evidence: [`apps/web/src/features/chat/pages/ChatIndexPage.tsx:30-36`](../apps/web/src/features/chat/pages/ChatIndexPage.tsx#L30-L36) removes every pending file with `splice(0)` before upload completion and ignores the generated SDK's `{ error }` result. [`:39-47`](../apps/web/src/features/chat/pages/ChatIndexPage.tsx#L39-L47) similarly ignores the create-run result before navigation; the upload-only flow at [`:50-56`](../apps/web/src/features/chat/pages/ChatIndexPage.tsx#L50-L56) has the same unchecked upload path.

Impact: an API response that resolves with an error can drain the local file queue, leave an empty/orphan chat, and navigate the user as though the upload or run was successfully created. The chat-scoped upload path correctly checks errors, so the inconsistent handling is confined to the new-chat entry flow.

Recommendation: inspect `{ data, error }` and throw/stop on errors. Keep files pending until each upload succeeds (or retain failed files for retry), and navigate only after the required upload/run operation succeeds.

### P2 — SSE reconnection bypasses access-token refresh

Evidence: [`apps/web/src/features/chat/hooks/useRunStream.ts:50-56`](../apps/web/src/features/chat/hooks/useRunStream.ts#L50-L56) sends a one-time bearer token via `fetchEventSource`. Its retry handler at [`:71-78`](../apps/web/src/features/chat/hooks/useRunStream.ts#L71-L78) retries the same request up to three times. Regular generated-client requests use [`authedFetch` in `apps/web/src/lib/auth.ts:58-61`](../apps/web/src/lib/auth.ts#L58-L61), which refreshes and retries a 401 response.

Impact: when an access token expires before opening or reconnecting a run stream, the UI reaches “Connection lost” despite a valid refresh cookie. Retrying does not recover until a page reload or another path refreshes the session.

Recommendation: make the SSE transport invoke the shared refresh flow on a 401 and reconnect with the renewed bearer token. Add a test covering an expired token followed by successful cookie-based refresh.

### P2 — Admin API failures render as empty operational data

Evidence: [`apps/web/src/features/admin/AdminPage.tsx:161-191`](../apps/web/src/features/admin/AdminPage.tsx#L161-L191) uses `.data ?? []` (or `.data`) for providers, models, roles, settings versions, plans, users, and audit records without checking the generated SDK `error` result.

Impact: authentication, authorization, network, and server failures are displayed as empty lists or default settings instead of failures. An operator can wrongly conclude that provider configuration, audit history, users, or settings do not exist.

Recommendation: make each query function throw when `error` is present and render a shared, visible error/retry state. Do not use an empty collection as an error fallback.

### P2 — Library and chat-document failures are rendered as empty source lists

Evidence: [`apps/web/src/features/library/hooks/useDocuments.ts:22-36`](../apps/web/src/features/library/hooks/useDocuments.ts#L22-L36) converts missing response data to an empty library or document list without checking `error`.

Impact: users can see an empty Library or source panel when the request actually failed, which can lead them to re-upload documents or trust a chat run that is missing expected sources.

Recommendation: propagate SDK errors to React Query and distinguish loading, empty, and failed states in the consuming components.

### P2 — Password-reset UI reports success for API error responses

Evidence: [`apps/web/src/features/auth/pages/ForgotPasswordPage.tsx:9-13`](../apps/web/src/features/auth/pages/ForgotPasswordPage.tsx#L9-L13) awaits the generated SDK call but never inspects its `{ error }` result, then unconditionally sets `sent`.

Impact: a failed reset request produces the same “link is on its way” message as a successful request. This masks outages and prevents the user from retrying with useful feedback.

Recommendation: preserve the intentionally generic success message only for successful API responses; display a generic retryable error for transport/server failures without revealing account existence.

### P3 — Authentication forms do not handle rejected requests

Evidence: [`apps/web/src/features/auth/pages/LoginPage.tsx:21-31`](../apps/web/src/features/auth/pages/LoginPage.tsx#L21-L31), [`SignupPage.tsx:21-31`](../apps/web/src/features/auth/pages/SignupPage.tsx#L21-L31), and [`ResetPasswordPage.tsx:11-18`](../apps/web/src/features/auth/pages/ResetPasswordPage.tsx#L11-L18) handle SDK error objects but have no `catch` for rejected fetch/runtime failures.

Impact: offline, CORS, or unexpected client failures clear the busy state in `finally` but yield an unhandled rejection and no actionable feedback.

Recommendation: catch rejected requests, show a generic retryable error, and retain the entered form fields.

## Review notes

- Findings are ordered by impact. P1 is a data/workflow-loss path; P2 is a material reliability or operator-correctness issue; P3 is user-facing error recovery.
- Tests exist for core chat components and hooks, but no test covers generated SDK error objects in the new-chat upload/run flow, password-reset submission, or an SSE 401 refresh/reconnect.
- The package lock file is committed and Playwright rejects non-local base URLs; neither is reported as a defect.
