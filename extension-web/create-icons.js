// 아이콘 생성 스크립트 (node로 실행)
// node create-icons.js
import { createCanvas } from 'canvas'
import { writeFileSync } from 'fs'

function createIcon(size) {
  const canvas = createCanvas(size, size)
  const ctx = canvas.getContext('2d')

  // 배경
  const grad = ctx.createLinearGradient(0, 0, size, size)
  grad.addColorStop(0, '#FF8C00')
  grad.addColorStop(1, '#FFB84D')
  ctx.fillStyle = grad
  ctx.roundRect(0, 0, size, size, size * 0.2)
  ctx.fill()

  // 텍스트 S
  ctx.fillStyle = '#000'
  ctx.font = `bold ${size * 0.55}px Arial`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('S', size / 2, size / 2)

  return canvas.toBuffer('image/png')
}

for (const size of [16, 48, 128]) {
  writeFileSync(`icon${size}.png`, createIcon(size))
  console.log(`icon${size}.png 생성 완료`)
}
