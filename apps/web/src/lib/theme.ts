export type Theme = 'light' | 'dark' | 'system'

export const THEME_STORAGE_KEY = 'veriforge-theme'

function systemTheme(): 'light' | 'dark' {
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

function resolvedTheme(theme: Theme): 'light' | 'dark' {
  return theme === 'system' ? systemTheme() : theme
}

export function getInitialTheme(): Theme {
  const saved = window.localStorage.getItem(THEME_STORAGE_KEY)
  if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
  return 'dark'
}

export function applyTheme(theme: Theme): void {
  const resolved = resolvedTheme(theme)
  document.documentElement.dataset.theme = resolved
  document.documentElement.dataset.themePreference = theme
  document.documentElement.style.colorScheme = resolved
}

export function saveTheme(theme: Theme): void {
  window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  applyTheme(theme)
}

export function initializeTheme(): void {
  applyTheme(getInitialTheme())
}
