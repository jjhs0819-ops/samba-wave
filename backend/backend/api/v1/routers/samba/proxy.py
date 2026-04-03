"""SambaWave Proxy API router - 외부 마켓 API 프록시.

Node.js proxy-server.mjs를 대체하는 통합 프록시 라우터.
무신사, KREAM, 롯데홈쇼핑, GS샵 외부 API를 프록시한다.

자격증명은 samba_settings 테이블에서 읽어온다:
- musinsa_cookie: 무신사 인증 쿠키
- kream_token: KREAM Bearer 토큰
- kream_cookie: KREAM 브라우저 쿠키
- lottehome_credentials: { userId, password, agncNo, env }
- gsshop_credentials: { supCd, aesKey, subSupCd, env }
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from typing import Any, Optional

import bcrypt
import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    UploadFile,
    File,
    Form,
)
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.forbidden.repository import SambaSettingsRepository
from backend.domain.samba.proxy.gsshop import GsShopApiError, GsShopClient
from backend.domain.samba.proxy.kream import KreamClient
from backend.domain.samba.proxy.lottehome import LotteApiError, LotteHomeClient
from backend.domain.samba.proxy.musinsa import MusinsaClient
from backend.utils.logger import logger

router = APIRouter(prefix="/proxy", tags=["samba-proxy"])


# ── Helper: read setting from DB ──


async def _get_setting(session: AsyncSession, key: str) -> Any:
    """samba_settings 테이블에서 설정값 조회."""
    repo = SambaSettingsRepository(session)
    row = await repo.find_by_async(key=key)
    if row:
        return row.value
    return None


async def _set_setting(session: AsyncSession, key: str, value: Any) -> None:
    """samba_settings 테이블에 설정값 저장 (forbidden service 위임)."""
    from backend.domain.samba.forbidden.service import SambaForbiddenService
    from backend.domain.samba.forbidden.repository import SambaForbiddenWordRepository

    svc = SambaForbiddenService(
        SambaForbiddenWordRepository(session), SambaSettingsRepository(session)
    )
    await svc.save_setting(key, value)


async def _get_musinsa_client(session: AsyncSession) -> MusinsaClient:
    cookie = await _get_setting(session, "musinsa_cookie") or ""
    return MusinsaClient(cookie=str(cookie))


@router.get("/musinsa/ip-check")
async def musinsa_ip_check():
    """무신사 CDN 차단 여부 테스트 — 서버 IP 기준."""
    test_url = "https://image.msscdn.net/images/goods_img/20260309/6099644/6099644_17736397410885_500.jpg"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as client:
            resp = await client.get(
                test_url,
                headers={
                    "Referer": "https://www.musinsa.com/",
                    "User-Agent": "Mozilla/5.0",
                },
            )
            size = len(resp.content)
            return {
                "status": resp.status_code,
                "size": size,
                "blocked": resp.status_code != 200 or size < 1000,
                "message": "정상"
                if resp.status_code == 200 and size >= 1000
                else f"차단 의심 (HTTP {resp.status_code}, {size}B)",
            }
    except httpx.ConnectTimeout:
        return {"status": 0, "blocked": True, "message": "연결 타임아웃 — IP 차단"}
    except httpx.ReadTimeout:
        return {"status": 0, "blocked": True, "message": "읽기 타임아웃 — IP 차단"}
    except Exception as e:
        return {"status": 0, "blocked": True, "message": f"오류: {type(e).__name__}"}


async def _get_kream_client(session: AsyncSession) -> KreamClient:
    token = await _get_setting(session, "kream_token") or ""
    cookie = await _get_setting(session, "kream_cookie") or ""
    return KreamClient(token=str(token), cookie=str(cookie))


async def _get_lotte_client(session: AsyncSession) -> LotteHomeClient:
    creds = await _get_setting(session, "lottehome_credentials") or {}
    if not isinstance(creds, dict):
        creds = {}
    return LotteHomeClient(
        user_id=creds.get("userId", ""),
        password=creds.get("password", ""),
        agnc_no=creds.get("agncNo", ""),
        env=creds.get("env", "test"),
    )


async def _get_gs_client(session: AsyncSession) -> GsShopClient:
    creds = await _get_setting(session, "gsshop_credentials") or {}
    if not isinstance(creds, dict):
        creds = {}
    return GsShopClient(
        sup_cd=creds.get("supCd", ""),
        aes_key=creds.get("aesKey", ""),
        sub_sup_cd=creds.get("subSupCd", ""),
        env=creds.get("env", "dev"),
    )


# ═══════════════════════════════════════════════
# 알리고 (Aligo) SMS 잔여건수 조회
# ═══════════════════════════════════════════════


@router.post("/aligo/remain")
async def aligo_remain(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """알리고 SMS 잔여건수 조회."""
    creds = await _get_setting(session, "aligo_sms")
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
            data = resp.json()
            # 알리고 응답: result_code == 1 이면 성공
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
    except Exception as exc:
        logger.error(f"[알리고] 잔여건수 조회 실패: {exc}")
        return {"success": False, "message": f"알리고 API 호출 실패: {exc}"}


# ═══════════════════════════════════════════════
# 알리고 SMS 발송
# ═══════════════════════════════════════════════


class SmsRequest(BaseModel):
    receiver: str  # 수신 번호
    message: str  # 메시지 내용
    title: str = ""  # LMS 제목 (길면 자동 LMS)


@router.post("/aligo/send-sms")
async def aligo_send_sms(
    body: SmsRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """알리고 SMS/LMS 발송."""
    creds = await _get_setting(session, "aligo_sms")
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

    # 90바이트 초과 시 LMS
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

    try:
        async with httpx.AsyncClient(timeout=15, verify=True) as client:
            resp = await client.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            result = resp.json()
            if result.get("result_code") == 1 or str(result.get("result_code")) == "1":
                return {
                    "success": True,
                    "message": f"{'LMS' if is_lms else 'SMS'} 발송 성공",
                    "msg_id": result.get("msg_id"),
                    "msg_type": "LMS" if is_lms else "SMS",
                }
            else:
                return {
                    "success": False,
                    "message": result.get("message", "발송 실패"),
                }
    except Exception as exc:
        logger.error(f"[알리고] SMS 발송 실패: {exc}")
        return {"success": False, "message": f"SMS 발송 실패: {exc}"}


# ═══════════════════════════════════════════════
# 알리고 카카오 알림톡 발송
# ═══════════════════════════════════════════════


class KakaoRequest(BaseModel):
    receiver: str  # 수신 번호
    message: str  # 메시지 내용
    template_code: str = ""  # 카카오 템플릿 코드 (비어있으면 친구톡)
    subject: str = ""  # 제목


@router.post("/aligo/send-kakao")
async def aligo_send_kakao(
    body: KakaoRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """알리고 카카오 알림톡/친구톡 발송."""
    creds = await _get_setting(session, "aligo_sms")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "SMS 설정이 저장되지 않았습니다."}

    kakao_creds = await _get_setting(session, "aligo_kakao")

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
        "key": api_key,
        "user_id": user_id,
        "sender": sender,
        "receiver_1": body.receiver.replace("-", ""),
        "message_1": body.message,
        "senderkey": sender_key,
        "tpl_code": body.template_code,
    }
    if body.subject:
        data["subject_1"] = body.subject

    # 템플릿 코드가 있으면 알림톡, 없으면 친구톡
    url = (
        "https://kakaoapi.aligo.in/akv10/alimtalk/send/"
        if body.template_code
        else "https://kakaoapi.aligo.in/akv10/friendtalk/send/"
    )

    try:
        async with httpx.AsyncClient(timeout=15, verify=True) as client:
            resp = await client.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            result = resp.json()
            if result.get("code") == 0 or str(result.get("code")) == "0":
                return {
                    "success": True,
                    "message": "카카오톡 발송 성공",
                    "msg_type": "알림톡" if body.template_code else "친구톡",
                }
            else:
                return {
                    "success": False,
                    "message": result.get("message", "카카오 발송 실패"),
                }
    except Exception as exc:
        logger.error(f"[알리고] 카카오 발송 실패: {exc}")
        return {"success": False, "message": f"카카오 발송 실패: {exc}"}


# ═══════════════════════════════════════════════
# 스마트스토어 (SmartStore) 인증 테스트
# ═══════════════════════════════════════════════


@router.get("/smartstore/search-brand")
async def smartstore_search_brand(
    name: str = Query(...),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> list[dict[str, Any]]:
    """스마트스토어 브랜드 검색."""
    client = await _get_ss_client(session)
    if not client:
        return []
    result = await client._call_api("GET", "/v1/product-brands", params={"name": name})
    return result if isinstance(result, list) else []


@router.get("/smartstore/search-manufacturer")
async def smartstore_search_manufacturer(
    name: str = Query(...),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> list[dict[str, Any]]:
    """스마트스토어 제조사 검색."""
    client = await _get_ss_client(session)
    if not client:
        return []
    result = await client._call_api(
        "GET", "/v1/product-manufacturers", params={"name": name}
    )
    return result if isinstance(result, list) else []


async def _get_ss_client(session: AsyncSession):
    """스마트스토어 클라이언트 생성 헬퍼."""
    from backend.domain.samba.proxy.smartstore import SmartStoreClient
    from sqlalchemy import text

    result = await session.exec(
        text(
            "SELECT additional_fields FROM samba_market_account WHERE market_type='smartstore' LIMIT 1"
        )
    )
    row = result.first()
    if not row or not row[0]:
        return None
    extras = row[0] if isinstance(row[0], dict) else {}
    cid = extras.get("clientId", "")
    csec = extras.get("clientSecret", "")
    if not cid or not csec:
        return None
    return SmartStoreClient(cid, csec)


@router.post("/smartstore/auth-test")
async def smartstore_auth_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """스마트스토어 Commerce API 인증 테스트 — OAuth2 토큰 발급 시도."""
    creds = await _get_setting(session, "store_smartstore")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "스마트스토어 설정이 저장되지 않았습니다."}

    client_id = creds.get("clientId", "")
    client_secret = creds.get("clientSecret", "")
    if not client_id or not client_secret:
        return {
            "success": False,
            "message": "Client ID 또는 Client Secret이 비어있습니다.",
        }

    try:
        # bcrypt 서명 생성 (네이버 Commerce API 인증 방식)
        timestamp = int(time.time() * 1000)
        password = f"{client_id}_{timestamp}"
        hashed = bcrypt.hashpw(
            password.encode("utf-8"),
            client_secret.encode("utf-8"),
        )
        client_secret_sign = base64.standard_b64encode(hashed).decode("utf-8")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.commerce.naver.com/external/v1/oauth2/token",
                data={
                    "client_id": client_id,
                    "timestamp": timestamp,
                    "client_secret_sign": client_secret_sign,
                    "grant_type": "client_credentials",
                    "type": "SELF",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("access_token", "")
                expires = data.get("expires_in", 0)
                return {
                    "success": True,
                    "message": f"인증 성공 (토큰 유효시간: {expires // 3600}시간)",
                    "token_preview": f"{token[:12]}..." if len(token) > 12 else token,
                }
            else:
                err = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                return {
                    "success": False,
                    "message": err.get("message")
                    or err.get("error_description")
                    or f"HTTP {resp.status_code}",
                }
    except Exception as exc:
        logger.error(f"[스마트스토어] 인증 테스트 실패: {exc}")
        return {"success": False, "message": f"API 호출 실패: {exc}"}


# ═══════════════════════════════════════════════
# 11번가 OpenAPI 인증 테스트
# ═══════════════════════════════════════════════


@router.post("/11st/auth-test")
async def elevenst_auth_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """11번가 OpenAPI 인증 테스트 — 상품검색 API 호출로 Key 유효성 확인."""
    creds = await _get_setting(session, "store_11st")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "11번가 설정이 저장되지 않았습니다."}

    api_key = creds.get("apiKey", "")
    if not api_key:
        return {"success": False, "message": "Open API Key가 비어있습니다."}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "http://openapi.11st.co.kr/openapi/OpenApiService.tmall",
                params={
                    "key": api_key,
                    "apiCode": "ProductSearch",
                    "keyword": "test",
                    "pageSize": "1",
                },
            )
            body = resp.text
            # 에러코드 003 = 미등록 API Key
            if "003" in body and "미등록" in body:
                return {"success": False, "message": "등록되지 않은 API Key입니다."}
            if "004" in body and "트래픽" in body:
                return {
                    "success": False,
                    "message": "트래픽 초과입니다. 잠시 후 다시 시도해주세요.",
                }
            if resp.status_code == 200 and "<ProductSearchResponse>" in body:
                return {"success": True, "message": "인증 성공 — API Key가 유효합니다."}
            if resp.status_code == 200:
                # XML 응답이지만 에러일 수 있음
                if "<error>" in body.lower() or "<code>" in body:
                    return {"success": False, "message": "API Key가 유효하지 않습니다."}
                return {"success": True, "message": "인증 성공"}
            return {"success": False, "message": f"HTTP {resp.status_code}"}
    except Exception as exc:
        logger.error(f"[11번가] 인증 테스트 실패: {exc}")
        return {"success": False, "message": f"API 호출 실패: {exc}"}


@router.post("/11st/seller-info")
async def elevenst_seller_info(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """11번가 출고지/반품교환지 주소 조회.

    GET /rest/areaservice/outboundarea (출고지)
    GET /rest/areaservice/inboundarea (반품/교환지)
    """
    from backend.domain.samba.proxy.elevenst import ElevenstClient

    creds = await _get_setting(session, "store_11st")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "11번가 설정이 저장되지 않았습니다."}
    api_key = creds.get("apiKey", "")
    if not api_key:
        return {"success": False, "message": "Open API Key가 비어있습니다."}

    try:
        client = ElevenstClient(api_key)

        # 출고지 + 반품/교환지 동시 조회
        outbound = await client.get_outbound_addresses()
        inbound = await client.get_inbound_addresses()

        if not outbound and not inbound:
            return {
                "success": False,
                "message": "출고지/반품지 정보가 없습니다. 11번가 셀러오피스에서 먼저 등록해주세요.",
            }

        result: dict[str, Any] = {}
        # 첫 번째 출고지 주소 사용
        if outbound:
            first_out = outbound[0]
            result["shipFromAddress"] = first_out.get("addr", "")
            result["shipFromAddrSeq"] = first_out.get("addrSeq", "")
            result["shipFromName"] = first_out.get("addrNm", "")
        # 첫 번째 반품/교환지 주소 사용
        if inbound:
            first_in = inbound[0]
            result["returnAddress"] = first_in.get("addr", "")
            result["returnAddrSeq"] = first_in.get("addrSeq", "")
            result["returnName"] = first_in.get("addrNm", "")

        # 전체 목록도 함께 반환
        result["outboundList"] = outbound
        result["inboundList"] = inbound

        return {"success": True, "message": "출고지/반품지 조회 성공", "data": result}
    except Exception as exc:
        logger.error(f"[11번가] 출고지/반품지 조회 실패: {exc}")
        return {"success": False, "message": f"출고지/반품지 조회 실패: {exc}"}


# ═══════════════════════════════════════════════
# 쿠팡 Wing API 인증 테스트
# ═══════════════════════════════════════════════


@router.post("/coupang/auth-test")
async def coupang_auth_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """쿠팡 Wing API 인증 테스트 — HMAC 서명으로 카테고리 조회."""
    creds = await _get_setting(session, "store_coupang")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "쿠팡 설정이 저장되지 않았습니다."}

    access_key = creds.get("accessKey", "")
    secret_key = creds.get("secretKey", "")
    if not access_key or not secret_key:
        return {
            "success": False,
            "message": "Access Key 또는 Secret Key가 비어있습니다.",
        }

    vendor_id = creds.get("vendorId", "")
    if not vendor_id:
        return {"success": False, "message": "Vendor ID가 비어있습니다."}

    try:
        from backend.domain.samba.proxy.coupang import CoupangClient

        client = CoupangClient(access_key, secret_key, vendor_id)
        # 카테고리 조회 API로 인증 테스트 (유효한 엔드포인트)
        await client.get_categories()
        return {"success": True, "message": "인증 성공 — API Key가 유효합니다."}
    except Exception as exc:
        logger.error(f"[쿠팡] 인증 테스트 실패: {exc}")
        return {"success": False, "message": f"인증 실패: {exc}"}


# ═══════════════════════════════════════════════
# 롯데ON Open API 인증 테스트
# ═══════════════════════════════════════════════


@router.post("/lotteon/auth-test")
async def lotteon_auth_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데ON Open API 인증 테스트 — 거래처 정보 조회 + 배송인프라 검증."""
    creds = await _get_setting(session, "store_lotteon")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "롯데ON 설정이 저장되지 않았습니다."}

    api_key = creds.get("apiKey", "")
    if not api_key:
        return {"success": False, "message": "API Key가 비어있습니다."}

    try:
        from backend.domain.samba.proxy.lotteon import LotteonClient

        client = LotteonClient(api_key)
        result = await client.test_auth()
        data = result.get("data", {})
        tr_info = (
            f" (거래처: {data.get('trGrpCd', '')}-{data.get('trNo', '')})"
            if data
            else ""
        )

        # 배송인프라 입력 여부 확인
        dv_cst_pol = creds.get("dvCstPolNo", "")
        owhp = creds.get("owhpNo", "")
        rtrp = creds.get("rtrpNo", "")
        missing = []
        if not dv_cst_pol:
            missing.append("배송정책번호")
        if not owhp:
            missing.append("출고지번호")
        if not rtrp:
            missing.append("회수지번호")

        infra_msg = ""
        if missing:
            infra_msg = f" ⚠ 미입력: {', '.join(missing)}"

        return {
            "success": True,
            "message": f"인증 성공{tr_info}{infra_msg}",
            "data": {
                **(data or {}),
                "dvCstPolNo": dv_cst_pol,
                "owhpNo": owhp,
                "rtrpNo": rtrp,
            },
        }
    except Exception as exc:
        logger.error(f"[롯데ON] 인증 테스트 실패: {exc}")
        return {"success": False, "message": f"인증 실패: {exc}"}


# ═══════════════════════════════════════════════
# SSG Open API 인증 테스트
# ═══════════════════════════════════════════════


@router.post("/ssg/auth-test")
async def ssg_auth_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """SSG Open API 인증 테스트 — 브랜드 목록 조회."""
    creds = await _get_setting(session, "store_ssg")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "SSG 설정이 저장되지 않았습니다."}

    api_key = creds.get("apiKey", "")
    if not api_key:
        return {"success": False, "message": "인증키가 비어있습니다."}

    try:
        from backend.domain.samba.proxy.ssg import SSGClient

        client = SSGClient(api_key)
        await client.test_auth()
        return {"success": True, "message": "인증 성공 — API Key가 유효합니다."}
    except Exception as exc:
        logger.error(f"[SSG] 인증 테스트 실패: {exc}")
        return {"success": False, "message": f"인증 실패: {exc}"}


# ═══════════════════════════════════════════════
# GS샵 인증 테스트 (개발/운영)
# ═══════════════════════════════════════════════


@router.post("/gsshop/auth-test")
async def gsshop_auth_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 AES256 인증 테스트 — 개발/운영 환경 모두 검증."""
    creds = await _get_setting(session, "store_gsshop")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "GS샵 설정이 저장되지 않았습니다."}

    sup_cd = creds.get("storeId", "")
    api_key_dev = creds.get("apiKeyDev", "")
    api_key_prod = creds.get("apiKeyProd", "")

    if not sup_cd:
        return {"success": False, "message": "스토어 ID(협력사코드)가 비어있습니다."}
    if not api_key_dev and not api_key_prod:
        return {
            "success": False,
            "message": "개발 또는 운영 AES256 인증키를 입력해주세요.",
        }

    results: list[str] = []
    any_ok = False

    # 개발 환경 테스트
    if api_key_dev:
        try:
            dev_client = GsShopClient(sup_cd=sup_cd, aes_key=api_key_dev, env="dev")
            dev_result = await dev_client.check_auth()
            if dev_result.get("authenticated"):
                results.append("개발: 인증 성공")
                any_ok = True
            else:
                results.append(f"개발: {dev_result.get('message', '인증 실패')}")
        except Exception as exc:
            results.append(f"개발: {exc}")

    # 운영 환경 테스트
    if api_key_prod:
        try:
            prod_client = GsShopClient(sup_cd=sup_cd, aes_key=api_key_prod, env="prod")
            prod_result = await prod_client.check_auth()
            if prod_result.get("authenticated"):
                results.append("운영: 인증 성공")
                any_ok = True
            else:
                results.append(f"운영: {prod_result.get('message', '인증 실패')}")
        except Exception as exc:
            results.append(f"운영: {exc}")

    msg = " / ".join(results)
    return {"success": any_ok, "message": msg}


# ═══════════════════════════════════════════════
# 통합 마켓 인증 테스트 (범용)
# ═══════════════════════════════════════════════


@router.post("/market/auth-test/{market_key}")
async def market_auth_test(
    market_key: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """범용 마켓 인증 테스트 — 설정값 존재 여부 확인."""
    creds = await _get_setting(session, f"store_{market_key}")
    if not creds or not isinstance(creds, dict):
        return {
            "success": False,
            "message": f"{market_key} 설정이 저장되지 않았습니다.",
        }

    # 빈 값 체크
    has_value = any(v for v in creds.values() if v and str(v).strip())
    if not has_value:
        return {"success": False, "message": "설정값이 비어있습니다."}

    return {"success": True, "message": "설정 저장됨 — 상품 전송 시 연동됩니다."}


# ═══════════════════════════════════════════════
# Claude AI API 인증 테스트
# ═══════════════════════════════════════════════


@router.post("/claude/test")
async def claude_api_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """Claude API 키 유효성 검증 — 최소 메시지 전송 테스트."""
    creds = await _get_setting(session, "claude")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "Claude API 설정이 저장되지 않았습니다."}

    api_key = creds.get("apiKey", "")
    model = creds.get("model", "claude-sonnet-4-6")
    if not api_key:
        return {"success": False, "message": "API Key가 비어있습니다."}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                used_model = data.get("model", model)
                return {
                    "success": True,
                    "message": f"인증 성공 (모델: {used_model})",
                }
            else:
                err = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                err_msg = (
                    err.get("error", {}).get("message", "")
                    if isinstance(err.get("error"), dict)
                    else str(err.get("error", ""))
                )
                return {
                    "success": False,
                    "message": err_msg or f"HTTP {resp.status_code}",
                }
    except Exception as exc:
        logger.error(f"[Claude] API 테스트 실패: {exc}")
        return {"success": False, "message": f"API 호출 실패: {exc}"}


@router.post("/gemini/test")
async def gemini_api_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """Gemini API 키 유효성 검증."""
    creds = await _get_setting(session, "gemini")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "Gemini API 설정이 저장되지 않았습니다."}

    api_key = creds.get("apiKey", "")
    model = creds.get("model", "gemini-2.5-flash")
    if not api_key:
        return {"success": False, "message": "API Key가 비어있습니다."}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                json={
                    "contents": [{"parts": [{"text": "hi"}]}],
                    "generationConfig": {"maxOutputTokens": 5},
                },
            )
            if resp.status_code == 200:
                return {"success": True, "message": f"인증 성공 (모델: {model})"}
            else:
                err = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                err_msg = (
                    err.get("error", {}).get("message", "")
                    if isinstance(err.get("error"), dict)
                    else str(err.get("error", ""))
                )
                return {
                    "success": False,
                    "message": err_msg or f"HTTP {resp.status_code}",
                }
    except Exception as exc:
        logger.error(f"[Gemini] API 테스트 실패: {exc}")
        return {"success": False, "message": f"API 호출 실패: {exc}"}


@router.post("/r2/test")
async def r2_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """Cloudflare R2 연결 테스트."""
    creds = await _get_setting(session, "cloudflare_r2")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "R2 settings not found"}

    account_id = str(creds.get("accountId", "")).strip()
    access_key = str(creds.get("accessKey", "")).strip()
    secret_key = str(creds.get("secretKey", "")).strip()
    bucket_name = str(creds.get("bucketName", "")).strip()

    if not access_key or not secret_key or not bucket_name:
        return {
            "success": False,
            "message": "Access Key, Secret Key, Bucket Name required",
        }

    try:
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        s3.head_bucket(Bucket=bucket_name)
        return {"success": True, "message": f"R2 connected (bucket: {bucket_name})"}
    except Exception as exc:
        logger.error(f"[R2] test failed: {exc}")
        return {"success": False, "message": f"R2 connection failed: {str(exc)[:200]}"}


@router.get("/fal/status")
async def fal_ai_status(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """fal.ai 계정 상태 확인 (잔액 부족 여부)."""
    creds = await _get_setting(session, "fal_ai")
    if not creds or not isinstance(creds, dict):
        return {"status": "no_key", "message": "API 키 미등록"}

    api_key = str(creds.get("apiKey", "")).strip()
    if not api_key:
        return {"status": "no_key", "message": "API 키 비어있음"}

    import os

    os.environ["FAL_KEY"] = api_key
    try:
        import fal_client

        # 최소 비용 호출로 계정 상태 확인 (실제 이미지 생성 없이 큐 제출만)
        handle = await fal_client.submit_async(
            "fal-ai/flux/dev",
            arguments={
                "prompt": "test",
                "num_inference_steps": 1,
                "image_size": "square_hd",
            },
        )
        # 큐 제출 성공 → 잔액 있음. 즉시 취소
        await fal_client.cancel_async("fal-ai/flux/dev", handle.request_id)
        return {"status": "ok", "message": "사용 가능"}
    except Exception as e:
        err = str(e)
        if "Exhausted balance" in err or "locked" in err.lower():
            return {"status": "no_balance", "message": "잔액 부족"}
        if "401" in err or "unauthorized" in err.lower():
            return {"status": "invalid_key", "message": "API 키 무효"}
        return {"status": "error", "message": err[:100]}


@router.post("/images/transform")
async def transform_images(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """AI 이미지 변환 (rembg/FLUX) 후 R2/로컬 저장."""
    from backend.domain.samba.image.service import ImageTransformService

    svc = ImageTransformService(session)
    product_ids = request.get("product_ids", [])
    group_ids = request.get("group_ids", [])
    scope = request.get(
        "scope", {"thumbnail": True, "additional": False, "detail": False}
    )
    mode = request.get("mode", "background")  # background | scene | model
    model_preset = request.get("model_preset", "female_v1")

    # 그룹 ID로 요청 시 해당 그룹의 상품 ID 조회
    if group_ids and not product_ids:
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )

        repo = SambaCollectedProductRepository(session)
        for gid in group_ids:
            products = await repo.list_by_filter(gid, skip=0, limit=10000)
            product_ids.extend([p.id for p in products])
        product_ids = list(set(product_ids))

    if not product_ids:
        return {"success": False, "message": "No products selected"}

    try:
        result = await svc.transform_products(product_ids, scope, mode, model_preset)
        # 전부 실패했으면 success=False
        transformed = result.get("total_transformed", 0)
        return {"success": transformed > 0, **result}
    except Exception as exc:
        logger.error(f"[이미지변환] transform failed: {exc}")
        return {"success": False, "message": str(exc)[:300]}


@router.get("/preset-images/list")
async def list_preset_images() -> dict[str, Any]:
    """프리셋 목록 + 이미지 URL 반환."""
    from backend.domain.samba.image.service import MODEL_PRESETS, PRESET_IMAGE_DIR

    presets = []
    for key, p in MODEL_PRESETS.items():
        filename = p.get("image", "")
        local_path = PRESET_IMAGE_DIR / filename if filename else None
        presets.append(
            {
                "key": key,
                "label": p["label"],
                "desc": p["desc"],
                "image": f"/static/model_presets/{filename}"
                if local_path and local_path.exists()
                else None,
            }
        )
    return {"success": True, "presets": presets}


@router.post("/preset-images/upload")
async def upload_preset_image(
    preset_key: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """프리셋 이미지를 직접 업로드."""
    from backend.domain.samba.image.service import MODEL_PRESETS, PRESET_IMAGE_DIR

    preset = MODEL_PRESETS.get(preset_key)
    if not preset:
        return {"success": False, "message": f"프리셋 '{preset_key}' 없음"}

    filename = preset.get("image", f"{preset_key}.png")
    out_path = PRESET_IMAGE_DIR / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    out_path.write_bytes(content)

    return {
        "success": True,
        "message": f"{preset['label']} 이미지 업로드 완료 ({len(content)} bytes)",
        "image": f"/static/model_presets/{filename}",
    }


@router.post("/preset-images/regenerate")
async def regenerate_preset_image(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """프리셋 이미지를 FLUX로 재생성."""
    from backend.domain.samba.image.service import (
        ImageTransformService,
        MODEL_PRESETS,
        PRESET_IMAGE_DIR,
    )

    preset_key = request.get("preset_key", "")
    custom_desc = request.get("desc", "")
    custom_label = request.get("label", "")
    save_only = request.get("save_only", False)
    preset = MODEL_PRESETS.get(preset_key)
    if not preset:
        return {"success": False, "message": f"프리셋 '{preset_key}' 없음"}

    # label/desc 텍스트 업데이트
    if custom_label:
        preset["label"] = custom_label
    if custom_desc:
        preset["desc"] = custom_desc

    # 텍스트만 저장 (이미지 재생성 없이)
    if save_only:
        return {"success": True, "message": f"{preset['label']} 설정 저장 완료"}

    svc = ImageTransformService(session)
    fal_key = await svc._get_flux_config()

    desc = custom_desc or preset["desc"]
    prompt = (
        f"Full body photo of {desc}. "
        "Wearing a black oversized crewneck and wide slacks. "
        "Minimal black derby shoes. Runway walking pose, cool expressionless face. "
        "Light gray studio background. Paris haute couture editorial style, photorealistic."
    )

    import os
    import fal_client

    os.environ["FAL_KEY"] = fal_key

    result = await fal_client.run_async(
        "fal-ai/flux/dev",
        arguments={
            "prompt": prompt,
            "num_inference_steps": 28,
            "guidance_scale": 3.5,
            "image_size": "portrait_3_4",
            "output_format": "png",
        },
    )

    images = result.get("images", [])
    if not images:
        return {"success": False, "message": "FLUX 응답에 이미지 없음"}

    output_url = images[0].get("url", "")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(output_url)
        resp.raise_for_status()
        img_bytes = resp.content

    filename = preset.get("image", f"{preset_key}.png")
    out_path = PRESET_IMAGE_DIR / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(img_bytes)

    if custom_desc:
        preset["desc"] = custom_desc

    return {
        "success": True,
        "message": f"{preset['label']} 이미지 재생성 완료",
        "image": f"/static/model_presets/{filename}",
    }


@router.post("/preset-images/sync-to-r2")
async def sync_preset_images_to_r2(
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """로컬 프리셋 이미지를 R2에 일괄 업로드."""
    from backend.domain.samba.image.service import ImageTransformService

    svc = ImageTransformService(session)
    return await svc.sync_presets_to_r2()


# ═══════════════════════════════════════════════
# AI 태그 공통 상수 및 헬퍼
# ═══════════════════════════════════════════════

_SOURCING_SITE_BANNED: frozenset[str] = frozenset(
    {
        "musinsa",
        "무신사",
        "kream",
        "크림",
        "abcmart",
        "abc마트",
        "올리브영",
        "oliveyoung",
        "ssg",
        "신세계",
        "롯데온",
        "lotteon",
        "gsshop",
        "gs샵",
        "ebay",
        "이베이",
        "zara",
        "자라",
        "fashionplus",
        "패션플러스",
        "grandstage",
        "그랜드스테이지",
        "okmall",
        "elandmall",
        "이랜드몰",
        "ssf",
        "ssf샵",
    }
)

_BRAND_BANNED: frozenset[str] = frozenset(
    {
        "nike",
        "나이키",
        "adidas",
        "아디다스",
        "뉴발란스",
        "new balance",
        "푸마",
        "puma",
        "리복",
        "reebok",
        "아식스",
        "asics",
        "컨버스",
        "converse",
        "반스",
        "vans",
        "휠라",
        "fila",
        "스케쳐스",
        "skechers",
        "노스페이스",
        "the north face",
        "코오롱",
        "kolon",
        "아이더",
        "eider",
        "블랙야크",
        "blackyak",
        "k2",
        "네파",
        "nepa",
        "밀레",
        "millet",
        "살로몬",
        "salomon",
        "메렐",
        "merrell",
        "콜롬비아",
        "columbia",
        "호카",
        "hoka",
        "온러닝",
        "on running",
        "라코스테",
        "lacoste",
        "폴로",
        "polo",
        "구찌",
        "gucci",
        "프라다",
        "prada",
        "버버리",
        "burberry",
        "발렌시아가",
        "balenciaga",
        "디올",
        "dior",
    }
)

_BRAND_PARTIAL_MATCH: frozenset[str] = frozenset(
    {
        "나이키",
        "아디다스",
        "뉴발란스",
        "푸마",
        "리복",
        "아식스",
        "컨버스",
        "반스",
        "휠라",
        "스케쳐스",
        "노스페이스",
        "코오롱",
        "아이더",
        "블랙야크",
        "네파",
        "밀레",
        "살로몬",
        "메렐",
        "콜롬비아",
        "호카",
        "라코스테",
        "폴로",
        "구찌",
        "프라다",
        "버버리",
        "발렌시아가",
        "디올",
        "nike",
        "adidas",
        "puma",
        "reebok",
        "asics",
        "converse",
        "vans",
        "fila",
        "skechers",
        "salomon",
        "merrell",
        "columbia",
        "hoka",
        "lacoste",
        "gucci",
        "prada",
        "burberry",
    }
)


async def _load_tag_filter_data(session) -> tuple[set[str], set[str]]:
    """DB에서 금지태그/미등록태그 + 전체 브랜드 목록을 1회 로드."""
    ss_banned: set[str] = set()
    db_brands: set[str] = set()
    try:
        from backend.domain.samba.forbidden.repository import SambaSettingsRepository

        repo = SambaSettingsRepository(session)
        for key in ("smartstore_banned_tags", "smartstore_unregistered_tags"):
            row = await repo.find_by_async(key=key)
            if row and isinstance(row.value, list):
                ss_banned.update(w.lower().replace(" ", "") for w in row.value)
    except Exception:
        pass
    try:
        from sqlmodel import select as _sel
        from backend.domain.samba.collector.model import SambaCollectedProduct as _CP

        result = await session.exec(_sel(_CP.brand).distinct())
        for b in result.all():
            if b and len(b) >= 2:
                db_brands.add(b.lower())
    except Exception:
        pass
    return ss_banned, db_brands


def _build_banned_set(
    source_site: str,
    brand: str,
    cats: list,
    rep_name: str,
    ss_banned: set[str],
    db_brands: set[str],
) -> tuple[set[str], set[str], set[str], set[str]]:
    """상품 정보 기반 금지어 집합 (_banned, _name_words, _brand_words, _ss_banned) 생성."""
    _banned = set(_SOURCING_SITE_BANNED | _BRAND_BANNED | ss_banned)
    if source_site:
        _banned.add(source_site.lower())
    for cat_part in cats:
        if cat_part:
            for w in re.split(r"[\s>/\-]+", cat_part):
                clean = w.strip().lower()
                if len(clean) >= 2:
                    _banned.add(clean)
    if brand:
        _banned.add(brand.lower())
        for w in brand.split():
            if len(w) >= 2:
                _banned.add(w.lower())

    _name_words: set[str] = set()
    for w in re.split(r"[\s/\-_()]+", rep_name):
        clean = re.sub(r"[^가-힣a-zA-Z0-9]", "", w).lower()
        if len(clean) >= 2:
            _name_words.add(clean)

    _brand_words = set(_BRAND_PARTIAL_MATCH | db_brands)
    if brand and len(brand) >= 2:
        _brand_words.add(brand.lower())

    return _banned, _name_words, _brand_words, ss_banned


def _is_valid_tag(
    tag: str,
    banned: set[str],
    name_words: set[str],
    ss_banned: set[str],
    brand_words: set[str],
) -> bool:
    """태그 유효성 검사."""
    t = tag.strip().lower()
    if not t:
        return False
    if t in banned or t in name_words:
        return False
    if t.replace(" ", "") in ss_banned:
        return False
    for bw in brand_words:
        if bw in t:
            return False
    return True


def _has_overlap_suffix(word: str, existing: list[str], min_suffix: int = 2) -> bool:
    """기존 SEO 키워드와 접미어가 겹치는지 확인.

    예: 기존에 '로고티셔츠'가 있으면 '그래픽티셔츠'는 '티셔츠' 접미어 중복 → True
    """
    wl = word.lower()
    for e in existing:
        el = e.lower()
        # 공통 접미어 검사 (뒤에서부터 매칭)
        common = 0
        for i in range(1, min(len(wl), len(el)) + 1):
            if wl[-i] == el[-i]:
                common = i
            else:
                break
        if common >= min_suffix and wl != el:
            return True
    return False


def _extract_seo_keywords(
    candidates: list[str],
    cats: list,
    banned: set[str],
    name_words: set[str],
    final_tags: list[str] | None = None,
    max_count: int = 3,
) -> list[str]:
    """최종 검증 태그와 겹치지 않는 SEO 키워드 3개 추출.

    최종 태그에 포함된 키워드는 SEO에서 제외하여 중복을 방지한다.
    태그에 선정되지 않은 후보 중에서 SEO에 적합한 키워드를 추출한다.
    """
    seo: list[str] = []
    # 최종 태그 집합 (소문자, 공백 제거)
    tag_set = {t.lower().replace(" ", "") for t in (final_tags or [])}
    # 태그에 포함되지 않은 후보 우선, 그 다음 전체 후보
    non_tag_candidates = [
        c for c in candidates if c.lower().replace(" ", "") not in tag_set
    ]
    pool = non_tag_candidates + [c for c in candidates if c not in non_tag_candidates]
    for kw in pool:
        cleaned = kw
        for cat_part in cats:
            if cat_part:
                cleaned = cleaned.replace(cat_part, "").strip()
        words = cleaned.split() if " " in cleaned else [cleaned]
        for word in words:
            w = word.strip()
            wl = w.lower().replace(" ", "")
            if len(w) < 2 or wl in banned or wl in name_words or w in seo:
                continue
            # 태그와 겹치면 SEO에서 제외
            if wl in tag_set:
                continue
            if _has_overlap_suffix(w, seo):
                continue
            seo.append(w)
            if len(seo) >= max_count:
                break
        if len(seo) >= max_count:
            break
    return seo


async def _get_smartstore_tag_client(session: AsyncSession):
    """활성 스마트스토어 계정으로 태그사전 검증용 클라이언트 생성. 없으면 None."""
    try:
        from backend.domain.samba.account.repository import SambaMarketAccountRepository
        from backend.domain.samba.proxy.smartstore import SmartStoreClient

        account_repo = SambaMarketAccountRepository(session)
        ss_accounts = await account_repo.filter_by_async(
            market_type="smartstore", is_active=True
        )
        if ss_accounts:
            acc = ss_accounts[0]
            additional = acc.additional_fields or {}
            _cid = additional.get("clientId") or acc.api_key
            _csec = additional.get("clientSecret") or acc.api_secret
            if _cid and _csec:
                logger.info("[AI태그] 스마트스토어 태그사전 검증 활성화")
                return SmartStoreClient(_cid, _csec)
    except Exception as e:
        logger.warning(
            f"[AI태그] 스마트스토어 클라이언트 초기화 실패 (태그사전 검증 비활성): {e}"
        )
    return None


@router.post("/ai-tags/generate")
async def generate_ai_tags(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """선택 상품을 그룹별로 묶어 대표 1개로 Claude 태그 생성 후 태그사전 검증 → 그룹 전체에 적용."""
    from backend.domain.samba.collector.repository import (
        SambaCollectedProductRepository,
    )

    product_ids = request.get("product_ids", [])
    req_group_ids = request.get("group_ids", [])
    logger.info(
        f"[AI태그] 요청: product_ids={len(product_ids)}개, group_ids={req_group_ids}"
    )

    if not product_ids and not req_group_ids:
        return {"success": False, "message": "상품 또는 그룹을 선택해주세요"}

    # Claude API 키 조회
    creds = await _get_setting(session, "claude")
    if not creds or not isinstance(creds, dict) or not creds.get("apiKey"):
        return {"success": False, "message": "Claude API 설정이 없습니다"}
    api_key = str(creds["apiKey"]).strip()
    model = str(creds.get("model", "claude-sonnet-4-6"))

    repo = SambaCollectedProductRepository(session)

    # 그룹 ID 직접 전달 시 바로 사용
    group_ids: set[str] = set(req_group_ids)
    ungrouped: list = []

    # 상품 ID로 전달 시 그룹 추출
    for pid in product_ids:
        product = await repo.get_async(pid)
        if not product:
            continue
        if product.search_filter_id:
            group_ids.add(product.search_filter_id)
        else:
            ungrouped.append(product)

    # 그룹별 전체 상품 조회 (샘플링용)
    group_products: dict[str, list] = {}
    for gid in group_ids:
        all_in_group = await repo.filter_by_async(search_filter_id=gid, limit=10000)
        if all_in_group:
            group_products[gid] = list(all_in_group)
    for p in ungrouped:
        group_products[p.id] = [p]

    if not group_products:
        return {"success": False, "message": "상품을 찾을 수 없습니다"}

    total_tagged = 0
    total_groups = len(group_products)
    failed_groups = 0
    api_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_tag_dict_validated = 0
    total_tag_dict_rejected = 0

    # 금지태그/브랜드 목록 1회 로드
    ss_banned_cache, db_brands_cache = await _load_tag_filter_data(session)

    # 스마트스토어 클라이언트 초기화 (태그사전 검증용)
    ss_client = await _get_smartstore_tag_client(session)

    async with httpx.AsyncClient(timeout=30) as http_client:
        for gid, products in group_products.items():
            rep = products[0]
            rep_name = rep.name or ""
            cats = [rep.category1, rep.category2, rep.category3, rep.category4]
            category = " > ".join(c for c in cats if c) or rep.category or ""
            brand = rep.brand or ""
            source_site = rep.source_site or ""

            # 그룹 내 다양한 상품명 샘플링 (최대 10개, 컬러 제거)
            seen_names: set[str] = set()
            sample_names: list[str] = []
            for p in products:
                n = p.name or ""
                if " - " in n:
                    n = n.split(" - ")[0].strip()
                if n and n not in seen_names:
                    seen_names.add(n)
                    sample_names.append(n)
                    if len(sample_names) >= 10:
                        break
            sample_str = "\n".join(f"  · {n}" for n in sample_names)

            # Claude API 호출
            prompt = (
                f"그룹 상품 정보 ({len(products)}개 상품):\n"
                f"- 브랜드: {brand}\n"
                f"- 카테고리: {category}\n"
                f"- 대표 상품명 (샘플 {len(sample_names)}개):\n{sample_str}\n\n"
                f"이 그룹의 모든 상품에 공통 적용할 검색용 태그를 25개 생성해주세요.\n"
                f"규칙:\n"
                f"1. 소비자가 네이버에서 실제로 검색할 만한 인기 키워드\n"
                f"2. 브랜드명('{brand}')은 제외\n"
                f"3. 한글로 작성\n"
                f"4. 쉼표로 구분하여 태그만 출력 (번호/설명 없이)\n"
                f"5. 수집사이트 이름(MUSINSA, 무신사, KREAM 등)은 제외\n"
                f"6. 브랜드명(나이키, 아디다스, 뉴발란스 등 모든 브랜드)은 절대 포함하지 마세요\n"
                f"7. 복합어보다 실제 검색에 사용되는 단순 키워드 위주 (예: 등산스니커즈(X) → 경량등산화(O))\n"
                f"8. 다양한 관점의 태그 필수 — 다음 카테고리별로 골고루 생성:\n"
                f"   - 용도/상황 (출근용, 데일리, 등산용, 캠핑, 여행)\n"
                f"   - 소재/기능 (고어텍스, 방수, 경량, 쿠션, 통기성)\n"
                f"   - 스타일/느낌 (캐주얼, 클래식, 빈티지, 트렌디)\n"
                f"   - 대상/성별 (남성, 여성, 남녀공용, 커플)\n"
                f"   - 시즌 (봄신발, 겨울신발, 사계절)\n"
                f"9. 같은 의미 단어 조합을 반복하지 마세요 (남성/남자, 여성/여자, 경량/가벼운 등 동의어는 하나만 사용)\n"
                f"10. 색상명(블랙, 화이트, 네이비, 그레이, 베이지, 카키, 레드, 블루 등)은 절대 포함하지 마세요 — 그룹 전체에 공통 적용됩니다\n"
            )

            try:
                # Claude API 호출 (429 rate limit 대비 최대 3회 재시도)
                resp = None
                for _attempt in range(3):
                    resp = await http_client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": model,
                            "max_tokens": 400,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    )
                    api_calls += 1
                    if resp.status_code == 429 and _attempt < 2:
                        import asyncio as _aio_tag

                        logger.warning(
                            f"[AI태그] Claude 429 rate limit — {30 * (_attempt + 1)}초 대기"
                        )
                        await _aio_tag.sleep(30 * (_attempt + 1))
                        continue
                    break
                if not resp or resp.status_code != 200:
                    logger.warning(
                        f"[AI태그] Claude 호출 실패: {resp.status_code if resp else 'no response'}"
                    )
                    failed_groups += 1
                    continue

                data = resp.json()
                usage = data.get("usage", {})
                total_input_tokens += usage.get("input_tokens", 0)
                total_output_tokens += usage.get("output_tokens", 0)
                text = data.get("content", [{}])[0].get("text", "")

                # 금지어 집합 생성
                banned, name_words, brand_words, ss_banned = _build_banned_set(
                    source_site,
                    brand,
                    cats,
                    rep_name,
                    ss_banned_cache,
                    db_brands_cache,
                )

                # 쉼표 구분 태그 파싱 + 금지어 필터링
                ai_tags = [
                    t.strip()
                    for t in text.split(",")
                    if _is_valid_tag(t, banned, name_words, ss_banned, brand_words)
                ]

                # AI 태그 중복 제거 (후보 전체 보존 — 태그사전 검증에서 탈락 대비)
                seen: set[str] = set()
                candidate_tags: list[str] = []
                for t in ai_tags:
                    tl = t.lower().replace(" ", "")
                    if tl not in seen:
                        seen.add(tl)
                        candidate_tags.append(t)

                if not candidate_tags:
                    continue

                # 태그사전 검증: 12개 선정 → 상위 2개 SEO + 나머지 10개 태그
                top12: list[str] = []
                if ss_client and candidate_tags:
                    try:
                        validated = await ss_client.validate_tags(
                            candidate_tags, max_count=15
                        )
                        top12 = [v["text"] for v in validated][:12]
                        if len(top12) < 12:
                            tag_set = set(top12)
                            for ct in candidate_tags:
                                if ct not in tag_set:
                                    top12.append(ct)
                                    tag_set.add(ct)
                                    if len(top12) >= 12:
                                        break
                        total_tag_dict_validated += len(top12)
                        total_tag_dict_rejected += len(candidate_tags) - len(top12)
                        logger.info(
                            f"[AI태그] 그룹 {gid}: 후보 {len(candidate_tags)}개 → 검증 {len(top12)}개"
                        )
                    except Exception as ve:
                        logger.error(
                            f"[AI태그] 태그사전 검증 예외 — 후보 태그 사용: {ve}"
                        )
                        top12 = candidate_tags[:12]
                else:
                    top12 = candidate_tags[:12]

                if not top12:
                    continue

                # 상위 2개 = SEO, 접미어 중복 시 앞 단어에서 공통 접미어 제거
                seo_kws = top12[:2]
                if len(seo_kws) == 2:
                    a, b = seo_kws[0], seo_kws[1]
                    # 공통 접미어 찾기 (뒤에서부터)
                    common = 0
                    for i in range(1, min(len(a), len(b)) + 1):
                        if a[-i] == b[-i]:
                            common = i
                        else:
                            break
                    if common >= 2:
                        prefix = a[:-common].strip()
                        if len(prefix) >= 1:
                            seo_kws[0] = prefix
                tags = top12[2:12]

                # 태그 생성 후 그룹 전체 상품 조회 → 벌크 적용
                all_in_group = await repo.filter_by_async(
                    search_filter_id=gid, limit=10000
                )
                for p in all_in_group:
                    existing = p.tags or []
                    merged = list(set(existing + tags + ["__ai_tagged__"]))
                    update_data: dict = {"tags": merged}
                    if seo_kws:
                        update_data["seo_keywords"] = seo_kws
                    await repo.update_async(p.id, **update_data)
                    total_tagged += 1

            except Exception as e:
                logger.error(f"[AI태그] 그룹 {gid} 실패: {e}")
                failed_groups += 1
                continue

    await session.commit()
    # 실비 계산 (Claude Sonnet 4.6: 입력 $3/1M, 출력 $15/1M, 환율 1400원)
    input_cost = total_input_tokens * 3 / 1_000_000 * 1400
    output_cost = total_output_tokens * 15 / 1_000_000 * 1400
    total_cost = round(input_cost + output_cost, 1)
    validated_msg = (
        f", 태그사전 통과 {total_tag_dict_validated}개/제외 {total_tag_dict_rejected}개"
        if ss_client
        else ""
    )
    fail_msg = f", 실패 {failed_groups}개 그룹" if failed_groups else ""
    return {
        "success": True,
        "message": f"태그 생성 완료 — {total_groups}개 그룹, {total_tagged}개 상품에 복사{fail_msg} (₩{total_cost}{validated_msg})",
        "total_tagged": total_tagged,
        "failed_groups": failed_groups,
        "api_calls": api_calls,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_krw": total_cost,
        "tag_dict_validated": total_tag_dict_validated,
        "tag_dict_rejected": total_tag_dict_rejected,
    }


@router.post("/ai-tags/preview")
async def preview_ai_tags(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """선택 상품의 그룹별 대표 1개로 Claude 태그 20개 생성 → 적용하지 않고 미리보기 반환."""
    from backend.domain.samba.collector.repository import (
        SambaCollectedProductRepository,
    )

    product_ids = request.get("product_ids", [])
    req_group_ids = request.get("group_ids", [])
    logger.info(
        f"[AI태그 미리보기] 요청: product_ids={len(product_ids)}개, group_ids={req_group_ids}"
    )

    if not product_ids and not req_group_ids:
        return {"success": False, "message": "상품 또는 그룹을 선택해주세요"}

    # Claude API 키 조회
    creds = await _get_setting(session, "claude")
    if not creds or not isinstance(creds, dict) or not creds.get("apiKey"):
        return {"success": False, "message": "Claude API 설정이 없습니다"}
    api_key = str(creds["apiKey"]).strip()
    model = str(creds.get("model", "claude-sonnet-4-6"))

    repo = SambaCollectedProductRepository(session)

    # 그룹 ID 수집
    group_ids: set[str] = set(req_group_ids)
    ungrouped: list = []
    for pid in product_ids:
        product = await repo.get_async(pid)
        if not product:
            continue
        if product.search_filter_id:
            group_ids.add(product.search_filter_id)
        else:
            ungrouped.append(product)

    # 그룹별 상품 조회
    groups: dict[str, list] = {}
    for gid in group_ids:
        all_in_group = await repo.filter_by_async(search_filter_id=gid, limit=10000)
        if all_in_group:
            groups[gid] = list(all_in_group)
    for p in ungrouped:
        groups[p.id] = [p]

    if not groups:
        return {"success": False, "message": "상품을 찾을 수 없습니다"}

    # 그룹명 조회
    from backend.domain.samba.collector.model import SambaSearchFilter as _SF_tag

    _filter_names: dict[str, str] = {}
    for gid in group_ids:
        sf = await session.get(_SF_tag, gid)
        if sf:
            _filter_names[gid] = sf.name or gid

    # 그룹별 태그 미리보기 결과
    preview_results: list[dict[str, Any]] = []
    failed_groups = 0
    api_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0

    # 금지태그/브랜드 목록 1회 로드
    ss_banned_cache, db_brands_cache = await _load_tag_filter_data(session)

    # 스마트스토어 클라이언트 초기화 (태그사전 검증용)
    ss_client_preview = await _get_smartstore_tag_client(session)

    async with httpx.AsyncClient(timeout=30) as http_client:
        for gid, products in groups.items():
            rep = products[0]
            rep_name = rep.name or ""
            cats = [rep.category1, rep.category2, rep.category3, rep.category4]
            category = " > ".join(c for c in cats if c) or rep.category or ""
            brand = rep.brand or ""
            source_site = rep.source_site or ""

            # 그룹 내 다양한 상품명 샘플링 (최대 10개, 컬러 제거)
            seen_names: set[str] = set()
            sample_names: list[str] = []
            for p in products:
                n = p.name or ""
                if " - " in n:
                    n = n.split(" - ")[0].strip()
                if n and n not in seen_names:
                    seen_names.add(n)
                    sample_names.append(n)
                    if len(sample_names) >= 10:
                        break
            sample_str = "\n".join(f"  · {n}" for n in sample_names)

            # Claude API 호출 (25개 요청 — 태그사전 검증 탈락 대비 여유분)
            prompt = (
                f"그룹 상품 정보 ({len(products)}개 상품):\n"
                f"- 브랜드: {brand}\n"
                f"- 카테고리: {category}\n"
                f"- 대표 상품명 (샘플 {len(sample_names)}개):\n{sample_str}\n\n"
                f"이 그룹의 모든 상품에 공통 적용할 검색용 태그를 25개 생성해주세요.\n"
                f"규칙:\n"
                f"1. 소비자가 네이버에서 실제로 검색할 만한 인기 키워드\n"
                f"2. 브랜드명('{brand}')은 제외\n"
                f"3. 한글로 작성\n"
                f"4. 쉼표로 구분하여 태그만 출력 (번호/설명 없이)\n"
                f"5. 수집사이트 이름(MUSINSA, 무신사, KREAM 등)은 제외\n"
                f"6. 브랜드명(나이키, 아디다스, 뉴발란스 등 모든 브랜드)은 절대 포함하지 마세요\n"
                f"7. 복합어보다 실제 검색에 사용되는 단순 키워드 위주 (예: 등산스니커즈(X) → 경량등산화(O))\n"
                f"8. 다양한 관점의 태그 필수 — 다음 카테고리별로 골고루 생성:\n"
                f"   - 용도/상황 (출근용, 데일리, 등산용, 캠핑, 여행)\n"
                f"   - 소재/기능 (고어텍스, 방수, 경량, 쿠션, 통기성)\n"
                f"   - 스타일/느낌 (캐주얼, 클래식, 빈티지, 트렌디)\n"
                f"   - 대상/성별 (남성, 여성, 남녀공용, 커플)\n"
                f"   - 시즌 (봄신발, 겨울신발, 사계절)\n"
                f"9. 같은 의미 단어 조합을 반복하지 마세요 (남성/남자, 여성/여자, 경량/가벼운 등 동의어는 하나만 사용)\n"
                f"10. 색상명(블랙, 화이트, 네이비, 그레이, 베이지, 카키, 레드, 블루 등)은 절대 포함하지 마세요 — 그룹 전체에 공통 적용됩니다\n"
            )

            try:
                # Claude API 호출 (429 rate limit 대비 최대 3회 재시도)
                resp = None
                for _attempt in range(3):
                    resp = await http_client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": model,
                            "max_tokens": 400,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                    )
                    api_calls += 1
                    if resp.status_code == 429 and _attempt < 2:
                        import asyncio as _aio_tag

                        logger.warning(
                            f"[AI태그 미리보기] Claude 429 rate limit — {30 * (_attempt + 1)}초 대기"
                        )
                        await _aio_tag.sleep(30 * (_attempt + 1))
                        continue
                    break
                if not resp or resp.status_code != 200:
                    logger.warning(
                        f"[AI태그 미리보기] Claude 호출 실패: {resp.status_code if resp else 'no response'}"
                    )
                    failed_groups += 1
                    continue

                data = resp.json()
                usage = data.get("usage", {})
                total_input_tokens += usage.get("input_tokens", 0)
                total_output_tokens += usage.get("output_tokens", 0)
                text = data.get("content", [{}])[0].get("text", "")

                # 금지어 집합 생성
                banned, name_words, brand_words, ss_banned = _build_banned_set(
                    source_site,
                    brand,
                    cats,
                    rep_name,
                    ss_banned_cache,
                    db_brands_cache,
                )

                # 중복 제거 후 후보 전체 보존
                seen: set[str] = set()
                candidate_tags: list[str] = []
                for t in text.split(","):
                    t = t.strip()
                    if not _is_valid_tag(t, banned, name_words, ss_banned, brand_words):
                        continue
                    tl = t.lower().replace(" ", "")
                    if tl not in seen:
                        seen.add(tl)
                        candidate_tags.append(t)

                # 태그사전 검증 — 10개 필수
                # 태그사전 검증: 12개 선정 → 상위 2개 SEO + 나머지 10개 태그
                top12_preview: list[str] = []
                rejected_tags: list[str] = []
                tag_validation_error = ""
                if ss_client_preview and candidate_tags:
                    try:
                        validated = await ss_client_preview.validate_tags(
                            candidate_tags, max_count=15
                        )
                        top12_preview = [v["text"] for v in validated][:12]
                        if len(top12_preview) < 12:
                            vt_set = set(top12_preview)
                            for ct in candidate_tags:
                                if ct not in vt_set:
                                    top12_preview.append(ct)
                                    vt_set.add(ct)
                                    if len(top12_preview) >= 12:
                                        break
                        rejected_tags = [
                            t for t in candidate_tags if t not in set(top12_preview)
                        ]
                    except Exception as ve:
                        tag_validation_error = str(ve)
                        logger.error(
                            f"[AI태그] 태그사전 검증 예외 — 후보 태그 사용: {ve}"
                        )
                        top12_preview = candidate_tags[:12]
                else:
                    top12_preview = candidate_tags[:12]

                # 상위 2개 = SEO, 접미어 중복 시 앞 단어에서 공통 접미어 제거
                seo_preview = top12_preview[:2]
                if len(seo_preview) == 2:
                    _a, _b = seo_preview[0], seo_preview[1]
                    _common = 0
                    for _i in range(1, min(len(_a), len(_b)) + 1):
                        if _a[-_i] == _b[-_i]:
                            _common = _i
                        else:
                            break
                    if _common >= 2:
                        _prefix = _a[:-_common].strip()
                        if len(_prefix) >= 1:
                            seo_preview[0] = _prefix
                validated_tags = top12_preview[2:12]

                preview_results.append(
                    {
                        "group_id": gid,
                        "group_name": _filter_names.get(gid, rep_name),
                        "product_count": len(products),
                        "rep_name": rep_name,
                        "tags": validated_tags,
                        "rejected_tags": rejected_tags,
                        "seo_keywords": seo_preview,
                        "candidate_count": len(candidate_tags),
                        "candidates": candidate_tags[:15],
                        "validation_error": tag_validation_error,
                    }
                )

            except Exception as e:
                logger.error(f"[AI태그 미리보기] 그룹 {gid} 실패: {e}")
                failed_groups += 1
                continue

    # 비용 계산
    input_cost = total_input_tokens * 3 / 1_000_000 * 1400
    output_cost = total_output_tokens * 15 / 1_000_000 * 1400
    total_cost = round(input_cost + output_cost, 1)

    fail_msg = f", 실패 {failed_groups}개 그룹" if failed_groups else ""
    return {
        "success": True,
        "message": f"{len(preview_results)}개 그룹 태그 미리보기 생성 완료{fail_msg} (₩{total_cost})",
        "previews": preview_results,
        "failed_groups": failed_groups,
        "api_calls": api_calls,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_krw": total_cost,
    }


@router.post("/ai-tags/apply")
async def apply_ai_tags(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """사용자가 확정한 태그를 그룹 전체 상품에 적용."""
    from backend.domain.samba.collector.repository import (
        SambaCollectedProductRepository,
    )

    # groups: [{ group_id, tags: [...] }]
    groups_data = request.get("groups", [])
    removed_tags = request.get("removed_tags", [])
    if not groups_data:
        return {"success": False, "message": "적용할 태그 데이터가 없습니다"}

    # 삭제된 태그를 금지태그(smartstore_banned_tags)에 추가
    banned_added = 0
    if removed_tags:
        try:
            from backend.domain.samba.forbidden.repository import (
                SambaSettingsRepository,
            )

            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="smartstore_banned_tags")
            existing_banned: list[str] = (
                row.value if row and isinstance(row.value, list) else []
            )
            existing_lower = {w.lower() for w in existing_banned}
            for tag in removed_tags:
                if tag.lower() not in existing_lower:
                    existing_banned.append(tag)
                    existing_lower.add(tag.lower())
                    banned_added += 1
            if banned_added > 0:
                await settings_repo.upsert_async(
                    key="smartstore_banned_tags", value=existing_banned
                )
                logger.info(
                    f"[AI태그] 금지태그 {banned_added}개 추가: {removed_tags[:5]}"
                )
        except Exception as e:
            logger.warning(f"[AI태그] 금지태그 저장 실패: {e}")

    repo = SambaCollectedProductRepository(session)
    total_tagged = 0

    for group in groups_data:
        gid = group.get("group_id", "")
        tags = group.get("tags", [])
        if not gid or not tags:
            continue

        # 그룹 상품 조회
        products = await repo.filter_by_async(search_filter_id=gid, limit=10000)
        if not products:
            # 개별 상품 (그룹 없는 경우)
            product = await repo.get_async(gid)
            if product:
                products = [product]
            else:
                continue

        # SEO 키워드: 프론트에서 수정한 값 우선, 없으면 자동 추출 (태그와 중복 방지)
        seo_kws: list[str] = group.get("seo_keywords", [])
        if not seo_kws:
            tag_lower_set = {t.lower().replace(" ", "") for t in tags}
            ordered = list(tags[10:]) + list(tags[:10])
            for kw in ordered:
                for word in kw.split():
                    w = word.strip()
                    wl = w.lower().replace(" ", "")
                    if len(w) >= 2 and wl not in tag_lower_set and w not in seo_kws:
                        seo_kws.append(w)
                        if len(seo_kws) >= 2:
                            break
                if len(seo_kws) >= 2:
                    break

        # 그룹 내 모든 상품에 적용 (개별 커밋 없이 일괄 처리)
        from sqlalchemy.orm.attributes import flag_modified as _fm
        from datetime import datetime as _dt, UTC as _utc

        for p in products:
            existing = p.tags or []
            merged = list(set(existing + tags + ["__ai_tagged__"]))
            p.tags = merged
            _fm(p, "tags")
            if seo_kws:
                p.seo_keywords = seo_kws
                _fm(p, "seo_keywords")
            if hasattr(p, "updated_at"):
                p.updated_at = _dt.now(_utc)
            session.add(p)
            total_tagged += 1

    await session.commit()
    return {
        "success": True,
        "message": f"{len(groups_data)}개 그룹, {total_tagged}개 상품에 태그 적용 완료"
        + (f" (금지태그 {banned_added}개 추가)" if banned_added else ""),
        "total_tagged": total_tagged,
        "banned_added": banned_added,
    }


# ═══════════════════════════════════════════════
# 이미지 필터링 (모델컷/연출컷/배너 자동 제거)
# ═══════════════════════════════════════════════


@router.post("/image-filter/filter")
async def filter_product_images(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """상품 이미지 자동 필터링 — 이미지컷만 남기고 모델컷/연출컷/배너 제거."""
    from backend.domain.samba.image.image_filter_service import ImageFilterService

    svc = ImageFilterService(session)
    product_ids: list[str] = request.get("product_ids", [])
    filter_id: str = request.get("filter_id", "")
    scope: str = request.get("scope", "images")  # images | detail | all
    method: str = request.get("method", "claude")  # claude | clip

    # filter_id로 요청 시 해당 그룹의 상품 ID 조회 (product_ids 우선)
    if filter_id and not product_ids:
        try:
            result = await svc.filter_by_group(filter_id, scope=scope, method=method)
            return result
        except Exception as exc:
            logger.error(f"[이미지필터] 그룹 필터링 실패: {exc}")
            return {"success": False, "message": str(exc)[:300]}

    if not product_ids:
        return {"success": False, "message": "product_ids 또는 filter_id를 입력하세요."}

    try:
        result = await svc.batch_filter(product_ids, scope=scope, method=method)
        return result
    except Exception as exc:
        logger.error(f"[이미지필터] 배치 필터링 실패: {exc}")
        return {"success": False, "message": str(exc)[:300]}


@router.post("/image-filter/compare")
async def compare_image_filter_methods(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """Claude vs CLIP 정확도 비교 — 같은 이미지에 둘 다 돌려서 결과 비교."""
    from backend.domain.samba.image.image_filter_service import ImageFilterService

    svc = ImageFilterService(session)
    urls: list[str] = request.get("urls", [])
    product_id: str = request.get("product_id", "")

    # product_id가 있으면 해당 상품 이미지 URL 조회
    if product_id and not urls:
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )

        repo = SambaCollectedProductRepository(session)
        product = await repo.get_async(product_id)
        if not product:
            return {"success": False, "message": "상품을 찾을 수 없습니다."}
        urls = product.images or []

    if not urls:
        return {"success": False, "message": "urls 또는 product_id를 입력하세요."}

    try:
        result = await svc.compare_methods(urls)
        return {"success": True, **result}
    except Exception as exc:
        logger.error(f"[이미지필터] 비교 실패: {exc}")
        return {"success": False, "message": str(exc)[:300]}


# ═══════════════════════════════════════════════
# 통합 소싱 (패션플러스: 직접 API / 나머지 5개: 확장앱 큐)
# ═══════════════════════════════════════════════

EXTENSION_SITES = {
    "ABCmart",
    "GrandStage",
    "OKmall",
    "LOTTEON",
    "GSShop",
    "ElandMall",
    "SSF",
}


def _get_sourcing_client(site: str):
    """직접 API 클라이언트 반환."""
    s = site.lower()
    if s in ("fashionplus", "fp"):
        from backend.domain.samba.proxy.fashionplus import FashionPlusClient

        return FashionPlusClient()
    if s == "nike":
        from backend.domain.samba.proxy.nike import NikeClient

        return NikeClient()
    if s == "adidas":
        from backend.domain.samba.proxy.adidas import AdidasClient

        return AdidasClient()
    return None


@router.get("/sourcing/collect-queue")
async def sourcing_collect_queue() -> dict[str, Any]:
    """확장앱이 폴링하는 소싱 수집 큐."""
    from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

    return SourcingQueue.get_next_job()


@router.post("/sourcing/collect-result")
async def sourcing_collect_result(body: dict[str, Any]) -> dict[str, Any]:
    """확장앱이 수집 결과를 전달."""
    from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

    request_id = body.get("requestId", "")
    data = body.get("data", {})
    ok = SourcingQueue.resolve_job(request_id, data)
    return {"success": ok}


@router.get("/sourcing/{site}/search")
async def sourcing_search(
    site: str,
    keyword: str = Query("", min_length=1),
    page: int = Query(1, ge=1),
) -> dict[str, Any]:
    """소싱처 통합 검색 API."""
    # 패션플러스: 직접 API
    client = _get_sourcing_client(site)
    if client:
        return await client.search(keyword, page)

    # 확장앱 기반 사이트
    if site in EXTENSION_SITES:
        from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

        try:
            request_id, future = SourcingQueue.add_search_job(site, keyword)
            result = await asyncio.wait_for(future, timeout=60)
            return result
        except asyncio.TimeoutError:
            SourcingQueue.resolvers.pop(request_id, None)
            return {"products": [], "total": 0, "error": "확장앱 응답 타임아웃 (60초)"}
        except Exception as e:
            return {"products": [], "total": 0, "error": str(e)}

    raise HTTPException(400, f"지원하지 않는 소싱처: {site}")


@router.get("/sourcing/{site}/detail/{product_id}")
async def sourcing_detail(
    site: str,
    product_id: str,
) -> dict[str, Any]:
    """소싱처 상품 상세 조회 API."""
    # 패션플러스: 직접 API
    client = _get_sourcing_client(site)
    if client:
        return await client.get_detail(product_id)

    # 확장앱 기반 사이트
    if site in EXTENSION_SITES:
        from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

        try:
            request_id, future = SourcingQueue.add_detail_job(site, product_id)
            result = await asyncio.wait_for(future, timeout=60)
            return result
        except asyncio.TimeoutError:
            SourcingQueue.resolvers.pop(request_id, None)
            return {"error": "확장앱 응답 타임아웃 (60초)"}
        except Exception as e:
            return {"error": str(e)}

    raise HTTPException(400, f"지원하지 않는 소싱처: {site}")


# ═══════════════════════════════════════════════
# 무신사 (Musinsa) endpoints
# ═══════════════════════════════════════════════


@router.get("/musinsa/goods/{goods_no}")
async def musinsa_goods_detail(
    goods_no: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """무신사 상품 상세 조회."""
    if not goods_no or not goods_no.isdigit():
        raise HTTPException(status_code=400, detail="유효하지 않은 상품번호입니다.")

    client = await _get_musinsa_client(session)
    try:
        product = await client.get_goods_detail(goods_no)
        return {"success": True, "data": product}
    except Exception as exc:
        logger.error(f"[무신사] {goods_no} 수집 실패: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/search-count")
async def search_count(
    source_site: str = Query(...),
    keyword: str = Query(""),
    url: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """소싱처별 검색 총 상품수 조회."""
    try:
        if source_site == "MUSINSA":
            client = await _get_musinsa_client(session)
            params: dict[str, Any] = {"keyword": keyword, "size": 1}
            if url:
                from urllib.parse import urlparse, parse_qs

                parsed = parse_qs(urlparse(url).query)
                if "brand" in parsed:
                    params["brand"] = parsed["brand"][0]
                if "category" in parsed:
                    params["category"] = parsed["category"][0]
                if "gf" in parsed:
                    params["gf"] = parsed["gf"][0]
                if "minPrice" in parsed:
                    params["min_price"] = int(parsed["minPrice"][0])
                if "maxPrice" in parsed:
                    params["max_price"] = int(parsed["maxPrice"][0])
                if not keyword and "keyword" in parsed:
                    params["keyword"] = parsed["keyword"][0]
            result = await client.search_products(**params)
            return {"totalCount": result.get("totalCount", 0)}

        elif source_site == "FashionPlus":
            search_word = keyword
            if not search_word and url:
                from urllib.parse import urlparse, parse_qs

                parsed = parse_qs(urlparse(url).query)
                search_word = parsed.get("searchWord", [""])[0]
            if not search_word:
                return {"totalCount": 0}
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.get(
                    "https://www.fashionplus.co.kr/search/goods/fetch",
                    params={
                        "searchWord": search_word,
                        "page": 1,
                        "pageSize": 1,
                        "sort": "recommend",
                    },
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                data = r.json()
                return {
                    "totalCount": data.get("goodsPaginator", {}).get("totalCount", 0)
                }

        elif source_site == "KREAM":
            # KREAM은 확장앱 기반 수집 — 카운트 조회 불가
            return {"totalCount": 0}

        elif source_site in ("ABCmart", "Nike", "Adidas", "OliveYoung"):
            # 이 소싱처들은 서버사이드 렌더링/확장앱 기반 — 카운트 조회 불가
            return {"totalCount": 0}

        else:
            return {"totalCount": 0}

    except Exception as e:
        logger.warning(f"[검색카운트] {source_site} 실패: {e}")
        return {"totalCount": 0}


@router.get("/musinsa/search-api")
async def musinsa_search_api(
    keyword: str = Query("", description="검색 키워드"),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=200),
    sort: str = Query("POPULAR"),
    category: str = Query(""),
    brand: str = Query(""),
    min_price: Optional[int] = Query(None, alias="minPrice"),
    max_price: Optional[int] = Query(None, alias="maxPrice"),
    gf: str = Query("A"),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """무신사 상품 검색 API."""
    if not keyword:
        raise HTTPException(status_code=400, detail="검색 키워드를 입력해주세요.")

    client = await _get_musinsa_client(session)
    try:
        return await client.search_products(
            keyword=keyword,
            page=page,
            size=size,
            sort=sort,
            category=category,
            brand=brand,
            min_price=min_price,
            max_price=max_price,
            gf=gf,
        )
    except Exception as exc:
        logger.error(f"[무신사] 검색 실패: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/musinsa/search")
async def musinsa_search_by_url(
    url: str = Query("", description="무신사 URL"),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """URL 기반 검색/리다이렉트 처리."""
    if not url or ("musinsa.com" not in url and "musinsa.onelink.me" not in url):
        raise HTTPException(status_code=400, detail="무신사 URL을 입력해주세요.")

    client = await _get_musinsa_client(session)
    try:
        return await client.search_by_url(url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class MusinsaSetCookieRequest(BaseModel):
    cookie: str


@router.post("/musinsa/set-cookie")
async def musinsa_set_cookie(
    body: MusinsaSetCookieRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """브라우저 확장에서 쿠키 직접 전달."""
    client = MusinsaClient(cookie=body.cookie)
    result = await client.set_cookie_and_verify(body.cookie)
    # DB에 저장
    await _set_setting(write_session, "musinsa_cookie", body.cookie)
    return result


class MusinsaCheckLoginRequest(BaseModel):
    cookie: Optional[str] = None


@router.post("/musinsa/check-login")
async def musinsa_check_login(
    body: MusinsaCheckLoginRequest = MusinsaCheckLoginRequest(),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """무신사 로그인 상태 확인."""
    client = await _get_musinsa_client(session)
    return await client.check_login_status(cookie=body.cookie)


@router.get("/musinsa/auth/status")
async def musinsa_auth_status(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """무신사 인증 상태 확인."""
    cookie = await _get_setting(session, "musinsa_cookie") or ""
    return {"isLoggedIn": bool(cookie), "cookieLength": len(str(cookie))}


@router.delete("/musinsa/auth")
async def musinsa_auth_delete(
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """무신사 쿠키 초기화 (로그아웃)."""
    await _set_setting(write_session, "musinsa_cookie", "")
    return {"success": True, "isLoggedIn": False, "message": "로그아웃 완료"}


class MusinsaCookiesRequest(BaseModel):
    cookies: list[str]


@router.post("/musinsa/cookies")
async def set_musinsa_cookies(
    body: MusinsaCookiesRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """무신사 쿠키 로테이션 목록 저장."""
    import json

    await _set_setting(write_session, "musinsa_cookies", json.dumps(body.cookies))
    return {"ok": True, "count": len(body.cookies)}


@router.get("/musinsa/cookies")
async def get_musinsa_cookies(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """무신사 쿠키 로테이션 목록 조회."""
    import json

    raw = await _get_setting(session, "musinsa_cookies")
    if raw:
        cookies = json.loads(raw) if isinstance(raw, str) else raw
        return {"cookies": cookies, "count": len(cookies)}
    return {"cookies": [], "count": 0}


class StockCheckRequest(BaseModel):
    goodsNos: list[str]


@router.post("/musinsa/stock-check")
async def musinsa_stock_check(
    body: StockCheckRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """재고 소진 감지 (서브에이전트)."""
    if not body.goodsNos:
        raise HTTPException(status_code=400, detail="goodsNos 배열이 필요합니다.")

    client = await _get_musinsa_client(session)
    return await client.check_stock(body.goodsNos)


class PriceMonitorProduct(BaseModel):
    goodsNo: str
    storedPrice: int = 0
    productId: Optional[str] = None


class PriceMonitorRequest(BaseModel):
    products: list[PriceMonitorProduct]


@router.post("/musinsa/price-monitor")
async def musinsa_price_monitor(
    body: PriceMonitorRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """가격 변동 감지 (서브에이전트)."""
    if not body.products:
        raise HTTPException(status_code=400, detail="products 배열이 필요합니다.")

    client = await _get_musinsa_client(session)
    products_dicts = [p.model_dump() for p in body.products]
    return await client.monitor_prices(products_dicts)


# ═══════════════════════════════════════════════
# KREAM endpoints
# ═══════════════════════════════════════════════

# 확장앱 큐: KreamClient 클래스 레벨 큐 사용 (collector.py와 공유)
# KreamClient.collect_queue, KreamClient.collect_resolvers
# KreamClient.search_queue, KreamClient.search_resolvers


class KreamLoginRequest(BaseModel):
    email: str
    password: str


@router.post("/kream/login")
async def kream_login(
    body: KreamLoginRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """KREAM 로그인."""
    client = KreamClient()
    result = await client.login(body.email, body.password)
    if result.get("success") and client.token:
        await _set_setting(write_session, "kream_token", client.token)
    return result


@router.get("/kream/auth/status")
async def kream_auth_status(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 인증 상태 확인."""
    client = await _get_kream_client(session)
    return await client.check_auth_status()


@router.delete("/kream/auth")
async def kream_auth_delete(
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """KREAM 로그아웃."""
    await _set_setting(write_session, "kream_token", "")
    await _set_setting(write_session, "kream_cookie", "")
    return {"success": True, "message": "KREAM 로그아웃 완료"}


class KreamSetTokenRequest(BaseModel):
    token: str
    userId: Optional[str] = None


@router.post("/kream/set-token")
async def kream_set_token(
    body: KreamSetTokenRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """KREAM 토큰 직접 설정."""
    if not body.token:
        raise HTTPException(status_code=400, detail="토큰을 입력해주세요.")
    await _set_setting(write_session, "kream_token", body.token)
    return {"success": True, "message": "토큰이 설정되었습니다."}


class KreamSetCookieRequest(BaseModel):
    cookie: str


@router.post("/kream/set-cookie")
async def kream_set_cookie(
    body: KreamSetCookieRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """확장앱에서 KREAM 쿠키 수신."""
    if not body.cookie:
        raise HTTPException(status_code=400, detail="쿠키가 필요합니다.")
    await _set_setting(write_session, "kream_cookie", body.cookie)
    cookie_count = len(body.cookie.split(";"))
    logger.info(f"[KREAM] 확장앱에서 쿠키 수신: {cookie_count}개")
    return {"success": True, "cookieCount": cookie_count}


# -- 확장앱 큐 방식 (수집) --


@router.get("/kream/collect-queue")
async def kream_collect_queue_poll() -> dict[str, Any]:
    """확장앱이 폴링: 대기 중인 수집 요청 가져가기."""
    if not KreamClient.collect_queue:
        return {"hasJob": False}
    job = KreamClient.collect_queue.pop(0)
    return {"hasJob": True, **job}


class KreamCollectResultRequest(BaseModel):
    requestId: str
    data: Any


@router.post("/kream/collect-result")
async def kream_collect_result(body: KreamCollectResultRequest) -> dict[str, Any]:
    """확장앱이 수집 완료 후 결과 전달."""
    future = KreamClient.collect_resolvers.get(body.requestId)
    if future and not future.done():
        future.set_result(body.data)
        KreamClient.collect_resolvers.pop(body.requestId, None)
        logger.info(f"[KREAM] 확장앱 수집 결과 수신: {body.requestId}")
    return {"success": True}


@router.get("/kream/products/{product_id}")
async def kream_product_detail(product_id: str) -> dict[str, Any]:
    """KREAM 상품 상세 조회 (확장앱 큐 방식, 최대 90초 대기)."""
    if not product_id:
        raise HTTPException(status_code=400, detail="상품 ID가 필요합니다.")

    client = KreamClient()
    try:
        return await client.get_product(product_id)
    except Exception as exc:
        raise HTTPException(status_code=504, detail=str(exc))


# -- 확장앱 큐 방식 (검색) --


@router.get("/kream/search-queue")
async def kream_search_queue_poll() -> dict[str, Any]:
    """확장앱이 3초마다 폴링: 대기 중인 검색 요청 가져가기."""
    if not KreamClient.search_queue:
        return {"hasJob": False}
    job = KreamClient.search_queue.pop(0)
    return {"hasJob": True, **job}


class KreamSearchResultRequest(BaseModel):
    requestId: str
    data: Any


@router.post("/kream/search-result")
async def kream_search_result(body: KreamSearchResultRequest) -> dict[str, Any]:
    """확장앱이 검색 완료 후 결과 전달."""
    future = KreamClient.search_resolvers.get(body.requestId)
    if future and not future.done():
        future.set_result(body.data)
        KreamClient.search_resolvers.pop(body.requestId, None)
        logger.info(f"[KREAM] 확장앱 검색 결과 수신: {body.requestId}")
    return {"success": True}


@router.get("/kream/search")
async def kream_search(
    keyword: str = Query("", description="검색 키워드"),
) -> dict[str, Any]:
    """KREAM 상품 검색 (확장앱 큐 방식, 최대 90초 대기)."""
    if not keyword:
        raise HTTPException(status_code=400, detail="검색 키워드를 입력해주세요.")

    client = KreamClient()
    try:
        items = await client.search(keyword)
        return {"success": True, "data": items}
    except Exception as exc:
        raise HTTPException(status_code=504, detail=str(exc))


@router.get("/kream/products/{product_id}/prices")
async def kream_product_prices(
    product_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 사이즈별 시세 조회."""
    client = await _get_kream_client(session)
    result = await client.get_prices(product_id)
    if not result.get("success"):
        status = 401 if "쿠키" in result.get("message", "") else 500
        raise HTTPException(status_code=status, detail=result.get("message"))
    return result


class KreamSellBidRequest(BaseModel):
    productId: str
    size: str
    price: int
    saleType: str = "general"


@router.post("/kream/sell/bid")
async def kream_sell_bid(
    body: KreamSellBidRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 매도 입찰 등록."""
    client = await _get_kream_client(session)
    if not client.token:
        raise HTTPException(status_code=401, detail="KREAM 로그인이 필요합니다.")

    result = await client.create_ask(
        product_id=body.productId,
        size=body.size,
        price=body.price,
        sale_type=body.saleType,
    )
    if not result.get("success"):
        raise HTTPException(
            status_code=400, detail=result.get("message", "매도 입찰 실패")
        )
    return result


class KreamUpdateBidRequest(BaseModel):
    price: int


@router.put("/kream/sell/bid/{ask_id}")
async def kream_update_bid(
    ask_id: str,
    body: KreamUpdateBidRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 매도 입찰 수정."""
    client = await _get_kream_client(session)
    return await client.update_ask(ask_id, body.price)


@router.delete("/kream/sell/bid/{ask_id}")
async def kream_cancel_bid(
    ask_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 매도 입찰 취소."""
    client = await _get_kream_client(session)
    return await client.cancel_ask(ask_id)


@router.get("/kream/sell/my-bids")
async def kream_my_bids(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """KREAM 내 매도 입찰 목록."""
    client = await _get_kream_client(session)
    if not client.token:
        raise HTTPException(status_code=401, detail="KREAM 로그인이 필요합니다.")
    return await client.get_my_asks()


@router.get("/kream/image-proxy")
async def kream_image_proxy(
    url: str = Query("", description="이미지 URL"),
) -> Response:
    """이미지 프록시 (KREAM 이미지 CORS 우회)."""
    if not url:
        raise HTTPException(status_code=400, detail="URL 필요")
    try:
        from urllib.parse import unquote

        image_bytes, content_type = await KreamClient.proxy_image(unquote(url))
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ═══════════════════════════════════════════════
# 롯데홈쇼핑 (Lotte Home Shopping) endpoints
# ═══════════════════════════════════════════════


class LotteAuthRequest(BaseModel):
    userId: str
    password: str
    agncNo: Optional[str] = ""
    env: Optional[str] = "test"


@router.post("/lottehome/auth")
async def lottehome_auth(
    body: LotteAuthRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 인증키 발급."""
    if not body.userId or not body.password:
        raise HTTPException(
            status_code=400, detail="협력업체ID와 비밀번호를 입력해주세요."
        )
    # DB에 자격증명 저장
    await _set_setting(
        write_session,
        "lottehome_credentials",
        {
            "userId": body.userId,
            "password": body.password,
            "agncNo": body.agncNo or "",
            "env": body.env or "test",
        },
    )
    client = LotteHomeClient(
        user_id=body.userId,
        password=body.password,
        agnc_no=body.agncNo or "",
        env=body.env or "test",
    )
    try:
        return await client.authenticate()
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}
    except Exception as exc:
        return {"success": False, "message": str(exc), "code": "AUTH_FAILED"}


@router.get("/lottehome/auth/status")
async def lottehome_auth_status(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 캐시된 인증 상태."""
    # 상태 없음 반환 (서버 인스턴스별 인증 캐시는 LotteHomeClient 인스턴스에 있으므로)
    return {"authenticated": False, "message": "인증 정보 없음 (재인증 필요)"}


@router.get("/lottehome/brands")
async def lottehome_brands(
    brnd_nm: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 브랜드 목록 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_brands(brnd_nm)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/categories")
async def lottehome_categories(
    disp_tp_cd: str = Query(""),
    md_gsgr_no: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 전시카테고리 목록 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_categories(disp_tp_cd, md_gsgr_no)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/md-groups")
async def lottehome_md_groups(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 MD상품군 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_md_groups()
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/delivery-policies")
async def lottehome_delivery_policies(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 배송비정책 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_delivery_policies()
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/delivery-places")
async def lottehome_delivery_places(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 배송지 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_return_places()
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.post("/lottehome/goods")
async def lottehome_register_goods(
    goods_data: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 신규상품등록."""
    client = await _get_lotte_client(session)
    try:
        result = await client.register_goods(goods_data)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.put("/lottehome/goods/new/{goods_req_no}")
async def lottehome_update_new_goods(
    goods_req_no: str,
    goods_data: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 신규상품수정."""
    client = await _get_lotte_client(session)
    try:
        result = await client.update_new_goods(goods_req_no, goods_data)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.put("/lottehome/goods/display/{goods_no}")
async def lottehome_update_display_goods(
    goods_no: str,
    goods_data: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 전시상품수정."""
    client = await _get_lotte_client(session)
    try:
        result = await client.update_display_goods(goods_no, goods_data)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class LotteSaleStatusRequest(BaseModel):
    sale_stat_cd: str = "20"


@router.patch("/lottehome/goods/{goods_no}/status")
async def lottehome_sale_status(
    goods_no: str,
    body: LotteSaleStatusRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 판매상태 변경."""
    client = await _get_lotte_client(session)
    try:
        result = await client.update_sale_status(goods_no, body.sale_stat_cd)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class LotteStockUpdateRequest(BaseModel):
    goods_no: str
    item_no: str
    inv_qty: int


@router.put("/lottehome/stock")
async def lottehome_update_stock(
    body: LotteStockUpdateRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 재고수정."""
    client = await _get_lotte_client(session)
    try:
        result = await client.update_stock(body.goods_no, body.item_no, body.inv_qty)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/lottehome/stock")
async def lottehome_search_stock(
    goods_no: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """롯데홈쇼핑 재고 조회."""
    client = await _get_lotte_client(session)
    try:
        result = await client.search_stock(goods_no)
        return {"success": True, "data": result.get("data")}
    except LotteApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


# ═══════════════════════════════════════════════
# GS샵 (GS Shop) endpoints
# ═══════════════════════════════════════════════


class GsShopCredsRequest(BaseModel):
    supCd: str
    aesKey: str
    subSupCd: Optional[str] = ""
    env: Optional[str] = "dev"


@router.post("/gsshop/auth/save")
async def gsshop_save_credentials(
    body: GsShopCredsRequest,
    write_session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """GS샵 자격증명 저장."""
    await _set_setting(
        write_session,
        "gsshop_credentials",
        {
            "supCd": body.supCd,
            "aesKey": body.aesKey,
            "subSupCd": body.subSupCd or "",
            "env": body.env or "dev",
        },
    )
    return {"success": True, "message": "GS샵 자격증명이 저장되었습니다."}


@router.get("/gsshop/auth/check")
async def gsshop_auth_check(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 인증 확인 (MDID 조회로 검증)."""
    client = await _get_gs_client(session)
    if not client.sup_cd or not client.aes_key:
        return {
            "success": False,
            "authenticated": False,
            "message": "supCd와 aesKey가 필요합니다.",
        }
    return await client.check_auth()


@router.get("/gsshop/brands")
async def gsshop_brands(
    brandNm: Optional[str] = Query(None),
    fromDtm: Optional[str] = Query(None),
    toDtm: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 브랜드 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_brands(
            brand_nm=brandNm, from_dtm=fromDtm, to_dtm=toDtm
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/categories")
async def gsshop_categories(
    sectSts: str = Query("A"),
    shopAttrCd: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 전시매장(카테고리) 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_categories(sect_sts=sectSts, shop_attr_cd=shopAttrCd)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/product-categories")
async def gsshop_product_categories(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 상품분류코드 전체 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_product_categories()
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/delivery-places")
async def gsshop_delivery_places(
    supAddrCd: str = Query(""),
    addrGbnNm: str = Query(""),
    dirdlvRelspYn: str = Query(""),
    dirdlvRetpYn: str = Query(""),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 출고지/반송지 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_delivery_places(
            sup_addr_cd=supAddrCd,
            addr_gbn_nm=addrGbnNm,
            dirdlv_relsp_yn=dirdlvRelspYn,
            dirdlv_retp_yn=dirdlvRetpYn,
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/md-list")
async def gsshop_md_list(
    subSupCheckYn: str = Query("N"),
    subSupCd: str = Query(""),
    prcModAuthYn: str = Query("A"),
    prdNmModAuthYn: str = Query("A"),
    descdModAuthYn: str = Query("A"),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 협력사 MDID 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_md_list(
            sub_sup_check_yn=subSupCheckYn,
            sub_sup_cd=subSupCd,
            prc_mod_auth_yn=prcModAuthYn,
            prd_nm_mod_auth_yn=prdNmModAuthYn,
            descd_mod_auth_yn=descdModAuthYn,
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.post("/gsshop/goods")
async def gsshop_register_goods(
    product_data: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 상품 등록."""
    client = await _get_gs_client(session)
    try:
        result = await client.register_goods(product_data)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {
            "success": False,
            "message": str(exc),
            "code": exc.code,
            "detail": exc.gs_data,
        }


@router.post("/gsshop/goods/{sup_prd_cd}/base-info")
async def gsshop_update_base_info(
    sup_prd_cd: str,
    body_data: dict[str, Any],
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 기본부가정보 수정."""
    client = await _get_gs_client(session)
    try:
        result = await client.update_goods_base_info(sup_prd_cd, body_data)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class GsPriceUpdateRequest(BaseModel):
    prdPrcInfo: dict[str, Any]


@router.post("/gsshop/goods/{sup_prd_cd}/price")
async def gsshop_update_price(
    sup_prd_cd: str,
    body: GsPriceUpdateRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 가격 수정."""
    client = await _get_gs_client(session)
    try:
        result = await client.update_goods_price(sup_prd_cd, body.prdPrcInfo)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class GsSaleStatusRequest(BaseModel):
    saleEndDtm: str
    attrSaleEndStModYn: str = "Y"


@router.post("/gsshop/goods/{sup_prd_cd}/sale-status")
async def gsshop_update_sale_status(
    sup_prd_cd: str,
    body: GsSaleStatusRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 판매상태 변경."""
    client = await _get_gs_client(session)
    try:
        result = await client.update_sale_status(
            sup_prd_cd, body.saleEndDtm, body.attrSaleEndStModYn
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class GsImagesRequest(BaseModel):
    prdCntntListCntntUrlNm: str = ""
    mobilBannerImgUrl: str = ""


@router.post("/gsshop/goods/{sup_prd_cd}/images")
async def gsshop_update_images(
    sup_prd_cd: str,
    body: GsImagesRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 이미지 수정."""
    client = await _get_gs_client(session)
    try:
        result = await client.update_images(
            sup_prd_cd, body.prdCntntListCntntUrlNm, body.mobilBannerImgUrl
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class GsAttributesRequest(BaseModel):
    attrPrdList: list[dict[str, Any]]
    prdTypCd: str = ""
    subSupCd: str = ""


@router.post("/gsshop/goods/{sup_prd_cd}/attributes")
async def gsshop_update_attributes(
    sup_prd_cd: str,
    body: GsAttributesRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 속성(옵션) 수정."""
    client = await _get_gs_client(session)
    try:
        result = await client.update_attributes(
            sup_prd_cd, body.attrPrdList, body.prdTypCd, body.subSupCd
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/goods/{sup_prd_cd}/approve-status")
async def gsshop_approve_status(
    sup_prd_cd: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 상품 승인상태 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_approve_status(sup_prd_cd)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/goods/{sup_prd_cd}")
async def gsshop_goods_detail(
    sup_prd_cd: str,
    searchItmCd: str = Query("ALL"),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 상품 상세 조회."""
    client = await _get_gs_client(session)
    try:
        result = await client.get_goods(sup_prd_cd, search_itm_cd=searchItmCd)
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/gsshop/promotions")
async def gsshop_promotions(
    fromDtm: str = Query(""),
    toDtm: str = Query(""),
    pmoApplySt: str = Query("ALL"),
    prdCd: str = Query(""),
    prdNm: str = Query(""),
    brandCd: str = Query(""),
    rowsPerPage: int = Query(100),
    pageIdx: int = Query(1),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 프로모션 목록 조회."""
    if not fromDtm or not toDtm:
        return {
            "success": False,
            "message": "fromDtm, toDtm 필수 (yyyyMMdd, 최대 7일)",
        }
    client = await _get_gs_client(session)
    try:
        result = await client.get_promotions(
            from_dtm=fromDtm,
            to_dtm=toDtm,
            pmo_apply_st=pmoApplySt,
            prd_cd=prdCd,
            prd_nm=prdNm,
            brand_cd=brandCd,
            rows_per_page=rowsPerPage,
            page_idx=pageIdx,
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


class GsPromotionApproveRequest(BaseModel):
    saleproAgreeDocNo: str
    pmoReqNo: str
    prdCd: str
    aprvStCd: str
    aprvRetRsn: Optional[str] = ""


@router.post("/gsshop/promotions/approve")
async def gsshop_approve_promotion(
    body: GsPromotionApproveRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """GS샵 프로모션 승인/반려 처리."""
    if (
        not body.saleproAgreeDocNo
        or not body.pmoReqNo
        or not body.prdCd
        or not body.aprvStCd
    ):
        return {
            "success": False,
            "message": "saleproAgreeDocNo, pmoReqNo, prdCd, aprvStCd 필수",
        }
    client = await _get_gs_client(session)
    try:
        result = await client.approve_promotion(
            salepro_agree_doc_no=body.saleproAgreeDocNo,
            pmo_req_no=body.pmoReqNo,
            prd_cd=body.prdCd,
            aprv_st_cd=body.aprvStCd,
            aprv_ret_rsn=body.aprvRetRsn or "",
        )
        return {"success": True, "data": result.get("data")}
    except GsShopApiError as exc:
        return {"success": False, "message": str(exc), "code": exc.code}


@router.get("/extension-config")
async def get_extension_config(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """확장앱에 전달할 최신 설정 (KREAM 셀렉터, 텍스트 패턴 등)."""
    kream_selectors = await _get_setting(session, "kream_selectors")
    return {"selectors": kream_selectors or {}}


# ═══════════════════════════════════════════════
# 범용 이미지 프록시
# ═══════════════════════════════════════════════


@router.get("/image-proxy")
async def image_proxy(
    url: str = Query("", description="이미지 URL"),
) -> Response:
    """외부 이미지 프록시 (핫링크 차단 우회)."""
    if not url:
        raise HTTPException(status_code=400, detail="URL 필요")
    from urllib.parse import unquote

    target = unquote(url)
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                target, headers={"Referer": target, "User-Agent": "Mozilla/5.0"}
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(
                content=resp.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=86400",
                    "Access-Control-Allow-Origin": "*",
                },
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
