// 삼바 주문도우미 — 설정/셀렉터 (한 곳에서 관리, 무신사 UI 변경 시 여기만 수정)
// content script(ISOLATED)와 공유되도록 globalThis 에 올린다.
globalThis.OH_CONFIG = {
  // 무신사 셀렉터
  sel: {
    optionTrigger: '[data-button-id="option_type"]',      // 옵션(사이즈) 드롭다운 열기
    optionValue: '[data-button-id="select_optionvalue"]',  // 사이즈 항목들
    buyButton: '[data-button-id="2depth_buy_btn"]',        // 구매하기
    // 주소 폼 (Vue) — 실제 입력은 MAIN world 주입으로 처리
    addrSaveButton: '.page-button button',                  // 저장하기
    addrListItemInfo: '.order-address-item__information',    // 목록 항목
    addrListChangeButton: '.page-button button',            // 변경하기
    addrAddLink: 'a.order-address-item__add',               // 배송지 추가하기
  },
  // 결제완료 결과 페이지 URL 패턴
  resultUrlRe: /\/order\/result\/(\d+)/,
  // 삼바 백엔드 (writeback) — 추후 연결
  sambaApiBase: '',   // 예: https://samba-wave-api-...run.app
};
