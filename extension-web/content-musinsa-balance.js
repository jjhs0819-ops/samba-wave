// 무신사 마이페이지에서 잔액 읽어서 백그라운드로 전송 (1회만)
;(async () => {
  // 중복 실행 방지
  if (window.__sambaBalanceSent__) return
  window.__sambaBalanceSent__ = true

  // 로그인 페이지로 리다이렉트된 경우 → 쿠키 만료
  await new Promise(r => setTimeout(r, 2000))
  if (location.href.includes('login') || location.href.includes('member.one.musinsa')) {
    console.log('[삼바웨이브] 로그인 페이지 감지 → 쿠키 만료')
    chrome.runtime.sendMessage({ action: 'musinsaBalance', money: -1, mileage: -1, username: '', expired: true })
    return
  }

  // 페이지 렌더링 충분히 대기 (React SPA)
  await new Promise(r => setTimeout(r, 3000))

  // 적립금 + 무신사머니 둘 다 나올 때까지 최대 10초 추가 대기
  let text = ''
  let mileage = 0
  let money = 0
  for (let i = 0; i < 5; i++) {
    text = document.body?.innerText || ''

    // 적립금 파싱
    mileage = 0
    const mileageIdx = text.indexOf('적립금')
    if (mileageIdx !== -1) {
      const after = text.substring(mileageIdx + 3, mileageIdx + 103)
      if (!after.trim().startsWith('가능')) {
        const m = after.match(/([\d,]+)\s*원/)
        if (m) mileage = parseInt(m[1].replace(/,/g, ''), 10)
      }
    }

    // 무신사머니 파싱
    money = 0
    const moneyIdx = text.indexOf('무신사머니')
    if (moneyIdx !== -1) {
      const after = text.substring(moneyIdx + 5, moneyIdx + 105)
      if (!after.substring(0, 20).includes('충전하기')) {
        const m = after.match(/([\d,]+)\s*원/)
        if (m) money = parseInt(m[1].replace(/,/g, ''), 10)
      }
    }

    // 둘 다 값이 있으면 전송
    if (mileage > 0 || money > 0) break
    await new Promise(r => setTimeout(r, 2000))
  }

  // 유저명 파싱
  let username = ''
  const profileLinks = document.querySelectorAll('a[href*="/my"], a[href*="/member"]')
  for (const el of profileLinks) {
    const t = el.textContent.trim().replace(/\s*>.*/, '')
    if (t && t.length >= 2 && t.length <= 20 && !t.includes('마이') && !t.includes('로그')) {
      username = t
      break
    }
  }
  if (!username) {
    const nameMatch = text.match(/마이\s*\n\s*(.{2,20}?)\s*>/)
    if (nameMatch) username = nameMatch[1].trim()
  }

  console.log(`[삼바웨이브] 결과: 머니 ${money.toLocaleString()} / 적립금 ${mileage.toLocaleString()} / 유저: ${username}`)

  chrome.runtime.sendMessage({
    action: 'musinsaBalance',
    money,
    mileage,
    username,
  })
})()
