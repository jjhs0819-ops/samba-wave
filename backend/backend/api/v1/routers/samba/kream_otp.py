"""크림 판매자센터 로그인 OTP 수신 API [2026-08-28].

크림은 refresh 토큰을 회전해주지 않아(수명 24h) 하루 한 번 재로그인이 강제된다.
로그인에는 휴대폰 문자 OTP 가 매번 필요하고, 인증 수단을 메일로 바꾸는 API 도
없다(파트너센터 번들 확인: /user/me, /user/me/password 뿐).

그래서 폰이 **6자리만** 넘겨주는 경로를 둔다. 폰에는 아이디·비밀번호를 두지 않는다.
  폰(MacroDroid/Tasker) — 크림 발신 문자 수신
    → POST /internal/kream/otp  { group, text }
  토큰 갱신 스크립트(_kream_token_refresh.py)
    → POST /auth/login → 문자 발송 → 여기서 코드 폴링 → POST /auth/login/otp

samba_auth(JWT) 를 우회하므로 X-Internal-Token 이 유일 방어선이다.
app_factory 에서 samba_auth 없이 등록한다.

엔드포인트:
  POST /internal/kream/otp        폰이 받은 문자 적재(원문 그대로 보내도 된다)
  GET  /internal/kream/otp/{grp}  스크립트가 최근 코드 조회(기본 3분 이내)
"""

from __future__ import annotations

import json
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import text as sa_text
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.core.config import settings
from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.utils.logger import logger

router = APIRouter(prefix="/internal/kream", tags=["samba-kream-otp"])

# 설정 키 — 그룹별로 따로 담는다(계정이 둘이고 폰도 둘이다)
_KEY = "kream_login_otp"
# 코드 유효시간. 크림 OTP 자체가 짧고, 오래된 코드를 쓰면 로그인이 깨진다.
_TTL_SEC = 180
# 문자에서 6자리를 뽑는다. 앞뒤 숫자에 붙은 값은 제외(전화번호·금액 오인 방지).
_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


async def _require_internal_token(
    x_internal_token: Optional[str] = Header(default=None),
) -> None:
    """X-Internal-Token 검증. 토큰 미설정(빈 값)이면 전체 차단."""
    expected = settings.cs_internal_token
    if not expected:
        raise HTTPException(status_code=503, detail="내부 API 비활성(토큰 미설정)")
    if x_internal_token != expected:
        raise HTTPException(status_code=401, detail="유효하지 않은 내부 토큰")


_GROUP_RE = re.compile(r'"?group"?\s*[:=]\s*"?([A-Za-z]{2,6})"?')


def _parse_raw(raw: str) -> tuple[str, str]:
    """본문에서 (그룹, 코드)를 뽑는다 — **JSON 이 깨져 있어도** 동작한다.

    [2026-08-28] 폰(MacroDroid)이 보내는 본문은
      {"group":"CN","text":"{sms_message}"}
    인데, 실제 문자에는 줄바꿈과 따옴표가 들어 있어 그대로 박히면 JSON 문법이
    깨진다. 그래서 FastAPI 모델 검증이 422 로 떨어졌다(실측: 문자 수신 3건 전부
    422, 변수가 빈 테스트만 200). 폰 규칙을 고치게 하는 대신 서버가 흡수한다.
    정상 JSON 이면 그대로 읽고, 아니면 원문 전체에서 정규식으로 찾는다.
    """
    grp, txt = "", raw
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            grp = str(d.get("group") or "")
            txt = str(d.get("text") or d.get("code") or "")
            if str(d.get("code") or "").strip().isdigit():
                return grp, str(d["code"]).strip()
    except Exception:
        m = _GROUP_RE.search(raw)
        grp = m.group(1) if m else ""
    m2 = _CODE_RE.search(txt)
    return grp, (m2.group(1) if m2 else "")


@router.post("/otp", dependencies=[Depends(_require_internal_token)])
async def receive_otp(
    request: Request,
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict:
    """폰이 받은 크림 로그인 문자를 적재한다. 원문을 그대로 보내도 된다.

    본문은 모델로 검증하지 않고 **원문 그대로** 읽는다 — 문자에 줄바꿈·따옴표가
    있어도 422 로 떨어지지 않게 하기 위해서다(_parse_raw 참조).
    """
    raw = (await request.body()).decode("utf-8", "replace")
    grp, code = _parse_raw(raw)
    grp = (grp or "JP").upper()
    if not code:
        # 크림 문자가 아니거나 형식이 다르면 조용히 무시한다 — 폰 규칙이 넓게
        # 걸려 있어도 서버가 걸러주는 편이 안전하다.
        return {"ok": False, "reason": "6자리 코드 없음"}
    payload = json.dumps({"code": code, "ts": time.time()})
    await session.execute(
        sa_text(
            "INSERT INTO samba_settings (key, value, updated_at) "
            "VALUES (:k, CAST(:v AS json), NOW()) "
            "ON CONFLICT (key) DO UPDATE "
            "SET value = EXCLUDED.value, updated_at = NOW()"
        ),
        [
            {"k": f"{_KEY}:{grp}", "v": payload},
            # [2026-08-28] 그룹 공용 자리에도 같이 넣는다. 폰 규칙에 group 을 잘못
            # 박아도(중국 폰에 JP 등) 로그인이 막히지 않게 하려는 것이다.
            # 두 계정이 동시에 로그인하는 일은 없고, 조회는 '로그인 요청 이후
            # 도착분'만 인정하므로 남의 코드를 집어 쓸 위험도 없다.
            {"k": f"{_KEY}:ANY", "v": payload},
        ],
    )
    await session.commit()
    logger.info("[크림OTP][%s] 코드 수신", grp)
    return {"ok": True, "group": grp}


@router.get("/otp/{group}", dependencies=[Depends(_require_internal_token)])
async def read_otp(
    group: str,
    max_age: int = _TTL_SEC,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict:
    """최근 코드 조회. max_age 초를 넘긴 코드는 없는 것으로 본다.

    [2026-08-28] 그룹 자리에 쓸 만한 코드가 없으면 **공용 자리(ANY)** 를 본다.
    폰 규칙에 group 을 잘못 박아도 로그인이 막히지 않게 하려는 것이다.
    """
    grp = (group or "JP").upper()

    def _pick(raw: str | None) -> tuple[str, int] | None:
        """(코드, 나이) — 없거나 만료면 None."""
        if not raw:
            return None
        try:
            d = json.loads(raw)
        except Exception:
            return None
        code = str(d.get("code") or "")
        if not code:
            return None
        age = int(time.time() - float(d.get("ts") or 0))
        return (code, age) if age <= max(1, int(max_age)) else None

    rows = {
        str(k): v
        for k, v in (
            await session.execute(
                sa_text(
                    "SELECT key, value::text FROM samba_settings WHERE key = ANY(:ks)"
                ),
                {"ks": [f"{_KEY}:{grp}", f"{_KEY}:ANY"]},
            )
        ).all()
    }
    for key in (f"{_KEY}:{grp}", f"{_KEY}:ANY"):
        got = _pick(rows.get(key))
        if got:
            return {
                "ok": True,
                "code": got[0],
                "age_sec": got[1],
                "via": "그룹" if key.endswith(grp) else "공용",
            }
    return {"ok": False, "reason": "쓸 수 있는 코드 없음"}
