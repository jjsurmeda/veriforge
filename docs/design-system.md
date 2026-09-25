# Veriforge design system — v3

Veriforge is a dense evidence workbench. The interface should feel like a calm instrument panel: quiet when evidence is still forming, explicit when a verdict or state arrives, and never more decorative than the work requires.

v3 takes structural cues from the supplied Perplexity and Grok references while keeping Veriforge's own name, mark, language, and product behaviour.

## 1. Product register

- **Audience:** engineers and architects evaluating a RAG system, plus people asking questions from their documents.
- **Primary job:** make an answer's provenance, reviewer state, retrieval decisions, quotas, and uncertainty inspectable without leaving the thread.
- **Personality:** forensic, precise, grounded.
- **UI job:** show trust while it is forming; do not perform certainty before verification.

## 2. Colour

Dark is the default. Semantic colour is reserved for state and evidence, never used as ambient decoration.

### Core surfaces

| token | dark | light | role |
| --- | --- | --- | --- |
| `background` | `#161616` | `#fcfcfa` | Main canvas |
| `surface` | `#1f1f1f` | `#ffffff` | Composer, cards, detail surfaces |
| `surface-raised` | `#2a2a2a` | `#efefec` | Active rows, pills, user bubble |
| `surface-hover` | `#262626` | `#e7e7e2` | Hover fill |
| `surface-muted` / panels | `#1b1b1b` | `#f5f5f2` | Sidebar and workspace panel |
| `border` | `#2e2e2e` | `#e6e6e2` | Hairline dividers |
| `border-strong` | `#3a3a3a` | `#d4d4ce` | Inputs and structural emphasis |

### Text and actions

| token | dark | light | role |
| --- | --- | --- | --- |
| `foreground` | `#ececec` | `#1a1a1a` | Primary text and icons |
| `muted-foreground` | `#9a9a9a` | `#6b6b66` | Metadata and secondary copy |
| `subtle-foreground` | `#858585` | `#6f6f6a` | Section labels and quiet metadata |
| `primary` | `#ececec` | `#1a1a1a` | Primary action fill |
| `on-primary` | `#161616` | `#fcfcfa` | Text on primary |
| `accent` | `#20b8cd` | `#1c737d` | Focus ring, links, active selection |
| `success` | `#75c99a` | `#2f7d5b` | Supported/ready |
| `warning` | `#e3b56a` | `#8a5a18` | Partial/attention |
| `danger` | `#f08d86` | `#a33e3a` | Failed/unsupported/destructive |

The dark `subtle-foreground` and light `accent` values are adjusted from the initial v3 proposal to meet WCAG AA contrast against their panel backgrounds. Use the semantic dot or badge together with text or shape; colour is never the only verdict cue.

Forbidden: purple/blue gradients, glow, glassmorphism, gradient text, default Tailwind greys, and coloured ambient backgrounds.

## 3. Typography

- **UI sans:** Inter Variable, 14–15px in chrome, 15px/1.6 for user messages.
- **Answer serif:** Source Serif 4 Variable, 17px/1.75, left-aligned, maximum reading width 720px.
- **Mono:** JetBrains Mono for IDs, scores, trace metadata, quota values, and compact technical labels.
- **Numbers:** always use `tabular-nums`.
- **Scale:** keep the product UI scale tight. Avoid fluid display sizing and excessive all-caps labels.
- **Icons:** Lucide at `strokeWidth={1.75}`; 18px in chrome, 14px in pills and metadata.

The answer surface is direct prose on the canvas. It is not a card, and it does not use a bubble, border, or shadow. A small `Answer` label and Bot avatar identify the assistant turn.

## 4. Shape and depth

- Controls: 8px radius.
- Cards and rows: 12px radius.
- Composer: 24px radius.
- Pills and avatars: full radius.
- Dark mode has no shadows. Depth comes from surface steps and hairlines.
- Light mode may use a soft shadow on the composer, popovers, menus, and auth card only.
- Do not stack a border, shadow, and tinted background on the same element unless the state needs to be especially clear.

## 5. Layout

### Authenticated chat

- `>=1280px`: 280px left sidebar, flexible main column, 400px right workspace.
- `1024–1279px`: right workspace is a fixed overlay drawer; the main thread remains underneath.
- `<1024px`: left navigation is a drawer; the workspace is a full-height drawer. Mobile targets are at least 44px.
- The AppHeader is dissolved on `/` and `/chat/*`; quota, theme, profile, and admin access move to the left sidebar or thread header. Sources and admin keep the header shell.
- Both panel states persist in guarded localStorage writes.

### Main thread

- Thread header: 56px, quiet title, thread actions, and workspace toggle.
- Message column: 720px maximum, left-aligned, 32px between turns and 12px between a user turn and its answer.
- User message: right-aligned `surface-raised` bubble, maximum 80%, 24px radius with an 8px tail corner.
- Assistant message: no bubble; serif prose with a 20px Bot avatar and `Answer` label.
- Inline citations: compact `surface-raised` pills with file icon, short document label, verdict dot, hover preview, and click-to-workspace behavior.
- Keep the existing horizontal source-card row in addition to the `N sources` pill.
- Answer actions: client-side Copy and Link to message are allowed. Do not add thumbs or regenerate without an existing API.
- Related follow-ups: full-width hairline rows under a `Related` heading. Preserve the existing `Suggested follow-ups:` copy for parity and e2e compatibility.

### Left sidebar

- Top row: Veriforge mark, search, collapse/expand.
- Primary rows: New chat, Sources, and Admin for admins.
- Sources and Chats are collapsible sections. Chat titles truncate to one line; pinned chats form a small pinned group.
- A row's existing rename, pin, and delete actions remain keyboard reachable. The overflow menu repeats those actions rather than replacing them.
- Bottom: compact quota pill, profile menu, user email/role, and theme toggle.

### Workspace panel

Tabs remain `Trace`, `Sources (n)`, and `Metrics` so existing selectors remain stable. The panel header includes a live indicator, expand control, and collapse control.

- **Sources/Citations:** query context, document rows, page refs, verdict, snippet, and retrieval scores.
- **Trace:** thinking disclosure, steps, DecisionTimeline, meters, Jev/fallback badges, and reasoning.
- **Metrics:** compact stat tiles, latency waterfall, answer scores, usage, and the existing empty state.

## 6. Components

### Composer

The composer is sticky at the bottom, max-width 720px, with a 24px radius. The placeholder is `Ask anything` for an empty thread and `Ask a follow-up` after a turn. The Plus/Run settings control opens the same settings surface. Mode, Model, Run source, and Collection controls remain native labelled selects/checkboxes. Submit is a round ArrowUp button; streaming changes it to a labelled Stop button. The textarea grows in place and never shifts the answer layout.

### Sources

Sources uses a collection sidebar, collection summary cards, a `+ New source` card, upload dropzone, document list, starter questions, and a document detail drawer. Keep all current status, page-quality, tag, re-index, delete, and upload outcome states.

### Auth

Auth pages use a centred 400px card on the canvas, Veriforge mark, theme toggle, `Secure access` label, existing fields/links/errors, and one primary action. No decorative blurred colour fields.

### Admin

Admin uses the same left-shell language and quiet hairline tables. All eight sections remain: Decision layer, Settings, Providers, Models, Roles, Plans, Users, and Audit. Preserve every Add, Save, Test, Activate, Create version, quota override, and role/status control. The DecisionLayerPanel window select and all stat/breaker/disagreement values remain.

## 7. Motion

- Hover and press: 150ms ease-out, colour/background/border only where possible.
- Buttons: `active:scale(0.97)`; text links do not scale.
- Popovers and menus: 150–200ms ease-out, scale from the trigger origin when a primitive exposes it.
- Panels: 240ms custom ease-out slide; never use `ease-in` for UI.
- Streaming: only the status line may shimmer. The answer grows in place.
- Repeated actions such as typing, sending, and switching chats feel immediate.
- `prefers-reduced-motion` removes nonessential animation and leaves state changes visible.

## 8. Voice and copy

Use plain, specific language: `Ask anything`, `Ask a follow-up`, `Sources`, `Related`, `Metrics land when the run completes.`, and the existing error text. Do not use filler such as “Unlock the power of…” or “Seamlessly…”. Keep user-facing errors calm and actionable.

## 9. Accessibility floor

- Every interactive element has hover, active, focus-visible, disabled, loading, and error states where applicable.
- Focus rings are 2px turquoise (`accent`) with offset.
- Body text meets 4.5:1 contrast in both themes; `subtle-foreground` is checked against panel surfaces.
- Every icon-only control has an `aria-label` and a tooltip where its meaning is not obvious.
- Native buttons, inputs, selects, and textareas remain keyboard operable. Workspace tabs use a labelled tablist and arrow-key navigation.
- Keep existing `aria-label`, `role`, and test selectors. A moved control must retain its accessible name.
- Tables, meters, status badges, and charts have text equivalents.
- No horizontal overflow or clipped controls at 390px.

## 10. Anti-slop pre-flight

- [x] Neutral surfaces and one turquoise accent.
- [x] No gradients, glow, glass, or gradient text.
- [x] No card-in-card nesting or uniform shadow stacks.
- [x] Lucide-only icon family at 1.75 stroke.
- [x] Left-aligned answer prose; centring only for empty/auth states.
- [x] Real type scale and tabular numeric data.
- [x] 4px spacing rhythm and purposeful motion.
- [x] Required screenshot and accessibility verification recorded in `docs/prompts/redesign-v3-audit.md`.
