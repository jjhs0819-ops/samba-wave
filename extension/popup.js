// 팝업 초기화
document.addEventListener('DOMContentLoaded', async () => {
  // 버전
  const ver = chrome.runtime.getManifest().version
  document.getElementById('version').textContent = `v${ver}`

  // background에서 상태 조회
  chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (res) => {
    if (!res) return

    // 무신사
    const mDot = document.getElementById('musinsa-dot')
    const mStatus = document.getElementById('musinsa-status')
    if (res.musinsa?.isLoggedIn) {
      mDot.classList.add('on')
      mStatus.textContent = `쿠키 ${res.musinsa.cookieCount}개`
    } else {
      mDot.classList.add('off')
      mStatus.textContent = '미연결'
    }

    // KREAM
    const kDot = document.getElementById('kream-dot')
    const kAction = document.getElementById('kream-action')
    if (res.kream?.isLoggedIn) {
      kDot.classList.add('on')
      kAction.innerHTML = `<span class="status-label">쿠키 ${res.kream.cookieCount}개</span>`
    } else {
      kDot.classList.add('off')
      kAction.innerHTML = '<button class="login-btn" id="kream-login-btn">로그인</button>'
      document.getElementById('kream-login-btn')?.addEventListener('click', () => {
        chrome.runtime.sendMessage({ type: 'KREAM_OPEN_LOGIN' })
      })
    }
  })

  // Proxy 연결 확인
  const pDot = document.getElementById('proxy-dot')
  const pStatus = document.getElementById('proxy-status')
  try {
    const res = await fetch('http://localhost:3001/api/health')
    if (res.ok) {
      pDot.classList.add('on')
      pStatus.textContent = '연결됨'
    } else throw new Error()
  } catch {
    pDot.classList.add('off')
    pStatus.textContent = '미연결'
  }
})
