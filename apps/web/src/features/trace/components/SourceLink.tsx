/** The URL as a link only when its scheme is http(s). A web result is
 *  untrusted text: `javascript:` and `data:` must never become an href. */
export function safeHttpUrl(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null
  } catch {
    return null
  }
}

export function SourceLink({ url }: { url: string | null | undefined }) {
  if (!url) return null
  const href = safeHttpUrl(url)
  const host = href ? new URL(href).hostname : null
  if (!href) return <span className="block truncate font-mono text-2xs text-fg-muted">{url}</span>
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" title={href} onClick={(event) => event.stopPropagation()} className="block truncate font-mono text-2xs text-accent underline hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring">
      {host}
      <span className="sr-only"> ({href})</span>
    </a>
  )
}
