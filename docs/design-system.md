# Veriforge — Design System & UI/UX Direction

This is the visual language for `apps/web`. It exists so "modern, clean
design" means something specific and repeatable, rather than whatever the
last component happened to look like. Follow it; propose changes here
before changing a component.

## 1. Grounding

Veriforge is a workbench for turning retrieved evidence into verified
answers — the *forge* tempering raw material (chunks, web pages) into
something trustworthy, and *veri* the promise that the result was actually
checked, not just asserted. The audience is engineers and architects
evaluating a RAG system, plus real users asking real questions.

The UI's one job: make trust visible **while it's still forming**. A person
should be able to tell, mid-stream, how much of an answer to believe and
why — without the interface performing a confidence it hasn't earned yet.

Two ideas carry the whole system:

1. **Evidence is material.** Chunks, scores and citations behave like
   objects with weight and provenance — not decoration.
2. **Trust is a live state, not a badge.** Colour changes happen when a
   verdict actually arrives, never as ambient styling.

## 2. Colour

The default theme is **light**: a cool workbench surface with a strong
indigo action colour, cyan for evidence in motion, and pink as a sparing
accent for selection and focus. Dark mode is a separately designed theme,
not an inversion. The semantic names below are the source of truth for
`apps/web/src/styles/tokens.css`.

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| `background` | `#F7F8FC` | `#0E1320` | App canvas; separates the workbench from the browser. |
| `surface` | `#FFFFFF` | `#151C2B` | Cards, panels, sidebars, composer, and tables. |
| `surface-muted` | `#EEF2F8` | `#1B2537` | Inset controls and secondary panels. |
| `border` | `#DCE3EF` | `#29364B` | Quiet dividers and card edges. |
| `foreground` | `#182238` | `#EEF2FF` | Primary text and iconography. |
| `muted-foreground` | `#667085` | `#A7B2C7` | Metadata, labels, and non-essential copy. |
| `primary` | `#6366F1` | `#818CF8` | Primary action, active selection, and focus glow. |
| `secondary` | `#06B6D4` | `#22D3EE` | Evidence and retrieval activity. |
| `accent` | `#EC4899` | `#F472B6` | A small amount of emphasis and live selection. |
| `success` | `#0E9F78` | `#34D399` | Supported, ready, and successful state. |
| `warning` | `#C27A08` | `#FBBF24` | Partial or attention state. |
| `danger` | `#D92D5F` | `#FB7185` | Failed, unsupported, or destructive state. |
| `info` | `#087EA4` | `#38BDF8` | Neutral system information. |

Soft pairings (`primary-soft`, `secondary-soft`, `accent-soft`, and the
matching semantic surfaces) are intentionally low-contrast fills; the
semantic foreground remains the readable colour. Verdict colour is always
paired with a shape, icon, or text label. The old near-black/ember/patina
vocabulary is removed rather than aliased, so a component cannot silently
fall back to the old visual language.

The persisted preference is stored under `veriforge-theme`. On a first visit,
the app follows `prefers-color-scheme`; after that, the user's choice wins.

## 3. Type

| Role | Face | Why |
| --- | --- | --- |
| Display / headline | Inter | Clear, contemporary UI voice with enough character for the workbench. |
| Body / UI | Inter | Dense labels and long evidence remain comfortable at small sizes. |
| Data (scores, latency, tokens, citations) | IBM Plex Mono | Tabular figures make comparisons and live metrics scannable. |

The type scale is an Inter-style rem scale: `0.8125 / 0.875 / 1 / 1.125 /
1.375 / 1.75 / 2.25`. Body copy sits at 0.9375–1rem. Line length caps near
72 characters in the transcript and trace panels.

## 4. Layout

The chat workspace is a **workbench**, not a card stack: three fixed panes,
left-aligned throughout. No centred marketing-style blocks inside the app.

```
┌────────────┬───────────────────────────────┬────────────────────────────┐
│ Chats      │ Transcript                     │ Trace ▸ Sources ▸ Metrics  │
│ (search)   │  Q: ...                        │ ● ingress   0.94 lookup    │
│ • Chat A   │  A: [1][2] ...answer text...   │ ● retrieve  8 chunks       │
│ • Chat B   │      ▓▓▓ streaming ▓▓▓          │ ● review    faithful 0.92 │
│            │  [1] doc.pdf p.4   0.87 ●      │                            │
│            │ ┌ composer: settings · send ┐                         │
└────────────┴───────────────────────────────┴────────────────────────────┘
```

Admin pages break from the three-pane shell into a left-nav plus dense,
sortable content tables — admins are scanning configuration, not browsing
a catalogue, so tables beat decorative cards there too.

## 5. Components

- **Citation chip.** Inline `[n]`, coloured by current verdict — muted while
  pending, then `success`, `warning`, or `danger`. A small filled numeral,
  closer to a footnote mark than a rounded pill with a shadow.
- **Trace row.** One line: a status dot, the node name, the result, and the
  Jev probability set in Plex Mono on the right. A fallback-engine decision
  gets a small "(fallback)" label in the muted colour — not a separate hue.
- **Latency waterfall / score bars.** Thin horizontal bars in a single
  surface-muted fill, labelled with the exact number. No per-bar rainbow
  gradients.
- **Buttons.** One filled primary style for the main action, plus quiet outline
  and text actions. The active stop action uses the danger semantic colour.
- **Cards and panels.** Use `surface`, a quiet `border`, radius `md` or `lg`,
  and a small elevation step on hover. Avoid a stack of identical cards where
  a list or table would scan faster.

## 6. Motion

Motion is purposeful and state-driven. Interactive elements shift colour,
border, elevation, or a small translate on hover and press. The theme toggle
crossfades surface and text colours smoothly. New messages enter with a
subtle 8px slide and fade, never a bounce. Citation chips retain their
verdict crossfade when a reviewer result arrives. Active and focus states use
a quiet primary/accent glow so keyboard users can see where they are.

Motion stays in the 150–320ms range and only communicates a real state
change, feedback, or reveal. `prefers-reduced-motion` is an accessibility
floor: all transitions and animations become instant, with no exceptions.

## 7. Voice

Plain, active, user-facing language. "Documents," not "collections," in
end-user copy (the word "collection" stays in admin/API surfaces only).
"Stop," not "Cancel run." "Couldn't find this in your documents," not
"Retrieval insufficient." Abstention copy always says two things, in
order: what was found, then what's missing — never an apology, never a
vague "I don't know."

## 8. Accessibility floor

WCAG 2.1 AA contrast in both themes. Verdict colour always paired with
shape, icon, or text. Visible keyboard focus uses the primary colour at 2px.
`prefers-reduced-motion` disables all nonessential motion — verdicts and
state changes still land, just instantly. Every chart in the Metrics tab has
a text equivalent in the row it summarises.

## 9. What we deliberately avoided

- The old near-black and ember-first palette; the default is now a designed
  light workbench with a paired dark theme.
- Numbered 01/02/03 markers anywhere content isn't actually a sequence —
  Deep-mode hop numbers are the one legitimate case.
- ALL-CAPS eyebrows, middle-dot metadata strings, trailing arrows on
  buttons, and hand-drawn replacement iconography.
- An identical rounded-card grid for citations, sources, and admin lists —
  each uses the layout that matches how it is actually scanned.
