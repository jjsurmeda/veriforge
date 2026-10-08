import { Compass } from 'lucide-react'

import { tourQuestionsFor, type TourQuestion } from './tourData'

/** The guided tour, as chips in an empty demo chat (item 4).
 *
 *  One row per behaviour the showcase has to demonstrate, each labelled with
 *  what it shows so a visitor picks a demonstration rather than a phrasing.
 *  Deliberately the same chip shape as `StarterQuestions` (design-system.md
 *  §5's Library language), with the behaviour under each question in the
 *  design system's plain voice.
 *
 *  The Deep chip is filtered out when a demo account may not use Deep
 *  (`DEMO_ALLOW_DEEP`), so the tour never offers a control the server will
 *  refuse.
 */
export function DemoTour({
  allowDeep,
  onSelect,
  onShowGates,
}: {
  allowDeep: boolean
  onSelect: (question: TourQuestion) => void
  /** Opens the gate card, for the decline questions. */
  onShowGates?: () => void
}) {
  const questions = tourQuestionsFor({ allowDeep })
  if (questions.length === 0) return null
  return (
    <section
      aria-labelledby="demo-tour-heading"
      className="rounded-xl border border-border bg-surface p-2"
    >
      <h2
        id="demo-tour-heading"
        className="flex items-center gap-1.5 px-2 py-1 text-xs font-medium text-fg-muted"
      >
        <Compass size={13} strokeWidth={1.75} className="text-fg" aria-hidden="true" />
        Six questions, six behaviours
      </h2>
      <ul className="divide-y divide-border">
        {questions.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onSelect(item)}
              className="flex min-h-11 w-full items-baseline gap-2 px-2 py-2 text-left transition-colors duration-150 hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-focus-ring"
            >
              {/* The behaviour is the label: a visitor picks what to see, not
                  a phrasing they happen to recognise. */}
              <span className="w-32 shrink-0 text-xs font-medium text-fg">{item.shows}</span>
              <span className="min-w-0 flex-1 text-xs leading-5 text-fg-muted">
                {item.question}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {onShowGates && (
        <p className="px-2 pb-1 pt-2 text-2xs text-fg-subtle">
          Each one opens its own trace: the gates it passed, the gate that stopped
          it, and the time each stage took.
        </p>
      )}
    </section>
  )
}