"""바이마(BUYMA) 마켓 플러그인.

기존 dispatcher._handle_buyma 로직을 플러그인 구조로 추출.
바이마는 공개 API가 없으므로 CSV 생성 방식으로 운영(정식 PS-API 승인 시 교체 예정).
인증 불필요 — _load_auth 오버라이드.

일본 마켓이므로 商品名은 일문상품명(name_ja)을 사용한다. name_ja가 비어있으면
Claude로 한→일 자동 번역 후 DB에 저장하고, 번역까지 실패하면 등록을 차단한다
(한글명이 일본 구매자에게 노출되는 사고 방지 — eBay name_en 정책과 동일).

[재고 자동관리 — 오토튠 연동 (2026-08, 정식 PS-API 승인 前 사전작업)]
바이마는 포이즌/크림과 달리 자기 카탈로그 매칭이 불필요(우리 리스팅 직접등록)하므로,
스마트스토어 등 일반 마켓처럼 기존 오토튠 파이프라인에 그대로 편입된다:
  - 오토튠(collector_autotune)이 소싱처(무신사) 재고/가격을 주기 재확인
  - 특정 사이즈 품절 → execute() 재전송(품절 사이즈 제외)로 반영
  - 전 사이즈 품절/상품 delist(아울렛 행사종료 등) → sale_status=sold_out →
    품절정리 루프가 마켓 무관하게 delete()를 호출 → 리스팅 삭제
즉 별도 재고배치 없이 오토튠이 바이마 재고를 자동 구동한다. 단 (a) delete()가
실제 반영되려면 정식 PS-API 필요(아래 구현부는 승인 후 채움), (b) 상품이 SAMBA를
통해 등록돼 registered_accounts=buyma로 잡혀 있어야 오토튠 감시 대상이 된다.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


async def _get_setting(session, key: str) -> Any:
    """samba_settings 테이블에서 설정값 조회 후 즉시 커밋 — idle in transaction 방지."""
    from sqlmodel import select

    from backend.domain.samba.forbidden.model import SambaSettings

    stmt = select(SambaSettings).where(SambaSettings.key == key)
    result = await session.execute(stmt)
    row = result.scalars().first()
    val = row.value if row else None
    try:
        await session.commit()
    except Exception:
        pass
    return val


async def _translate_to_japanese(name: str, brand: str = "", session=None) -> str:
    """한글 상품명을 BUYMA용 일본어로 번역 (Claude API).

    API 키 우선순위: DB(samba_settings.claude) → 환경변수(ANTHROPIC_API_KEY).
    실패/거부 응답이면 빈 문자열 반환(호출부에서 등록 차단).
    """
    import anthropic

    from backend.core.config import settings

    api_key = ""
    if session:
        claude_settings = await _get_setting(session, "claude")
        if claude_settings and isinstance(claude_settings, dict):
            api_key = claude_settings.get("apiKey", "")
    if not api_key:
        api_key = settings.anthropic_api_key
    if not api_key:
        logger.warning("[바이마] Claude API 키 없음 — 일문 번역 스킵")
        return ""

    prompt = f"""Translate this Korean product name to natural Japanese for a BUYMA (Japanese marketplace) listing.
Brand (Korean): {brand}
Korean product name: {name}

Rules:
- Convert the brand to its official Japanese/katakana name (e.g. 나이키→ナイキ, 아디다스→adidas, 뉴발란스→New Balance, 푸마→PUMA, 아식스→asics)
- Keep model numbers/codes as-is (e.g. IE2166)
- Remove unnecessary brackets like [공식], [정품]
- Natural Japanese product title, max 30 full-width Japanese characters
- No quotes, output ONLY the translated title
- NEVER explain or apologize, ONLY output the title"""

    client = anthropic.AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=120,
        messages=[{"role": "user", "content": prompt}],
    )
    translated = resp.content[0].text.strip()[:40]

    lower = translated.lower()
    bad_patterns = [
        "i cannot",
        "i can't",
        "i'm unable",
        "sorry",
        "apologize",
        "i need to",
        "note:",
        "however",
        "unfortunately",
        "please",
        "translate",
        "없습니다",
        "죄송",
        "확인",
    ]
    if any(p in lower for p in bad_patterns):
        logger.warning("[바이마] 일문 번역 거부 응답: '%s' → 스킵", translated[:40])
        return ""
    # 한글 5자 이상 잔존 = 번역 실패로 간주
    kr_count = sum(1 for c in translated if "가" <= c <= "힣")
    if kr_count >= 5:
        logger.warning("[바이마] 일문 번역 한글 잔존: '%s' → 스킵", translated[:40])
        return ""

    return translated


class BuymaPlugin(MarketPlugin):
    market_type = "buyma"
    policy_key = "바이마"
    required_fields = ["name", "sale_price"]

    async def _load_auth(self, session, account) -> dict | None:
        """PS-API creds 로드 (accessToken/client_id/secret/storeId/sandbox).

        토큰이 있으면 API 등록 경로, 없으면 CSV 폴백. account가 없으면 _no_auth.
        """
        from backend.domain.samba.account.credentials import buyma_creds

        creds = buyma_creds(account) if account else {}
        return creds if creds else {"_no_auth": True}

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """BuymaClient.transform_product 위임."""
        from backend.domain.samba.proxy.buyma import BuymaClient

        settings = kwargs.get("account_settings", {})
        return BuymaClient.transform_product(product, category_id, settings)

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """바이마 상품 등록 — CSV 행 데이터 반환 (API 없음)."""
        from backend.domain.samba.proxy.buyma import BuymaClient

        # 일문상품명(name_ja) 자동 번역 — 비어있으면 Claude로 한→일 번역 후 DB 저장.
        # (일본 마켓이라 한글명 노출 방지 — eBay name_en 자동번역 패턴과 동일)
        if not product.get("name_ja") and product.get("name") and session:
            product = dict(product)  # 원본 변경 방지
            try:
                translated = await _translate_to_japanese(
                    product["name"], product.get("brand", ""), session=session
                )
                if translated:
                    product["name_ja"] = translated
                    # DB에도 저장 (다음 전송 재사용 + 상품관리 UI 표시)
                    product_id = product.get("id", "")
                    if product_id:
                        from sqlmodel import select

                        from backend.domain.samba.collector.model import (
                            SambaCollectedProduct,
                        )

                        stmt = select(SambaCollectedProduct).where(
                            SambaCollectedProduct.id == product_id
                        )
                        row = (await session.execute(stmt)).scalars().first()
                        if row:
                            row.name_ja = translated
                            session.add(row)
                            await session.flush()
                    logger.info(
                        "[바이마] 일문 번역: %s → %s",
                        product["name"][:30],
                        translated[:40],
                    )
            except Exception as e:
                logger.warning(f"[바이마] 일문 번역 실패(무시): {e}")

        # 번역 후에도 일문명 없으면 등록 차단 (한글명 노출 방지)
        if not product.get("name_ja"):
            return {
                "success": False,
                "message": "일문상품명(name_ja) 미설정 — 자동번역 실패. 수동 입력 후 재전송 필요.",
                "error_type": "missing_name_ja",
            }

        settings = creds if creds and "_no_auth" not in creds else {}

        # PS-API 경로: 액세스 토큰이 있으면 실제 API 등록 (카테고리는 상품필드로 내부매핑)
        token = settings.get("accessToken", "")
        if token:
            from backend.domain.samba.proxy.buyma import BuymaApiClient

            client = BuymaApiClient(
                token,
                sandbox=bool(settings.get("sandbox")),
                client_id=settings.get("clientId", ""),
                client_secret=settings.get("clientSecret", ""),
            )
            res = await client.register_product(product, control="publish")
            if res.get("success"):
                return {
                    "success": True,
                    "data": res,
                    "productNo": res.get("reference_number") or product.get("id") or "",
                    "message": res.get("message", ""),
                }
            return {
                "success": False,
                "message": res.get("message", ""),
                "error_type": res.get("error_type", "api_error"),
            }

        # 폴백: 토큰 없으면 기존 CSV 방식
        client = BuymaClient(seller_id=settings.get("storeId", ""))
        try:
            result = await client.register_product(product, category_id)
            return {
                "success": True,
                "data": result,
                "productNo": product.get("id") or "",
                "message": result.get("message", ""),
            }
        except Exception as e:
            logger.error(f"[바이마] CSV 생성 실패: {e}")
            return {"success": False, "message": str(e), "error_type": "unknown"}

    async def delete(self, session, product_no: str, account) -> dict[str, Any]:
        """바이마 리스팅 삭제 — 오토튠 품절정리 루프가 호출.

        소싱처(무신사) 상품이 delist/전 사이즈 품절되면(sale_status=sold_out) 이행
        불가하므로, 마켓 무관 품절정리 파이프라인이 이 메서드로 바이마 리스팅을 내린다.
        (사이즈 일부만 품절인 경우는 execute() 재전송으로 처리되고, 여기 delete는
        전멸/delist 케이스 담당.)

        정식 PS-API 승인 후 상품삭제 엔드포인트로 실제 반영한다. 현재는 API 미설정 시
        조용한 no-op 대신 '보류'를 명시 반환 — 오토튠 로그로 수동 처리 대상이 드러난다.
        """
        from backend.domain.samba.account.credentials import buyma_creds

        creds = buyma_creds(account) if account else {}
        token = creds.get("accessToken", "")
        if not token:
            logger.info(
                "[바이마] 삭제 요청 product_no=%s — PS-API 토큰 없음, 수동 처리 대기",
                product_no,
            )
            return {
                "success": False,
                "message": "바이마 PS-API 토큰 미설정 — 삭제 보류(수동 삭제 필요).",
                "error_type": "api_not_ready",
            }

        from backend.domain.samba.proxy.buyma import BuymaApiClient

        client = BuymaApiClient(token, sandbox=bool(creds.get("sandbox")))
        res = await client.set_control(str(product_no), "delete")
        logger.info("[바이마] 삭제(control=delete) product_no=%s → %s", product_no, res)
        return res
