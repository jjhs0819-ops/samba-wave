"""카카오톡 나에게 보내기 알림 유틸."""

import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

_KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
_KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


async def _get_access_token(api_key: str, refresh_token: str) -> str | None:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            _KAKAO_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": api_key,
                "refresh_token": refresh_token,
            },
        ) as resp:
            data = await resp.json()
            return data.get("access_token")


async def send_kakao_message(text: str) -> None:
    api_key = os.environ.get("KAKAO_API_KEY", "")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN", "")
    if not api_key or not refresh_token:
        logger.debug("[카카오알림] 환경변수 미설정, 스킵")
        return

    try:
        access_token = await _get_access_token(api_key, refresh_token)
        if not access_token:
            logger.warning("[카카오알림] access_token 발급 실패")
            return

        import json

        template = json.dumps({"object_type": "text", "text": text, "link": {}})
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _KAKAO_MEMO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                data={"template_object": template},
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.warning(
                        "[카카오알림] 전송 실패 status=%s body=%s", resp.status, body
                    )
    except Exception as exc:
        logger.warning("[카카오알림] 예외 발생: %s", exc)
