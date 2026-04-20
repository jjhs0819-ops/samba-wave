"""SambaWave Collector service."""

import re
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

    async def _exists_by_name(
        self,
        tenant_id: Optional[str],
        source_site: str,
        name: str,
        exclude_site_product_id: Optional[str] = None,
    ) -> bool:
        """동일 소싱처 내 동일 원 상품명 존재 여부 (삭제 포함)."""
        q = select(SambaCollectedProduct).where(
            SambaCollectedProduct.tenant_id == tenant_id,
            SambaCollectedProduct.source_site == source_site,
            SambaCollectedProduct.name == name.strip(),
        )
        if exclude_site_product_id:
            q = q.where(
                SambaCollectedProduct.site_product_id != exclude_site_product_id
            )
        result = await self.product_repo.session.execute(q.limit(1))
        return result.scalars().first() is not None

    async def create_collected_product(
        self, data: Dict[str, Any]
    ) -> Optional[SambaCollectedProduct]:
        self._sanitize_kream_data(data)
        self._clean_company_names(data)
        self._fill_optional_images(data)
        await self._fill_source_brand(data)
        await self._inherit_group_attributes(data)
        _derive_sale_status(data)
        # 동일 소싱처 내 동일 원 상품명 존재 시 수집 차단
        name_val = (data.get("name") or "").strip()
        if name_val:
            if await self._exists_by_name(
                tenant_id=data.get("tenant_id"),
                source_site=data.get("source_site", ""),
                name=name_val,
                exclude_site_product_id=data.get("site_product_id"),
            ):
                return None
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
        # 태그/SEO/정책: SearchFilter 전체에서 참조 (같은 검색그룹이면 공유)
        filter_refs = await self.product_repo.list_by_filter(fid, limit=1)
        # market_prices: group_key 단위로 참조 (동일 SKU 패밀리에서만 의미 있음)
        group_refs: list = []
        group_key = (data.get("group_key") or "").strip()
        if group_key:
            group_refs = await self.product_repo.filter_by_async(
                search_filter_id=fid,
                group_key=group_key,
                limit=1,
                order_by="created_at",
                order_by_desc=True,
            )
        if filter_refs:
            ref = filter_refs[0]
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
        if group_refs:
            gref = group_refs[0]
            # 마켓 가격 복사 (동일 모델 SKU 패밀리 내에서만)
            if gref.market_prices:
                data["market_prices"] = dict(gref.market_prices)

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

        # 마켓 등록된 상품명 + (source_site, site_product_id) 키 사전 조회
        # tenant_id가 None인 경우도 포함 (멀티테넌시 미적용 환경)
        tenant_ids = {d.get("tenant_id") for d in items}
        registered_names_by_tid: Dict[str, set] = {}
        registered_keys_by_tid: Dict[str, set] = {}
        for tid in tenant_ids:
            key = str(tid) if tid is not None else "__null__"
            names, keys = await self.product_repo.get_registered_name_keys(tid)
            registered_names_by_tid[key] = names
            registered_keys_by_tid[key] = keys

        # 동일 소싱처 내 동일 원 상품명 중복 필터링
        source_site_pairs = {(d.get("tenant_id"), d.get("source_site")) for d in items}
        # (tenant_id, source_site, name) → set of site_product_ids
        existing_name_spids: Dict[tuple, set] = {}
        for tid, ss in source_site_pairs:
            rows = (
                await self.product_repo.session.execute(
                    select(
                        SambaCollectedProduct.name,
                        SambaCollectedProduct.site_product_id,
                    ).where(
                        SambaCollectedProduct.tenant_id == tid,
                        SambaCollectedProduct.source_site == ss,
                    )
                )
            ).all()
            for row_name, row_spid in rows:
                k = (tid, ss, (row_name or "").strip())
                existing_name_spids.setdefault(k, set()).add(row_spid)
        seen_names: set = set()
        filtered_items: list = []
        for d in items:
            tid = str(d.get("tenant_id") or "")
            ss = d.get("source_site")
            nm = (d.get("name") or "").strip()
            spid = d.get("site_product_id")
            key = (tid, ss, nm)
            existing_spids = existing_name_spids.get(key, set())
            if existing_spids:
                if spid and spid in existing_spids:
                    # 동일 site_product_id 재수집 → upsert 허용
                    pass
                else:
                    # 다른 상품이 동일 이름 → skip
                    continue
            elif key in seen_names:
                # 배치 내 자체 중복 → skip
                continue
            # 마켓 등록된 상품명 차단: 동일 상품(같은 키) 갱신은 허용
            tid_key = tid if tid else "__null__"
            reg_names = registered_names_by_tid.get(tid_key, set())
            reg_keys = registered_keys_by_tid.get(tid_key, set())
            if nm in reg_names and (ss, spid) not in reg_keys:
                continue
            seen_names.add(key)
            filtered_items.append(d)
        items = filtered_items

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

    async def get_duplicate_products(self, tenant_id: str) -> list:
        """동일 name 중복 상품 그룹 반환 (원본=가장 먼저 수집된 것, 나머지=중복)."""
        from collections import defaultdict

        products = await self.product_repo.find_duplicates(tenant_id)
        groups_map: dict = defaultdict(list)
        for p in products:
            groups_map[(p.name or "").strip()].append(p)

        def _to_dict(p) -> dict:
            return {
                "id": p.id,
                "name": p.name,
                "source_site": p.source_site,
                "brand": p.brand,
                "sale_price": p.sale_price,
                "images": (p.images or [])[:1],
                "registered_accounts": p.registered_accounts,
                "status": p.status,
            }

        def _is_registered(p) -> bool:
            ra = p.registered_accounts
            return bool(ra and ra not in ([], "null", None))

        def _min_pid(p) -> int:
            """market_product_nos 값 중 가장 작은 pid 숫자. 없으면 inf."""
            mpn = p.market_product_nos
            if not mpn or mpn in ({}, None):
                return 2**62
            try:
                pids = [int(v) for v in mpn.values() if str(v).isdigit()]
                return min(pids) if pids else 2**62
            except Exception:
                return 2**62

        result = []
        for name, items in groups_map.items():
            if len(items) <= 1:
                continue
            # 등록된 상품 중 pid가 가장 작은 것(먼저 마켓 등록)을 원본으로
            registered = [p for p in items if _is_registered(p)]
            if registered:
                original = min(registered, key=_min_pid)
            else:
                original = items[0]
            duplicates = [p for p in items if p.id != original.id]
            result.append(
                {
                    "name": name,
                    "total": len(items),
                    "registered": [_to_dict(original)],
                    "duplicates": [_to_dict(p) for p in duplicates],
                }
            )
        return result

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
