// 팝업 초기화 — 버전 정보만 표시
document.addEventListener('DOMContentLoaded', () => {
  const ver = chrome.runtime.getManifest().version
  document.getElementById('version').textContent = `v${ver}`
})
