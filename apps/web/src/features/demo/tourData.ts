/** The six tour questions, and what each one is meant to show (item 4).

 *  Every one of these was verified against the Shared books corpus with a
 *  real hybrid-search query before being put here — the D1 method, and the
 *  proofs are in `docs/showcase.md`. A tour question the corpus cannot answer
 *  is not a tour question, however good it looks.
 *
 *  `expect` is what the corpus does, from those searches — not what the model
 *  is hoped to do. The `Deep` question is the one exception and says so: Deep
 *  is the only mode that reads several passages and compares them, and the
 *  corpus proof for it is that the passages exist in one document, which is
 *  what multi-hop needs.
 *
 *  Kept as data rather than JSX so the order is one list, the copy is
 *  reviewable in one place, and a test can assert the corpus proofs are still
 *  recorded.
 */

export interface TourQuestion {
  /** Stable id, used as the chip's key and in the tour script. */
  id: string
  /** The question, sent verbatim. */
  question: string
  /** What it demonstrates, in the design system's plain voice. */
  shows: string
  /** What the corpus actually does, from the recorded search. */
  expect: string
  /** `deep` when the question needs Deep mode. */
  mode?: 'auto' | 'deep'
}

export const TOUR_QUESTIONS: TourQuestion[] = [
  {
    id: 'cited',
    question: 'Why does Alice say the Duchess’s kitchen must be full of soup?',
    shows: 'A cited answer.',
    expect:
      'Alice’s Adventures in Wonderland, the Mock Turtle’s "Beautiful Soup" passage, ' +
      'ranks in the top four hybrid hits (bm25 23.0, vector 0.62). Rehearsed: ' +
      'sufficiency 0.45, relevance 0.82, entity 0.93, all cleared.',
  },
  {
    id: 'abstain',
    question: 'What is the ISBN number of Pride and Prejudice?',
    shows: 'An abstention.',
    expect:
      'Retrieval returns the Gutenberg front matter and table of contents, which ' +
      'contain no ISBN. Rehearsed: sufficiency 0.02 and relevance 0.03 both below ' +
      'their floors, so the run declined and named the sufficiency gate. The ' +
      'abstention text still offers Web and Deep — the server-written template ' +
      'does not know the account — but a demo account is not shown those buttons.',
  },
  {
    id: 'conflict',
    question: 'How many months of warranty does the AW-2000 manual specify?',
    shows: 'A decline the corpus cannot support.',
    expect:
      'HONEST GAP, NOT THE BEHAVIOUR THE BRIEF ASKS FOR. The books are the only ' +
      'Shared collection, so there is nothing here that two sources disagree ' +
      'about: rehearsed, this abstains with sufficiency 0.02 and relevance 0.01, ' +
      'which is a second abstention rather than a conflict disclosure. A real ' +
      'conflict needs two conflicting warranty documents in Shared; they live in ' +
      'the private eval corpora, which must stay private. See docs/showcase.md.',
  },
  {
    id: 'entity',
    question: 'What ingress protection rating does the AW-2000 handbook promise?',
    shows: 'An entity-mismatch decline.',
    expect:
      'Retrieval returns books that merely resemble the phrasing (top vector 0.19, ' +
      'no bm25 above 12.7) and no AW-2000 passage at all. Rehearsed: entity 0.01 ' +
      'against a 0.50 floor while sufficiency also failed, so the decline names ' +
      'whichever gate the run acted on.',
  },
  {
    id: 'multilingual',
    question: 'Was geschieht mit Samsa, als er die Nachricht von seinem Vater liest?',
    shows: 'An answer in another language.',
    expect:
      'Die Verwandlung, the passage where Samsa reads his father’s message, ranks ' +
      'first with bm25 48.7 — the strongest single-question result in the set. ' +
      'Rehearsed: answered, all three gates cleared.',
  },
  {
    id: 'deep',
    question:
      'Compare how Holmes and Watson differ in their willingness to believe other people’s accounts?',
    shows: 'A Deep run across several passages.',
    expect:
      'Four Sherlock Holmes passages in the top four hybrid hits (bm25 19.0 on the ' +
      'first). Multi-hop needs several passages about one thing; only Deep reads ' +
      'them all. NOT rehearsed: Deep is off on the demo plan by default ' +
      '(DEMO_ALLOW_DEEP), and this is the one question with no measured run.',
    mode: 'deep',
  },
]

/** The tour questions a demo account may actually run: Deep is off by default
 *  (`DEMO_ALLOW_DEEP`), so the Deep chip is filtered out rather than shown and
 *  then refused by the server. */
export function tourQuestionsFor(options: { allowDeep: boolean }): TourQuestion[] {
  return TOUR_QUESTIONS.filter((item) => item.mode !== 'deep' || options.allowDeep)
}