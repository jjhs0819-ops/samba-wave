// SSG 백화점관(department.ssg.com) — alert/confirm 모달 무력화.
// 임직원/사업자 회원 전용 상품 진입 시 alert("임직원 및 사업자 회원만 구매 가능…")로
// 페이지 처리가 멈춰 가격/재고 추출이 실패하고 다른 상품 처리도 정체되는 문제 차단.
// document_start + world:MAIN으로 inline 스크립트 실행 직전에 주입되어 모달 자체를 막음.
;(function () {
  try {
    const _origAlert = window.alert
    window.alert = function (msg) {
      try {
        console.log('[SSG] alert suppressed:', msg)
      } catch {}
    }
    // confirm 은 false 리턴 — true 리턴 시 임직원 전용 페이지의 inline script 가
    // location.href 로 로그인 페이지로 리다이렉트되어 staffOnly 마커가 사라지고,
    // 백엔드/폴링이 임직원 전용 상품을 감지하지 못해 "확장앱 미응답 또는 파싱 실패" 로 기록됨.
    window.confirm = function () {
      return false
    }
    window.prompt = function () {
      return null
    }
    // history.back 도 무력화 — confirm=false 분기에서 history.back() 이 호출되면
    // 페이지를 이탈하여 staffOnly HTML 마커("임직원 및 사업자 회원")가 사라짐.
    // 페이지를 그대로 유지해야 폴링/preCheck 가 staffOnly 신호를 잡고 sold_out 처리됨.
    try {
      history.back = function () {}
      history.go = function () {}
    } catch {}
    // beforeunload는 살려둠 (탭 닫기 정상 동작)
  } catch (e) {
    // noop
  }
})()
