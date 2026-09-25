# Veriforge UI redesign v3 — audit

## Design read

Reading this as: a dense evidence workbench for engineers and architects, with a quiet neutral instrument-panel language, a serif answer surface, and restrained state colour. The supplied Perplexity and Grok screenshots are directional references for hierarchy and density only; Veriforge keeps its own name, mark, copy, and product language.

## Skill pass

Loaded before code:

- `redesign-existing-projects`
- `impeccable` (product register and audit reference)
- `design-taste-frontend`
- `frontend-design:frontend-design`
- `high-end-visual-design`
- `emil-design-eng`
- `git-master`

The environment does not expose `ui-ux-pro-max:ui-ux-pro-max`, `design:ux-copy`, `dataviz`, `design:design-critique`, or `design:accessibility-review`. Their requested checks are recorded below and were performed manually with the available impeccable, frontend-design, and Playwright workflows. The high-end visual skill's generic bans on Inter, Lucide, borders, and shadows conflict with the explicit v3 brief; the screenshots and v3 requirements win.

## Current-state findings

### Product and shell

- `AppShell` renders a separate 56px `AppHeader` above every authenticated route. Chat pages then render their own sidebar, creating two competing navigation layers.
- `ChatSidebar` owns chat-list collapse state in local storage, but it does not own quota, theme, profile, search, admin navigation, or a structured Sources section.
- The right `TracePanel` is desktop-only (`lg:flex`) and has no persisted collapse/expand state or mobile drawer presentation.
- The current shell uses translucent surfaces, `backdrop-blur`, and repeated small shadows. That is visual noise for a dense evidence tool and conflicts with the requested surface-step depth model.

### Chat

- `MessageList` renders both user and assistant content as bordered/shadowed bubbles. The v3 direction needs a right-aligned user bubble and unboxed assistant prose.
- Assistant content is plain pre-wrapped text. Markdown-like headings, bold lead-ins, nested lists, and source pills are not styled as a coherent answer surface.
- Citation logic is already isolated in `CitationChip`; its numbered superscript presentation can be replaced without changing citation lookup, verdict calculation, tooltip data, or click/focus behavior.
- The existing source-card row, reviewer revision disclosure, suggestions, abstention actions, status labels, error copy, and metrics footer are all present and must remain.
- The existing composer already owns the correct mutation/query behavior. It can be restyled and its controls surfaced in the toolbar without changing handlers or validation.

### Trace and sources

- `TracePanel` already has Trace, Sources, and Metrics tabs, counts, live state, decision timeline data, latency waterfall, usage rows, and the metrics empty state.
- `SourcesTab` and the message-level source disclosures already carry document names, excerpts, page refs, scores, and rerank/support data. The redesign should change presentation, not discard those values.
- `DecisionTimeline` already carries the Jev/fallback distinction, meter values, thresholds, outcomes, reasoning, and stage labels. These are high-value parity data.

### Other pages

- Sources, auth, and admin are structurally sound but share the old blue/purple token vocabulary, raised-card treatment, and inconsistent focus/shadow language.
- Admin has eight navigable sections plus the decision layer. Its forms and table rows are the parity-sensitive surface; visual changes must not simplify or hide any action.
- Auth has separate login, signup, forgot-password, reset-password, and OAuth callback routes. The redesign should centre a 400px card on the neutral canvas and keep every field, link, callback status, and error state.

## Anti-slop diagnosis

Patterns to remove or replace in presentation:

1. Purple/blue semantic palette and coloured action fills → neutral surfaces with one turquoise accent and light-on-dark primary buttons.
2. Glassmorphism/backdrop blur on structural panels → solid surface steps and hairlines.
3. Card-in-card stacks and ubiquitous `shadow-sm`/`shadow-md` → depth through `background`, `surface`, `surface-raised`, and borders; light-mode shadows only on composer/popovers.
4. Bubble treatment for assistant answers → direct serif prose on the canvas.
5. Generic uppercase mono labels everywhere → restrained 11–13px sans labels, with mono reserved for IDs, scores, and trace metadata.
6. Generic centered SaaS hero composition → left-aligned thread content; centering is reserved for empty states and auth.
7. Mixed icon treatment → Lucide at `strokeWidth={1.75}`, 18px chrome / 14px pills, with no emoji icons.

No capability is removed. The only replacement decisions are decorative treatments, recorded below.

## Layout and UX decisions

- At `>=1280px`: left rail/sidebar, central 720px reading column, and 400px workspace panel are visible together.
- At `1024–1279px`: workspace becomes a right overlay drawer; the thread remains readable underneath.
- At `<1024px`: left navigation becomes a drawer opened by the existing `Open navigation` control; the workspace becomes a right/bottom drawer with the same tab controls.
- Both panel states persist through guarded localStorage reads/writes (`try/catch`); a storage failure must not break the app.
- Mobile controls retain a minimum 44px hit area. Dense metadata may use smaller type, but buttons and comboboxes remain usable without hover.
- The main answer column uses `max-width: 720px` and a 17px/1.75 serif reading style. Lists use disc bullets, 24px nesting, and 12px item spacing.
- Streaming text grows in place. No first-paint page animation is added; only the existing stream/status treatment may shimmer.
- Panel transitions use 240ms ease-out; hover/press transitions use 150ms and colour/background only; repeated typing/sending/switching actions stay immediate.
- `prefers-reduced-motion` disables nonessential transitions and leaves state changes visible.

## Token validation

Proposed v3 values are from the brief except where a contrast check required a documented adjustment.

| token | dark | light | validation / note |
| --- | --- | --- | --- |
| background | `#161616` | `#fcfcfa` | Canvas separation retained. |
| sidebar / panel | `#1b1b1b` | `#f5f5f2` | Structural surface step. |
| surface | `#1f1f1f` | `#ffffff` | Composer/cards. |
| surface-raised | `#2a2a2a` | `#efefec` | Pills, active rows, user bubble. |
| surface-hover | `#262626` | `#e7e7e2` | Hover fill; not a status colour. |
| border | `#2e2e2e` | `#e6e6e2` | Hairline only. |
| border-strong | `#3a3a3a` | `#d4d4ce` | Inputs and focused structural edges. |
| foreground | `#ececec` | `#1a1a1a` | 15.32:1 on dark; 16.94:1 on light. |
| muted-foreground | `#9a9a9a` | `#6b6b66` | 6.12:1 on dark panel; 4.90:1 on light panel. |
| subtle-foreground | `#858585` (adjusted) | `#6f6f6a` (adjusted) | Dark brief value `#6b6b6b` is only 3.23:1 on `#1b1b1b`; adjusted values are 4.67:1 and 4.62:1. |
| primary | `#ececec` | `#1a1a1a` | Light-on-dark / dark-on-light action. |
| on-primary | `#161616` | `#fcfcfa` | Paired foreground. |
| accent | `#20b8cd` | `#1c737d` (adjusted) | Dark value is 7.58:1 on canvas; brief light value `#20808d` is 4.24:1 on panel, so it is darkened to 5.06:1. |
| success / warning / danger | desaturated semantic values | desaturated semantic values | Dots/badges only, always paired with text or shape. |

Typography uses Inter Variable for chrome, Source Serif 4 Variable for answer prose, and JetBrains Mono for metadata. All numeric displays use `tabular-nums`. The Roboto packages are removed.

## Removals & replacements

No feature, control, datum, route, query, store field, aria label, role, or e2e assertion is removed. These are presentation-only replacements from the loaded design skills:

| element | old location | skill + its reasoning | action (removed / replaced by X) | commit |
| --- | --- | --- | --- | --- |
| Structural glass panels | `AppHeader`, `AppShell`, `ChatSidebar`, `TracePanel` | `redesign-existing-projects` / `impeccable`: translucent surfaces and repeated shadows flatten hierarchy and add noise | replaced by solid `background` / `surface` / `surface-raised` steps and hairlines | tokens / shell |
| Repeated card elevation | Chat, sources, admin, auth cards | `design-taste-frontend`: uniform rounded boxes read as template output | replaced by surface steps; light-only composer/popover shadows | shell / pages |
| Purple/blue action vocabulary | global token classes and primary buttons | `redesign-existing-projects`: saturated multiple accents feel generic AI SaaS | replaced by neutral primary plus turquoise focus/accent | tokens |
| Bubble styling for assistant content | `MessageList` assistant message box | `design-taste-frontend` and v3 brief: answer prose should read as evidence, not a card | replaced by unboxed serif prose; citation and action logic unchanged | thread |
| Uppercase mono labels on primary chrome | sidebar/header/table headings | `frontend-design:frontend-design`: type scale should carry hierarchy without decorative all-caps noise | replaced by sentence-case sans labels; mono retained for IDs/scores | tokens / pages |

## Pre-delivery checklist

- [x] Neutral palette, no gradients, glow, glass, or gradient text.
- [x] Single turquoise accent used for focus, links, and active state.
- [x] No card-in-card nesting or stacked border + shadow + background.
- [x] Lucide icons only, 1.75 stroke, consistent size.
- [x] Six-step or smaller type scale with tabular numeric data.
- [x] Hover, active, focus-visible, disabled, loading, error, and empty states on every interactive surface.
- [x] 4px spacing rhythm across turns, rows, panels, and controls.
- [x] No first-paint choreography; streaming shimmer only where semantically active.
- [x] 44px mobile targets and no horizontal overflow at 390px.
- [x] Dark and light contrast checked for body and subtle text.
- [x] Keyboard tab order, focus rings, and `prefers-reduced-motion` verified.
- [x] Reference screenshots compared side by side at 1440px, 1100px, and 390px.

## Unavailable skill substitutions

The named `ui-ux-pro-max`, copy, dataviz, screenshot critique, and accessibility skills are not installed in this environment. Their requested checks are represented in the layout, token, component, and pre-delivery sections above and will be verified with the available impeccable, Playwright, lint, build, and test tooling rather than represented as completed skill runs.

## Verification record

- `npm run build` passes with the new font packages and v3 tokens.
- `npm test` passes: 6 files, 21 tests.
- `npm run lint` completes with existing Fast Refresh and effect warnings only; no errors.
- Playwright against the local Vite/API stack passes all 20 e2e tests. The decision-layer theme setup now explicitly normalizes the new dark default before taking its light/dark screenshots; no assertion was removed or weakened.
- Real-browser QA covered auth, chat, sources, completed answer, workspace tabs, theme switching, sidebar persistence, mobile navigation, and 1440/1100/390px layouts. The mobile workspace panel closes below 1024px so the navigation drawer remains reachable.
- Manual screenshot critique found no blocking layout defect. The source-card strip remains intentionally horizontally scrollable when more cards exceed the reading width.
