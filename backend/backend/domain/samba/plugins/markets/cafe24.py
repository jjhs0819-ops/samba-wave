"""카페24 마켓 플러그인 — OAuth2 기반 상품 등록/수정/삭제.

카페24 Admin REST API v2 사용.
인증: OAuth2 (access_token + refresh_token)
상품 등록 플로우:
  1. 상품 생성 (POST /products)
  2. 이미지 URL 설정 (PUT /products/{no})
  3. 카테고리 연결 (POST /categories/products)
  4. 옵션 등록 (POST /products/{no}/options)
  5. 품목(variant)별 재고 설정 (PUT /products/{no}/variants/{code})
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class Cafe24Plugin(MarketPlugin):
    """카페24 마켓 플러그인.

    자사몰 솔루션 — 카페24 API를 통해 상품 등록/수정/삭제.
    """

    market_type = "cafe24"
    policy_key = "카페24"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        from backend.domain.samba.proxy.cafe24 import Cafe24Client

        return Cafe24Client.transform_product(product, category_id)

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """카페24 상품 등록/수정."""
        from backend.domain.samba.proxy.cafe24 import Cafe24Client

        # 인증정보 추출
        mall_id = creds.get("mallId", "")
        client_id = creds.get("clientId", "")
        client_secret = creds.get("clientSecret", "")
        access_token = creds.get("accessToken", "")
        refresh_token = creds.get("refreshToken", "")

        if not mall_id:
            return {
                "success": False,
                "message": "카페24 Mall ID가 없습니다. 계정 설정에서 mallId를 입력해주세요.",
            }
        if not client_id or not client_secret:
            return {
                "success": False,
                "message": "카페24 Client ID/Secret이 없습니다. 계정 설정에서 입력해주세요.",
            }
        if not access_token and not refresh_token:
            return {
                "success": False,
                "message": "카페24 Access Token 또는 Refresh Token이 없습니다.",
            }

        client = Cafe24Client(
            mall_id=mall_id,
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        # 계정 설정 주입
        product_copy = dict(product)
        if account:
            extras = account.additional_fields or {}
            if extras.get("asPhone"):
                product_copy["_as_phone"] = extras["asPhone"]

        # 정책에서 배송비/재고 설정
        policy_id = product.get("applied_policy_id")
        if policy_id:
            from backend.domain.samba.policy.repository import SambaPolicyRepository

            policy_repo = SambaPolicyRepository(session)
            _policy = await policy_repo.get_async(policy_id)
            if _policy:
                pr = _policy.pricing or {}
                mp = (_policy.market_policies or {}).get("카페24", {})
                shipping = int(mp.get("shippingCost") or pr.get("shippingCost") or 0)
                if shipping > 0:
                    product_copy["_delivery_fee_type"] = "PAID"
                    product_copy["_delivery_base_fee"] = shipping
                if mp.get("maxStock"):
                    product_copy["_max_stock"] = mp["maxStock"]

        # 상품 데이터 변환
        data = Cafe24Client.transform_product(product_copy, category_id)

        # ── 상품 수정 모드 ──
        if existing_no:
            try:
                product_no = int(existing_no)
                result = await client.update_product(product_no, data)

                # 토큰 갱신됐으면 저장
                await self._save_tokens_if_changed(session, account, client)

                return {
                    "success": True,
                    "message": "카페24 수정 성공",
                    "data": result,
                }
            except Exception as e:
                err_msg = str(e)
                if "404" in err_msg:
                    logger.warning(f"[카페24] 상품 {existing_no} 없음 → 신규등록 전환")
                    # 신규등록으로 전환
                else:
                    return {"success": False, "message": f"카페24 수정 실패: {err_msg}"}

        # ── 상품 신규등록 ──
        try:
            # 1. 상품 생성
            result = await client.register_product(data)
            product_no = result.get("product_no")
            if not product_no:
                return {
                    "success": False,
                    "message": "카페24 상품 생성 실패: product_no 없음",
                }

            logger.info(f"[카페24] 1단계 완료 — 상품 생성: product_no={product_no}")

            # 2. 카테고리 연결 (카테고리 ID가 있는 경우)
            if category_id:
                try:
                    await client.link_product_to_category(product_no, int(category_id))
                    logger.info(
                        f"[카페24] 2단계 완료 — 카테고리 연결: category_no={category_id}"
                    )
                except Exception as cat_e:
                    logger.warning(f"[카페24] 카테고리 연결 실패 (무시): {cat_e}")

            # 3. 옵션 등록
            options = product_copy.get("options") or []
            sale_price = int(product_copy.get("sale_price", 0) or 0)
            max_stock = product_copy.get("_max_stock", 0)

            if options:
                opt_payload = Cafe24Client.build_options_payload(
                    options, sale_price, max_stock
                )
                if opt_payload:
                    try:
                        await client.register_options(product_no, opt_payload)
                        logger.info(
                            f"[카페24] 3단계 완료 — 옵션 등록: {len(opt_payload)}개 옵션그룹"
                        )

                        # 4. variant별 재고 설정
                        import asyncio

                        await asyncio.sleep(1)  # 옵션 등록 후 variant 생성 대기
                        variants = await client.get_variants(product_no)
                        if variants:
                            updates = Cafe24Client.build_variant_updates(
                                options,
                                variants,
                                sale_price,
                                max_stock,
                            )
                            for upd in updates:
                                vcode = upd.pop("variant_code")
                                try:
                                    await client.update_variant(product_no, vcode, upd)
                                except Exception as var_e:
                                    logger.warning(
                                        f"[카페24] variant {vcode} 업데이트 실패: {var_e}"
                                    )
                            logger.info(
                                f"[카페24] 4단계 완료 — variant 재고 설정: {len(updates)}개"
                            )
                    except Exception as opt_e:
                        logger.warning(f"[카페24] 옵션 등록 실패 (무시): {opt_e}")

            # 토큰 갱신됐으면 저장
            await self._save_tokens_if_changed(session, account, client)

            return {
                "success": True,
                "message": "카페24 등록 성공",
                "data": {"product_no": product_no, **result},
            }

        except Exception as e:
            return {"success": False, "message": f"카페24 등록 실패: {e}"}

    async def delete(self, session, product_no: str, account) -> dict[str, Any]:
        """카페24 상품 판매중지."""
        creds = await self._load_auth(session, account)
        if not creds:
            return {"success": False, "message": "카페24 인증정보 없음"}

        from backend.domain.samba.proxy.cafe24 import Cafe24Client

        client = Cafe24Client(
            mall_id=creds.get("mallId", ""),
            client_id=creds.get("clientId", ""),
            client_secret=creds.get("clientSecret", ""),
            access_token=creds.get("accessToken", ""),
            refresh_token=creds.get("refreshToken", ""),
        )

        try:
            await client.stop_selling(int(product_no))
            return {"success": True, "message": "카페24 판매중지 완료"}
        except Exception as e:
            return {"success": False, "message": f"카페24 판매중지 실패: {e}"}

    async def test_auth(self, session, account) -> bool:
        """카페24 인증 테스트 — 카테고리 조회로 확인."""
        creds = await self._load_auth(session, account)
        if not creds:
            return False

        from backend.domain.samba.proxy.cafe24 import Cafe24Client

        client = Cafe24Client(
            mall_id=creds.get("mallId", ""),
            client_id=creds.get("clientId", ""),
            client_secret=creds.get("clientSecret", ""),
            access_token=creds.get("accessToken", ""),
            refresh_token=creds.get("refreshToken", ""),
        )
        try:
            cats = await client.get_categories()
            logger.info(f"[카페24] 인증 테스트 성공: {len(cats)}개 카테고리")
            return True
        except Exception as e:
            logger.warning(f"[카페24] 인증 테스트 실패: {e}")
            return False

    @staticmethod
    async def _save_tokens_if_changed(session, account, client) -> None:
        """토큰이 갱신됐으면 계정에 저장."""
        if not account:
            return
        extras = account.additional_fields or {}
        old_token = extras.get("accessToken", "")
        if client.access_token and client.access_token != old_token:
            extras["accessToken"] = client.access_token
            if client.refresh_token:
                extras["refreshToken"] = client.refresh_token
            account.additional_fields = extras
            session.add(account)
            try:
                await session.commit()
                logger.info("[카페24] 갱신된 토큰 계정에 저장 완료")
            except Exception as e:
                logger.warning(f"[카페24] 토큰 저장 실패: {e}")
