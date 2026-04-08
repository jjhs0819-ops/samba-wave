// ABCmart/GrandStage 멤버십 등급 자동 감지 — 로그인 시 한 번 감지 → 백엔드 전송
;(function () {
  const scripts = document.querySelectorAll('script')
  for (const s of scripts) {
    const text = s.textContent
    if (!text.includes('abc.userDetails')) continue

    const rateMatch = text.match(/alwaysDisCntRate\s*:\s*'(\d+(?:\.\d+)?)'/)
    const gradeMatch = text.match(/mbshpGradeName\s*:\s*'([^']*)'/)
    const loginMatch = text.match(/loginYn\s*:\s*'(\w+)'/)

    if (loginMatch && loginMatch[1] === 'true') {
      const rate = parseFloat(rateMatch?.[1] || '0')
      const grade = gradeMatch?.[1] || ''

      if (rate > 0 && grade) {
        // 이전 저장값과 같으면 스킵
        chrome.storage.local.get('abcmart_membership_rate', (stored) => {
          if (stored.abcmart_membership_rate === rate) return
          chrome.runtime.sendMessage({
            action: 'abcmartMembership',
            membershipRate: rate,
            membershipGrade: grade,
          })
        })
      }
    }
    break
  }
})()
