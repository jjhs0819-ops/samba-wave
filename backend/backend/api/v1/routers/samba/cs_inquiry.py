"""SambaWave CS 문의 API router."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.dtos.samba.cs_inquiry import (
    CSInquiryBatchDelete,
    CSInquiryCreate,
    CSInquiryReply,
)

router = APIRouter(prefix="/cs-inquiries", tags=["samba-cs-inquiries"])


def _read_service(session: AsyncSession):
    from backend.domain.samba.cs_inquiry.repository import SambaCSInquiryRepository
    from backend.domain.samba.cs_inquiry.service import SambaCSInquiryService

    return SambaCSInquiryService(SambaCSInquiryRepository(session))


def _write_service(session: AsyncSession):
    from backend.domain.samba.cs_inquiry.repository import SambaCSInquiryRepository
    from backend.domain.samba.cs_inquiry.service import SambaCSInquiryService

    return SambaCSInquiryService(SambaCSInquiryRepository(session))


@router.get("/stats")
async def get_cs_stats(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """CS 문의 통계."""
    svc = _read_service(session)
    return await svc.get_stats()


@router.get("/templates")
async def get_reply_templates(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """CS 답변 템플릿 목록 (DB 저장분 + 기본 템플릿 병합)."""
    from backend.domain.samba.cs_inquiry.service import SambaCSInquiryService, CS_REPLY_TEMPLATES
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    repo = SambaSettingsRepository(session)
    row = await repo.find_by_async(key="cs_reply_templates")
    db_templates = {}
    if row and isinstance(row.value, dict):
        db_templates = row.value
    # 기본 템플릿 + DB 템플릿 병합 (DB가 우선)
    merged = {**CS_REPLY_TEMPLATES, **db_templates}
    return merged


class TemplateBody(BaseModel):
    key: str
    name: str
    content: str


@router.post("/templates")
async def add_reply_template(
    body: TemplateBody,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 답변 템플릿 추가/수정."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository
    from backend.domain.samba.forbidden.service import SambaForbiddenService
    from backend.domain.samba.forbidden.repository import SambaForbiddenWordRepository

    settings_repo = SambaSettingsRepository(session)
    svc = SambaForbiddenService(SambaForbiddenWordRepository(session), settings_repo)

    row = await settings_repo.find_by_async(key="cs_reply_templates")
    templates = {}
    if row and isinstance(row.value, dict):
        templates = row.value
    templates[body.key] = {"name": body.name, "content": body.content}
    await svc.save_setting("cs_reply_templates", templates)
    return {"ok": True, "key": body.key}


@router.delete("/templates/{template_key}")
async def delete_reply_template(
    template_key: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 답변 템플릿 삭제."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository
    from backend.domain.samba.forbidden.service import SambaForbiddenService
    from backend.domain.samba.forbidden.repository import SambaForbiddenWordRepository

    settings_repo = SambaSettingsRepository(session)
    svc = SambaForbiddenService(SambaForbiddenWordRepository(session), settings_repo)

    row = await settings_repo.find_by_async(key="cs_reply_templates")
    templates = {}
    if row and isinstance(row.value, dict):
        templates = row.value
    if template_key in templates:
        del templates[template_key]
        await svc.save_setting("cs_reply_templates", templates)
    return {"ok": True}


@router.get("")
async def list_cs_inquiries(
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=200),
    market: Optional[str] = None,
    inquiry_type: Optional[str] = None,
    reply_status: Optional[str] = None,
    search: Optional[str] = None,
    sort_field: str = Query("inquiry_date"),
    sort_desc: bool = Query(True),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """CS 문의 목록 (필터 + 페이지네이션)."""
    svc = _read_service(session)
    return await svc.list_inquiries(
        skip=skip,
        limit=limit,
        market=market,
        inquiry_type=inquiry_type,
        reply_status=reply_status,
        search=search,
        sort_field=sort_field,
        sort_desc=sort_desc,
    )


@router.post("", status_code=201)
async def create_cs_inquiry(
    body: CSInquiryCreate,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 수동 등록."""
    svc = _write_service(session)
    return await svc.create_inquiry(body.model_dump(exclude_unset=True))


@router.get("/{inquiry_id}")
async def get_cs_inquiry(
    inquiry_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """CS 문의 단건 조회."""
    svc = _read_service(session)
    inquiry = await svc.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")
    return inquiry


@router.post("/{inquiry_id}/reply")
async def reply_cs_inquiry(
    inquiry_id: str,
    body: CSInquiryReply,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 답변 등록 — DB 저장 + 마켓 전송 통합."""
    import json
    import logging
    from datetime import datetime, timezone
    from sqlmodel import select
    from backend.domain.samba.forbidden.model import SambaSettings
    from backend.domain.samba.proxy.smartstore import SmartStoreClient

    logger = logging.getLogger(__name__)
    svc = _write_service(session)
    inquiry = await svc.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")

    market_sent = False
    market_msg = ""
    answer_no = inquiry.market_answer_no if inquiry.market_answer_no and inquiry.market_answer_no != "None" else ""

    # 마켓 전송 시도 (market_inquiry_no가 있는 경우)
    if inquiry.market_inquiry_no:
        try:
            if inquiry.market == "스마트스토어":
                settings_result = await session.execute(
                    select(SambaSettings).where(SambaSettings.key.like("store_smartstore%"))
                )
                ss_settings = settings_result.scalars().first()
                if ss_settings:
                    config = json.loads(ss_settings.value) if isinstance(ss_settings.value, str) else ss_settings.value
                    client = SmartStoreClient(config["clientId"], config["clientSecret"])
                    inq_no = int(inquiry.market_inquiry_no)

                    if inquiry.inquiry_type == "product_question":
                        result = await client.answer_product_qna(inq_no, body.reply)
                        market_sent = True
                        market_msg = "상품문의 답변 전송 완료"
                    else:
                        if inquiry.market_answer_no:
                            result = await client.update_inquiry_answer(
                                inq_no, int(inquiry.market_answer_no), body.reply,
                            )
                        else:
                            result = await client.answer_inquiry(inq_no, body.reply)
                        answer_data = result.get("data", {}) if isinstance(result, dict) else {}
                        new_answer_no = str(answer_data.get("inquiryCommentNo", ""))
                        if new_answer_no:
                            answer_no = new_answer_no
                        market_sent = True
                        market_msg = "고객문의 답변 전송 완료"
        except Exception as e:
            logger.warning(f"[CS답변] 마켓 전송 실패 (DB 저장은 진행): {e}")
            market_msg = f"마켓 전송 실패: {e}"

    # DB 저장 (마켓 전송 성공 여부와 무관하게 항상 저장)
    updated = await svc.reply_inquiry(inquiry_id, body.reply)
    if answer_no and answer_no != (inquiry.market_answer_no or ""):
        from backend.domain.samba.cs_inquiry.repository import SambaCSInquiryRepository
        repo = SambaCSInquiryRepository(session)
        await repo.update_async(inquiry_id, market_answer_no=answer_no)

    return {
        **(updated.__dict__ if updated else {}),
        "market_sent": market_sent,
        "market_message": market_msg,
    }


async def _find_collected_product_by_market_product_no(
    session: AsyncSession, market_product_no: str
) -> "dict | None":
    """마켓 상품번호로 수집상품을 찾아 연결 정보를 반환하는 공통 함수.

    market_product_nos JSON 컬럼에서 해당 상품번호를 검색한다.
    모든 마켓(스마트스토어/쿠팡/11번가 등) 공통으로 사용.

    Returns:
        { id, source_site, site_product_id, name, images, original_link, product_link } or None
    """
    if not market_product_no:
        return None
    from sqlalchemy import text as sa_text
    from backend.domain.samba.collector.model import SambaCollectedProduct

    # market_product_nos JSON에서 값으로 검색 (PostgreSQL JSON 연산)
    sql = sa_text(
        "SELECT id, source_site, site_product_id, name, images "
        "FROM samba_collected_product "
        "WHERE market_product_nos::text LIKE :pattern "
        "LIMIT 1"
    )
    result = await session.execute(sql, {"pattern": f'%"{market_product_no}"%'})
    row = result.fetchone()
    if not row:
        return None

    pid, source_site, site_product_id, name, images = row

    # 소싱처 URL 생성
    sourcing_urls = {
        "MUSINSA": f"https://www.musinsa.com/app/goods/{site_product_id}",
        "KREAM": f"https://kream.co.kr/products/{site_product_id}",
        "LOTTEON": f"https://www.lotteon.com/product/{site_product_id}",
        "SSG": f"https://www.ssg.com/item/itemView.ssg?itemId={site_product_id}",
        "ABCmart": f"https://abcmart.a-rt.com/product/{site_product_id}",
        "FashionPlus": f"https://www.fashionplus.co.kr/goods/{site_product_id}",
        "Nike": f"https://www.nike.com/kr/t/{site_product_id}",
        "Adidas": f"https://www.adidas.co.kr/{site_product_id}",
    }
    original_link = sourcing_urls.get(source_site, "")

    # 대표 이미지
    thumb = ""
    if images and isinstance(images, list) and len(images) > 0:
        thumb = images[0]

    return {
        "id": pid,
        "source_site": source_site,
        "site_product_id": site_product_id,
        "name": name,
        "images": images,
        "original_link": original_link,
        "product_image": thumb,
    }


def _build_market_product_url(market: str, product_no: str, store_slug: str = "") -> str:
    """마켓별 상품 판매 페이지 URL 생성. 모든 마켓 공통."""
    urls = {
        "스마트스토어": f"https://smartstore.naver.com/{store_slug}/products/{product_no}" if store_slug else f"https://search.shopping.naver.com/product/{product_no}",
        "쿠팡": f"https://www.coupang.com/vp/products/{product_no}",
        "11번가": f"https://www.11st.co.kr/products/{product_no}",
        "롯데ON": f"https://www.lotteon.com/product/{product_no}",
        "SSG": f"https://www.ssg.com/item/itemView.ssg?itemId={product_no}",
        "롯데홈쇼핑": f"https://www.lotteimall.com/product/{product_no}",
        "GS샵": f"https://www.gsshop.com/prd/prd.gs?prdid={product_no}",
        "KREAM": f"https://kream.co.kr/products/{product_no}",
        "Toss": f"https://toss.im/shopping/product/{product_no}",
    }
    return urls.get(market, "")


@router.post("/sync-from-markets")
async def sync_cs_from_markets(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """마켓에서 CS 문의 동기화 (스마트스토어 고객문의 + 톡톡)."""
    import logging
    from datetime import datetime, timedelta, timezone
    from sqlmodel import select
    from backend.domain.samba.forbidden.model import SambaSettings
    from backend.domain.samba.proxy.smartstore import SmartStoreClient
    from backend.domain.samba.cs_inquiry.model import SambaCSInquiry

    logger = logging.getLogger(__name__)
    svc = _write_service(session)
    synced = 0
    errors = []

    # 스마트스토어 계정 조회
    try:
        settings_result = await session.execute(
            select(SambaSettings).where(SambaSettings.key.like("store_smartstore%"))
        )
        ss_settings = settings_result.scalars().all()
    except Exception as e:
        raise HTTPException(500, f"설정 조회 실패: {e}")

    for setting in ss_settings:
        try:
            import json
            config = json.loads(setting.value) if isinstance(setting.value, str) else setting.value
            client_id = config.get("clientId", "")
            client_secret = config.get("clientSecret", "")
            account_name = config.get("businessName", "") or config.get("storeId", "")
            store_slug = config.get("storeSlug", "") or config.get("storeId", "")

            if not client_id or not client_secret:
                continue

            client = SmartStoreClient(client_id, client_secret)

            # 최근 30일 문의 조회 (KST 기준 ISO 8601)
            from zoneinfo import ZoneInfo
            kst = ZoneInfo("Asia/Seoul")
            now_kst = datetime.now(kst)
            end_date = (now_kst + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000+09:00")
            start_date = (now_kst - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00.000+09:00")

            result = await client.get_inquiries(
                from_date=start_date,
                to_date=end_date,
                size=100,
            )

            # 응답 구조 파싱
            data = result.get("data", result)
            contents = []
            if isinstance(data, dict):
                contents = data.get("contents", []) or data.get("content", [])
                if not contents:
                    for key in data:
                        val = data[key]
                        if isinstance(val, list) and val:
                            contents = val
                            break
            elif isinstance(data, list):
                contents = data

            for item in contents:
                inquiry_no = str(item.get("questionId", item.get("inquiryNo", item.get("id", ""))))
                if not inquiry_no:
                    continue

                # 중복 체크
                existing = await session.execute(
                    select(SambaCSInquiry).where(
                        SambaCSInquiry.market == "스마트스토어",
                        SambaCSInquiry.market_inquiry_no == inquiry_no,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                inquiry_type = "product_question"
                is_answered = item.get("answered", False)
                reply_content = item.get("answer", "")

                # inquiry_date 문자열 → datetime 변환
                raw_date = item.get("createDate", None)
                parsed_date = None
                if raw_date:
                    try:
                        from dateutil.parser import parse as parse_dt
                        parsed_date = parse_dt(raw_date)
                    except Exception:
                        parsed_date = None

                # 마켓 상품번호로 수집상품 매칭 (스마트스토어: productId)
                market_product_no = str(item.get("productId", item.get("productNo", item.get("originProductNo", ""))))
                matched = await _find_collected_product_by_market_product_no(session, market_product_no)

                product_link = _build_market_product_url("스마트스토어", market_product_no, store_slug) if market_product_no else ""

                inquiry_data = {
                    "market": "스마트스토어",
                    "market_inquiry_no": inquiry_no,
                    "market_answer_no": None,
                    "market_order_id": None,
                    "market_product_no": market_product_no or None,
                    "account_name": account_name,
                    "inquiry_type": inquiry_type,
                    "questioner": item.get("maskedWriterId", ""),
                    "product_name": item.get("productName", ""),
                    "product_image": matched["product_image"] if matched else "",
                    "product_link": product_link,
                    "original_link": matched["original_link"] if matched else "",
                    "collected_product_id": matched["id"] if matched else None,
                    "content": item.get("question", ""),
                    "reply": reply_content if is_answered else None,
                    "reply_status": "replied" if is_answered else "pending",
                    "inquiry_date": parsed_date,
                    "replied_at": None,
                }

                await svc.create_inquiry(inquiry_data)
                synced += 1

            logger.info(f"[CS동기화] 스마트스토어({account_name}) 상품문의: {len(contents)}건 조회, {synced}건 동기화")

            # ── 고객문의 (구매 후 1:1 문의, /v1/pay-user/inquiries) ──
            try:
                # LocalDate 형식 (YYYY-MM-DD)
                start_local = (now_kst - timedelta(days=90)).strftime("%Y-%m-%d")
                end_local = (now_kst + timedelta(days=1)).strftime("%Y-%m-%d")

                purchase_result = await client.get_purchase_inquiries(
                    start_date=start_local,
                    end_date=end_local,
                    size=100,
                )
                p_data = purchase_result.get("data", purchase_result)
                p_contents = []
                if isinstance(p_data, dict):
                    p_contents = p_data.get("content", []) or p_data.get("contents", [])
                    if not p_contents:
                        for key in p_data:
                            val = p_data[key]
                            if isinstance(val, list) and val:
                                p_contents = val
                                break
                elif isinstance(p_data, list):
                    p_contents = p_data

                for item in p_contents:
                    inq_no = str(item.get("inquiryNo", item.get("id", "")))
                    if not inq_no:
                        continue

                    existing = await session.execute(
                        select(SambaCSInquiry).where(
                            SambaCSInquiry.market == "스마트스토어",
                            SambaCSInquiry.market_inquiry_no == inq_no,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    # 문의 유형 (category 필드: 배송, 교환/반품 등)
                    category_raw = item.get("category", item.get("inquiryType", "general"))
                    type_map = {
                        "배송": "delivery",
                        "교환/반품": "exchange_return",
                        "교환": "exchange_return",
                        "반품": "exchange_return",
                        "취소": "exchange_return",
                        "상품": "product",
                        "DELIVERY": "delivery",
                        "EXCHANGE_RETURN": "exchange_return",
                        "CANCEL": "exchange_return",
                        "ETC": "general",
                    }
                    mapped_type = type_map.get(str(category_raw), "general")

                    is_answered = item.get("answered", False)
                    reply_content = item.get("answerContent", "") or ""

                    raw_date = item.get("inquiryRegistrationDateTime", None)
                    parsed_date = None
                    if raw_date:
                        try:
                            from dateutil.parser import parse as parse_dt
                            parsed_date = parse_dt(raw_date)
                        except Exception:
                            parsed_date = None

                    mpno = str(item.get("productNo", item.get("productId", "")))
                    matched = await _find_collected_product_by_market_product_no(session, mpno)
                    product_link = _build_market_product_url("스마트스토어", mpno, store_slug) if mpno else ""

                    inquiry_data = {
                        "market": "스마트스토어",
                        "market_inquiry_no": inq_no,
                        "market_answer_no": str(item["answerContentId"]) if item.get("answerContentId") else None,
                        "market_order_id": item.get("orderId", item.get("productOrderIdList", None)),
                        "market_product_no": mpno or None,
                        "account_name": account_name,
                        "inquiry_type": mapped_type,
                        "questioner": item.get("customerId", item.get("customerName", "")),
                        "product_name": item.get("productName", ""),
                        "product_image": matched["product_image"] if matched else "",
                        "product_link": product_link,
                        "original_link": matched["original_link"] if matched else "",
                        "collected_product_id": matched["id"] if matched else None,
                        "content": item.get("inquiryContent", item.get("question", item.get("content", ""))),
                        "reply": reply_content if is_answered else None,
                        "reply_status": "replied" if is_answered else "pending",
                        "inquiry_date": parsed_date,
                        "replied_at": None,
                    }

                    await svc.create_inquiry(inquiry_data)
                    synced += 1

                logger.info(f"[CS동기화] 스마트스토어({account_name}) 구매문의: {len(p_contents)}건 조회")
            except Exception as e:
                logger.warning(f"[CS동기화] 스마트스토어 구매문의 조회 실패: {e}")

        except Exception as e:
            logger.error(f"[CS동기화] 스마트스토어 동기화 실패: {e}")
            errors.append(str(e))

    # ── 롯데ON CS 문의 동기화 ──────────────────────────────────────────────
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    account_repo = SambaMarketAccountRepository(session)
    lotteon_accounts = await account_repo.filter_by_async(market_type="lotteon", is_active=True)

    for acct in lotteon_accounts:
        try:
            from backend.domain.samba.proxy.lotteon import LotteonClient
            acct_extras = acct.additional_fields or {}
            api_key = acct_extras.get("apiKey", "") or acct.api_key or ""
            if not api_key:
                logger.warning(f"[CS동기화] 롯데ON({acct.seller_id}) API Key 없음 — 건너뜀")
                continue

            lotteon_client = LotteonClient(api_key)
            await lotteon_client.test_auth()
            cs_items = await lotteon_client.get_cs_inquiries(days=30)
            logger.info(f"[CS동기화] 롯데ON({acct.seller_id}): {len(cs_items)}건 조회")

            for item in cs_items:
                # 문의 번호 추출 (응답 구조 확인 후 보정 예정)
                inquiry_no = str(
                    item.get("qnaNo") or item.get("csNo") or item.get("inquiryNo")
                    or item.get("id") or ""
                )
                if not inquiry_no:
                    continue

                # 중복 체크
                existing = await session.execute(
                    select(SambaCSInquiry).where(
                        SambaCSInquiry.market == "롯데ON",
                        SambaCSInquiry.market_inquiry_no == inquiry_no,
                    )
                )
                if existing.scalar_one_or_none():
                    continue

                is_answered = bool(
                    item.get("ansYn") == "Y" or item.get("answered")
                    or item.get("reply") or item.get("answerContent")
                )
                reply_content = (
                    item.get("answerContent") or item.get("reply")
                    or item.get("ansCntn") or ""
                )
                raw_date = item.get("regDt") or item.get("createDate") or item.get("qnaRegDt")
                parsed_date = None
                if raw_date:
                    try:
                        from dateutil.parser import parse as parse_dt
                        parsed_date = parse_dt(str(raw_date))
                    except Exception:
                        parsed_date = None

                product_no = str(
                    item.get("spdNo") or item.get("pdNo") or item.get("productNo") or ""
                )
                product_name = item.get("spdNm") or item.get("pdNm") or item.get("productName") or ""
                question_content = (
                    item.get("qnaCntn") or item.get("question") or item.get("content") or item.get("cntn") or ""
                )

                logger.info(
                    f"[CS동기화] 롯데ON 문의 파싱: no={inquiry_no!r} keys={list(item.keys())[:10]}"
                )

                inquiry_data = {
                    "market": "롯데ON",
                    "market_inquiry_no": inquiry_no,
                    "account_name": acct.seller_id or acct.market_name,
                    "inquiry_type": "product_question",
                    "questioner": item.get("buyerNm") or item.get("custNm") or "",
                    "market_product_no": product_no,
                    "product_name": product_name,
                    "content": question_content,
                    "reply": reply_content if is_answered else None,
                    "reply_status": "replied" if is_answered else "pending",
                    "inquiry_date": parsed_date,
                }
                await svc.create_inquiry(inquiry_data)
                synced += 1

            logger.info(f"[CS동기화] 롯데ON({acct.seller_id}): {synced}건 동기화 완료")
        except Exception as e:
            logger.error(f"[CS동기화] 롯데ON 동기화 실패: {e}")
            errors.append(f"롯데ON: {e}")

    # 미연결 CS 문의 일괄 매칭 (market_product_no → market_product_nos)
    linked = 0
    try:
        from sqlmodel import select as sel
        unlinked = await session.execute(
            sel(SambaCSInquiry).where(
                SambaCSInquiry.collected_product_id.is_(None),
            )
        )
        unlinked_items = unlinked.scalars().all()
        if unlinked_items:
            from sqlalchemy import text as sa_text
            cp_result = await session.execute(sa_text(
                "SELECT id, source_site, site_product_id, images, market_product_nos "
                "FROM samba_collected_product "
                "WHERE market_product_nos IS NOT NULL LIMIT 50000"
            ))
            cp_rows = cp_result.fetchall()

            # 마켓상품번호 → 수집상품 매핑
            mpn_map: dict[str, tuple] = {}
            for row in cp_rows:
                pid, site, spid, imgs, mpnos = row
                if mpnos and isinstance(mpnos, dict):
                    for k, v in mpnos.items():
                        if v:
                            mpn_map[str(v)] = (pid, site, spid, imgs, mpnos)

            sourcing_urls = {
                "MUSINSA": "https://www.musinsa.com/app/goods/{}",
                "KREAM": "https://kream.co.kr/products/{}",
                "LOTTEON": "https://www.lotteon.com/product/{}",
                "SSG": "https://www.ssg.com/item/itemView.ssg?itemId={}",
                "ABCmart": "https://abcmart.a-rt.com/product/{}",
                "FashionPlus": "https://www.fashionplus.co.kr/goods/{}",
                "Nike": "https://www.nike.com/kr/t/{}",
                "Adidas": "https://www.adidas.co.kr/{}",
            }

            for inq in unlinked_items:
                # market_product_no로 매칭 (유일한 기준)
                mpno = inq.market_product_no
                if not mpno:
                    continue
                matched = mpn_map.get(str(mpno))
                if not matched:
                    continue

                pid, site, spid, imgs, mpnos = matched
                inq.collected_product_id = pid
                if not inq.original_link and site in sourcing_urls and spid:
                    inq.original_link = sourcing_urls[site].format(spid)
                if (not inq.product_image or inq.product_image == "") and imgs and isinstance(imgs, list) and imgs:
                    inq.product_image = imgs[0]
                # product_link: market_product_nos에서 마켓 상품번호 추출
                if not inq.product_link and mpnos and isinstance(mpnos, dict) and inq.market:
                    for mk, mv in mpnos.items():
                        if mv and not mk.endswith("_origin"):
                            inq.product_link = _build_market_product_url(inq.market, str(mv))
                            break
                linked += 1

            if linked > 0:
                await session.commit()
                logger.info(f"[CS동기화] 미연결 문의 {linked}건 상품 매칭 완료")
    except Exception as e:
        logger.warning(f"[CS동기화] 미연결 매칭 중 오류: {e}")

    return {
        "success": True,
        "synced": synced,
        "linked": linked,
        "errors": errors,
        "message": f"CS 문의 {synced}건 동기화 완료" + (f", {linked}건 상품연결" if linked else "") + (f" (에러 {len(errors)}건)" if errors else ""),
    }


@router.post("/{inquiry_id}/send-reply")
async def send_reply_to_market(
    inquiry_id: str,
    body: CSInquiryReply,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 답변을 마켓에 전송."""
    import json
    from datetime import datetime, timezone
    from sqlmodel import select
    from backend.domain.samba.forbidden.model import SambaSettings
    from backend.domain.samba.proxy.smartstore import SmartStoreClient

    svc = _write_service(session)
    inquiry = await svc.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(404, "문의를 찾을 수 없습니다")

    if not inquiry.market_inquiry_no:
        raise HTTPException(400, "마켓 문의 번호가 없습니다 (수동 등록 문의는 마켓 전송 불가)")

    if inquiry.market == "스마트스토어":
        # 스마트스토어 계정 조회
        settings_result = await session.execute(
            select(SambaSettings).where(SambaSettings.key.like("store_smartstore%"))
        )
        ss_settings = settings_result.scalars().first()
        if not ss_settings:
            raise HTTPException(400, "스마트스토어 계정 설정이 없습니다")

        config = json.loads(ss_settings.value) if isinstance(ss_settings.value, str) else ss_settings.value
        client = SmartStoreClient(config["clientId"], config["clientSecret"])

        inquiry_no = int(inquiry.market_inquiry_no)

        if inquiry.inquiry_type == "product_question":
            # 상품문의(Q&A) → PUT /v1/contents/qnas/{questionId}
            result = await client.answer_product_qna(inquiry_no, body.reply)
            answer_no = ""
        else:
            # 고객문의(1:1) → POST /v1/pay-merchant/inquiries/{inquiryNo}/answer
            if inquiry.market_answer_no:
                result = await client.update_inquiry_answer(
                    inquiry_no, int(inquiry.market_answer_no), body.reply,
                )
            else:
                result = await client.answer_inquiry(inquiry_no, body.reply)
            answer_data = result.get("data", {})
            answer_no = str(answer_data.get("inquiryCommentNo", ""))

        from backend.domain.samba.cs_inquiry.repository import SambaCSInquiryRepository
        repo = SambaCSInquiryRepository(session)
        await repo.update_async(
            inquiry_id,
            reply=body.reply,
            reply_status="replied",
            market_answer_no=answer_no if answer_no else inquiry.market_answer_no,
            replied_at=datetime.now(timezone.utc),
        )

        msg = "상품문의 답변 전송 완료" if inquiry.inquiry_type == "product_question" else "고객문의 답변 전송 완료"
        return {"success": True, "message": f"스마트스토어 {msg}", "data": result.get("data") if isinstance(result, dict) else {}}

    raise HTTPException(400, f"'{inquiry.market}' 마켓은 아직 답변 전송을 지원하지 않습니다")


@router.post("/batch-delete")
async def batch_delete_cs_inquiries(
    body: CSInquiryBatchDelete,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 선택 삭제."""
    svc = _write_service(session)
    count = await svc.delete_batch(body.ids)
    return {"deleted": count}


@router.delete("/{inquiry_id}")
async def delete_cs_inquiry(
    inquiry_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 단건 삭제."""
    svc = _write_service(session)
    deleted = await svc.delete_inquiry(inquiry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")
    return {"ok": True}


@router.post("/{inquiry_id}/hide")
async def hide_cs_inquiry(
    inquiry_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """CS 문의 숨기기."""
    svc = _write_service(session)
    inquiry = await svc.get_inquiry(inquiry_id)
    if not inquiry:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다")
    await svc.repo.update_async(inquiry_id, is_hidden=True)
    return {"ok": True}
