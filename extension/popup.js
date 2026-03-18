// 팝업 초기화
document.addEventListener('DOMContentLoaded', () => {
  // 버전 표시
  const ver = chrome.runtime.getManifest().version
  document.getElementById('version').textContent = `v${ver}`
})
