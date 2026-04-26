import { fetchWithAuth, SAMBA_PREFIX } from '@/lib/samba/api/shared'

/** 외부 이미지 URL → 배경 제거(WASM) → 흰 배경 합성 → WebP Blob */
export async function removeBgFromUrl(imageUrl: string): Promise<Blob> {
  const resp = await fetchWithAuth(
    `${SAMBA_PREFIX}/proxy/image-fetch?url=${encodeURIComponent(imageUrl)}`
  )
  if (!resp.ok) throw new Error(`이미지 로드 실패: ${resp.status}`)
  const imgBlob = await resp.blob()

  // jsdelivr CDN에서 모델 다운로드 (unpkg 대비 국내 안정적)
  const { removeBackground } = await import('@imgly/background-removal')
  const transparentBlob = await removeBackground(imgBlob, {
    publicPath: 'https://cdn.jsdelivr.net/npm/@imgly/background-removal@1.7.0/dist/',
  })

  const bitmap = await createImageBitmap(transparentBlob)
  const canvas = document.createElement('canvas')
  canvas.width = bitmap.width
  canvas.height = bitmap.height
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#FFFFFF'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(bitmap, 0, 0)
  bitmap.close()

  return new Promise<Blob>((resolve, reject) =>
    canvas.toBlob(
      b => (b ? resolve(b) : reject(new Error('canvas toBlob 실패'))),
      'image/webp',
      0.92
    )
  )
}

/** 이미지 Blob → R2 업로드 → public URL 반환 */
export async function uploadBlobToR2(blob: Blob, filename: string): Promise<string> {
  const form = new FormData()
  form.append('file', blob, filename)
  const resp = await fetchWithAuth(
    `${SAMBA_PREFIX}/proxy/r2/upload-image?filename=${encodeURIComponent(filename)}`,
    { method: 'POST', body: form }
  )
  if (!resp.ok) throw new Error(`R2 업로드 실패: ${resp.status}`)
  const data = (await resp.json()) as { success: boolean; public_url: string; message?: string }
  if (!data.success) throw new Error(data.message || 'R2 업로드 실패')
  return data.public_url
}
