// 삼바 주문도우미 — 삼바 페이지 MAIN world 훅 (페이지 컨텍스트)
// window.open 을 가로채 원문링크의 source_url 을 캡처한다.
// (manifest content_script world:MAIN 으로 로드되어 페이지 CSP 영향 없음)
(function () {
  if (window.__ohOpenHooked) return;
  window.__ohOpenHooked = true;
  const orig = window.open.bind(window);

  // ISOLATED content script가 원문링크 클릭을 감지하면 OH_ARM 을 쏜다 → 무장
  window.addEventListener('OH_ARM', () => { window.__ohArmed = true; });

  window.open = function (url, ...rest) {
    try {
      if (window.__ohArmed && url) {
        window.__ohArmed = false;
        // source_url 을 ISOLATED 쪽으로 전달하고 원래 open 은 억제(배경이 탭 오픈)
        window.dispatchEvent(new CustomEvent('OH_TRIGGER', { detail: { url: String(url) } }));
        return null;
      }
    } catch (e) { /* noop */ }
    return orig(url, ...rest);
  };
})();
