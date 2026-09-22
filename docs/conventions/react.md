# React conventions — `apps/web`

Companion to `docs/design-system.md` (visual language) and `CLAUDE.md`
(non-negotiables). This file answers the structural questions a new
component or feature raises, so they get answered the same way in every
slice.

## Folder structure: feature-first, not type-first

```
apps/web/src/
  features/
    chat/
      components/       ChatComposer.tsx, MessageList.tsx, ...
      hooks/             useRunStream.ts, useChatList.ts
      store.ts           Zustand slice for this feature, if it has one
      types.ts           Feature-local types not in the generated client
    trace/
      components/        TraceRow.tsx, CitationChip.tsx, ThinkingPanel.tsx
      hooks/              useTrace.ts
    sources/
    admin/
      providers/
      models/
      evals/
  components/ui/          shadcn/ui primitives only — nothing feature-specific
  generated/               openapi-ts output — never hand-edit (CLAUDE.md)
  lib/                     fetch-event-source wrapper, auth, query client
  styles/tokens.css        mirrors docs/design-system.md §2–3
```

A component belongs to a feature folder unless it's a true primitive
(button, input, dialog) reused across features with zero feature-specific
logic — those go in `components/ui`. If you're unsure, default to the
feature folder; moving a genuinely-shared component out later is a cheap
refactor, and premature sharing is what causes design-system drift.

## State: TanStack Query vs. Zustand, never both for the same data

- **TanStack Query** owns everything that comes from a REST endpoint and
  can be refetched: chat list, messages, collections, documents, admin
  settings, usage. If it has a `GET` endpoint in TRD §12, it's a query.
- **Zustand** owns only live, in-flight run state that doesn't have a
  REST shape while it's happening: streaming answer text, trace events,
  decision events, the current run's status. The store is keyed by
  `run_id` and is cleared when the run completes and its final state is
  written back into the TanStack Query cache (the completed message).
- Never mirror Query data into Zustand "for convenience," and never poll
  a Query endpoint for something the SSE stream already delivers live —
  that's the specific anti-pattern that causes double-rendering bugs on
  this kind of app.

## SSE events → UI state

- One hook, `useRunStream(runId)`, owns the `fetch-event-source`
  connection and is the *only* place that writes to the run's Zustand
  slice. Components read from the store; they never subscribe to the
  stream directly.
- The hook switches on the discriminated `type` field from TRD §12's
  event union (generated type, not hand-rolled) and does the minimum
  translation into store updates — no business logic in the hook itself
  (e.g., faithfulness-threshold decisions belong in the backend, not a
  `switch` case here).
- On mount with an existing `run_id` (reopening a chat mid-run, or a
  completed run), the hook calls `subscribe` with `after_seq` from the
  last known event rather than reading from the top, matching the
  `RunBus` resume behaviour in TRD §7/§12.
- Reconnection is explicit and bounded: 3 retries with backoff, then the
  hook surfaces a "Connection lost — resume" affordance rather than
  retrying forever.

## Generated vs. hand-written

- Anything under `src/generated/` is produced by `openapi-ts` from the
  FastAPI OpenAPI schema and the SSE event union. It is never edited by
  hand, per `CLAUDE.md`. If a generated type is wrong, the Pydantic model
  is wrong — fix it there and regenerate.
- Hand-written API-adjacent code (query hooks wrapping the generated
  client, e.g. `useChatList`) lives in the owning feature's `hooks/`
  folder, not in `generated/` or a shared `api/` folder — keeps the
  generated boundary unambiguous.

## Styling

- Tailwind utility classes only; no CSS-in-JS. Design tokens (colour,
  type, spacing) come from `styles/tokens.css`, which mirrors
  `docs/design-system.md` exactly — if a value isn't a token, it's
  probably not in the design system and shouldn't be hardcoded in a
  component.
- shadcn/ui components are a starting point, restyled to the tokens, not
  used with their default Tailwind theme. Don't add a shadcn component
  whose visual language (rounded cards, default shadows) works against
  §5/§9 of the design system without adjusting it first.
- Citation chips, trace rows and score bars are shared components in
  `features/trace/components/`, reused everywhere verdicts or scores
  appear (transcript, Sources tab, eval run diffs) — don't reimplement
  chip logic per feature.

## Naming

- Components: `PascalCase.tsx`, one component per file, file name matches
  the default export.
- Hooks: `useX.ts`, colocated with the feature that owns the state, not
  in a global `hooks/` folder unless genuinely feature-agnostic (e.g.
  `useMediaQuery`).
- Zustand stores: `<feature>Store.ts`, one store per feature max — don't
  split a feature's live state across multiple stores.

## Accessibility and motion

Follow `docs/design-system.md` §6 and §8 exactly: the citation-chip
crossfade is the only load-independent motion in the app; everything else
either responds to a user action or doesn't animate. Every new
interactive component gets a visible focus ring and is operable by
keyboard before it's considered done — this isn't a pass at the end of a
slice, it's part of building the component.