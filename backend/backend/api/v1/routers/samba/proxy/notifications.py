"""알리고 SMS/카카오 알림 관련 엔드포인트."""

from __future__ import annotations

from typing import Any, Optional

import json
import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.message_log.model import MessageLog
from backend.domain.samba.message_log.repository import MessageLogRepository
from backend.domain.samba.tenant.middleware import get_optional_tenant_id
from backend.utils.logger import logger

from ._helpers import _get_setting

router = APIRouter(tags=["samba-proxy"])


def _parse_aligo_response(resp: httpx.Response, context: str) -> dict[str, Any]:
    """알리고 응답을 안전하게 파싱.

    알리고 API 서버(apis.aligo.in)가 장애 시 HTTP 5xx + 빈 본문(text/html)을
    반환하는데, 이를 그대로 resp.json() 하면 'Expecting value: line 1 column 1'
    이라는 정체불명 에러가 노출됨. status·본문을 먼저 확인해 명확한 메시지로 변환.
    """
    body_snippet = resp.text[:300]
    # 비2xx → 알리고측 장애로 간주
    if resp.status_code >= 400:
        logger.error(
            f"[알리고] {context} HTTP {resp.status_code} "
            f"(len={len(resp.text)}, body={body_snippet!r})"
        )
        raise ValueError(
            f"알리고 SMS 서버 오류(HTTP {resp.status_code}). "
            f"알리고측 일시 장애로 보입니다. 잠시 후 다시 시도해주세요."
        )
    # 2xx 이지만 본문이 비었거나 JSON 아님
    try:
        return resp.json()
    except Exception:
        logger.error(
            f"[알리고] {context} 비JSON 응답 "
            f"(status={resp.status_code}, len={len(resp.text)}, body={body_snippet!r})"
        )
        raise ValueError(
            "알리고 응답을 해석할 수 없습니다(빈/비JSON 응답). "
            "알리고측 장애 가능성이 있으니 잠시 후 다시 시도해주세요."
        )


# ═══════════════════════════════════════════════
# 알리고 (Aligo) SMS 잔여건수 조회
# ═══════════════════════════════════════════════


@router.post("/aligo/remain")
async def aligo_remain(
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> dict[str, Any]:
    """알리고 SMS 잔여건수 조회."""
    creds = await _get_setting(session, "aligo_sms", tenant_id)
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "SMS 설정이 저장되지 않았습니다."}

    api_key = creds.get("apiKey", "")
    user_id = creds.get("userId", "")
    if not api_key or not user_id:
        return {"success": False, "message": "API Key 또는 Identifier가 비어있습니다."}

    try:
        async with httpx.AsyncClient(timeout=15, verify=True) as client:
            resp = await client.post(
                "https://apis.aligo.in/remain/",
                data={"key": api_key, "user_id": user_id},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            data = _parse_aligo_response(resp, "잔여건수 조회")
            if data.get("result_code") == 1 or str(data.get("result_code")) == "1":
                return {
                    "success": True,
                    "message": "인증 성공",
                    "SMS_CNT": data.get("SMS_CNT", 0),
                    "LMS_CNT": data.get("LMS_CNT", 0),
                    "MMS_CNT": data.get("MMS_CNT", 0),
                }
            else:
                return {
                    "success": False,
                    "message": data.get("message", "알리고 API 인증 실패"),
                }
    except ValueError as exc:
        # _parse_aligo_response가 이미 명확한 메시지 + 로깅 완료
        return {"success": False, "message": str(exc)}
    except Exception as exc:
        logger.error(f"[알리고] 잔여건수 조회 실패: {exc}")
        return {"success": False, "message": f"알리고 API 호출 실패: {exc}"}


# ═══════════════════════════════════════════════
# 알리고 SMS 발송
# ═══════════════════════════════════════════════


class SmsRequest(BaseModel):
    receiver: str
    message: str
    title: str = ""
    order_id: Optional[str] = None
    template_raw: Optional[str] = None


@router.post("/aligo/send-sms")
async def aligo_send_sms(
    body: SmsRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> dict[str, Any]:
    """알리고 SMS/LMS 발송."""
    creds = await _get_setting(session, "aligo_sms", tenant_id)
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "SMS 설정이 저장되지 않았습니다."}

    api_key = creds.get("apiKey", "")
    user_id = creds.get("userId", "")
    sender = creds.get("sender", "")
    if not api_key or not user_id or not sender:
        return {
            "success": False,
            "message": "SMS 설정이 불완전합니다 (apiKey/userId/sender 필요).",
        }

    msg_bytes = len(body.message.encode("euc-kr", errors="replace"))
    is_lms = msg_bytes > 90

    data = {
        "key": api_key,
        "user_id": user_id,
        "sender": sender,
        "receiver": body.receiver.replace("-", ""),
        "msg": body.message,
    }
    if is_lms and body.title:
        data["title"] = body.title

    url = "https://apis.aligo.in/send/"
    success = False
    msg_id = None
    result_msg = ""

    try:
        async with httpx.AsyncClient(timeout=15, verify=True) as client:
            resp = await client.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            result = _parse_aligo_response(resp, "SMS 발송")
            if result.get("result_code") == 1 or str(result.get("result_code")) == "1":
                success = True
                msg_id = str(result.get("msg_id", ""))
                result_msg = f"{'LMS' if is_lms else 'SMS'} 발송 성공"
            else:
                result_msg = result.get("message", "발송 실패")
    except ValueError as exc:
        # _parse_aligo_response가 이미 명확한 메시지 + 로깅 완료
        result_msg = str(exc)
    except Exception as exc:
        logger.error(f"[알리고] SMS 발송 실패: {exc}")
        result_msg = f"SMS 발송 실패: {exc}"

    # 발송 이력 저장 (성공/실패 모두)
    try:
        repo = MessageLogRepository(session)
        await repo.create(
            MessageLog(
                tenant_id=tenant_id,
                order_id=body.order_id,
                customer_phone=body.receiver,
                message_type="sms",
                template_raw=body.template_raw,
                rendered_message=body.message,
                receiver=body.receiver.replace("-", ""),
                success=success,
                result_message=result_msg,
                msg_id=msg_id,
            )
        )
    except Exception as exc:
        logger.error(f"[알리고] SMS 이력 저장 실패: {exc}")

    if success:
        return {
            "success": True,
            "message": result_msg,
            "msg_id": msg_id,
            "msg_type": "LMS" if is_lms else "SMS",
        }
    return {"success": False, "message": result_msg}


# ═══════════════════════════════════════════════
# 알리고 카카오 알림톡 발송
# ═══════════════════════════════════════════════


class KakaoRequest(BaseModel):
    receiver: str
    message: str
    template_code: str = ""
    subject: str = ""
    order_id: Optional[str] = None
    template_raw: Optional[str] = None


@router.post("/aligo/send-kakao")
async def aligo_send_kakao(
    body: KakaoRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
) -> dict[str, Any]:
    """알리고 카카오 알림톡/친구톡 발송."""
    creds = await _get_setting(session, "aligo_sms", tenant_id)
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "SMS 설정이 저장되지 않았습니다."}

    kakao_creds = await _get_setting(session, "aligo_kakao", tenant_id)

    api_key = creds.get("apiKey", "")
    user_id = creds.get("userId", "")
    sender = creds.get("sender", "")
    sender_key = (
        (kakao_creds or {}).get("senderKey", "")
        if isinstance(kakao_creds, dict)
        else ""
    )

    if not api_key or not user_id:
        return {"success": False, "message": "SMS 설정이 불완전합니다."}
    if not sender_key:
        return {
            "success": False,
            "message": "카카오 발신프로필 키(senderKey)가 설정되지 않았습니다. 설정 페이지에서 등록해주세요.",
        }

    data = {
        "apikey": api_key,
        "userid": user_id,
        "sender": sender,
        "receiver_1": body.receiver.replace("-", ""),
        "message_1": body.message,
        "senderkey": sender_key,
        "tpl_code": body.template_code,
    }
    if body.subject:
        data["subject_1"] = body.subject
    elif not body.template_code:
        _first_line = (
            body.message.strip().splitlines()[0] if body.message.strip() else ""
        )
        data["subject_1"] = _first_line[:40] or "고객 안내"

    url = (
        "https://kakaoapi.aligo.in/akv10/alimtalk/send/"
        if body.template_code
        else "https://kakaoapi.aligo.in/akv10/friend/send/"
    )

    success = False
    result_msg = ""
    _kakao_mid = ""

    try:
        async with httpx.AsyncClient(timeout=15, verify=True) as client:
            token_resp = await client.post(
                "https://kakaoapi.aligo.in/akv10/token/create/30/s",
                data={"apikey": api_key, "userid": user_id},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_result = token_resp.json()
            if str(token_result.get("code")) != "0":
                raise RuntimeError(token_result.get("message", "카카오 토큰 발급 실패"))
            data["token"] = token_result.get("token", "")

            # 알림톡 템플릿에 버튼(채널추가 등)이 있으면 발송 시 button_1로 함께 보내야
            # 카카오가 '템플릿 일치'로 인정해 실제 전송한다. 안 보내면 접수(code=0)는
            # 되지만 카카오가 '메시지가 템플릿과 일치하지않음'으로 최종 전송을 거부한다.
            if body.template_code:
                try:
                    _tmpl = await client.post(
                        "https://kakaoapi.aligo.in/akv10/template/list/",
                        data={
                            "apikey": api_key,
                            "userid": user_id,
                            "token": data["token"],
                            "senderkey": sender_key,
                            "tpl_code": body.template_code,
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    for _t in _tmpl.json().get("list") or []:
                        if str(_t.get("templtCode")) == str(body.template_code):
                            _btns = _t.get("buttons")
                            if _btns:
                                data["button_1"] = json.dumps(
                                    {"button": _btns}, ensure_ascii=False
                                )
                            break
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[알리고] 템플릿 버튼 조회 실패: %s", exc)
                try:
                    _t2 = await client.post(
                        "https://kakaoapi.aligo.in/akv10/token/create/30/s",
                        data={"apikey": api_key, "userid": user_id},
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    _t2j = _t2.json()
                    if str(_t2j.get("code")) == "0" and _t2j.get("token"):
                        data["token"] = _t2j.get("token", "")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[알리고] 발송용 토큰 재발급 실패: %s", exc)

            resp = await client.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            result = _parse_aligo_response(resp, "카카오 발송")
            logger.info(
                "[알리고발송경로] url=%s tpl_code=%r code=%s receiver=%s",
                url,
                body.template_code,
                result.get("code"),
                data.get("receiver_1"),
            )
            if result.get("code") == 0 or str(result.get("code")) == "0":
                success = True
                result_msg = "카카오톡 발송 성공"
                _kakao_mid = str((result.get("info") or {}).get("mid", "") or "")
            else:
                result_msg = result.get("message", "카카오 발송 실패")
                logger.error(
                    "[알리고진단] 발송실패 url=%s tpl=%r userid=%r 응답=%r",
                    url,
                    body.template_code,
                    data.get("userid"),
                    resp.text[:400],
                )
    except ValueError as exc:
        # _parse_aligo_response가 이미 명확한 메시지 + 로깅 완료
        result_msg = str(exc)
    except Exception as exc:
        logger.error(f"[알리고] 카카오 발송 실패: {exc}")
        result_msg = f"카카오 발송 실패: {exc}"

    # 발송 이력 저장 (성공/실패 모두)
    try:
        repo = MessageLogRepository(session)
        await repo.create(
            MessageLog(
                tenant_id=tenant_id,
                order_id=body.order_id,
                customer_phone=body.receiver,
                message_type="kakao",
                template_raw=body.template_raw,
                rendered_message=body.message,
                receiver=body.receiver.replace("-", ""),
                success=success,
                result_message=result_msg,
                msg_id=_kakao_mid,
            )
        )
    except Exception as exc:
        logger.error(f"[알리고] 카카오 이력 저장 실패: {exc}")

    if success:
        return {
            "success": True,
            "message": result_msg,
            "msg_type": "알림톡" if body.template_code else "친구톡",
        }
    return {"success": False, "message": result_msg}
