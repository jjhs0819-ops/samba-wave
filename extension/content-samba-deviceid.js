// 삼바 프론트엔드 페이지에 확장앱 deviceId를 전달한다.
// 프론트엔드(layout.tsx)의 attachDeviceIdListener가 window.message 이벤트로 수신하여
// sessionStorage에 저장하고, 오토튠 시작 시 백엔드로 전송한다.
// 이 deviceId를 가진 확장앱만 collect-queue에서 오토튠 작업을 받아가므로,
// 동일 계정으로 접속한 다른 PC의 브라우저에서는 탭이 열리지 않는다.
(function () {
  function sendDeviceId(deviceId) {
    if (!deviceId) return
    try {
      window.postMessage(
        { source: 'samba-extension', type: 'DEVICE_ID', deviceId },
        window.location.origin,
      )
    } catch {
      // cross-origin 등의 이유로 실패하면 조용히 무시
    }
  }

  // content_script는 chrome.storage.local 접근 가능
  chrome.storage.local.get('deviceId', (data) => {
    if (data && data.deviceId) {
      sendDeviceId(data.deviceId)
      // 페이지가 이후에 mount되는 React 컴포넌트에서도 받을 수 있도록 재전송 스케줄
      setTimeout(() => sendDeviceId(data.deviceId), 500)
      setTimeout(() => sendDeviceId(data.deviceId), 2000)
    } else {
      // 최초 설치 직후 background가 아직 deviceId를 만들지 않은 경우 대비
      // 서비스워커에 요청
      chrome.runtime.sendMessage({ type: 'GET_DEVICE_ID' }, (resp) => {
        if (resp && resp.deviceId) sendDeviceId(resp.deviceId)
      })
    }
  })
})()
