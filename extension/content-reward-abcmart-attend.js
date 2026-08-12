// content-reward-abcmart-attend.js
// ABC마트(ABC-CAMP) 출석체크 자동 수행
//
// [2026-08-12] 화면이 ABC-CAMP 로 바뀌면서 방식이 달라졌다.
//   예전: POST /rest/attend 한 방이면 출석 인정
//   지금: 출석체크 화면(member.a-rt.com/p/attendance-check)의 타임라인에서
//         **'출석하기' 버튼을 실제로 눌러야** 인정된다.
// 그래서 API 만 던지던 예전 코드는 아무것도 안 하고 '완료' 로 보고했다.
// 이제는 버튼을 누르고, '이번달 출석 N회' 가 늘었는지 확인해야 성공으로 본다.
;(async () => {
  if (window.__sambaRewardAbcAttendSent__) return
  window.__sambaRewardAbcAttendSent__ = true

  function send(extra) {
    return chrome.runtime.sendMessage({
      type: 'REWARD_RESULT',
      rewardAction: 'abcmart_attendance',
      ...extra,
    }).catch(() => {})
  }

  function log(msg) {
    console.log('[적립금-ABC마트출석]', msg)
  }

  const sleep = ms => new Promise(r => setTimeout(r, ms))

  async function waitUntil(fn, timeout = 10000, step = 400) {
    const end = Date.now() + timeout
    while (Date.now() < end) {
      try { const v = fn(); if (v) return v } catch (_) {}
      await sleep(step)
    }
    return null
  }

  // 합성 click() 을 무시하는 위젯이 있어 실제 마우스처럼 좌표를 실어 보낸다.
  function realClick(el) {
    if (!el) return false
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height) return false
    const opt = {
      bubbles: true, cancelable: true, composed: true, button: 0,
      clientX: r.left + r.width / 2, clientY: r.top + r.height / 2,
    }
    for (const type of ['pointerover', 'pointermove', 'pointerdown', 'mousedown',
                        'pointerup', 'mouseup', 'click']) {
      const Ctor = type.startsWith('pointer') ? PointerEvent : MouseEvent
      try { el.dispatchEvent(new Ctor(type, opt)) } catch (_) {
        el.dispatchEvent(new MouseEvent(type.replace('pointer', 'mouse'), opt))
      }
    }
    try { el.click() } catch (_) {}
    return true
  }

  // '이번달 출석 4회' — 출석이 실제로 됐는지 판정하는 기준.
  function attendCount() {
    const m = (document.body.innerText || '').match(/이번달\s*출석\s*(\d+)\s*회/)
    return m ? Number(m[1]) : null
  }

  // '출석하기' 는 버튼이 아닐 수 있어(툴팁/뱃지) 글자로 찾아 올라간다.
  function findAttendButton() {
    const nodes = Array.from(document.querySelectorAll('button, a, span, div, p'))
      .filter(el => {
        const t = (el.textContent || '').trim()
        return t === '출석하기' && el.offsetParent !== null
      })
    if (!nodes.length) return null
    // 가장 안쪽(글자만 든) 요소를 고른다 — 큰 컨테이너를 누르면 안 먹는다.
    return nodes.sort((a, b) => a.textContent.length - b.textContent.length)[0]
  }

  await sleep(2000)
  log('ABC-CAMP 출석체크 페이지 진입')

  try {
    const body = document.body.innerText || ''
    if (/로그인/.test(body) && /아이디|비밀번호/.test(body)) {
      log('로그인이 필요합니다')
      send({ success: false, error: '로그인 필요' })
      return
    }

    const before = attendCount()
    let btn = findAttendButton()
    if (!btn) {
      // 버튼이 늦게 그려질 수 있다.
      btn = await waitUntil(findAttendButton, 6000)
    }

    if (!btn) {
      // 오늘 이미 했으면 '출석하기' 가 사라진다 — 출석 횟수가 읽히면 완료로 본다.
      if (before !== null && before > 0) {
        log(`오늘 이미 출석 완료 (이번달 ${before}회)`)
        send({ success: true, alreadyDone: true, stampCount: before, stampScore: 0 })
      } else {
        log('출석하기 버튼을 찾지 못했습니다')
        send({ success: false, error: '출석하기 버튼 없음' })
      }
      return
    }

    btn.scrollIntoView({ behavior: 'instant', block: 'center' })
    await sleep(600)
    realClick(btn)
    log(`'출석하기' 클릭 (클릭 전 이번달 ${before ?? '?'}회)`)

    // 확인 팝업이 뜨면 눌러준다.
    const confirmBtn = await waitUntil(() => {
      return Array.from(document.querySelectorAll('button, a'))
        .find(b => ['확인', '출석하기', '닫기'].includes((b.textContent || '').trim())
                   && b.offsetParent !== null && b !== btn)
    }, 3000)
    if (confirmBtn) { await sleep(500); realClick(confirmBtn) }

    // 실제로 늘었는지 확인 — 이게 없으면 안 눌려도 '완료' 가 된다.
    const ok = await waitUntil(() => {
      const now = attendCount()
      if (before === null) return now !== null && now > 0
      return now !== null && now > before
    }, 10000)

    if (ok) {
      const now = attendCount()
      log(`✓ 출석 완료 (이번달 ${now}회)`)
      send({ success: true, alreadyDone: false, stampCount: now ?? 0, stampScore: 0 })
      return
    }

    // 숫자가 안 늘었는데 버튼이 사라졌으면 화면 갱신이 늦는 것일 수 있다.
    if (!findAttendButton()) {
      log('출석 버튼은 사라졌으나 횟수 확인 실패 — 미확정으로 보고')
      send({ success: false, error: '출석 확인 안 됨(버튼은 사라짐)' })
    } else {
      log('출석하기 클릭이 반영되지 않음')
      send({ success: false, error: '출석 클릭 반영 안 됨' })
    }
  } catch (e) {
    log(`오류: ${e.message}`)
    send({ success: false, error: e.message })
  }
})()
