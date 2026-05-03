export function normalizePlayautoAliasCode(value: string | null | undefined): string {
  const trimmed = String(value || '').trim()
  if (!trimmed) return ''
  const upper = trimmed.toUpperCase()
  if (/^\d+\.0+$/.test(upper)) return upper.replace(/\.0+$/, '')
  return upper
}

export function parsePlayautoAliasEntry(value: string | null | undefined): { code: string; alias: string } {
  const raw = String(value || '').trim()
  if (!raw) return { code: '', alias: '' }
  const match = raw.match(/^(.*?)\s*[-\u2010-\u2015\u2212]\s*(.+)$/)
  if (!match) return { code: normalizePlayautoAliasCode(raw), alias: '' }
  return {
    code: normalizePlayautoAliasCode(match[1]),
    alias: String(match[2] || '').trim(),
  }
}

export function formatPlayautoAliasEntry(code: string | null | undefined, alias: string | null | undefined): string {
  const trimmedCode = String(code || '').trim()
  const trimmedAlias = String(alias || '').trim()
  if (!trimmedCode) return trimmedAlias
  if (!trimmedAlias) return trimmedCode
  return `${trimmedCode}-${trimmedAlias}`
}
