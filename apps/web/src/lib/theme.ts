export type Theme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'veriforge-theme'

export function getInitialTheme(): Theme {
  const saved = window.localStorage.getItem(THEME_STORAGE_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return 'dark'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
}

export function saveTheme(theme: Theme): void {
  window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  applyTheme(theme)
}

export function initializeTheme(): void {
  applyTheme(getInitialTheme())
}
