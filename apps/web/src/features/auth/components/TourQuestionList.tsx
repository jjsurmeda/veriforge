import { TOUR_QUESTIONS } from '../../demo/tourData'

/** The six tour questions on the login page, under "Try the demo" (item 4).
 *
 *  The list the chips are built from is the same one the tour itself uses, so
 *  the login page and the empty demo chat cannot disagree about what the
 *  showcase demonstrates. Clicking one here starts the demo and then sends it,
 *  which is what "try" means.
 *
 *  A question the demo account may not run — the Deep one, unless the operator
 *  enabled Deep — is not offered at all, rather than offered and refused.
 */
export function TourQuestionList({ onSelect }: { onSelect?: (question: string) => void }) {
  return (
    <section aria-labelledby="tour-questions-heading" className="mt-3">
      <h2 id="tour-questions-heading" className="px-1 text-2xs text-fg-subtle">
        What the demo shows
      </h2>
      <ul className="mt-1 space-y-0.5">
        {TOUR_QUESTIONS.map((item) => (
          <li key={item.id} className="flex items-baseline gap-2 px-1 py-0.5">
            <span aria-hidden="true" className="mt-1.5 size-1 shrink-0 rounded-full bg-fg-subtle" />
            <span className="min-w-0 text-2xs leading-5 text-fg-muted">
              <span className="text-fg">{item.shows}</span>{' '}
              <span className="font-mono">{item.question}</span>
              {onSelect && (
                <button
                  type="button"
                  onClick={() => onSelect(item.question)}
                  className="ml-1.5 rounded font-medium text-fg underline decoration-border underline-offset-2 transition-colors duration-150 hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
                >
                  try it
                </button>
              )}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}