import { create } from 'zustand'

type Theme = 'dark'

interface ThemeState {
  theme: Theme
  toggle: () => void
  setTheme: (t: Theme) => void
}

export const useThemeStore = create<ThemeState>()((set) => ({
  theme: 'dark',
  toggle: () => set({ theme: 'dark' }),
  setTheme: () => set({ theme: 'dark' }),
}))
