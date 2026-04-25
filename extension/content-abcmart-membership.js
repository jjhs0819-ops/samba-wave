// ABCmart/GrandStage 멤버십 등급 + 로그인 쿠키 자동 동기화
// - 로그인 페이지 방문 시 1회 등급/쿠키 감지 → 백엔드 전송
// - 비로그인 감지 시 expired=true로 알림 (서버가 만료 마킹)
;(function () {
  let detectedRate = 0
  let detectedGrade = ''
  let isLoggedIn = false

  const scripts = document.querySelectorAll('script')
  for (const s of scripts) {
    const text = s.textContent
    if (!text.includes('abc.userDetails')) continue

    const rateMatch = text.match(/alwaysDisCntRate\s*:\s*'(\d+(?:\.\d+)?)'/)
    const gradeMatch = text.match(/mbshpGradeName\s*:\s*'([^']*)'/)
    const loginMatch = text.match(/loginYn\s*:\s*'(\w+)'/)

    isLoggedIn = !!(loginMatch && loginMatch[1] === 'true')
    detectedRate = parseFloat(rateMatch?.[1] || '0')
    detectedGrade = gradeMatch?.[1] || ''
    break
  }

  if (isLoggedIn) {
    // 이전 저장값(등급)과 동일하면 등급 sync는 스킵, 단 쿠키는 매번 갱신
    chrome.storage.local.get(['abcmart_membership_rate', 'abcmart_cookie_synced_at'], (stored) => {
      const rateChanged = stored.abcmart_membership_rate !== detectedRate
      const lastSyncTs = stored.abcmart_cookie_synced_at || 0
      // 쿠키는 1시간마다 재sync (만료 방어)
      const cookieStale = Date.now() - lastSyncTs > 60 * 60 * 1000

      if (!rateChanged && !cookieStale) return

      chrome.runtime.sendMessage({
        action: 'abcmartMembership',
        membershipRate: detectedRate,
        membershipGrade: detectedGrade,
        needsCookie: true,
        expired: false,
      })
    })
  } else {
    // 비로그인 감지 → 서버에 만료 알림 (이미 만료 표시됐으면 중복 무해)
    chrome.runtime.sendMessage({
      action: 'abcmartMembership',
      membershipRate: 0,
      membershipGrade: '',
      needsCookie: false,
      expired: true,
    })
  }
})()
