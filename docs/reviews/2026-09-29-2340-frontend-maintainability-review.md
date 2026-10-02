# Frontend maintainability review

Reviewed 2026-09-29. Scope: `apps/web` conventions, readability, duplication, and complexity. This is separate from the frontend reliability/security review and is read-only.

## Findings

### P2 — The admin console is a 597-line multi-domain component

Evidence: [`apps/web/src/features/admin/AdminPage.tsx:1-57`](../apps/web/src/features/admin/AdminPage.tsx#L1-L57) imports every admin-domain API and type. The same component owns nine independent query results and all mutation definitions at [`:130-337`](../apps/web/src/features/admin/AdminPage.tsx#L130-L337), then renders every section and several row components through [`:339-597`](../apps/web/src/features/admin/AdminPage.tsx#L339-L597).

Why it matters: adding or changing one domain (providers, plans, users, settings, or audit) requires navigating a large unrelated file and risks unintended coupling through shared local state, notices, and invalidations. It also conflicts with the documented feature-first direction that illustrates separate admin areas in [`docs/conventions/react.md:20-36`](conventions/react.md#L20-L36).

Recommendation: split only at existing domain boundaries: keep `AdminPage` as the role gate/navigation shell, and move the settings, providers/models/roles, plans/users, and audit sections into local admin components/hooks. Do not introduce a generic form or CRUD framework; the existing endpoint-specific forms are small enough to remain explicit.

### P2 — The live-run state implementation contradicts its written convention

Evidence: the convention says Zustand holds only in-flight state and is cleared on completion at [`docs/conventions/react.md:38-50`](conventions/react.md#L38-L50). In contrast, [`apps/web/src/features/chat/store.ts:75-86`](../apps/web/src/features/chat/store.ts#L75-L86) deliberately retains completed runs, and [`useRunStream.ts:61-68`](../apps/web/src/features/chat/hooks/useRunStream.ts#L61-L68) documents the same alternative behaviour.

Why it matters: contributors cannot tell whether the source of truth after completion is TanStack Query or Zustand. That makes future changes to trace replay, cache invalidation, and run cleanup more error-prone.

Recommendation: make one rule true. Either update the convention to explicitly allow one retained run for the trace panel, or move the terminal trace data into the query cache and clear Zustand as documented. The current implementation has a stated rationale, so correcting the document may be the smallest change.

### P2 — Generated-client result handling is duplicated and has no consistent convention

Evidence: hooks such as [`apps/web/src/features/chat/hooks/useQuota.ts:6-17`](../apps/web/src/features/chat/hooks/useQuota.ts#L6-L17) check and throw SDK errors, while [`useChatList.ts:14-18`](../apps/web/src/features/chat/hooks/useChatList.ts#L14-L18), [`library/hooks/useDocuments.ts:22-36`](../apps/web/src/features/library/hooks/useDocuments.ts#L22-L36), and the nine admin queries at [`AdminPage.tsx:161-191`](../apps/web/src/features/admin/AdminPage.tsx#L161-L191) unwrap the same `{ data, error }` shape differently.

Why it matters: the repetitive, hand-written unwrapping is already producing divergent semantics: some callers expose failures and others turn them into empty data. The pattern will continue to drift as endpoints are added.

Recommendation: add one small `unwrap` helper beside the generated-client configuration that returns `data` or throws `error`, then use it in query hooks. Keep endpoint calls in their owning feature hooks; this removes repeated error branches without creating another API layer.

### P3 — Chat-row actions are duplicated within the sidebar

Evidence: the sidebar renders direct rename, pin, and delete buttons at [`apps/web/src/features/chat/components/ChatSidebar.tsx:167-196`](../apps/web/src/features/chat/components/ChatSidebar.tsx#L167-L196), then renders the same mutations again in its overflow menu at [`:197-204`](../apps/web/src/features/chat/components/ChatSidebar.tsx#L197-L204).

Why it matters: the two surfaces can drift in labels, disabled/pending state, error handling, or available actions. A fix to a chat action must be made in multiple event handlers.

Recommendation: keep both interaction surfaces if they are intentional, but drive them from the same local action callbacks (for example `rename`, `togglePin`, and `remove`) instead of repeating inline mutation calls. A generic menu/action framework is unnecessary.

### P3 — Dense inline JSX obscures component boundaries and diffs

Evidence: [`apps/web/src/features/chat/pages/ChatView.tsx:171-193`](../apps/web/src/features/chat/pages/ChatView.tsx#L171-L193) combines nested menus, handlers, and layout into single long lines; the admin form body has the same pattern at [`apps/web/src/features/admin/AdminPage.tsx:395-440`](../apps/web/src/features/admin/AdminPage.tsx#L395-L440). `ChatSidebar` has similar dense, duplicated control markup at [`:119-212`](../apps/web/src/features/chat/components/ChatSidebar.tsx#L119-L212).

Why it matters: review diffs conceal behavioural changes inside styling and make small edits harder to inspect. This is a readability issue, not a reason to abstract Tailwind utilities.

Recommendation: format JSX one prop/child group per line and extract only semantic blocks that already have a name (for example, `ThreadActions` or `RuntimeSettingsPanel`). Leave ordinary Tailwind class composition inline.

## Review notes

- The feature layout, generated-code boundary, and separation of live stream state from REST query state are otherwise sound foundations.
- I did not flag repeated form fields or Tailwind utilities alone: at their current scale, a generic form system or class abstraction would add more indirection than it removes.
- No source code or tests were changed.
