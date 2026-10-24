/** Milliseconds as a person reads them: under a second stays in ms, above it
 *  switches to seconds so "12453 ms" becomes "12.5 s". */
export function formatMs(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`
}

const countFormatter = new Intl.NumberFormat()

/** Thousands separators for token and context counts. */
export function formatCount(value: number): string {
  return countFormatter.format(value)
}
