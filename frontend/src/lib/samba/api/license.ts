import { API_BASE } from '@/lib/samba/legacy'

const LICENSE_VERIFY_URL = `${API_BASE}/api/v1/license/verify`

export interface LicenseVerifyResult {
  valid: boolean
  message: string
  expires_at: string | null
  buyer_name: string | null
}

export async function verifyLicenseKey(licenseKey: string): Promise<LicenseVerifyResult> {
  const res = await fetch(LICENSE_VERIFY_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ license_key: licenseKey }),
  })
  if (!res.ok) throw new Error('라이선스 서버 연결 실패')
  return res.json()
}
