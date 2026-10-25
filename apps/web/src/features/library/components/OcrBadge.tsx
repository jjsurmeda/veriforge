import type { PageFlag } from '../../../generated/types.gen'

/** Beta: pages read with OCR carry an `ocr` flag (set by ingest). Shows an OCR
 *  chip, and a plain note when the engine was unsure or pages were skipped. */
export function OcrBadge({ pageFlags }: { pageFlags: PageFlag[] | null }) {
  const has = (flag: string) => (pageFlags ?? []).some((entry) => entry.flags.includes(flag))
  if (!has('ocr') && !has('ocr_skipped')) return null
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 text-2xs">
      {has('ocr') && (
        <span title="Read with OCR (beta)" className="rounded-full bg-raised px-1.5 py-0.5 text-[0.65rem] font-medium text-fg-muted">
          OCR
        </span>
      )}
      {has('ocr_low_confidence') && <span className="text-warning">low-confidence OCR</span>}
      {has('ocr_skipped') && <span className="text-warning">scanned pages skipped</span>}
    </span>
  )
}
