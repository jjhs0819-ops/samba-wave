// 순수 Node.js 내장 모듈만으로 RGBA PNG 생성 (투명 모서리)
import { deflateSync } from 'zlib'
import { writeFileSync } from 'fs'

function crc32(buf) {
  let crc = 0xFFFFFFFF
  for (const b of buf) {
    crc ^= b
    for (let i = 0; i < 8; i++) crc = (crc & 1) ? (0xEDB88320 ^ (crc >>> 1)) : (crc >>> 1)
  }
  return (crc ^ 0xFFFFFFFF) >>> 0
}

function chunk(type, data) {
  const t = Buffer.from(type, 'ascii')
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length)
  const crcBuf = Buffer.alloc(4)
  crcBuf.writeUInt32BE(crc32(Buffer.concat([t, data])))
  return Buffer.concat([len, t, data, crcBuf])
}

function makePng(size) {
  // IHDR - color type 6 = RGBA
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8   // bit depth
  ihdr[9] = 6   // RGBA
  ihdr[10] = ihdr[11] = ihdr[12] = 0

  const radius = size * 0.22  // 둥근 모서리 반지름

  const rows = []
  for (let y = 0; y < size; y++) {
    const row = [0]  // 필터 바이트
    for (let x = 0; x < size; x++) {
      const nx = x / size
      const ny = y / size
      const cx = x + 0.5
      const cy = y + 0.5

      // 둥근 모서리 안쪽인지 계산
      const qx = Math.max(radius - cx, 0, cx - (size - radius))
      const qy = Math.max(radius - cy, 0, cy - (size - radius))
      const dist = Math.sqrt(qx * qx + qy * qy)

      // 안티앨리어싱: 경계 1px를 부드럽게
      const alpha = dist < radius ? 255 : dist < radius + 1 ? Math.round(255 * (1 - (dist - radius))) : 0

      if (alpha === 0) {
        row.push(0, 0, 0, 0)  // 투명
        continue
      }

      // 오렌지 그라데이션 배경: #FF8C00 → #FFB84D
      const t = (nx + ny) / 2
      const gr = 255
      const gg = Math.round(140 + (184 - 140) * t)
      const gb = Math.round(77 * t)

      // 웨이브 3줄 (위→아래, 점점 굵고 밝게)
      const freq = Math.PI * 2.2
      const wave1 = 0.35 + Math.sin(freq * nx + 0.0) * 0.07
      const wave2 = 0.55 + Math.sin(freq * nx + 0.8) * 0.09
      const wave3 = 0.73 + Math.sin(freq * nx + 0.4) * 0.06

      const t1 = Math.max(0, 1 - Math.abs(ny - wave1) / 0.04)
      const t2 = Math.max(0, 1 - Math.abs(ny - wave2) / 0.05)
      const t3 = Math.max(0, 1 - Math.abs(ny - wave3) / 0.06)

      let r = gr, g = gg, b = gb

      // 파도 블렌딩 (밝은 웨이브를 배경 위에 얹기)
      if (t3 > 0) {
        r = Math.round(r * (1 - t3 * 0.6) + 255 * t3 * 0.6)
        g = Math.round(g * (1 - t3 * 0.6) + 200 * t3 * 0.6)
        b = Math.round(b * (1 - t3 * 0.6) + 80 * t3 * 0.6)
      }
      if (t2 > 0) {
        r = Math.round(r * (1 - t2 * 0.5) + 240 * t2 * 0.5)
        g = Math.round(g * (1 - t2 * 0.5) + 160 * t2 * 0.5)
        b = Math.round(b * (1 - t2 * 0.5) + 20 * t2 * 0.5)
      }
      if (t1 > 0) {
        r = Math.round(r * (1 - t1 * 0.35) + 220 * t1 * 0.35)
        g = Math.round(g * (1 - t1 * 0.35) + 120 * t1 * 0.35)
        b = Math.round(b * (1 - t1 * 0.35) + 0)
      }

      row.push(
        Math.min(255, r),
        Math.min(255, g),
        Math.min(255, b),
        alpha
      )
    }
    rows.push(Buffer.from(row))
  }

  const raw = Buffer.concat(rows)
  const compressed = deflateSync(raw, { level: 9 })
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
  return Buffer.concat([sig, chunk('IHDR', ihdr), chunk('IDAT', compressed), chunk('IEND', Buffer.alloc(0))])
}

for (const size of [16, 48, 128]) {
  writeFileSync(new URL(`./icon${size}.png`, import.meta.url), makePng(size))
  console.log(`icon${size}.png 생성 완료 (${size}x${size} RGBA)`)
}
console.log('완료!')
