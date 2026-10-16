export type Theme = 'dark' | 'light';
const storageKey = 'aqa-copilot-theme';

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem(storageKey, theme); } catch { /* Still usable without storage. */ }
}

export function initializeTheme() {
  let theme: Theme = 'dark';
  try { if (localStorage.getItem(storageKey) === 'light') theme = 'light'; } catch { /* Use default. */ }
  document.documentElement.dataset.theme = theme;
}
