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

Six named tokens, dark-first (this is a long-session working tool), with a
full light-mode pairing.

| Token | Hex | Role |
| --- | --- | --- |
| Ink | `#10131A` | Base background, dark. Blue-black, not a flat near-black. |
| Graphite | `#1A1F29` | Surfaces: panels, composer, trace rows. |
| Mist | `#2B3140` | Borders, dividers, disabled state, "(fallback)" labels. |
| Ember | `#FF6A2C` | **Active/generating only** — a run in progress, a hop firing, the Stop button. Never a static brand accent. |
| Patina | `#1FA37E` | Verified / supported claims and citations. Proven-over-time, like oxidised metal — not a generic SaaS mint. |
| Rust | `#C1432B` | Contradicted / unsupported claims. Deliberately more red, less orange, than Ember, so the two never get confused mid-stream. |
| Paper | `#F3F4F1` | Light-mode background — cool off-white, not cream. |

Amber `#E8A33D` marks "partial" verdicts, between Patina and Rust. Colour
is always paired with a shape (chip outline, icon) per the WCAG requirement
in the TRD — never colour alone.

**Why not the obvious choices:** warm-cream-plus-terracotta and
near-black-plus-acid-accent are the two most common AI-generated defaults
right now. Ember reads as molten copper, not clay — more saturated, and
used for exactly one live state rather than as a decorative brand colour.
Patina is green-shifted rather than the expected cyan/mint SaaS accent,
because the metaphor is proven metal, not a status light.

## 3. Type

| Role | Face | Why |
| --- | --- | --- |
| Display / headline | Space Grotesk | Geometric, slightly mechanical — reads like an instrument face, not a marketing serif. |
| Body / UI | IBM Plex Sans | Built for on-screen density and long reading sessions; technical without being the default system font. |
| Data (scores, latency, tokens, citations) | IBM Plex Mono | Tabular figures so numbers actually align when compared. Functional, not a decorative label wrapper — used only where digits are being compared. |

Scale (rem, 1rem = 16px): `0.8125 / 0.875 / 1 / 1.125 / 1.375 / 1.75 / 2.25`.
Body copy sits at 0.9375–1rem. Line length caps near 72 characters in the
transcript and trace panels.

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
│            │ ┌ composer: mode · source · send ┐                         │
└────────────┴───────────────────────────────┴────────────────────────────┘
```

Admin pages break from the three-pane shell into a left-nav plus dense,
sortable content tables — admins are scanning configuration, not browsing
a catalogue, so tables beat cards there too.

## 5. Components

- **Citation chip.** Inline `[n]`, coloured by current verdict — grey while
  pending, then Patina / Amber / Rust. A small filled numeral, closer to a
  footnote mark than a rounded pill with a shadow.
- **Trace row.** One line: a status dot, the node name, the result, and the
  Jev probability set in Plex Mono on the right. A fallback-engine decision
  gets a small "(fallback)" label in Mist — not a separate colour.
- **Latency waterfall / score bars.** Thin horizontal bars in a single
  Graphite fill, labelled with the exact number. No per-bar rainbow
  gradients.
- **Buttons.** One filled primary style, Ember, reserved for the actively
  running Stop action. Everything else is outline or text buttons in
  Ink/Paper tones.

## 6. Motion

One deliberate, response-triggered sequence: while an answer streams,
citation chips sit grey. The moment the reviewer returns a verdict for a
claim, its chip crossfades to its verdict colour (200ms) and a thin
underline briefly traces under the claim it belongs to. That's the whole
motion budget — no load-in animations, no hover-lift on every card. This
motion answers a real event (a verdict arriving), which is the case worth
animating.

## 7. Voice

Plain, active, user-facing language. "Documents," not "collections," in
end-user copy (the word "collection" stays in admin/API surfaces only).
"Stop," not "Cancel run." "Couldn't find this in your documents," not
"Retrieval insufficient." Abstention copy always says two things, in
order: what was found, then what's missing — never an apology, never a
vague "I don't know."

## 8. Accessibility floor

WCAG 2.1 AA contrast in both themes. Verdict colour always paired with
shape. Visible keyboard focus ring, Ember, 2px. `prefers-reduced-motion`
disables the chip crossfade — verdicts still land, just instantly. Every
chart in the Metrics tab has a text equivalent in the row it summarises.

## 9. What we deliberately avoided

- Cream/terracotta and near-black/acid-accent default palettes (§2).
- Numbered 01/02/03 markers anywhere content isn't actually a sequence —
  Deep-mode hop numbers are the one legitimate case.
- ALL-CAPS eyebrows, middle-dot metadata strings, trailing arrows on
  buttons.
- An identical rounded-card grid for citations, sources and admin lists —
  each uses the layout that matches how it's actually scanned.