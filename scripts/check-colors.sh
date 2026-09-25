#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$root/apps/web/src"
tokens="$src/styles/tokens.css"
failed=0

if rg -n --glob '*.{ts,tsx,css}' --glob '!styles/tokens.css' 'rgb\(|hsl\(|#[0-9a-fA-F]{3,8}|\b(turquoise|accent|secondary|info-soft)\b|(bg|text|border)-(gray|slate|zinc|neutral|stone|sky|cyan|teal|blue)-' "$src" | rg -v '/styles/tokens\.css:'; then
  failed=1
fi

if ! rg -q -- '--color-(main|sidebar|panel|surface|raised|popover|fg|focus-ring)' "$tokens"; then
  printf '%s\n' 'tokens.css is missing the v3.1 token contract' >&2
  failed=1
fi

exit "$failed"
