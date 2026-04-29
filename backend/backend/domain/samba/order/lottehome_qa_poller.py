"""롯데홈쇼핑 QA 승인 상태 자동 동기화 — 30분 간격."""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

LOTTEHOME_QA_SYNC_INTERVAL = int(
    os.environ.get("LOTTEHOME_QA_SYNC_INTERVAL_SECONDS", str(30 * 60))
)


async def _run_lottehome_qa_sync() -> tuple[int, int]:
    """pending 상품을 조회하여 승인된 건을 approved로 업데이트. (checked, updated) 반환."""
    from sqlalchemy import update as sa_update
    from sqlmodel import select

    from backend.db.orm import get_write_session
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.forbidden.model import SambaSettings
    from backend.domain.samba.proxy.lottehome import LotteHomeClient

    async with get_write_session() as session:
        # credentials 조회
        creds_result = await session.exec(
            select(SambaSettings).where(SambaSettings.key == "lottehome_credentials")
        )
        creds_row = creds_result.first()
        if not creds_row:
            return 0, 0
        creds = creds_row.value or {}

        user_id = creds.get("userId", "")
        password = creds.get("password", "")
        if not user_id or not password:
            return 0, 0

        client = LotteHomeClient(
            user_id, password, creds.get("agncNo", ""), creds.get("env", "prod")
        )

        # pending 상품 조회
        result = await session.execute(
            select(SambaCollectedProduct).where(
                SambaCollectedProduct.market_product_nos != None  # noqa: E711
            )
        )
        products = result.scalars().all()

        checked = 0
        updated = 0

        for product in products:
            m_nos = product.market_product_nos or {}
            pending_accounts = [
                k.replace("_qa", "")
                for k, v in m_nos.items()
                if k.endswith("_qa") and v == "pending"
            ]
            if not pending_accounts:
                continue

            for acc_id in pending_accounts:
                goods_no = m_nos.get(acc_id, "")
                if not goods_no:
                    continue
                checked += 1
                try:
                    detail = await client.search_goods_view(goods_no)
                    data = detail.get("data", {})
                    result = data.get("Result", data)
                    goods_info = (
                        result.get("GoodsInfo", result)
                        if isinstance(result, dict)
                        else result
                    )
                    sale_stat = str(goods_info.get("SaleStatCd", "") or "")
                    qa_result = str(goods_info.get("QaRsltCd", "") or "")
                    # 판매진행(10) 또는 QA 합격(10/15/30) → 승인 완료
                    if sale_stat == "10" or qa_result in ("10", "15", "30"):
                        new_nos = dict(m_nos)
                        new_nos[f"{acc_id}_qa"] = "approved"
                        await session.execute(
                            sa_update(SambaCollectedProduct)
                            .where(SambaCollectedProduct.id == product.id)
                            .values(market_product_nos=new_nos)
                        )
                        await session.commit()
                        updated += 1
                        logger.info(
                            "[롯데QA폴러] %s → approved (goods_no=%s)",
                            product.id,
                            goods_no,
                        )
                except Exception as exc:
                    logger.warning("[롯데QA폴러] %s 체크 실패: %s", goods_no, exc)

        return checked, updated


async def start_lottehome_qa_poller() -> None:
    """롯데홈쇼핑 QA 승인 상태를 주기적으로 동기화하는 백그라운드 루프."""
    # 서버 완전 기동 대기 (주문 폴러와 겹치지 않도록 90초 오프셋)
    await asyncio.sleep(90)
    logger.info("[롯데QA폴러] 시작 (간격: %d초)", LOTTEHOME_QA_SYNC_INTERVAL)

    while True:
        try:
            checked, updated = await _run_lottehome_qa_sync()
            if checked:
                logger.info("[롯데QA폴러] 점검 %d건, 승인처리 %d건", checked, updated)
        except asyncio.CancelledError:
            logger.info("[롯데QA폴러] 종료")
            return
        except Exception as exc:
            logger.warning("[롯데QA폴러] 오류: %s", exc)

        await asyncio.sleep(LOTTEHOME_QA_SYNC_INTERVAL)
