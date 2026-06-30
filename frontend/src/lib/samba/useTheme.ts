import { light, dark } from '@/lib/samba/colors'
import { useThemeStore } from '@/lib/samba/themeStore'

/** 현재 테마 팔레트 반환. `import { light as c }` 대체용. */
export function useTheme() {
  const theme = useThemeStore((s) => s.theme)
  return theme === 'dark' ? dark : light
}
