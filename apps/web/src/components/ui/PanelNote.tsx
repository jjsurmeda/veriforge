import type { ReactNode } from 'react'
import { LoaderCircle } from 'lucide-react'

/** One quiet line for a panel whose content is still arriving. Deliberately
 *  not a skeleton: the design system has no placeholder language, and a blank
 *  list is indistinguishable from an empty one — which is how a slow first
 *  read used to announce "no documents yet" before the answer arrived. */
export function PanelNote({ children }: { children: ReactNode }) {
  return (
    <p role="status" className="flex items-center gap-1.5 px-4 py-3 text-xs text-fg-muted">
      <LoaderCircle
        size={13}
        strokeWidth={1.75}
        className="shrink-0 animate-spin motion-reduce:animate-none"
        aria-hidden="true"
      />
      {children}
    </p>
  )
}