export function normalizePlayautoAliasCode(value: string | null | undefined): string {
  const trimmed = String(value || '').trim()
  if (!trimmed) return ''
  const upper = trimmed.toUpperCase()
  if (/^\d+\.0+$/.test(upper)) return upper.replace(/\.0+$/, '')
  return upper
}

export function formatSourceSiteLabel(sourceSite: string | null | undefined, siteAliasMap: Record<string, string>): string {
  const site = String(sourceSite || '').trim()
  if (!site) return ''
  const match = site.match(/^(.+)\(([^)]+)\)$/)
  const siteName = match?.[1]?.trim()
  const siteCode = match?.[2]?.trim()
  if (!siteName || !siteCode) return site

  const alias = siteAliasMap[normalizePlayautoAliasCode(siteCode)] || siteAliasMap[siteCode]
  return alias ? `${siteName}(${alias})` : site
}
