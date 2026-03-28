// 무신사 마이페이지에서 잔액 읽어서 백그라운드로 전송
;(async () => {
  // 페이지 렌더링 대기 (React SPA)
  await new Promise(r => setTimeout(r, 4000))

  const text = document.body?.innerText || ''
  if (!text || text.length < 100) {
    console.log('[삼바웨이브] 페이지 내용 없음, 건너뜀')
    return
  }

  // 적립금 파싱
  let mileage = 0
  const mileageMatch = text.match(/적립금[\s\S]{0,30}?([\d,]+)\s*원/)
  if (mileageMatch) {
    mileage = parseInt(mileageMatch[1].replace(/,/g, ''), 10)
  }

  // 무신사머니 파싱 — "충전하기"면 0원
  let money = 0
  const moneySection = text.match(/무신사머니([\s\S]{0,30})/)
  if (moneySection && !moneySection[1].includes('충전')) {
    const moneyMatch = moneySection[1].match(/([\d,]+)\s*원/)
    if (moneyMatch) {
      money = parseInt(moneyMatch[1].replace(/,/g, ''), 10)
    }
  }

  // 유저명 파싱 (마이페이지 상단 "홍길동1 >" 형태)
  let username = ''
  // 방법1: "마이" 아래 첫 번째 링크 텍스트
  const profileLinks = document.querySelectorAll('a[href*="/my"], a[href*="/member"]')
  for (const el of profileLinks) {
    const t = el.textContent.trim().replace(/\s*>.*/, '')
    if (t && t.length >= 2 && t.length <= 20 && !t.includes('마이') && !t.includes('로그')) {
      username = t
      break
    }
  }
  // 방법2: innerText에서 "마이\n홍길동" 패턴
  if (!username) {
    const nameMatch = text.match(/마이\s*\n\s*(.{2,20}?)\s*>/)
    if (nameMatch) username = nameMatch[1].trim()
  }

  console.log(`[삼바웨이브] 무신사 잔액: 머니 ${money.toLocaleString()} / 적립금 ${mileage.toLocaleString()} / 유저: ${username}`)

  // 백그라운드로 전송 — background.js가 쿠키 + 아이디 매칭 처리
  chrome.runtime.sendMessage({
    action: 'musinsaBalance',
    money,
    mileage,
    username,
  })
})()
