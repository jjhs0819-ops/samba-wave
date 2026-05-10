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
    window.confirm = function () {
      return true
    }
    window.prompt = function () {
      return null
    }
    // beforeunload는 살려둠 (탭 닫기 정상 동작)
  } catch (e) {
    // noop
  }
})()
