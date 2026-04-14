"""SambaWave Collector service."""

from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from backend.domain.samba.collector.model import (
    SambaCollectedProduct,
    SambaSearchFilter,
)
from backend.domain.samba.collector.repository import (
    SambaCollectedProductRepository,
    SambaSearchFilterRepository,
)

# 브랜드/제조사 필드의 의미없는 플레이스홀더 값
_BRAND_PLACEHOLDERS = {
    "상세참조",
    "상품상세참조",
    "상세설명참조",
    "상세페이지참조",
    "상세 참조",
}


def _is_placeholder(value: str) -> bool:
    """브랜드/제조사 필드의 플레이스홀더 값 여부 판별."""
    return value.strip() in _BRAND_PLACEHOLDERS


def _derive_sale_status(data: Dict[str, Any]) -> None:
    """전옵션 품절이면 sale_status를 sold_out으로 자동 설정."""
    if data.get("sale_status") and data["sale_status"] != "in_stock":
        return
    options = data.get("options")
    if not options or not isinstance(options, list) or len(options) == 0:
        return
    if all((opt.get("stock", 0) or 0) <= 0 for opt in options if isinstance(opt, dict)):
        data["sale_status"] = "sold_out"


class SambaCollectorService:
    def __init__(
        self,
        filter_repo: SambaSearchFilterRepository,
        product_repo: SambaCollectedProductRepository,
    ):
        self.filter_repo = filter_repo
        self.product_repo = product_repo

    # ==================== Search Filters ====================

    async def list_filters(
        self, skip: int = 0, limit: int = 50
    ) -> List[SambaSearchFilter]:
        return await self.filter_repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def create_filter(self, data: Dict[str, Any]) -> SambaSearchFilter:
        return await self.filter_repo.create_async(**data)

    async def update_filter(
        self, filter_id: str, data: Dict[str, Any]
    ) -> Optional[SambaSearchFilter]:
        return await self.filter_repo.update_async(filter_id, **data)

    async def delete_filter(self, filter_id: str) -> bool:
        return await self.filter_repo.delete_async(filter_id)

    # ==================== Collected Products ====================

    async def list_collected_products(
        self,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
        source_site: Optional[str] = None,
    ) -> List[SambaCollectedProduct]:
        if status and source_site:
            return await self.product_repo.list_by_filters(
                status=status, source_site=source_site
            )
        if status:
            return await self.product_repo.list_by_status(status)
        if source_site:
            return await self.product_repo.list_by_filters(source_site=source_site)
        return await self.product_repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def get_collected_product(
        self, product_id: str
    ) -> Optional[SambaCollectedProduct]:
        return await self.product_repo.get_async(product_id)

    async def create_collected_product(
        self, data: Dict[str, Any]
    ) -> SambaCollectedProduct:
        self._sanitize_kream_data(data)
        self._clean_company_names(data)
        self._fill_optional_images(data)
        await self._fill_source_brand(data)
        await self._inherit_group_attributes(data)
        _derive_sale_status(data)
        try:
            return await self.product_repo.create_async(**data)
        except IntegrityError:
            # 다른 검색필터에서 이미 수집된 상품 → 기존 상품 업데이트
            await self.product_repo.session.rollback()
            existing = (
                (
                    await self.product_repo.session.execute(
                        select(SambaCollectedProduct).where(
                            SambaCollectedProduct.source_site
                            == data.get("source_site"),
                            SambaCollectedProduct.site_product_id
                            == data.get("site_product_id"),
                        )
                    )
                )
                .scalars()
                .first()
            )
            if existing:
                for k, v in data.items():
                    if k not in ("id", "source_site", "site_product_id", "created_at"):
                        setattr(existing, k, v)
                await self.product_repo.session.flush()
                return existing
            raise

    async def _fill_source_brand(self, data: Dict[str, Any]) -> None:
        """검색필터의 source_brand_name으로 빈 brand/manufacturer 자동 채움."""
        fid = data.get("search_filter_id")
        if not fid:
            return
        sf = await self.filter_repo.get_async(fid)
        if not sf or not sf.source_brand_name:
            return
        brand = sf.source_brand_name
        if not (data.get("brand") or "").strip():
            data["brand"] = brand
        mfr = (data.get("manufacturer") or "").strip()
        if not mfr or _is_placeholder(mfr):
            data["manufacturer"] = brand

    async def _inherit_group_attributes(self, data: Dict[str, Any]) -> None:
        """같은 그룹 기존 상품의 태그/SEO/정책/마켓가격을 신규 상품에 상속."""
        fid = data.get("search_filter_id")
        if not fid:
            return
        # 이미 설정된 값은 덮어쓰지 않음
        if (
            data.get("tags")
            or data.get("seo_keywords")
            or data.get("applied_policy_id")
        ):
            return
        existing = await self.product_repo.list_by_filter(fid, limit=1)
        if not existing:
            return
        ref = existing[0]
        # 태그 복사 (내부 시스템 태그 제외)
        ref_tags = [t for t in (ref.tags or []) if not t.startswith("__")]
        if ref_tags:
            data["tags"] = ref_tags + ["__ai_tagged__"]
        # SEO 키워드 복사
        if ref.seo_keywords:
            data["seo_keywords"] = list(ref.seo_keywords)
        # 정책 복사
        if ref.applied_policy_id:
            data["applied_policy_id"] = ref.applied_policy_id
        # 마켓 가격 복사
        if ref.market_prices:
            data["market_prices"] = dict(ref.market_prices)

    def prepare_product_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """전처리만 수행 (배치 저장용). DB 저장은 별도."""
        self._sanitize_kream_data(data)
        self._clean_company_names(data)
        self._fill_optional_images(data)
        return data

    async def bulk_create_products(self, items: list[Dict[str, Any]]) -> int:
        """배치 INSERT — 전처리 완료된 데이터 리스트.
        검색필터에 정책이 설정되어 있으면 신규 상품에 자동 적용한다.
        모든 소싱처(무신사/롯데온/SSG 등)가 이 함수를 공통 사용.
        """
        if not items:
            return 0
        # 검색필터의 정책을 신규 상품에 자동 적용
        filter_ids = {
            item.get("search_filter_id")
            for item in items
            if item.get("search_filter_id")
        }
        filter_policy_map: Dict[str, str] = {}
        filter_brand_map: Dict[str, str] = {}
        if filter_ids:
            filters = await self.filter_repo.filter_by_async(limit=len(filter_ids) + 10)
            for f in filters:
                if f.id in filter_ids:
                    if f.applied_policy_id:
                        filter_policy_map[f.id] = f.applied_policy_id
                    if f.source_brand_name:
                        filter_brand_map[f.id] = f.source_brand_name
        for item in items:
            if not item.get("applied_policy_id"):
                fid = item.get("search_filter_id", "")
                if fid in filter_policy_map:
                    item["applied_policy_id"] = filter_policy_map[fid]
        # 소싱처 브랜드명으로 빈 brand/manufacturer 자동 채움
        for item in items:
            fid = item.get("search_filter_id", "")
            source_brand = filter_brand_map.get(fid)
            if not source_brand:
                continue
            if not (item.get("brand") or "").strip():
                item["brand"] = source_brand
            mfr = (item.get("manufacturer") or "").strip()
            if not mfr or _is_placeholder(mfr):
                item["manufacturer"] = source_brand
        from backend.domain.samba.collector.model import SambaCollectedProduct
        from sqlalchemy.exc import IntegrityError

        created = 0
        for d in items:
            _derive_sale_status(d)
            obj = SambaCollectedProduct(**d)
            self.product_repo.session.add(obj)
            try:
                await self.product_repo.session.flush()
                created += 1
            except IntegrityError:
                # 동시 수집으로 중복 발생 시 기존 상품 업데이트
                await self.product_repo.session.rollback()
                existing = (
                    (
                        await self.product_repo.session.execute(
                            select(SambaCollectedProduct).where(
                                SambaCollectedProduct.source_site
                                == d.get("source_site"),
                                SambaCollectedProduct.site_product_id
                                == d.get("site_product_id"),
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if existing:
                    update_fields = {
                        k: v
                        for k, v in d.items()
                        if k
                        not in ("id", "source_site", "site_product_id", "created_at")
                    }
                    for k, v in update_fields.items():
                        setattr(existing, k, v)
                    await self.product_repo.session.flush()
                    created += 1
        await self.product_repo.session.commit()
        return created

    async def update_collected_product(
        self, product_id: str, data: Dict[str, Any]
    ) -> Optional[SambaCollectedProduct]:
        self._sanitize_kream_data(data)
        self._clean_company_names(data)
        self._fill_optional_images(data)
        # tags가 None으로 전달되면 기존 태그를 덮어쓰지 않도록 제거
        # (명시적으로 빈 리스트 []를 보내면 태그 초기화 허용)
        if "tags" in data and data["tags"] is None:
            del data["tags"]
        return await self.product_repo.update_async(product_id, **data)

    @staticmethod
    def _sanitize_kream_data(data: Dict[str, Any]) -> None:
        """비-KREAM 상품의 kream_data 오염 방지.

        확장앱이 무신사 고시정보를 kream_data로 보내는 경우,
        올바른 필드(material, color 등)로 분리하고 kream_data를 제거한다.
        """
        if data.get("source_site") == "KREAM":
            return
        kd = data.get("kream_data")
        if not isinstance(kd, dict):
            return
        field_map = {
            "color": "color",
            "material": "material",
            "brandNation": "origin",
        }
        for kd_key, field in field_map.items():
            if kd.get(kd_key) and not data.get(field):
                data[field] = kd[kd_key]
        data.pop("kream_data", None)

    @staticmethod
    def _clean_company_names(data: Dict[str, Any]) -> None:
        """브랜드/제조사에서 (주), ㈜, (株) 제거."""
        import re

        _pattern = re.compile(r"\(주\)|㈜|\(株\)")
        for field in ("brand", "manufacturer"):
            val = data.get(field)
            if val and isinstance(val, str):
                cleaned = _pattern.sub("", val).strip()
                if cleaned:
                    data[field] = cleaned

    @staticmethod
    def _fill_optional_images(data: Dict[str, Any]) -> None:
        """추가이미지가 부족하면 상세이미지로 보충 (최대 9장)."""
        images = data.get("images")
        detail_images = data.get("detail_images")
        if not isinstance(images, list) or not isinstance(detail_images, list):
            return
        if len(images) >= 9:
            return
        existing = set(images)
        for di in detail_images:
            if di not in existing and len(images) < 9:
                images.append(di)
                existing.add(di)
        data["images"] = images

    async def delete_collected_product(self, product_id: str) -> bool:
        return await self.product_repo.delete_async(product_id)

    async def search_collected_products(
        self, query: str, limit: int = 100
    ) -> List[SambaCollectedProduct]:
        return await self.product_repo.search(query, limit)

    async def apply_policy_to_filter_products(
        self,
        filter_id: str,
        policy_id: str,
        policy_data: Optional[Dict[str, Any]] = None,
    ) -> int:
        """그룹(필터)에 적용된 정책을 해당 그룹의 모든 상품에 전파."""
        if not policy_data:
            # 가격 계산 불필요 → bulk update로 한 번에 처리
            return await self.product_repo.bulk_update_by_filter(
                filter_id, applied_policy_id=policy_id
            )
        # 가격 계산 필요 → 상품별 처리 (sale_price가 다름)
        products = await self.product_repo.list_by_filter(filter_id)
        use_range = policy_data.get("use_range_margin", False)
        range_margins = policy_data.get("range_margins", [])
        default_margin = policy_data.get("margin_rate", 15)
        shipping = policy_data.get("shipping_cost", 0)
        extra = policy_data.get("extra_charge", 0)
        updated = 0
        for p in products:
            base = p.sale_price or p.original_price or 0
            # 범위 마진: 원가 구간별 마진율 적용
            margin_rate = default_margin
            if use_range and range_margins:
                for r in range_margins:
                    max_val = r.get("max") or 9999999999
                    if base >= r.get("min", 0) and base < max_val:
                        margin_rate = r.get("rate", 15)
                        break
            # 소싱처별 추가 마진
            source_margin = 0
            ssm_data = policy_data.get("source_site_margins") or {}
            if ssm_data and p.source_site:
                _ssm = ssm_data.get(p.source_site, {})
                _ss_rate = _ssm.get("marginRate", 0)
                _ss_amount = _ssm.get("marginAmount", 0)
                if _ss_rate > 0:
                    source_margin += round(base * _ss_rate / 100)
                if _ss_amount > 0:
                    source_margin += _ss_amount
            calculated = int(
                base * (1 + margin_rate / 100) + source_margin + shipping + extra
            )
            await self.product_repo.update_async(
                p.id,
                applied_policy_id=policy_id,
                market_prices={"default": calculated},
            )
            updated += 1
        return updated
