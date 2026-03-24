"""롯데홈쇼핑 마켓 플러그인.

기존 dispatcher._handle_lottehome + _transform_for_lottehome 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


async def _get_setting(session, key: str) -> Any:
  """samba_settings 테이블에서 설정값 조회."""
  from backend.domain.samba.forbidden.model import SambaSettings
  from sqlmodel import select
  stmt = select(SambaSettings).where(SambaSettings.key == key)
  result = await session.execute(stmt)
  row = result.scalars().first()
  return row.value if row else None


def _transform_for_lottehome(
  product: dict[str, Any], category_id: str, creds: dict[str, Any] | None = None,
) -> dict[str, Any]:
  """수집 상품 → 롯데홈쇼핑 API 형식 변환.

  API 문서: registApiGoodsInfo.lotte 파라미터 기준.
  """
  creds = creds or {}
  images = product.get("images") or []
  sale_price = int(product.get("sale_price", 0) or 0)
  # 판매가 끝자리 0 필수 (API 에러 1062)
  if sale_price % 10 != 0:
    sale_price = (sale_price // 10 + 1) * 10

  # 마진율 (정수, 1~99)
  margin_rate = int(product.get("margin_rate", 0) or 0)
  if margin_rate <= 0:
    margin_rate = 20

  # MD상품군번호 — 테스트: 24973(구두/신발), 카테고리코드가 없으면 creds에서 기본값
  md_gsgr_no = creds.get("md_gsgr_no", "") or category_id or ""

  # 품목코드 — 기본 102(구두/신발)
  ec_goods_artc_cd = creds.get("ec_goods_artc_cd", "102")

  data: dict[str, Any] = {
    # 필수
    "brnd_no": product.get("brand_code", "") or creds.get("brnd_no", "010565"),
    "goods_nm": product.get("name", ""),
    "md_gsgr_no": md_gsgr_no,
    "pur_shp_cd": "3",  # 위탁판매
    "sale_shp_cd": "10",  # 정상
    "sale_prc": str(sale_price),
    "mrgn_rt": str(margin_rate),
    "tdf_sct_cd": "1",  # 과세
    "disp_no": category_id or creds.get("disp_no", ""),
    "inv_mgmt_yn": "Y",
    "item_mgmt_yn": "N",
    "inv_qty": "999",
    "dlv_proc_tp_cd": "1",  # 업체배송
    "gift_pkg_yn": "N",
    "exch_rtgs_sct_cd": "20",  # 교환/반품 가능
    "dlv_mean_cd": "10",  # 택배
    "dlv_goods_sct_cd": "01",  # 일반상품
    "dlv_dday": "2",  # 배송기일 2일
    "byr_age_lmt_cd": "0",  # 나이제한 없음
    "dlv_polc_no": creds.get("dlv_polc_no", ""),
    "corp_dlvp_sn": creds.get("corp_dlvp_sn", ""),  # 반품지
    "corp_rls_pl_sn": creds.get("corp_rls_pl_sn", ""),  # 출고지
    "orpl_nm": product.get("origin", "") or "해외",
    "mfcp_nm": product.get("manufacturer", "") or product.get("brand", "") or "상세페이지 참조",
    "img_url": images[0] if images else "",
    "dtl_info_fcont": product.get("detail_html", "") or f"<p>{product.get('name', '')}</p>",
    "sum_pkg_psb_yn": "N",
    "ec_goods_artc_cd": ec_goods_artc_cd,
    "cdl_yn": "Y",  # 업체직송
    "cdl_goods_std": "30",  # 중형
    "prl_imp_yn": "N",
    "price_site_yn": "Y",
  }

  # 부가이미지 (최대 5장)
  for i, img in enumerate(images[1:6], start=1):
    data[f"img_url{i}"] = img

  # 품목별 항목정보 (구두/신발 102 기본값)
  if ec_goods_artc_cd == "102":
    data["10030"] = product.get("color", "") or "상세 이미지 참조"  # 색상
    data["10084"] = product.get("material", "") or "상세 이미지 참조"  # 주요소재
    data["10107"] = product.get("size_info", "") or "상세 이미지 참조"  # 크기
    data["10041_RD"] = "Y"  # 수입여부
    data["10041"] = "Y"
    data["10116"] = "품질보증기준에 따름"  # 품질보증기준
    data["10001"] = "상세페이지 참조"  # A/S 책임자/전화번호
  elif ec_goods_artc_cd == "101":
    data["10030"] = product.get("color", "") or "상세 이미지 참조"
    data["10035"] = "상세 이미지 참조"  # 세탁방법
    data["10041_RD"] = "Y"
    data["10041"] = "Y"
    data["10073"] = "상세 이미지 참조"  # 제조연월
    data["10116"] = "품질보증기준에 따름"
    data["10001"] = "상세페이지 참조"

  return data


class LotteHomePlugin(MarketPlugin):
  market_type = "lottehome"
  policy_key = "롯데홈쇼핑"
  required_fields = ["name", "sale_price"]

  def transform(self, product: dict, category_id: str, **kwargs) -> dict:
    """상품 데이터 → 롯데홈쇼핑 API 포맷 변환."""
    creds = kwargs.get("creds", {})
    return _transform_for_lottehome(product, category_id, creds)

  async def execute(
    self,
    session,
    product: dict,
    creds: dict,
    category_id: str,
    account,
    existing_no: str,
  ) -> dict[str, Any]:
    """롯데홈쇼핑 상품 등록 — 전체 로직."""
    from backend.domain.samba.proxy.lottehome import LotteHomeClient

    # account.additional_fields 우선, creds(base._load_auth) 보완
    auth_creds: dict[str, Any] = dict(creds)
    if account:
      extra = getattr(account, "additional_fields", None) or {}
      if extra.get("userId") or extra.get("password") or extra.get("agncNo"):
        auth_creds = {**auth_creds, **extra}
      elif getattr(account, "seller_id", None):
        auth_creds.setdefault("userId", account.seller_id)
        auth_creds.setdefault("password", extra.get("password", ""))
        auth_creds.setdefault("agncNo", extra.get("agncNo", account.seller_id))
        auth_creds.setdefault("env", extra.get("env", "test"))

    if not auth_creds:
      setting = await _get_setting(session, "lottehome_credentials")
      if setting and isinstance(setting, dict):
        auth_creds = setting
    if not auth_creds:
      setting = await _get_setting(session, "store_lottehome")
      if setting and isinstance(setting, dict):
        auth_creds = setting
    if not auth_creds:
      return {"success": False, "message": "롯데홈쇼핑 설정이 없습니다."}

    user_id = auth_creds.get("userId", "") or (getattr(account, "seller_id", "") if account else "")
    password = auth_creds.get("password", "")
    agnc_no = auth_creds.get("agncNo", "")
    env = auth_creds.get("env", "test")

    if not user_id or not password:
      return {"success": False, "message": "롯데홈쇼핑 userId/password가 없습니다."}

    client = LotteHomeClient(user_id, password, agnc_no, env)

    # 반품지/출고지/배송정책 자동 조회 (auth_creds에 없으면)
    if not auth_creds.get("corp_dlvp_sn") or not auth_creds.get("corp_rls_pl_sn") or not auth_creds.get("dlv_polc_no"):
      try:
        # 배송지(출고지/반품지) 조회
        places = await client.search_delivery_places()
        place_data = places.get("data", {})
        place_result = place_data.get("Result", place_data)
        place_list = place_result.get("DlvPlcList", place_result.get("DlvpList", {}))
        items = place_list.get("DlvPlcInfo", place_list.get("DlvpInfo", []))
        if isinstance(items, dict):
          items = [items]
        for item in (items if isinstance(items, list) else []):
          tp = item.get("dlvp_tp_cd", "")
          sn = item.get("corp_dlvp_sn", "")
          if tp in ("10", "30") and not auth_creds.get("corp_dlvp_sn") and sn:
            auth_creds["corp_dlvp_sn"] = sn  # 반품지
            logger.info(f"[롯데홈쇼핑] 반품지 자동 조회: {sn}")
          if tp in ("40", "50") and not auth_creds.get("corp_rls_pl_sn") and sn:
            auth_creds["corp_rls_pl_sn"] = sn  # 출고지
            logger.info(f"[롯데홈쇼핑] 출고지 자동 조회: {sn}")
        # 배송정책 조회
        if not auth_creds.get("dlv_polc_no"):
          policies = await client.search_delivery_policies()
          pol_data = policies.get("data", {})
          pol_result = pol_data.get("Result", pol_data)
          pol_list = pol_result.get("DlvPolcList", pol_result.get("DlvPolcInfo", {}))
          pol_items = pol_list.get("DlvPolcInfo", []) if isinstance(pol_list, dict) else pol_list
          if isinstance(pol_items, dict):
            pol_items = [pol_items]
          if isinstance(pol_items, list) and pol_items:
            auth_creds["dlv_polc_no"] = pol_items[0].get("dlv_polc_no", "")
            logger.info(f"[롯데홈쇼핑] 배송정책 자동 조회: {auth_creds['dlv_polc_no']}")
      except Exception as e:
        logger.warning(f"[롯데홈쇼핑] 배송지/정책 자동 조회 실패: {e}")

    goods_data = _transform_for_lottehome(product, category_id, auth_creds)
    result = await client.register_goods(goods_data)

    # 상품번호 추출
    g_data = result.get("data", {})
    g_result = g_data.get("GoodsResults", g_data.get("Result", g_data))
    goods_no = ""
    if isinstance(g_result, dict):
      goods_no = g_result.get("goods_no", "") or g_result.get("Result", "")
    return {"success": True, "message": "롯데홈쇼핑 등록 성공", "data": result, "goodsNo": goods_no}
