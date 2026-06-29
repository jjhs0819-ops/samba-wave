"""현대홈쇼핑(Hmall) Open API 클라이언트.

인증: oauserId / oauseKey 헤더
포맷: XML 요청/응답
BASE_URL: http://openapi.hmall.com/front
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Optional

import httpx

from backend.utils.logger import logger

_BASE_URL = "http://openapi.hmall.com/front"
_DEFAULT_USER_IP = "127.0.0.1"
_DEFAULT_USER_GBCd = "20"  # 협력사 구분코드


class HmallApiError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HmallClient:
    """현대홈쇼핑 Open API 클라이언트."""

    def __init__(
        self,
        oauser_id: str,
        oause_key: str,
        user_id: str,
        ven_cd: str,
        user_nm: str = "",
        user_ip: str = _DEFAULT_USER_IP,
    ) -> None:
        self.oauser_id = oauser_id
        self.oause_key = oause_key
        self.user_id = user_id
        self.ven_cd = ven_cd
        self.user_nm = user_nm or user_id
        self.user_ip = user_ip

    # ─────────────────────────────────────────────
    # 내부: XML 빌더 헬퍼
    # ─────────────────────────────────────────────

    def _session_dataset(self, ds_id: str = "sessionVO") -> ET.Element:
        """세션 Dataset XML 엘리먼트 생성."""
        ds = ET.Element("Dataset", id=ds_id)
        rows = ET.SubElement(ds, "rows")
        row = ET.SubElement(rows, "row")
        ET.SubElement(row, "userGbcd").text = _DEFAULT_USER_GBCd
        ET.SubElement(row, "userId").text = self.user_id
        ET.SubElement(row, "userIp").text = self.user_ip
        ET.SubElement(row, "userNm").text = self.user_nm
        return ds

    def _build_xml(self, datasets: list[ET.Element]) -> str:
        root = ET.Element("Root")
        for ds in datasets:
            root.append(ds)
        return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(
            root, encoding="unicode"
        )

    # ─────────────────────────────────────────────
    # 내부: HTTP 호출
    # ─────────────────────────────────────────────

    async def _call(self, path: str, xml_body: str) -> ET.Element:
        url = _BASE_URL + path
        headers = {
            "Content-Type": "application/xml; charset=UTF-8",
            "Accept": "application/xml",
            "oauserId": self.oauser_id,
            "oauseKey": self.oause_key,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url, content=xml_body.encode("utf-8"), headers=headers
            )

        text = resp.text
        logger.info(f"[Hmall] POST {path} -> HTTP {resp.status_code}")

        try:
            root = ET.fromstring(text)
        except ET.ParseError as e:
            raise HmallApiError(
                "PARSE_ERROR", f"XML 파싱 실패: {e} / 응답: {text[:300]}"
            )

        # 에러 응답 확인
        if root.tag == "error":
            code = root.findtext("code") or "ERROR"
            msg = root.findtext("message") or text[:200]
            raise HmallApiError(code, f"Hmall API 오류 [{code}]: {msg}")

        # Dataset[id=result] 에서 code/message 확인
        result_ds = root.find(".//Dataset[@id='result']")
        if result_ds is not None:
            code = result_ds.findtext(".//row/code") or ""
            msg = result_ds.findtext(".//row/message") or ""
            if code and code != "0000":
                raise HmallApiError(code, f"Hmall API 실패 [{code}]: {msg}")

        return root

    # ─────────────────────────────────────────────
    # 상품 조회
    # ─────────────────────────────────────────────

    async def list_products(
        self,
        search_keyword: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """판매상품 목록 조회 (selectVenSellItemQryList)."""
        ds_cond = ET.Element("Dataset", id="dsCond")
        rows = ET.SubElement(ds_cond, "rows")
        row = ET.SubElement(rows, "row")
        ET.SubElement(row, "venCd").text = self.ven_cd
        ET.SubElement(row, "pageNo").text = str(page)
        ET.SubElement(row, "pageSize").text = str(page_size)
        if search_keyword:
            ET.SubElement(row, "searchKeyword").text = search_keyword

        xml_body = self._build_xml([ds_cond])
        root = await self._call("/pd/pdc/selectVenSellItemQryList.do", xml_body)

        items = []
        for row_el in root.findall(".//Dataset[@id='dsList']//row"):
            items.append({child.tag: child.text for child in row_el})
        return items

    # ─────────────────────────────────────────────
    # 재고 관리
    # ─────────────────────────────────────────────

    async def get_unit_stocks(
        self,
        slitm_cd: str,
        ven_cd: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """속성별 재고 조회 (selectUnitStocks).

        slitmCd: 판매상품코드 (Hmall 상품코드)
        """
        ds_cond = ET.Element("Dataset", id="dsCond")
        rows = ET.SubElement(ds_cond, "rows")
        row = ET.SubElement(rows, "row")
        ET.SubElement(row, "slitmCd").text = slitm_cd
        ET.SubElement(row, "venCd").text = ven_cd or self.ven_cd

        xml_body = self._build_xml(
            [
                self._session_dataset("dsSession"),
                ds_cond,
            ]
        )
        root = await self._call("/pd/pdc/selectUnitStocks.do", xml_body)

        items = []
        for row_el in root.findall(".//Dataset[@id='dsList']//row"):
            items.append({child.tag: child.text for child in row_el})
        return items

    async def update_stock(
        self,
        slitm_cd: str,
        units: list[dict[str, Any]],
    ) -> bool:
        """속성별 재고 수정 (updateUnitStockByExcel).

        units 예시: [{"uitmCd": "00001", "addQty": 10, "maxSellPossQty": 999}]
        """
        ds_session = self._session_dataset("sessionVO")

        ds_list = ET.Element("Dataset", id="dsList")
        rows = ET.SubElement(ds_list, "rows")
        for u in units:
            row = ET.SubElement(rows, "row")
            ET.SubElement(row, "slitmCd").text = slitm_cd
            ET.SubElement(row, "uitmCd").text = str(u.get("uitmCd", ""))
            ET.SubElement(row, "addQty").text = str(u.get("addQty", 0))
            ET.SubElement(row, "maxSellPossQty").text = str(
                u.get("maxSellPossQty", 999)
            )
            ET.SubElement(row, "sellGbcd").text = str(u.get("sellGbcd", "00"))
            ET.SubElement(row, "stckGdYn").text = str(u.get("stckGdYn", "N"))

        xml_body = self._build_xml([ds_session, ds_list])
        await self._call("/pd/pdc/updateUnitStockByExcel.do", xml_body)
        return True

    # ─────────────────────────────────────────────
    # 전시상태 수정 (판매중지/재개)
    # ─────────────────────────────────────────────

    async def suspend_products(self, slitm_cds: list[str]) -> bool:
        """상품 전시 중지 요청 (insertItnDispModReqList).

        판매중지: 전시상태 수정으로 내림.
        """
        return await self._modify_disp(slitm_cds)

    async def _modify_disp(self, slitm_cds: list[str]) -> bool:
        """전시상태 수정 요청."""
        ds_session = self._session_dataset("sessionVO")

        ds_list = ET.Element("Dataset", id="dsSlitmListTran")
        rows = ET.SubElement(ds_list, "rows")
        for cd in slitm_cds:
            row = ET.SubElement(rows, "row")
            ET.SubElement(row, "slitmCd").text = cd

        xml_body = self._build_xml([ds_session, ds_list])
        await self._call("/pd/pdc/insertItnDispModReqList.do", xml_body)
        return True

    async def change_sell_status(
        self, slitm_cds: list[str], sell_gbcd: str = "11"
    ) -> bool:
        """판매구분 변경 (updateVenSellItemList).

        sell_gbcd: "11"=온라인판매, "10"=판매중지
        """
        ds_session = self._session_dataset("sessionVO")

        ds_list = ET.Element("Dataset", id="dsSlitmListTran")
        rows = ET.SubElement(ds_list, "rows")
        for cd in slitm_cds:
            row = ET.SubElement(rows, "row")
            ET.SubElement(row, "itemSellGbcd").text = sell_gbcd
            ET.SubElement(row, "slitmCd").text = cd

        xml_body = self._build_xml([ds_session, ds_list])
        await self._call("/pd/pdc/updateVenSellItemList.do", xml_body)
        return True

    # ─────────────────────────────────────────────
    # 가격 수정
    # ─────────────────────────────────────────────

    async def update_price(
        self,
        slitm_cd: str,
        sell_prc: int,
        apply_start_dt: str = "",
        apply_start_time: str = "0000",
    ) -> bool:
        """상품 가격 수정 요청 (updateItemPrcHist).

        sell_prc: 판매가 (정수)
        apply_start_dt: 적용 시작일 (YYYYMMDD), 빈값이면 당일
        """
        from datetime import datetime, timezone, timedelta

        if not apply_start_dt:
            kst = datetime.now(tz=timezone(timedelta(hours=9)))
            apply_start_dt = kst.strftime("%Y%m%d")

        ds_session = self._session_dataset("sessionVO")

        ds_price = ET.Element("Dataset", id="dsItemPrcHistTran")
        rows = ET.SubElement(ds_price, "rows")
        row = ET.SubElement(rows, "row")
        ET.SubElement(row, "slitmCd").text = slitm_cd
        ET.SubElement(row, "sellPrc").text = str(sell_prc)
        ET.SubElement(row, "prcAplyStrtDtm").text = apply_start_dt
        ET.SubElement(row, "prcAplyStrtTime").text = apply_start_time
        ET.SubElement(row, "prcAthzGbcd").text = "00"  # 가격권한구분코드

        xml_body = self._build_xml([ds_session, ds_price])
        await self._call("/pd/pdh/updateItemPrcHist.do", xml_body)
        return True

    # ─────────────────────────────────────────────
    # 출고(주문) 조회
    # ─────────────────────────────────────────────

    async def get_orders(
        self,
        from_date: str,
        to_date: str,
        prgr_gb: str = "P0",
        mda_gb: str = "20",
    ) -> list[dict[str, Any]]:
        """출고(주문) 조회 (selectOshpDtlList).

        prgr_gb: P0=출고대기, P1=주문확인, P2=출고완료, P3=배송완료
        mda_gb: 20=Hmall
        """
        ds_input = ET.Element("Dataset", id="dsInput")
        rows = ET.SubElement(ds_input, "rows")
        row = ET.SubElement(rows, "row")
        ET.SubElement(row, "venCd").text = self.ven_cd
        ET.SubElement(row, "fromDate").text = from_date
        ET.SubElement(row, "toDate").text = to_date
        ET.SubElement(row, "mdaGb").text = mda_gb
        ET.SubElement(row, "prgrGb").text = prgr_gb

        xml_body = self._build_xml([ds_input])
        root = await self._call("/sc/scb/scbd/selectOshpDtlList.do", xml_body)

        items = []
        for row_el in root.findall(".//Dataset[@id='dsOutput']//row"):
            items.append({child.tag: child.text for child in row_el})
        return items

    # ─────────────────────────────────────────────
    # 출고 처리 (송장 등록)
    # ─────────────────────────────────────────────

    async def confirm_shipment(
        self,
        deliveries: list[dict[str, Any]],
        proc_gb: str = "P2",
    ) -> bool:
        """출고 처리 (multiOshpProcess).

        proc_gb: P1=주문확인, P2=출고완료(송장등록), P3=배송완료
        deliveries 필드:
          - dlvstNo: 출고번호
          - dlvstPtcSeq: 출고명세순번
          - ordNo: 주문번호
          - ordPtcSeq: 주문명세순번
          - invcNo: 송장번호
          - dsrvDlvcoCd: 배송사코드
        """
        ds_input = ET.Element("Dataset", id="dsInput")
        rows = ET.SubElement(ds_input, "rows")
        for d in deliveries:
            row = ET.SubElement(rows, "row")
            ET.SubElement(row, "chk").text = "1"
            ET.SubElement(row, "venCd").text = self.ven_cd
            ET.SubElement(row, "ven2Cd").text = d.get("ven2Cd", "")
            ET.SubElement(row, "dlvstNo").text = d["dlvstNo"]
            ET.SubElement(row, "dlvstPtcSeq").text = str(d["dlvstPtcSeq"])
            ET.SubElement(row, "ordNo").text = d["ordNo"]
            ET.SubElement(row, "ordPtcSeq").text = str(d["ordPtcSeq"])
            ET.SubElement(row, "procGb").text = proc_gb
            ET.SubElement(row, "invcNo").text = d.get("invcNo", "")
            ET.SubElement(row, "dsrvDlvcoCd").text = d.get("dsrvDlvcoCd", "")
            ET.SubElement(row, "rgstId").text = self.user_id
            ET.SubElement(row, "rgstIp").text = self.user_ip

        xml_body = self._build_xml([ds_input])
        await self._call("/sc/scb/scbd/multiOshpProcess.do", xml_body)
        return True
