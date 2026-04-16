// 프록시 URL 파싱/조합 유틸 함수

// http://user:pass@host:port 형식의 URL을 분리
export const parseProxyUrl = (url: string): { username: string; password: string; ip: string; port: string } => {
  const m = url.match(/^https?:\/\/([^:]+):([^@]+)@([^:]+):(\d+)$/)
  if (m) return { username: m[1], password: m[2], ip: m[3], port: m[4] }
  return { username: '', password: '', ip: '', port: '' }
}

// 필드값을 http://user:pass@host:port 형식으로 조합
export const buildProxyUrl = (f: { username: string; password: string; ip: string; port: string }): string =>
  f.ip ? `http://${f.username}:${f.password}@${f.ip}:${f.port}` : ''
