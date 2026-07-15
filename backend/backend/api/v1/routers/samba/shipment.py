"""SambaWave Shipment API router."""

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import defer
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.tenant.middleware import get_optional_tenant_id, require_admin

router = APIRouter(prefix="/shipments", tags=["samba-shipments"])


class ShipmentStartRequest(BaseModel):
    product_ids: list[str]
    update_items: list[str]  # ['price', 'stock', 'image', 'description']
    target_account_ids: list[str]
    skip_unchanged: bool = False  # 가격 변동 없으면 스킵


class MarketDeleteRequest(BaseModel):
    product_ids: list[str]
    target_account_ids: list[str]
    current_idx: int | None = None  # 전체 삭제 중 현재 인덱스 (로그 표시용)
    total_count: int | None = None  # 전체 삭제 대상 수 (로그 표시용)
    log_to_buffer: bool = False  # True: 상품전송삭제 페이지 링 버퍼에 기록


class MarketDeleteByAccountRequest(BaseModel):
    account_id: str
    dry_run: bool = False


def _get_service(session: AsyncSession):
    from backend.domain.samba.shipment.repository import SambaShipmentRepository
    from backend.domain.samba.shipment.service import SambaShipmentService

    return SambaShipmentService(SambaShipmentRepository(session), session)


class CancelRequest(BaseModel):
    job_id: Optional[str] = None


@router.post("/cancel")
async def cancel_transmit(body: CancelRequest = CancelRequest()):
    """진행 중인 전송 강제 중단. job_id가 주어지면 해당 잡만 취소."""
    from backend.domain.samba.shipment.service import request_cancel_transmit

    request_cancel_transmit(body.job_id)
    target = f"잡 {body.job_id}" if body.job_id else "전체"
    return {"ok": True, "message": f"전송 중단 요청 완료 ({target})"}


@router.post("/emergency-stop")
async def emergency_stop(
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """작업중지 — 전송 백그라운드 작업 즉시 중단 + pending/running Job 전부 취소 (오토튠 제외)."""
    from backend.domain.samba.emergency import trigger_emergency_stop
    from backend.domain.samba.shipment.service import request_cancel_transmit
    from sqlalchemy import text

    # 1. 비상정지 플래그 ON
    trigger_emergency_stop()
    # 2. 전송 취소 플래그
    request_cancel_transmit()
    # 3. pending/running Job 전부 취소
    r = await session.execute(
        text(
            "UPDATE samba_jobs SET status = 'cancelled', completed_at = now() WHERE status IN ('pending', 'running')"
        )
    )
    cancelled_count = r.rowcount
    await session.commit()

    # 플래그 해제하지 않음 — 워커가 감지 후 직접 해제
    return {
        "ok": True,
        "cancelled_jobs": cancelled_count,
        "message": "비상정지 완료",
    }


@router.post("/emergency-clear")
async def emergency_clear(admin: str = Depends(require_admin)):
    """비상정지 해제 — 전송/오토튠 재개 가능."""
    from backend.domain.samba.emergency import clear_emergency_stop
    from backend.domain.samba.shipment.service import clear_cancel_transmit

    clear_emergency_stop()
    clear_cancel_transmit()
    return {"ok": True, "message": "비상정지 해제"}


@router.post("/ssg/cleanup-orphans")
async def cleanup_ssg_orphans(
    account_id: str = Query(..., description="정리할 SSG 계정 id"),
    dry_run: bool = Query(
        True,
        description="true면 유령 개수/샘플만, false면 실제 판매종료(sellStatCd=90)",
    ),
    max_delete: int = Query(
        200, ge=0, le=100000, description="한 번에 종료할 최대 유령 수"
    ),
    debug: bool = Query(
        False,
        description="true면 SSG getItemList 파라미터 조합별 첫 페이지 raw 구조/건수 진단 반환(삭제 안 함)",
    ),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """SSG 역방향 유령 정리 — 삼바엔 없는데 SSG엔 판매중인 상품을 판매종료.

    SSG 판매중(sellStatCd!=90) 전량 나열 → 각 splVenItemId(= 삼바 수집상품 id)가
    삼바 DB에 상품으로 존재하지 않으면 유령 → dry_run=false 시 delete_product 로
    영구판매중지(sellStatCd=90). 삼바에 상품이 존재하면 절대 유령 판정하지 않아
    오삭제 위험이 낮다(멱등이라 이미 90이어도 안전).

    반드시 account_id 로 특정 계정만 좁혀 실행. 최초 dry_run=true 로
    ghost_count/ghost_sample 을 확인한 뒤 dry_run=false 로 종료한다. 유령이 많으면
    HTTP 524(타임아웃)나도 서버는 끝까지 처리하며 max_delete 배치로 반복 호출한다.

    ⚠ splVenItemId 가 삼바 상품 id 형식과 다르면 전량이 유령으로 잡힐 수 있으니,
    최초 dry_run 응답의 ghost_sample(splVenItemId 형식)·db_existing 수치를 반드시
    검증한 뒤 dry_run=false 로 넘어갈 것.
    """
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.proxy.ssg_ghost_reconciler import (
        _reconcile_one_account,
    )

    acc = (
        await session.exec(
            select(SambaMarketAccount).where(
                SambaMarketAccount.id == account_id,
                SambaMarketAccount.is_active == True,  # noqa: E712
            )
        )
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="활성 계정을 찾을 수 없습니다")
    if acc.market_type != "ssg":
        raise HTTPException(
            status_code=400, detail=f"SSG 계정이 아닙니다: {acc.market_type}"
        )

    acc_dict = {
        "id": acc.id,
        "account_label": acc.account_label,
        "api_key": acc.api_key,
        "additional_fields": acc.additional_fields or {},
    }
    # SSG 전량 나열(수십 초) 동안 이 세션이 idle-in-transaction 으로 커넥션을
    # 물지 않도록 먼저 종료 — reconciler 는 내부에서 자체 세션으로 DB 대조.
    await session.commit()

    if debug:
        # getItemList 가 1건만 반환하는 원인 격리 — 파라미터 조합별 첫 페이지 구조/건수.
        from backend.domain.samba.proxy.ssg import SSGClient
        from backend.domain.samba.proxy.ssg_ghost_reconciler import (
            _extract_api_key,
            _extract_site_no,
        )

        _site = _extract_site_no(acc_dict)
        _client = SSGClient(_extract_api_key(acc_dict), site_no=_site)
        _combos = [
            ("siteNo+ps100", {"page": "1", "pageSize": "100", "siteNo": _site}),
            ("no_siteNo+ps100", {"page": "1", "pageSize": "100"}),
            ("siteNo+ps10", {"page": "1", "pageSize": "10", "siteNo": _site}),
            ("siteNo+pageSize1000", {"page": "1", "pageSize": "1000", "siteNo": _site}),
        ]
        _out: dict[str, Any] = {"site_no": _site, "combos": {}}
        for _label, _params in _combos:
            try:
                _resp = await _client._call_api(
                    "GET", "/item/0.1/getItemList.ssg", params=_params
                )
                _result = _resp.get("result", _resp) if isinstance(_resp, dict) else {}
                _items_raw = (
                    _result.get("items") if isinstance(_result, dict) else None
                )
                _iv = (
                    _items_raw.get("item")
                    if isinstance(_items_raw, dict)
                    else _items_raw
                )
                _cnt = (
                    len(_iv)
                    if isinstance(_iv, list)
                    else (1 if isinstance(_iv, dict) else 0)
                )
                _sample = (
                    (_iv[0] if isinstance(_iv, list) and _iv else _iv) if _cnt else None
                )
                _out["combos"][_label] = {
                    "result_keys": list(_result.keys())
                    if isinstance(_result, dict)
                    else str(type(_result)),
                    "items_raw_type": type(_items_raw).__name__,
                    "item_type": type(_iv).__name__,
                    "count_first_page": _cnt,
                    "total_field": (
                        _result.get("totalCnt")
                        or _result.get("totalCount")
                        or _result.get("total")
                    )
                    if isinstance(_result, dict)
                    else None,
                    "sample_keys": list(_sample.keys())
                    if isinstance(_sample, dict)
                    else None,
                }
            except Exception as _e:
                _out["combos"][_label] = {"error": str(_e)[:300]}
        return _out

    return await _reconcile_one_account(
        acc_dict, dry_run=dry_run, max_delete=max_delete
    )


@router.post("/playauto/backfill-mastercode")
async def backfill_playauto_mastercode(
    account_id: str = Query(..., description="backfill할 플레이오토 계정 id"),
    dry_run: bool = Query(
        True, description="true면 분류만, false면 실제 MasterCode 저장"
    ),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """플레이오토 MasterCode backfill — 등록됐는데 market_product_nos가 null인 상품 번호 복구.

    등록 성공응답에서 MasterCode를 msg에서만 뽑는 취약파싱 + 프록시 재시도 유실로,
    registered인데 EMP 번호 미저장(null)이 된 상품이 있다. 그 결과 주문 매칭 실패
    (이미지/원문링크 안 뜸)·삭제·오토튠 품절이 막힌다.

    EMP 상품 전체(get_products)를 받아 품번(site_product_id)/상품명으로 MasterCode를
    매칭해 market_product_nos[account]에 채운다.
    - backfilled: 번호 채운 수 (→ 주문매칭·삭제·오토튠 정상화)
    - missing_in_emp: EMP에도 없음 = 등록 실패/삭제(별도 처리)
    ⚠ 재전송 금지(mpn null→__AUTO__ 신규등록→EMP 중복생성). 최초 dry_run=true 로 확인.
    """
    import json as _json

    from sqlalchemy import text as _text
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.proxy.playauto import PlayAutoClient

    acc = (
        await session.exec(
            select(SambaMarketAccount).where(
                SambaMarketAccount.id == account_id,
                SambaMarketAccount.is_active == True,  # noqa: E712
            )
        )
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="활성 계정을 찾을 수 없습니다")
    if acc.market_type != "playauto":
        raise HTTPException(
            status_code=400, detail=f"플레이오토 계정이 아닙니다: {acc.market_type}"
        )
    extras = acc.additional_fields or {}
    api_key = extras.get("apiKey", "") or acc.api_key or ""
    if not api_key:
        raise HTTPException(status_code=400, detail="플레이오토 apiKey 없음")

    def _first(d: dict, keys: list[str]) -> str:
        for k in keys:
            v = d.get(k) if isinstance(d, dict) else None
            if v is not None and str(v).strip():
                return str(v).strip()
        return ""

    _MK = ["MasterCode", "masterCode", "master_code", "Code", "code"]
    _MODK = ["Model", "model", "ModelName", "modelName"]
    _NMK = ["ProdName", "prodName", "prod_name", "Name", "name"]

    client = PlayAutoClient(api_key)
    # EMP 전량 조회(수십 초) 동안 세션이 idle-in-tx 로 커넥션 물지 않도록 먼저 종료
    await session.commit()
    try:
        emp = await client.get_products("")
    finally:
        await client.close()

    by_model: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for e in emp or []:
        if not isinstance(e, dict):
            continue
        mc = _first(e, _MK)
        if not mc:
            continue
        md = _first(e, _MODK)
        nm = _first(e, _NMK)
        if md:
            by_model.setdefault(md, mc)
        if nm:
            by_name.setdefault(nm, mc)

    rows = (
        await session.execute(
            _text(
                "SELECT id, market_product_nos, name, site_product_id, style_code "
                "FROM samba_collected_product "
                "WHERE registered_accounts @> CAST(:arr AS jsonb)"
            ).bindparams(arr=f'["{account_id}"]')
        )
    ).all()

    backfilled: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    already = 0
    for rid, mpn_raw, name, spid, scode in rows:
        mpn = dict(mpn_raw or {})
        if str(mpn.get(account_id) or "").strip():
            already += 1
            continue
        mc = ""
        for key in (spid, scode):
            if key and str(key).strip() in by_model:
                mc = by_model[str(key).strip()]
                break
        if not mc and name and name in by_name:
            mc = by_name[name]
        if mc:
            backfilled.append(
                {"id": rid, "master": mc, "name": (name or "")[:30], "spid": spid}
            )
            if not dry_run:
                mpn[account_id] = mc
                await session.execute(
                    _text(
                        "UPDATE samba_collected_product "
                        "SET market_product_nos = CAST(:nos AS jsonb) WHERE id = :id"
                    ).bindparams(
                        nos=_json.dumps(mpn, ensure_ascii=False), id=rid
                    )
                )
        else:
            missing.append({"id": rid, "name": (name or "")[:30], "spid": spid})
    if not dry_run:
        await session.commit()

    return {
        "account_id": account_id,
        "emp_products": len(emp or []),
        "by_model_map": len(by_model),
        "by_name_map": len(by_name),
        "db_registered": len(rows),
        "already_has_number": already,
        "backfilled": len(backfilled),
        "missing_in_emp": len(missing),
        "dry_run": dry_run,
        "backfill_sample": backfilled[:15],
        "missing_sample": missing[:15],
    }


@router.post("/esm/cleanup-orphans")
async def cleanup_esm_orphans(
    account_id: str = Query(..., description="정리할 ESM(옥션/G마켓) 계정 id"),
    dry_run: bool = Query(
        True, description="true면 개수/목록만, false면 실제 판매중지+삭제"
    ),
    wipe_all: bool = Query(
        False,
        description="true면 삼바 추적분까지 포함해 계정 전체 삭제(초기화) + 삼바 추적 제거",
    ),
    max_delete: int = Query(
        100, ge=0, le=100000, description="한 번에 삭제할 최대 개수"
    ),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """ESM(옥션/G마켓) 유령/중복 상품 정리 — 계정 스코프 한정.

    기본(wipe_all=false): DB `market_product_nos`가 추적 안 하는 goodsNo(=유령/중복
    등록분)만 삭제. 전송 타임아웃(ESM 등록됐으나 삼바 실패처리→번호 미저장)+재전송/
    오토튠 반복으로 쌓인 중복을 정리한다. 삼바 추적 정상분은 보존.

    전체삭제(wipe_all=true): 삼바 추적분 포함 계정의 ESM 등록 전체를 삭제하고,
    삼바 쪽 추적(market_product_nos/registered_accounts)에서도 이 계정을 제거한다.
    "계정 초기화 후 fresh 재전송" 용도. ⚠ 되돌릴 수 없다.

    반드시 account_id 로 특정 계정만 좁혀 실행한다(다른 계정 오삭제 방지).
    최초 dry_run=true 로 개수 확인 후 dry_run=false 로 삭제.
    삭제는 판매중지 → delete 2단계(ESM은 판매중 직접 삭제 불가).
    삭제량이 많으면 HTTP는 524(타임아웃)나도 서버는 끝까지 처리하며, max_delete
    배치로 나눠 반복 호출한다.

    ⚠ 이 계정에 삼바 외 경로(수동/타툴)로 올린 정상 등록이 있으면 그것도
    삭제되므로, 계정이 삼바 전용일 때만 사용한다.
    """
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.proxy.esmplus_ghost_reconciler import (
        _build_esm_client,
        _fetch_db_tracked_nos,
        _scan_market_goods,
        _stop_and_delete,
    )

    acc = (
        await session.exec(
            select(SambaMarketAccount).where(
                SambaMarketAccount.id == account_id,
                SambaMarketAccount.is_active == True,  # noqa: E712
            )
        )
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="활성 계정을 찾을 수 없습니다")
    if acc.market_type not in ("auction", "gmarket"):
        raise HTTPException(
            status_code=400,
            detail=f"ESM(옥션/G마켓) 계정이 아닙니다: {acc.market_type}",
        )

    acc_dict = {
        "id": acc.id,
        "account_label": acc.account_label,
        "seller_id": acc.seller_id,
        "additional_fields": acc.additional_fields or {},
        "market_type": acc.market_type,
    }
    # DB 추적 번호 먼저 조회 후 트랜잭션 종료 — 이후 ESM 전수 페이징(수십 초)이
    # idle-in-transaction 으로 커넥션을 물지 않도록.
    tracked = await _fetch_db_tracked_nos(account_id)
    await session.commit()

    client = await _build_esm_client(acc_dict)
    if not client:
        raise HTTPException(
            status_code=400, detail="ESM 자격증명/셀러ID 없음 — 계정 설정 확인"
        )

    market_goods = await _scan_market_goods(client)
    orphans = sorted(market_goods - tracked)
    targets = sorted(market_goods) if wipe_all else orphans

    label = f"{acc.market_type}/{acc.seller_id}"
    mode = "전체삭제(wipe)" if wipe_all else "유령정리"
    result: dict[str, Any] = {
        "account_id": account_id,
        "account_label": label,
        "mode": mode,
        "market_total": len(market_goods),
        "db_tracked": len(tracked),
        "orphans": len(orphans),
        "delete_target": len(targets),
        "dry_run": dry_run,
        "target_sample": targets[:20],
    }
    if dry_run or not targets:
        result["message"] = (
            f"[{label}] {mode} — ESM {len(market_goods)}개, 삼바추적 {len(tracked)}개, "
            f"삭제대상 {len(targets)}개 (dry_run — 삭제 안 함)"
        )
        return result

    deleted: list[str] = []
    failed: list[str] = []
    for gno in targets[:max_delete]:
        r = await _stop_and_delete(client, gno)
        if r == "deleted":
            deleted.append(gno)
        else:
            failed.append(f"{gno}:{r}")

    # 전체삭제 모드 + 이번 호출로 남은 대상을 모두 처리(배치 마지막)했으면,
    # 삼바 추적(market_product_nos/registered_accounts)에서도 이 계정 제거 →
    # 재전송 시 fresh CREATE 되도록 초기화.
    reset_rows = 0
    if wipe_all and len(targets) <= max_delete:
        from sqlalchemy import text as _t

        _rr = await session.execute(
            _t(
                "UPDATE samba_collected_product "
                "SET market_product_nos = market_product_nos - :acct, "
                "    registered_accounts = "
                "        COALESCE(registered_accounts, '[]'::jsonb) - :acct "
                "WHERE market_product_nos ? :acct"
            ),
            {"acct": account_id},
        )
        reset_rows = _rr.rowcount or 0
        await session.commit()

    result["deleted"] = len(deleted)
    result["delete_failed"] = len(failed)
    result["failed_sample"] = failed[:10]
    result["samba_tracking_reset_rows"] = reset_rows
    result["message"] = (
        f"[{label}] {mode} — 대상 {len(targets)}개 중 {len(deleted)}개 삭제완료, "
        f"실패 {len(failed)}개, 삼바추적 정리 {reset_rows}행 (최대 {max_delete}개 처리)"
    )
    logger.info(f"[esm_cleanup] {result['message']}")
    return result


class CleanupOrphansRequest(BaseModel):
    # 화면 필터로 좁혀진 product_id 목록 — 비어있으면 tenant 전체 (호환)
    product_ids: Optional[list[str]] = None


@router.post("/smartstore/cleanup-orphans")
async def cleanup_smartstore_orphans(
    body: CleanupOrphansRequest = CleanupOrphansRequest(),
    dry_run: bool = Query(True, description="true면 목록만, false면 실제 삭제"),
    account_id: Optional[str] = Query(None, description="특정 계정만 정리"),
    max_delete: int = Query(
        50, ge=0, le=100000, description="한 번에 삭제할 최대 개수"
    ),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """스마트스토어 고아 상품 정리.

    DB `market_product_nos`에 없는 Naver 등록 상품을 탐지/삭제.
    최초 호출 시 dry_run=true로 목록 확인 후 dry_run=false로 실제 삭제.
    `body.product_ids`가 주어지면 화면 필터 결과만 분석 대상으로 한정한다.
    """
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.smartstore import SmartStoreClient

    # 1. 스마트스토어 계정 조회
    q = select(SambaMarketAccount).where(
        SambaMarketAccount.market_type == "smartstore",
        SambaMarketAccount.is_active == True,  # noqa: E712
    )
    if account_id:
        q = q.where(SambaMarketAccount.id == account_id)
    result = await session.exec(q)
    accounts = result.all()
    if not accounts:
        raise HTTPException(status_code=404, detail="활성 스마트스토어 계정 없음")

    # 2. DB 상품 로드 — 화면 필터 product_ids 우선, 없으면 tenant_id 범위
    from sqlalchemy import or_

    tenant_ids = list({a.tenant_id for a in accounts if a.tenant_id})
    # 무거운 컬럼 defer — 전체 카탈로그 스캔 시 TOAST 로드로 인한 풀 고갈 방지
    # (이 함수는 market_product_nos/style_code/name/registered_accounts 만 사용)
    prod_query = select(SambaCollectedProduct).options(
        defer(SambaCollectedProduct.detail_html),
        defer(SambaCollectedProduct.detail_images),
        defer(SambaCollectedProduct.images),
        defer(SambaCollectedProduct.extra_data),
    )
    # 고아(Naver 삭제) 판정 기준은 **항상 전체 카탈로그**여야 한다.
    # 화면 필터(product_ids)로 좁힌 부분집합과 비교하면 필터 밖의 정상
    # 등록상품이 "DB에 없음"으로 오판돼 Naver에서 실삭제되는 사고가 난다.
    # → 전체를 한 번 로드하고, 필터는 역고아/재연결(DB 정리) 범위에만 적용.
    if tenant_ids:
        # 멀티테넌시 도입 전 NULL 포함
        prod_query = prod_query.where(
            or_(
                SambaCollectedProduct.tenant_id.in_(tenant_ids),
                SambaCollectedProduct.tenant_id.is_(None),
            )
        )
    prod_result = await session.exec(prod_query)
    all_db_products = prod_result.all()
    # 화면 필터 — 역고아/재연결 후보를 이 집합으로 한정 (고아 판정엔 미적용)
    filter_ids: set[str] = {str(i) for i in (body.product_ids or [])}

    # 초기 조회 트랜잭션 즉시 종료 — 이후 네이버 전수 페이징(수십 초~수 분,
    # 429 백오프 포함)이 idle-in-transaction 상태로 트랜잭션을 물고 있으면
    # IIT 타임아웃(write 300s, orm.py)/kill_idle_tx(150s)가 연결을 끊어
    # "Database error" 500으로 전체 실패한다. 커밋으로 tx를 닫으면 연결은
    # 'idle'(안전)이 되고, 이후 relink/stale 정리는 각자 짧은 tx로 처리된다.
    # (expire_on_commit=False라 로드된 ORM 객체 속성은 계속 사용 가능)
    await session.commit()

    # 삼바가 등록한 상품 식별용 style_code 집합
    all_style_codes: set[str] = {
        str(p.style_code) for p in all_db_products if p.style_code
    }

    # 3. 각 계정별 Naver 조회 + 고아 판별
    per_account = []
    total_naver = 0
    total_orphans = 0
    total_stale_db = 0
    total_deleted = 0

    for account in accounts:
        add_info = account.additional_fields or {}
        client_id = add_info.get("clientId") or account.api_key or ""
        client_secret = add_info.get("clientSecret") or account.api_secret or ""
        if not client_id or not client_secret:
            per_account.append({"account_id": account.id, "error": "API 키 없음"})
            continue

        # 이 계정에 매핑된 product_no 수집 + DB product → originProductNo 역매핑
        account_db_nos: set[str] = set()
        # DB 상품 id → 매핑된 originProductNo (stale 판정용)
        db_origin_map: dict[str, dict] = {}
        for p in all_db_products:
            nos = p.market_product_nos or {}
            origin_no_for_p: str = ""
            for k in (account.id, f"{account.id}_origin"):
                v = nos.get(k)
                if isinstance(v, str) and v:
                    account_db_nos.add(v)
                    if not origin_no_for_p:
                        origin_no_for_p = v
                elif isinstance(v, dict):
                    for kk in (
                        "originProductNo",
                        "productNo",
                        "smartstoreChannelProductNo",
                    ):
                        vv = v.get(kk)
                        if vv:
                            account_db_nos.add(str(vv))
                            if not origin_no_for_p and kk == "originProductNo":
                                origin_no_for_p = str(vv)
            # 역고아/재연결 후보는 화면 필터 범위로만 한정
            # (account_db_nos는 전체 카탈로그 기준 — 고아/충돌 판정용)
            if origin_no_for_p and (not filter_ids or str(p.id) in filter_ids):
                db_origin_map[origin_no_for_p] = {
                    "db_id": str(p.id),
                    "site_product_id": str(getattr(p, "site_product_id", "") or ""),
                    "style_code": str(p.style_code or ""),
                    "mapped_origin_no": origin_no_for_p,
                    "product_name": (p.name or "")[:80],
                }

        client = SmartStoreClient(client_id, client_secret)

        # 페이징 수집 — 1페이지로 totalPages 파악 후 나머지 페이지 동시 조회
        # (순차 호출 시 8천개 기준 100s+ 소요 → Caddy 120s 타임아웃으로 502 발생)
        naver_products: list[dict] = []

        def _extract_contents(resp: object) -> list[dict]:
            if isinstance(resp, list):
                return resp
            if isinstance(resp, dict):
                v = resp.get("contents") or resp.get("data") or []
                return v if isinstance(v, list) else []
            return []

        r1 = await client._call_api(
            "POST",
            "/v1/products/search",
            body={"page": 1, "size": 100},
        )
        page1_contents = _extract_contents(r1)
        naver_products.extend(page1_contents)

        # 전체 페이지 수 확인 — totalPages 우선, 없으면 totalElements 기반 산출
        total_pages = 0
        if isinstance(r1, dict):
            tp = r1.get("totalPages")
            if isinstance(tp, int) and tp > 0:
                total_pages = tp
            else:
                te = r1.get("totalElements")
                if isinstance(te, int) and te > 0:
                    total_pages = (te + 99) // 100
        if total_pages <= 0:
            # 메타 정보 없으면 페이지가 가득 찼는지로 추정 (단일 페이지로 종료)
            total_pages = 1 if len(page1_contents) < 100 else 200
        total_pages = min(total_pages, 200)  # 20,000개 상한 유지

        # Naver Commerce API /products/search는 RPS 한도가 매우 낮아
        # sem=2도 36/99 페이지 실패 사고. 동시성 1(순차)로 낮추고 호출 사이
        # 강제 0.4s 간격(=최대 2.5 RPS) + 5회 재시도(2/4/8/16/32s 백오프).
        # 99페이지 × ~0.5s = ~50s, 200페이지 상한이어도 ~100s로 Caddy 120s 안전권.
        failed_pages: list[int] = []
        if total_pages > 1:
            sem = asyncio.Semaphore(1)

            async def _fetch_page(pno: int) -> tuple[int, list[dict], bool]:
                """returns (page_no, contents, success)."""
                last_err: Exception | None = None
                for attempt in range(5):
                    try:
                        async with sem:
                            rr = await client._call_api(
                                "POST",
                                "/v1/products/search",
                                body={"page": pno, "size": 100},
                            )
                            # 다음 호출까지 최소 간격 보장 (sem 보유 상태에서 sleep)
                            await asyncio.sleep(0.4)
                        return pno, _extract_contents(rr), True
                    except Exception as e:
                        last_err = e
                        err_msg = str(e)
                        # 429일 때만 길게 백오프, 그 외엔 짧게
                        if "429" in err_msg or "Too Many" in err_msg:
                            await asyncio.sleep(2 * (2**attempt))  # 2/4/8/16/32s
                        else:
                            await asyncio.sleep(0.5 * (2**attempt))  # 0.5/1/2/4/8s
                logger.warning(f"[고아정리] page {pno} 5회 재시도 실패: {last_err}")
                return pno, [], False

            results = await asyncio.gather(
                *[_fetch_page(p) for p in range(2, total_pages + 1)],
                return_exceptions=True,
            )
            for rr in results:
                if isinstance(rr, BaseException):
                    continue
                pno, contents, ok = rr
                if ok:
                    naver_products.extend(contents)
                else:
                    failed_pages.append(pno)

        total_naver += len(naver_products)

        # Naver 상품의 originProductNo / channelProductNo 전체 집합 (stale 역방향 판정용)
        # + sellerManagementCode → 살아있는 상품번호 맵 (역고아 재연결용)
        account_naver_nos: set[str] = set()
        account_naver_mgmt_map: dict[str, dict[str, str]] = {}
        for np in naver_products:
            on = str(
                np.get("originProductNo")
                or np.get("originProduct", {}).get("id", "")
                or ""
            )
            if on:
                account_naver_nos.add(on)
            first_cn = ""
            for cp in np.get("channelProducts", []):
                cn = cp.get("channelProductNo")
                if cn:
                    account_naver_nos.add(str(cn))
                    if not first_cn:
                        first_cn = str(cn)
            mgmt = str(np.get("sellerManagementCode") or "")
            if mgmt and on:
                account_naver_mgmt_map[mgmt] = {
                    "origin_no": on,
                    "channel_no": first_cn,
                }

        orphans = []
        for np in naver_products:
            origin_no = str(np.get("originProductNo") or "")
            if not origin_no:
                continue

            channel_products = np.get("channelProducts", [])
            channel_nos = [
                str(cp.get("channelProductNo", ""))
                for cp in channel_products
                if cp.get("channelProductNo")
            ]
            # originProductNo / channelProductNo 직접 비교
            in_db = (origin_no in account_db_nos) or any(
                cn in account_db_nos for cn in channel_nos
            )
            # 구 등록 상품은 account_db_nos에 origin_no 미포함 → sellerManagementCode(=style_code)로 추가 확인
            if not in_db:
                mgmt_code = str(np.get("sellerManagementCode") or "")
                if mgmt_code and mgmt_code in all_style_codes:
                    in_db = True
            if not in_db:
                name = next(
                    (cp.get("name", "") for cp in channel_products if cp.get("name")),
                    "",
                )
                orphans.append({"origin_no": origin_no, "name": name[:80]})

        total_orphans += len(orphans)

        # DB→Naver 역고아/재연결 판정 (순수 로직 — ghost_utils 참조):
        # - 페이지 누락 시 판정 전체 보류 (못 본 페이지 상품을 역고아로 오판 → 정상 매핑 해제 방지)
        # - originNo는 죽었지만 같은 품번(sellerManagementCode) 상품이 살아있으면
        #   스킵(방치)이 아니라 재연결 대상으로 분류 → 새 originNo/channelNo로 매핑 갱신
        from backend.domain.samba.shipment.ghost_utils import judge_smartstore_stale

        stale_skipped = bool(failed_pages)
        stale_db, relinks, relink_ambiguous = judge_smartstore_stale(
            db_origin_map,
            account_naver_nos,
            account_naver_mgmt_map,
            pages_incomplete=stale_skipped,
            # 전체 카탈로그 기준 매핑번호 집합 — 재연결 대상이 이미 다른 상품의
            # 매핑(주인 있음)이면 재연결 대신 역고아 처리 (#534 이중매핑 방지)
            claimed_nos=account_db_nos,
        )
        if stale_skipped:
            logger.warning(
                f"[고아정리] {account.id}: 페이지 누락 {len(failed_pages)}건 — "
                f"역고아/재연결 판정 보류 (오판 방지)"
            )
        total_stale_db += len(stale_db)

        deleted_here: list[str] = []
        failed: list[dict] = []
        if not dry_run and orphans:
            # max_delete 한도 적용 + Naver 429 레이트리밋 대응
            # (직전 search 페이징 직후 delete 폭주 시 429 다발 → 33/50 실패 사례)
            remaining = max_delete - total_deleted
            if remaining > 0:
                for o in orphans[:remaining]:
                    last_err: str | None = None
                    for attempt in range(4):  # 최초 1회 + 재시도 3회
                        try:
                            await client.delete_product(o["origin_no"])
                            deleted_here.append(o["origin_no"])
                            last_err = None
                            break
                        except Exception as e:
                            err_msg = str(e)
                            last_err = err_msg
                            if "429" in err_msg and attempt < 3:
                                # 1s, 2s, 4s 지수 백오프 (총 7초까지)
                                await asyncio.sleep(2**attempt)
                                continue
                            break
                    if last_err is not None:
                        failed.append({"origin_no": o["origin_no"], "error": last_err})
                    # 다음 삭제 호출 사이 0.3초 간격 → RPS ≈ 3 (Naver 안전권)
                    await asyncio.sleep(0.3)
                total_deleted += len(deleted_here)

        # 재연결(relink) — 같은 품번이 Naver에 살아있는 매핑은 새 상품번호로 갱신
        # (Naver 호출 없음, DB 매핑만 수정. 등록표시는 유지된다.)
        relinked: list[str] = []
        if not dry_run and relinks:
            from sqlalchemy.orm.attributes import flag_modified as _fm_relink

            relink_by_db_id = {r["db_id"]: r for r in relinks if r.get("db_id")}
            if relink_by_db_id:
                relink_q = select(SambaCollectedProduct).where(
                    SambaCollectedProduct.id.in_(list(relink_by_db_id))
                )
                relink_result = await session.exec(relink_q)
                for prod in relink_result.all():
                    r = relink_by_db_id[str(prod.id)]
                    nos = dict(prod.market_product_nos or {})
                    nos[f"{account.id}_origin"] = r["new_origin_no"]
                    # bare 키는 채널번호 우선 (등록 저장 포맷과 동일 — service.py 참조)
                    nos[account.id] = r["new_channel_no"] or r["new_origin_no"]
                    prod.market_product_nos = nos
                    _fm_relink(prod, "market_product_nos")
                    session.add(prod)
                    relinked.append(str(prod.id))
                if relinked:
                    await session.commit()
                    logger.info(
                        f"[고아정리] {account.id}: 역고아 재연결 {len(relinked)}건 "
                        f"(originNo 갱신)"
                    )

        # 역고아(stale_db) 정리 — Naver 호출 없이 DB의 해당 계정 매핑만 제거
        # market_product_nos[account.id] / market_product_nos[f"{account.id}_origin"] 삭제 +
        # registered_accounts 배열에서 account.id 제거
        stale_cleared: list[str] = []
        if not dry_run and stale_db:
            from sqlalchemy.orm.attributes import flag_modified

            db_ids_to_clear = [s["db_id"] for s in stale_db if s.get("db_id")]
            if db_ids_to_clear:
                clear_q = select(SambaCollectedProduct).where(
                    SambaCollectedProduct.id.in_(db_ids_to_clear)
                )
                clear_result = await session.exec(clear_q)
                for prod in clear_result.all():
                    nos = dict(prod.market_product_nos or {})
                    changed = False
                    for k in (account.id, f"{account.id}_origin"):
                        if k in nos:
                            nos.pop(k, None)
                            changed = True
                    if changed:
                        prod.market_product_nos = nos
                        flag_modified(prod, "market_product_nos")
                    regs = list(prod.registered_accounts or [])
                    if account.id in regs:
                        regs = [a for a in regs if a != account.id]
                        prod.registered_accounts = regs
                        flag_modified(prod, "registered_accounts")
                        changed = True
                    if changed:
                        session.add(prod)
                        stale_cleared.append(str(prod.id))
                if stale_cleared:
                    await session.commit()
                    logger.info(
                        f"[고아정리] {account.id}: 역고아 DB 매핑 정리 {len(stale_cleared)}건"
                    )

        per_account.append(
            {
                "account_id": account.id,
                "naver_count": len(naver_products),
                "orphan_count": len(orphans),
                "orphans": orphans,
                "stale_db_count": len(stale_db),
                "stale_db": stale_db[:50],
                "stale_cleared": stale_cleared,
                "stale_skipped": stale_skipped,
                "relink_count": len(relinks),
                "relinks": relinks[:50],
                "relinked": relinked,
                "relink_ambiguous_count": len(relink_ambiguous),
                "relink_ambiguous": relink_ambiguous[:50],
                "deleted": deleted_here,
                "failed": failed,
                "failed_pages": failed_pages,
                "total_pages": total_pages,
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "db_no_count": len(all_db_products),
        "style_code_count": len(all_style_codes),
        "total_stale_db": total_stale_db,
        "total_stale_cleared": sum(
            len(a.get("stale_cleared") or []) for a in per_account
        ),
        "total_relinks": sum(a.get("relink_count") or 0 for a in per_account),
        "total_relinked": sum(len(a.get("relinked") or []) for a in per_account),
        "total_naver": total_naver,
        "total_orphans": total_orphans,
        "total_deleted": total_deleted,
        "max_delete": max_delete,
        "accounts": per_account,
    }


@router.get("/ghost-summary")
async def ghost_summary(
    hours: int = Query(48, ge=1, le=720, description="최근 N시간 내 이벤트 집계"),
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """최근 N시간 내 유령 감지 이벤트 요약.

    상품관리 페이지 상단 배너용. 마켓별 최신 이벤트 1건씩 + 총 건수 합산.
    """
    from sqlalchemy import text as sa_text

    sql = sa_text(
        """
        SELECT event_type, market_type, severity, summary, detail, created_at
        FROM samba_monitor_event
        WHERE event_type IN (
            'lotteon_ghost_detected',
            'elevenst_missing_prdno_detected',
            'smartstore_ghost_detected',
            'coupang_ghost_detected',
            'lottehome_ghost_detected'
        )
          AND created_at >= NOW() - (:h || ' hours')::interval
        ORDER BY created_at DESC
        """
    )
    rows = (await session.execute(sql, {"h": str(hours)})).mappings().all()

    def _extract_count(detail: Any) -> int:
        # JSONB는 dict로 들어옴
        if isinstance(detail, dict):
            for k in ("total_missing", "ghosts", "total"):
                v = detail.get(k)
                if isinstance(v, (int, float)):
                    return int(v)
        return 0

    # reconciler가 사이클·배포마다 같은 유령을 monitor_event에 반복 기록하므로,
    # 계정(account_id) 단위 '최신 1건'만 합산해야 함. rows가 created_at DESC라
    # 같은 (market, account_id)의 첫 등장 = 최신 → 그 1건만 count, 이후 중복은 스킵.
    # (이 dedup 누락이 배너 11,190 = 실제 795 × 사이클수 과대집계 버그의 원인)
    by_market: dict[str, dict] = {}
    seen_accounts: dict[str, set[str]] = {}
    for r in rows:
        m = r.get("market_type") or "unknown"
        detail = r.get("detail") or {}
        if not isinstance(detail, dict):
            detail = {}
        # account_id 없으면 이벤트 고유 키로 취급(병합 안 함 — 과소집계 방지)
        acct_key = str(detail.get("account_id") or f"_row_{r.get('created_at')}")
        if m not in by_market:
            # 마켓 최초 등장 = 최신 이벤트 → 배너 표시 필드(요약/심각도/시각)로 사용
            by_market[m] = {
                "market": m,
                "event_type": r.get("event_type"),
                "severity": r.get("severity"),
                "summary": r.get("summary"),
                "count": 0,
                "created_at": r.get("created_at").isoformat()
                if r.get("created_at")
                else None,
            }
            seen_accounts[m] = set()
        if acct_key in seen_accounts[m]:
            continue  # 같은 계정의 오래된 중복 이벤트 — 합산 제외
        seen_accounts[m].add(acct_key)
        by_market[m]["count"] += _extract_count(detail)

    markets = list(by_market.values())
    total = sum(m.get("count", 0) for m in markets)
    return {
        "ok": True,
        "hours": hours,
        "total_count": total,
        "markets": markets,
    }


class ElevenstCleanupRequest(BaseModel):
    # 화면 필터로 좁혀진 product_id 목록 — 비어있으면 해당 계정 전체
    product_ids: Optional[list[str]] = None


@router.post("/elevenst/cleanup-orphans")
async def cleanup_elevenst_orphans(
    body: ElevenstCleanupRequest = ElevenstCleanupRequest(),
    dry_run: bool = Query(True, description="true면 목록만, false면 실제 매핑 정리"),
    account_id: Optional[str] = Query(
        None, description="특정 계정만 점검 (미지정 시 모든 11번가 계정)"
    ),
    max_check: int = Query(
        500, ge=1, le=20000, description="계정당 점검할 최대 prdNo 개수"
    ),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """11번가 유령 매핑 정리.

    11번가는 GET 권한이 모든 계정에 미부여 상태이므로, 가격 변경 없는 minimal PUT으로
    응답 메시지를 분류해 유령 prdNo를 탐지한다.
    - "삭제된 상품" / "존재하지 않는 상품" → 유령 → DB 매핑 정리
    - 정상 200 → 살아있음 → skip
    - 그 외 에러 → fail (재시도 대상으로 분리)
    """
    from sqlalchemy.orm.attributes import flag_modified
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.elevenst import (
        ElevenstApiError,
        ElevenstClient,
        ElevenstRateLimitError,
    )

    # 유령 판정 키워드 (plugins.markets.elevenst._GHOST_ERROR_PATTERNS 와 동일)
    GHOST_PATTERNS = ("삭제된 상품", "존재하지 않는 상품")

    # 1) 11번가 계정 조회
    q = select(SambaMarketAccount).where(
        SambaMarketAccount.market_type == "11st",
        SambaMarketAccount.is_active == True,  # noqa: E712
    )
    if account_id:
        q = q.where(SambaMarketAccount.id == account_id)
    accounts = (await session.execute(q)).scalars().all()
    if not accounts:
        raise HTTPException(status_code=404, detail="활성 11번가 계정 없음")

    per_account: list[dict] = []
    total_checked = 0
    total_ghosts = 0
    total_cleared = 0
    total_alive = 0
    total_failed = 0

    for account in accounts:
        add_f = account.additional_fields or {}
        api_key = (
            (add_f.get("apiKey") if isinstance(add_f, dict) else "")
            or account.api_key
            or ""
        )
        if not api_key:
            per_account.append(
                {
                    "account_id": account.id,
                    "label": account.account_label,
                    "error": "API 키 없음",
                }
            )
            continue

        # 2) 이 계정에 등록된 상품 + prdNo 추출
        prod_q = select(SambaCollectedProduct).where(
            SambaCollectedProduct.registered_accounts.op("@>")([account.id])
        )
        if body.product_ids:
            prod_q = prod_q.where(SambaCollectedProduct.id.in_(body.product_ids))
        products = (await session.execute(prod_q)).scalars().all()

        targets: list[dict] = []
        for p in products:
            nos = p.market_product_nos or {}
            v = nos.get(account.id)
            prd_no = ""
            if isinstance(v, str):
                prd_no = v.strip()
            elif isinstance(v, dict):
                prd_no = str(v.get("prdNo") or v.get("productNo") or "").strip()
            if prd_no:
                targets.append(
                    {"product_id": p.id, "prd_no": prd_no, "name": (p.name or "")[:60]}
                )
            if len(targets) >= max_check:
                break

        # 3) minimal PUT 으로 상태 점검 (가격 변경 효과 없는 selPrc 0 + 다른 필드 없음)
        # → 11번가는 prdNo 상태를 먼저 검증 후 XML 검증하므로
        #   "삭제된 상품" / "존재하지 않는 상품" 응답을 우선적으로 받음
        # → 살아있는 상품은 selPrc 0 자체가 검증 실패로 다른 에러 메시지 반환 → 유령 아님으로 분류
        client = ElevenstClient(api_key)
        ghosts: list[dict] = []
        alive_count = 0
        failed: list[dict] = []
        cleared: list[str] = []

        # selPrc 0 + selMthdCd 만 — 살아있는 상품 가격 변경 0원 검증실패 유도
        probe_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Product><selMthdCd>01</selMthdCd><selPrc>0</selPrc></Product>"
        )

        for t in targets:
            try:
                await client.update_product(t["prd_no"], probe_xml)
                # 200 성공이 나오면 (이론상 없음 — selPrc 0 검증 통과 불가) 살아있음으로 간주
                alive_count += 1
            except ElevenstRateLimitError as e:
                # Rate limit은 즉시 중단, 남은 건 fail 처리하지 않고 다음 사이클에 재시도
                logger.warning(f"[유령정리][11번가] {account.id} rate limit, 중단: {e}")
                failed.append({"prd_no": t["prd_no"], "error": "rate_limit"})
                break
            except ElevenstApiError as e:
                msg = str(e)
                if any(p in msg for p in GHOST_PATTERNS):
                    ghosts.append(
                        {
                            "product_id": t["product_id"],
                            "prd_no": t["prd_no"],
                            "name": t["name"],
                            "reason": msg,
                        }
                    )
                else:
                    # 살아있으나 selPrc 0 검증실패 등 정상 케이스
                    alive_count += 1
            except Exception as e:
                failed.append({"prd_no": t["prd_no"], "error": str(e)[:120]})
            await asyncio.sleep(0.4)  # ~2.5 RPS

        # 4) dry_run=false 일 때 실제 정리
        if not dry_run and ghosts:
            ghost_pids = [g["product_id"] for g in ghosts]
            clear_q = select(SambaCollectedProduct).where(
                SambaCollectedProduct.id.in_(ghost_pids)
            )
            clear_rows = (await session.execute(clear_q)).scalars().all()
            for prod in clear_rows:
                changed = False
                nos = dict(prod.market_product_nos or {})
                for k in (account.id, f"{account.id}_origin"):
                    if k in nos:
                        nos.pop(k, None)
                        changed = True
                if changed:
                    prod.market_product_nos = nos
                    flag_modified(prod, "market_product_nos")
                regs = list(prod.registered_accounts or [])
                if account.id in regs:
                    regs = [a for a in regs if a != account.id]
                    prod.registered_accounts = regs
                    flag_modified(prod, "registered_accounts")
                    changed = True
                if changed:
                    session.add(prod)
                    cleared.append(str(prod.id))
            if cleared:
                await session.commit()
                logger.warning(f"[유령정리][11번가] {account.id} 정리 {len(cleared)}건")

        total_checked += len(targets)
        total_ghosts += len(ghosts)
        total_alive += alive_count
        total_failed += len(failed)
        total_cleared += len(cleared)

        per_account.append(
            {
                "account_id": account.id,
                "label": account.account_label,
                "checked": len(targets),
                "alive": alive_count,
                "ghost_count": len(ghosts),
                "ghosts": ghosts[:100],
                "cleared": cleared,
                "failed_count": len(failed),
                "failed": failed[:50],
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "max_check": max_check,
        "total_checked": total_checked,
        "total_alive": total_alive,
        "total_ghosts": total_ghosts,
        "total_cleared": total_cleared,
        "total_failed": total_failed,
        "accounts": per_account,
    }


@router.post("/elevenst/cleanup-missing-prdno")
async def cleanup_elevenst_missing_prdno(
    body: ElevenstCleanupRequest = ElevenstCleanupRequest(),
    dry_run: bool = Query(
        True, description="true면 조회만, false면 실제 판매중지+DB정리"
    ),
    account_id: Optional[str] = Query(
        None, description="특정 계정만 (미지정 시 모든 11번가 계정)"
    ),
    max_check: int = Query(500, ge=1, le=20000, description="계정당 점검 최대 상품 수"),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """11번가 prdNo 누락 매핑 정리.

    상황: registered_accounts에는 11번가 계정이 있는데, market_product_nos에 prdNo가
    저장 안 된 케이스. 등록 도중 응답 미수신 또는 과거 ghost 방지 패치 이전 데이터.

    절차:
    1) sellerPrdCd(=samba product.id)로 11번가 sellerprodcode API 역조회
    2) selStatCd=103(판매중) → prdNo 복구 + 판매중지(stopdisplay) 호출 + DB 정리
    3) selStatCd=104/105/106/108 → 이미 판매 종료 상태, DB만 정리
    4) 11번가에도 없음(404) → DB만 정리
    """
    from sqlalchemy.orm.attributes import flag_modified
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.elevenst import (
        ElevenstApiError,
        ElevenstClient,
        ElevenstRateLimitError,
    )

    # 1) 11번가 계정 조회
    q = select(SambaMarketAccount).where(
        SambaMarketAccount.market_type == "11st",
        SambaMarketAccount.is_active == True,  # noqa: E712
    )
    if account_id:
        q = q.where(SambaMarketAccount.id == account_id)
    accounts = (await session.execute(q)).scalars().all()
    if not accounts:
        raise HTTPException(status_code=404, detail="활성 11번가 계정 없음")

    # 판매 종료 상태 코드
    DEAD_STATS = {"104", "105", "106", "108"}

    per_account: list[dict] = []
    total_checked = 0
    total_alive = 0
    total_dead = 0
    total_missing = 0
    total_failed = 0
    total_recovered = 0  # prdNo 복구 후 판매중지 성공
    total_db_cleared = 0  # DB 매핑 정리

    for account in accounts:
        add_f = account.additional_fields or {}
        api_key = (
            (add_f.get("apiKey") if isinstance(add_f, dict) else "")
            or account.api_key
            or ""
        )
        if not api_key:
            per_account.append(
                {
                    "account_id": account.id,
                    "label": account.account_label,
                    "error": "API 키 없음",
                }
            )
            continue

        # 2) registered_accounts에 이 계정은 있지만 prdNo 없는 상품 추출
        prod_q = select(SambaCollectedProduct).where(
            SambaCollectedProduct.registered_accounts.op("@>")([account.id])
        )
        if body.product_ids:
            prod_q = prod_q.where(SambaCollectedProduct.id.in_(body.product_ids))
        products = (await session.execute(prod_q)).scalars().all()

        targets: list[SambaCollectedProduct] = []
        for p in products:
            nos = p.market_product_nos or {}
            v = nos.get(account.id)
            prd_no = ""
            if isinstance(v, str):
                prd_no = v.strip()
            elif isinstance(v, dict):
                prd_no = str(v.get("prdNo") or v.get("productNo") or "").strip()
            if not prd_no:
                targets.append(p)
            if len(targets) >= max_check:
                break

        client = ElevenstClient(api_key)
        alive_items: list[dict] = []  # 살아있음 → 판매중지 대상
        dead_items: list[dict] = []  # 이미 판매종료 → DB만 정리
        missing_items: list[dict] = []  # 11번가에도 없음 → DB만 정리
        failed: list[dict] = []
        recovered_ids: list[str] = []
        db_cleared_ids: list[str] = []

        for prod in targets:
            seller_code = str(prod.id)
            try:
                info = await client.find_by_seller_code(seller_code)
            except ElevenstRateLimitError as e:
                logger.warning(
                    f"[유령정리-누락][11번가] {account.id} rate limit 중단: {e}"
                )
                failed.append({"product_id": prod.id, "error": "rate_limit"})
                break
            except ElevenstApiError as e:
                failed.append({"product_id": prod.id, "error": str(e)[:120]})
                await asyncio.sleep(0.4)
                continue
            except Exception as e:
                failed.append({"product_id": prod.id, "error": str(e)[:120]})
                await asyncio.sleep(0.4)
                continue

            entry = {
                "product_id": prod.id,
                "name": (prod.name or "")[:60],
                "seller_code": seller_code,
                "prd_no": info.get("prd_no", ""),
                "sel_stat_cd": info.get("sel_stat_cd", ""),
                "sel_stat_nm": info.get("sel_stat_nm", ""),
            }

            if not info.get("found"):
                missing_items.append(entry)
            elif info.get("sel_stat_cd") in DEAD_STATS:
                dead_items.append(entry)
            else:
                # 판매중(103) 또는 그 외 → 살아있음으로 간주
                alive_items.append(entry)

            await asyncio.sleep(0.4)  # ~2.5 RPS

        # 3) dry_run=false 일 때 실제 처리
        if not dry_run:
            # 3-1) 살아있는 케이스 → prdNo DB 저장 후 stopdisplay 호출 후 DB 정리
            for item in list(alive_items):
                pid = item["product_id"]
                prd_no = item["prd_no"]
                prod = next((p for p in targets if p.id == pid), None)
                if prod is None or not prd_no:
                    continue

                # prdNo 일단 DB에 기록 (중단 시에도 다음 시도에 활용)
                nos = dict(prod.market_product_nos or {})
                nos[account.id] = prd_no
                prod.market_product_nos = nos
                flag_modified(prod, "market_product_nos")
                session.add(prod)
                await session.commit()

                # 판매중지 호출
                try:
                    await client.delete_product(prd_no)
                    recovered_ids.append(pid)
                except ElevenstRateLimitError as e:
                    logger.warning(
                        f"[유령정리-누락][11번가] stopdisplay rate limit {pid}: {e}"
                    )
                    failed.append({"product_id": pid, "error": "rate_limit"})
                    break
                except ElevenstApiError as e:
                    msg = str(e)
                    # 이미 죽은 상태로 응답하면 dead로 격하
                    if "삭제된 상품" in msg or "존재하지 않는 상품" in msg:
                        dead_items.append(item)
                    else:
                        failed.append({"product_id": pid, "error": msg[:120]})
                        await asyncio.sleep(0.4)
                        continue
                except Exception as e:
                    failed.append({"product_id": pid, "error": str(e)[:120]})
                    await asyncio.sleep(0.4)
                    continue

                # 판매중지 성공 → DB 매핑 제거
                nos2 = dict(prod.market_product_nos or {})
                for k in (account.id, f"{account.id}_origin"):
                    nos2.pop(k, None)
                prod.market_product_nos = nos2
                flag_modified(prod, "market_product_nos")
                regs = [a for a in (prod.registered_accounts or []) if a != account.id]
                prod.registered_accounts = regs
                flag_modified(prod, "registered_accounts")
                session.add(prod)
                await session.commit()
                db_cleared_ids.append(pid)
                await asyncio.sleep(0.4)

            # 3-2) 이미 죽은 케이스 + 11번가에도 없는 케이스 → DB만 정리
            for bucket in (dead_items, missing_items):
                for item in bucket:
                    pid = item["product_id"]
                    prod = next((p for p in targets if p.id == pid), None)
                    if prod is None:
                        continue
                    nos2 = dict(prod.market_product_nos or {})
                    changed = False
                    for k in (account.id, f"{account.id}_origin"):
                        if k in nos2:
                            nos2.pop(k, None)
                            changed = True
                    if changed:
                        prod.market_product_nos = nos2
                        flag_modified(prod, "market_product_nos")
                    regs_old = list(prod.registered_accounts or [])
                    if account.id in regs_old:
                        prod.registered_accounts = [
                            a for a in regs_old if a != account.id
                        ]
                        flag_modified(prod, "registered_accounts")
                        changed = True
                    if changed:
                        session.add(prod)
                        db_cleared_ids.append(pid)
            if db_cleared_ids:
                await session.commit()
                logger.warning(
                    f"[유령정리-누락][11번가] {account.id} 복구 {len(recovered_ids)} / DB정리 {len(db_cleared_ids)}"
                )

        total_checked += len(targets)
        total_alive += len(alive_items)
        total_dead += len(dead_items)
        total_missing += len(missing_items)
        total_failed += len(failed)
        total_recovered += len(recovered_ids)
        total_db_cleared += len(db_cleared_ids)

        per_account.append(
            {
                "account_id": account.id,
                "label": account.account_label,
                "checked": len(targets),
                "alive_count": len(alive_items),
                "alive": alive_items[:100],
                "dead_count": len(dead_items),
                "dead": dead_items[:100],
                "missing_count": len(missing_items),
                "missing": missing_items[:100],
                "recovered_count": len(recovered_ids),
                "db_cleared_count": len(db_cleared_ids),
                "failed_count": len(failed),
                "failed": failed[:50],
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "max_check": max_check,
        "total_checked": total_checked,
        "total_alive": total_alive,
        "total_dead": total_dead,
        "total_missing": total_missing,
        "total_recovered": total_recovered,
        "total_db_cleared": total_db_cleared,
        "total_failed": total_failed,
        "accounts": per_account,
    }


# ----------------------------------------------------------------------
# 쿠팡 유령삭제 (양방향 동기화) — 스마트스토어 패턴 본뜸
# ----------------------------------------------------------------------


@router.post("/coupang/cleanup-orphans")
async def cleanup_coupang_orphans(
    body: CleanupOrphansRequest = CleanupOrphansRequest(),
    dry_run: bool = Query(True, description="true면 목록만, false면 실제 삭제"),
    account_id: Optional[str] = Query(None, description="특정 쿠팡 계정만 정리"),
    max_delete: int = Query(
        50, ge=0, le=100000, description="한 번에 삭제할 최대 orphan 수"
    ),
    full: bool = Query(
        False,
        description="true면 orphans/stale_db 전체 반환 (단건 스트리밍 러너용). false면 100개로 캡.",
    ),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """쿠팡 유령상품 양방향 동기화.

    - orphan: 쿠팡에 있는데 DB 매핑 없음 → `delete_product(spid)` 호출
    - stale : DB는 등록됨인데 쿠팡 목록에 없음 → DB 매핑만 정리

    statusName=DELETED 는 이미 삭제된 상태이므로 비교에서 제외.
    """
    from sqlalchemy.orm.attributes import flag_modified
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.coupang import CoupangApiError, CoupangClient

    # 1) 활성 쿠팡 계정 조회
    q = select(SambaMarketAccount).where(
        SambaMarketAccount.market_type == "coupang",
        SambaMarketAccount.is_active == True,  # noqa: E712
    )
    if account_id:
        q = q.where(SambaMarketAccount.id == account_id)
    accounts = (await session.execute(q)).scalars().all()
    if not accounts:
        raise HTTPException(status_code=404, detail="활성 쿠팡 계정 없음")

    # 2) DB 상품 로드 (전체 카탈로그 — 화면 필터 무시)
    # [중요·issue #565] orphan("쿠팡에 있는데 DB 매핑 없음") 판정은 반드시 전체 DB를
    # 비교 대상으로 삼아야 한다. 화면 필터(body.product_ids)로 부분집합만 로드하면
    # 쿠팡 미등록 상품만 필터된 경우 account_db_spids=0 → 쿠팡 전체가 orphan 오판 →
    # 전량 삭제(복구 불가) 위험. 따라서 body.product_ids 는 의도적으로 적용하지 않는다.
    # 무거운 컬럼 defer — 전체 카탈로그 스캔 시 TOAST 로드로 인한 풀 고갈 방지
    prod_q = select(SambaCollectedProduct).options(
        defer(SambaCollectedProduct.detail_html),
        defer(SambaCollectedProduct.detail_images),
        defer(SambaCollectedProduct.images),
        defer(SambaCollectedProduct.extra_data),
    )
    all_db_products = (await session.execute(prod_q)).scalars().all()

    per_account: list[dict] = []
    total_market = 0
    total_orphans = 0
    total_stale_db = 0
    total_deleted = 0
    total_stale_cleared = 0

    for account in accounts:
        add_f = account.additional_fields or {}
        if not isinstance(add_f, dict):
            add_f = {}
        access_key = str(add_f.get("accessKey") or account.api_key or "").strip()
        secret_key = str(add_f.get("secretKey") or account.api_secret or "").strip()
        vendor_id = str(add_f.get("vendorId") or account.seller_id or "").strip()
        if not access_key or not secret_key or not vendor_id:
            per_account.append(
                {
                    "account_id": account.id,
                    "label": account.account_label,
                    "error": "쿠팡 인증정보 누락",
                }
            )
            continue

        # 2-1) 이 계정에 매핑된 sellerProductId set + DB id 역매핑
        account_db_spids: set[str] = set()
        db_spid_map: dict[str, dict] = {}  # spid → {db_id, name, ...}
        for p in all_db_products:
            nos = p.market_product_nos or {}
            v = nos.get(account.id)
            spid = ""
            if isinstance(v, str):
                spid = v.strip()
            elif isinstance(v, dict):
                spid = str(
                    v.get("sellerProductId")
                    or v.get("spid")
                    or v.get("productNo")
                    or ""
                ).strip()
            if spid:
                account_db_spids.add(spid)
                db_spid_map[spid] = {
                    "db_id": str(p.id),
                    "style_code": str(p.style_code or ""),
                    "mapped_spid": spid,
                    "product_name": (p.name or "")[:80],
                }

        # 3) 쿠팡 list_seller_products 전체 페이징 수집 (DELETED 제외)
        client = CoupangClient(access_key, secret_key, vendor_id)
        try:
            coupang_items = await client.list_seller_products(
                status=None, max_per_page=100
            )
        except CoupangApiError as e:
            per_account.append(
                {
                    "account_id": account.id,
                    "label": account.account_label,
                    "error": f"쿠팡 목록 조회 실패: {str(e)[:200]}",
                }
            )
            continue

        # DELETED 상태 제외
        market_spids: set[str] = set()
        market_info: dict[str, dict] = {}
        for it in coupang_items:
            sn = (it.get("status_name") or "").upper()
            if sn in ("DELETED", "DENIED"):
                continue
            spid = it.get("seller_product_id") or ""
            if not spid:
                continue
            market_spids.add(spid)
            market_info[spid] = it

        total_market += len(market_spids)

        # 4) orphan / stale 분류
        orphan_spids = market_spids - account_db_spids
        stale_spids = account_db_spids - market_spids

        orphans: list[dict] = []
        for spid in orphan_spids:
            info = market_info.get(spid) or {}
            orphans.append(
                {
                    "spid": spid,
                    "name": (info.get("product_name") or "")[:80],
                    "status_name": info.get("status_name") or "",
                }
            )

        stale_db: list[dict] = []
        for spid in stale_spids:
            info = db_spid_map.get(spid)
            if info:
                stale_db.append(info)

        total_orphans += len(orphans)
        total_stale_db += len(stale_db)

        deleted_here: list[str] = []
        failed: list[dict] = []
        stale_cleared: list[str] = []

        if not dry_run:
            # 4-1) orphan → 쿠팡 delete_product 호출
            remaining = max_delete - total_deleted
            if remaining > 0 and orphans:
                for o in orphans[:remaining]:
                    last_err: str | None = None
                    for attempt in range(4):
                        try:
                            await client.delete_product(o["spid"])
                            deleted_here.append(o["spid"])
                            last_err = None
                            break
                        except CoupangApiError as e:
                            err_msg = str(e)
                            last_err = err_msg
                            if (
                                "429" in err_msg or "TOO_MANY" in err_msg.upper()
                            ) and attempt < 3:
                                await asyncio.sleep(2**attempt)
                                continue
                            break
                        except Exception as e:
                            last_err = str(e)[:200]
                            break
                    if last_err is not None:
                        failed.append({"spid": o["spid"], "error": last_err})
                    await asyncio.sleep(0.4)
                total_deleted += len(deleted_here)

            # 4-2) stale → DB 매핑 정리
            if stale_db:
                db_ids_to_clear = [s["db_id"] for s in stale_db if s.get("db_id")]
                if db_ids_to_clear:
                    clear_q = select(SambaCollectedProduct).where(
                        SambaCollectedProduct.id.in_(db_ids_to_clear)
                    )
                    for prod in (await session.execute(clear_q)).scalars().all():
                        nos = dict(prod.market_product_nos or {})
                        changed = False
                        for k in (
                            account.id,
                            f"{account.id}_pid",
                            f"{account.id}_vid",
                            f"{account.id}_origin",
                        ):
                            if k in nos:
                                nos.pop(k, None)
                                changed = True
                        if changed:
                            prod.market_product_nos = nos
                            flag_modified(prod, "market_product_nos")
                        regs = list(prod.registered_accounts or [])
                        if account.id in regs:
                            prod.registered_accounts = [
                                a for a in regs if a != account.id
                            ]
                            flag_modified(prod, "registered_accounts")
                            changed = True
                        if changed:
                            session.add(prod)
                            stale_cleared.append(str(prod.id))
                    if stale_cleared:
                        await session.commit()
                        total_stale_cleared += len(stale_cleared)
                        logger.info(
                            f"[쿠팡 유령정리] {account.id} stale DB 정리 {len(stale_cleared)}건"
                        )

        per_account.append(
            {
                "account_id": account.id,
                "label": account.account_label,
                "market_count": len(market_spids),
                "orphan_count": len(orphans),
                "orphans": orphans if full else orphans[:100],
                "stale_db_count": len(stale_db),
                "stale_db": stale_db if full else stale_db[:100],
                "stale_cleared": stale_cleared,
                "deleted": deleted_here,
                "failed": failed,
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "total_market": total_market,
        "total_orphans": total_orphans,
        "total_stale_db": total_stale_db,
        "total_deleted": total_deleted,
        "total_stale_cleared": total_stale_cleared,
        "max_delete": max_delete,
        "accounts": per_account,
    }


# ----------------------------------------------------------------------
# 쿠팡 유령삭제 — 단건 처리 (스트리밍 로그용)
#   - 프론트가 1건씩 호출해 항목별 성공/실패를 실시간으로 표시
#   - 단일 워커 점유 시간 짧음 → Caddy timeout / health-fail 회피
# ----------------------------------------------------------------------


class CoupangClearStaleRequest(BaseModel):
    account_id: str
    db_id: str


class CoupangDeleteOrphanRequest(BaseModel):
    account_id: str
    spid: str


@router.post("/coupang/clear-stale-mapping")
async def clear_coupang_stale_mapping(
    body: CoupangClearStaleRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """쿠팡 stale 매핑 단건 정리 — 삼바 DB만 손댐(쿠팡 API 호출 없음)."""
    from sqlalchemy.orm.attributes import flag_modified
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct

    account = (
        await session.execute(
            select(SambaMarketAccount).where(SambaMarketAccount.id == body.account_id)
        )
    ).scalar_one_or_none()
    if not account or account.market_type != "coupang":
        raise HTTPException(status_code=404, detail="쿠팡 계정 없음")

    prod = (
        await session.execute(
            select(SambaCollectedProduct).where(SambaCollectedProduct.id == body.db_id)
        )
    ).scalar_one_or_none()
    if not prod:
        return {"ok": False, "cleared": False, "error": "상품 없음"}

    changed = False
    nos = dict(prod.market_product_nos or {})
    for k in (
        account.id,
        f"{account.id}_pid",
        f"{account.id}_vid",
        f"{account.id}_origin",
    ):
        if k in nos:
            nos.pop(k, None)
            changed = True
    if changed:
        prod.market_product_nos = nos
        flag_modified(prod, "market_product_nos")
    regs = list(prod.registered_accounts or [])
    if account.id in regs:
        prod.registered_accounts = [a for a in regs if a != account.id]
        flag_modified(prod, "registered_accounts")
        changed = True
    if changed:
        session.add(prod)
        await session.commit()
    return {"ok": True, "cleared": changed}


@router.post("/coupang/delete-orphan")
async def delete_coupang_orphan(
    body: CoupangDeleteOrphanRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """쿠팡 orphan 단건 삭제 — 상품삭제 버튼과 동일한 stop-then-delete 우회 로직 사용.

    승인완료(APPROVED)/부분승인 상품은 즉시 DELETE 가 거부되므로 dispatcher 가
    옵션 전체 sales/stop → 대기 → DELETE 재시도 (5s/15s/30s) 까지 자동 수행한다.
    """
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.shipment.dispatcher import delete_from_market

    account = (
        await session.execute(
            select(SambaMarketAccount).where(SambaMarketAccount.id == body.account_id)
        )
    ).scalar_one_or_none()
    if not account or account.market_type != "coupang":
        raise HTTPException(status_code=404, detail="쿠팡 계정 없음")

    # orphan 은 DB 매핑 없음 → product_dict 를 spid 만으로 최소 구성
    product_dict = {
        "id": "",
        "market_product_no": {"coupang": body.spid},
        "registered_accounts": [body.account_id],
    }

    try:
        result = await delete_from_market(
            session,
            "coupang",
            product_dict,
            account=account,
            market_delete=True,
        )
        if result.get("success"):
            return {
                "ok": True,
                "message": result.get("message", "삭제 완료"),
                "ghost_cleanup": bool(result.get("ghost_cleanup")),
            }
        return {"ok": False, "error": result.get("message", "삭제 실패")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


# ----------------------------------------------------------------------
# 11번가 유령삭제 양방향(v2) — list_seller_products 기반
# ----------------------------------------------------------------------


def _scoped_mapping_clause(account_ids: list[str]):
    """대상 계정의 매핑(market_product_nos)/등록 플래그(registered_accounts) 흔적이
    있는 행만 고르는 WHERE 절 — 유령정리 계열의 전체 테이블 로드 제거용.

    jsonb_typeof 가드로 깨진 형태(스칼라/리스트 mpn, 스칼라 regs)에서도 에러 없이
    동작한다 (과거 mpn 리스트 파손 행 실사례 있음).
    """
    from sqlalchemy import text as _sa_text

    conds = []
    params: dict[str, str] = {}
    for i, aid in enumerate(account_ids):
        conds.append(
            f"(jsonb_typeof(market_product_nos::jsonb) = 'object'"
            f" AND (market_product_nos::jsonb ? :ghk{i}"
            f" OR market_product_nos::jsonb ? :ghko{i}))"
            f" OR (jsonb_typeof(registered_accounts::jsonb) = 'array'"
            f" AND registered_accounts::jsonb ? :ghk{i})"
        )
        params[f"ghk{i}"] = aid
        params[f"ghko{i}"] = f"{aid}_origin"
    return _sa_text("(" + " OR ".join(conds) + ")").bindparams(**params)


@router.post("/elevenst/cleanup-orphans-v2")
async def cleanup_elevenst_orphans_v2(
    body: CleanupOrphansRequest = CleanupOrphansRequest(),
    dry_run: bool = Query(True, description="true면 목록만, false면 실제 처리"),
    account_id: Optional[str] = Query(None, description="특정 11번가 계정만"),
    max_delete: int = Query(
        50, ge=0, le=100000, description="한 번에 처리할 최대 orphan 수"
    ),
    clear_stale: bool = Query(
        False,
        description="stale(DB에만 있는 매핑) DB 정리 여부 — 목록 조회 부분실패 시 "
        "정상 매핑 오삭제 위험이 있어 기본 OFF",
    ),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """11번가 유령상품 양방향 동기화 (스마트스토어 패턴).

    - 11번가 전체 상태 enumerate 후 판매중(103)만 orphan 판정에 사용
    - orphan: 11번가 판매중인데 DB 매핑 없음 → delete_product(=stopdisplay)
    - stale : DB 매핑은 있는데 11번가 전체 목록(품절/중지 포함)에 없음 →
      clear_stale=true 일 때만 DB 정리 (기본 OFF — 오삭제 사고 방지)

    sellerPrdCd(=samba product.id)도 함께 수집해 DB id 매칭 보강.
    """
    from sqlalchemy.orm.attributes import flag_modified
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.elevenst import (
        ElevenstApiError,
        ElevenstClient,
        ElevenstRateLimitError,
    )

    q = select(SambaMarketAccount).where(
        SambaMarketAccount.market_type == "11st",
        SambaMarketAccount.is_active == True,  # noqa: E712
    )
    if account_id:
        q = q.where(SambaMarketAccount.id == account_id)
    accounts = (await session.execute(q)).scalars().all()
    if not accounts:
        raise HTTPException(status_code=404, detail="활성 11번가 계정 없음")

    prod_q = select(SambaCollectedProduct)
    if body.product_ids:
        prod_q = prod_q.where(SambaCollectedProduct.id.in_(body.product_ids))
    else:
        # 전체 테이블 로드 금지 — 대상 계정의 매핑/등록 흔적이 있는 행만 조회.
        # 전 행 ORM 로드는 상품 수만 단위에서 수 분이 걸려 gateway 504/DB idle
        # 타임아웃으로 "데이터베이스 에러"가 나던 원인 (2026-07-06 실측 468s→504).
        prod_q = prod_q.where(_scoped_mapping_clause([a.id for a in accounts]))
    all_db_products = (await session.execute(prod_q)).scalars().all()
    # ORM 객체 → 평문 데이터로 선추출. 아래 commit 으로 트랜잭션을 닫은 뒤에도
    # expire 된 ORM 속성에 접근하지 않도록 한다.
    db_products_data = [
        {
            "id": str(p.id),
            "style_code": str(p.style_code or ""),
            "name": p.name or "",
            "market_product_nos": (
                dict(p.market_product_nos)
                if isinstance(p.market_product_nos, dict)
                else {}
            ),
            "registered_accounts": list(p.registered_accounts or [])
            if isinstance(p.registered_accounts, list)
            else [],
        }
        for p in all_db_products
    ]
    # 마켓 API 페이징(계정당 수십초~수분) 동안 트랜잭션을 잡고 있으면 DB 의
    # idle_in_transaction_session_timeout(120s)에 커넥션이 끊긴다 — 읽기가 끝난
    # 시점에 트랜잭션을 닫는다 (이후 쓰기는 새 트랜잭션에서 수행).
    await session.commit()

    per_account: list[dict] = []
    total_market = 0
    total_orphans = 0
    total_stale_db = 0
    total_deleted = 0
    total_stale_cleared = 0

    for account in accounts:
        add_f = account.additional_fields or {}
        if not isinstance(add_f, dict):
            add_f = {}
        api_key = str(add_f.get("apiKey") or account.api_key or "").strip()
        if not api_key:
            per_account.append(
                {
                    "account_id": account.id,
                    "label": account.account_label,
                    "error": "11번가 API 키 없음",
                }
            )
            continue

        # DB → prdNo 매핑 (이 계정용)
        account_db_prdnos: set[str] = set()
        db_prdno_map: dict[str, dict] = {}
        for p in db_products_data:
            nos = p["market_product_nos"]
            v = nos.get(account.id)
            prd_no = ""
            if isinstance(v, str):
                prd_no = v.strip()
            elif isinstance(v, dict):
                prd_no = str(v.get("prdNo") or v.get("productNo") or "").strip()
            if prd_no:
                account_db_prdnos.add(prd_no)
                db_prdno_map[prd_no] = {
                    "db_id": p["id"],
                    "style_code": p["style_code"],
                    "mapped_prdno": prd_no,
                    "product_name": p["name"][:80],
                }

        client = ElevenstClient(api_key)
        try:
            # 전체 상태 조회 — 판매중(103)만 조회하면 품절/전시중지 매핑이 전부
            # stale 로 오판된다 (오토튠 품절 전환 상품 등). orphan 판정은 아래에서
            # 판매중만 분리해 사용.
            market_items = await client.list_seller_products(
                sel_stat_cd="", page_size=500
            )
        except ElevenstRateLimitError as e:
            per_account.append(
                {
                    "account_id": account.id,
                    "label": account.account_label,
                    "error": f"rate_limit (retry_after={e.retry_after}s)",
                }
            )
            continue
        except ElevenstApiError as e:
            per_account.append(
                {
                    "account_id": account.id,
                    "label": account.account_label,
                    "error": f"11번가 목록 조회 실패: {str(e)[:200]}",
                }
            )
            continue

        market_prdnos: set[str] = set()  # 판매중(103)만 — orphan 판정용
        market_all_prdnos: set[str] = set()  # 전체 상태 — stale 판정용
        market_info: dict[str, dict] = {}
        # sellerPrdCd(=samba product.id) 기반 보강 매핑
        seller_code_to_prdno: dict[str, str] = {}
        for it in market_items:
            pn = it.get("prd_no") or ""
            if not pn:
                continue
            market_all_prdnos.add(pn)
            if str(it.get("sel_stat_cd") or "") == "103":
                market_prdnos.add(pn)
                market_info[pn] = it
            sc = (it.get("seller_code") or "").strip()
            if sc:
                seller_code_to_prdno[sc] = pn

        total_market += len(market_prdnos)

        # sellerPrdCd가 우리 DB product.id 와 일치하면 → 그 prdNo는 우리 것
        # (registered_accounts에 이 account 가 들어있는 경우만 인정)
        recovered_in_db: set[str] = set()
        for p in db_products_data:
            if account.id not in p["registered_accounts"]:
                continue
            pn = seller_code_to_prdno.get(p["id"])
            if pn:
                account_db_prdnos.add(pn)
                recovered_in_db.add(pn)

        orphan_prdnos = market_prdnos - account_db_prdnos
        # stale 은 품절/중지 포함 전체 목록 기준 — 판매중 목록만으로 판정하면
        # 품절 전환 상품이 대량 오판된다 (실측: 계정당 수백~1,300건).
        stale_prdnos = account_db_prdnos - market_all_prdnos

        orphans: list[dict] = []
        for pn in orphan_prdnos:
            info = market_info.get(pn) or {}
            orphans.append(
                {
                    "prd_no": pn,
                    "name": (info.get("name") or "")[:80],
                    "seller_code": info.get("seller_code") or "",
                }
            )

        stale_db: list[dict] = []
        for pn in stale_prdnos:
            info = db_prdno_map.get(pn)
            if info:
                stale_db.append(info)

        total_orphans += len(orphans)
        total_stale_db += len(stale_db)

        deleted_here: list[str] = []
        failed: list[dict] = []
        stale_cleared: list[str] = []

        if not dry_run:
            remaining = max_delete - total_deleted
            if remaining > 0 and orphans:
                rate_limited = False
                for o in orphans[:remaining]:
                    if rate_limited:
                        break
                    try:
                        await client.delete_product(o["prd_no"])
                        deleted_here.append(o["prd_no"])
                    except ElevenstRateLimitError as e:
                        failed.append(
                            {
                                "prd_no": o["prd_no"],
                                "error": f"rate_limit({e.retry_after}s)",
                            }
                        )
                        rate_limited = True
                    except ElevenstApiError as e:
                        msg = str(e)
                        if "삭제된 상품" in msg or "존재하지 않는 상품" in msg:
                            # 이미 죽은 상태 — 통과
                            deleted_here.append(o["prd_no"])
                        else:
                            failed.append({"prd_no": o["prd_no"], "error": msg[:200]})
                    except Exception as e:
                        failed.append({"prd_no": o["prd_no"], "error": str(e)[:200]})
                    await asyncio.sleep(0.4)
                total_deleted += len(deleted_here)

            # stale DB 정리 — clear_stale 옵트인일 때만.
            # 목록 조회가 페이징 도중 조용히 끊기면 정상 매핑이 대량 stale 오판되어
            # 무조건 클리어 시 등록기록이 소실된다 (2026-07-06 1,159건 실사고).
            if stale_db and clear_stale:
                # 조회 부실 가드 — 마켓 전체 조회수가 DB 매핑수의 절반 미만이면
                # 부분실패 가능성이 높으므로 정리를 건너뛴다.
                if len(market_all_prdnos) < len(account_db_prdnos) // 2:
                    logger.warning(
                        f"[11번가 유령정리v2] {account.id} 마켓 조회 부실 의심 "
                        f"(조회 {len(market_all_prdnos)} < 매핑 {len(account_db_prdnos)}/2) "
                        f"— stale 정리 스킵"
                    )
                else:
                    db_ids_to_clear = [s["db_id"] for s in stale_db if s.get("db_id")]
                    if db_ids_to_clear:
                        clear_q = select(SambaCollectedProduct).where(
                            SambaCollectedProduct.id.in_(db_ids_to_clear)
                        )
                        for prod in (await session.execute(clear_q)).scalars().all():
                            nos = dict(prod.market_product_nos or {})
                            changed = False
                            for k in (account.id, f"{account.id}_origin"):
                                if k in nos:
                                    nos.pop(k, None)
                                    changed = True
                            if changed:
                                prod.market_product_nos = nos
                                flag_modified(prod, "market_product_nos")
                            regs = list(prod.registered_accounts or [])
                            if account.id in regs:
                                prod.registered_accounts = [
                                    a for a in regs if a != account.id
                                ]
                                flag_modified(prod, "registered_accounts")
                                changed = True
                            if changed:
                                session.add(prod)
                                stale_cleared.append(str(prod.id))
                        if stale_cleared:
                            await session.commit()
                            total_stale_cleared += len(stale_cleared)
                            logger.info(
                                f"[11번가 유령정리v2] {account.id} stale DB 정리 {len(stale_cleared)}건"
                            )

        per_account.append(
            {
                "account_id": account.id,
                "label": account.account_label,
                "market_count": len(market_prdnos),
                "orphan_count": len(orphans),
                "orphans": orphans[:100],
                "stale_db_count": len(stale_db),
                "stale_db": stale_db[:100],
                "stale_cleared": stale_cleared,
                "deleted": deleted_here,
                "failed": failed,
                "recovered_via_seller_code": len(recovered_in_db),
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "total_market": total_market,
        "total_orphans": total_orphans,
        "total_stale_db": total_stale_db,
        "total_deleted": total_deleted,
        "total_stale_cleared": total_stale_cleared,
        "max_delete": max_delete,
        "accounts": per_account,
    }


# ----------------------------------------------------------------------
# 롯데ON 유령삭제 양방향 — list_registered_products 기반
# ----------------------------------------------------------------------


@router.post("/lotteon/cleanup-orphans")
async def cleanup_lotteon_orphans(
    body: CleanupOrphansRequest = CleanupOrphansRequest(),
    dry_run: bool = Query(True, description="true면 목록만, false면 실제 처리"),
    account_id: Optional[str] = Query(None, description="특정 롯데ON 계정만"),
    max_delete: int = Query(
        50, ge=0, le=100000, description="한 번에 처리할 최대 orphan 수"
    ),
    clear_stale: bool = Query(
        False,
        description="stale(DB에만 있는 매핑) DB 정리 여부 — 목록 조회 부분실패 시 "
        "정상 매핑 오삭제 위험이 있어 기본 OFF",
    ),
    session: AsyncSession = Depends(get_write_session_dependency),
    admin: str = Depends(require_admin),
):
    """롯데ON 유령상품 양방향 동기화.

    - orphan: 롯데ON 판매중인데 DB 매핑 없음 → change_status(slStatCd=END)
    - stale : DB 매핑은 있는데 롯데ON 전체 목록(END/SOUT 포함)에 없음 →
      clear_stale=true 일 때만 DB 정리 (기본 OFF — 오삭제 사고 방지)
    """
    import json as _json

    from sqlalchemy.orm.attributes import flag_modified
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.proxy.lotteon import LotteonClient

    q = select(SambaMarketAccount).where(
        SambaMarketAccount.market_type == "lotteon",
        SambaMarketAccount.is_active == True,  # noqa: E712
    )
    if account_id:
        q = q.where(SambaMarketAccount.id == account_id)
    accounts = (await session.execute(q)).scalars().all()
    if not accounts:
        raise HTTPException(status_code=404, detail="활성 롯데ON 계정 없음")

    prod_q = select(SambaCollectedProduct)
    if body.product_ids:
        prod_q = prod_q.where(SambaCollectedProduct.id.in_(body.product_ids))
    else:
        # 전체 테이블 로드 금지 — 대상 계정의 매핑/등록 흔적이 있는 행만 조회.
        # 전 행 ORM 로드는 상품 수만 단위에서 수 분이 걸려 gateway 504/DB idle
        # 타임아웃으로 "데이터베이스 에러"가 나던 원인 (2026-07-03 실측 538s→502).
        prod_q = prod_q.where(_scoped_mapping_clause([a.id for a in accounts]))
    all_db_products = (await session.execute(prod_q)).scalars().all()
    # ORM 객체 → 평문 데이터 선추출 (commit 후 expire 속성 접근 방지)
    db_products_data = [
        {
            "id": str(p.id),
            "style_code": str(p.style_code or ""),
            "name": p.name or "",
            "market_product_nos": (
                dict(p.market_product_nos)
                if isinstance(p.market_product_nos, dict)
                else {}
            ),
        }
        for p in all_db_products
    ]
    # 마켓 API 페이징(대형 계정 160+페이지, 수 분) 동안 트랜잭션 유지 시 DB 의
    # idle_in_transaction_session_timeout(120s)에 커넥션이 끊긴다 — 여기서 닫는다.
    await session.commit()

    per_account: list[dict] = []
    total_market = 0
    total_orphans = 0
    total_stale_db = 0
    total_deleted = 0
    total_stale_cleared = 0

    PAGE_SIZE = 100

    for account in accounts:
        add_f = account.additional_fields or {}
        if isinstance(add_f, str):
            try:
                add_f = _json.loads(add_f)
            except Exception:
                add_f = {}
        if not isinstance(add_f, dict):
            add_f = {}
        api_key = (
            str(account.api_key or "").strip() or str(add_f.get("apiKey") or "").strip()
        )
        if not api_key:
            per_account.append(
                {
                    "account_id": account.id,
                    "label": account.account_label,
                    "error": "롯데ON API 키 없음",
                }
            )
            continue

        # DB → spdNo 매핑
        account_db_spds: set[str] = set()
        db_spd_map: dict[str, dict] = {}
        for p in db_products_data:
            nos = p["market_product_nos"]
            v = nos.get(account.id) or nos.get(f"{account.id}_origin")
            spd = ""
            if isinstance(v, str):
                spd = v.strip()
            elif isinstance(v, dict):
                spd = str(v.get("spdNo") or v.get("productNo") or "").strip()
            if spd:
                account_db_spds.add(spd)
                db_spd_map[spd] = {
                    "db_id": p["id"],
                    "style_code": p["style_code"],
                    "mapped_spd": spd,
                    "product_name": p["name"][:80],
                }

        client = LotteonClient(api_key)
        # trGrpCd/trNo 획득 (필수) — 누락 시 list INVALID_INPUT
        await client.test_auth()
        market_spds: set[str] = set()  # 판매중 계열 — orphan 판정용
        market_all_spds: set[str] = set()  # END/SOUT 포함 전체 — stale 판정용
        market_info: dict[str, dict] = {}
        page = 1
        error_msg: Optional[str] = None
        while True:
            try:
                resp = await client.list_registered_products(
                    page=page,
                    size=PAGE_SIZE,
                    reg_strt_dttm="20200101000000",
                    reg_end_dttm="99991231235959",
                )
            except Exception as e:
                error_msg = f"롯데ON 목록 조회 실패(page={page}): {str(e)[:200]}"
                break
            data = (resp or {}).get("data") or []
            if not isinstance(data, list):
                break
            for it in data:
                if not isinstance(it, dict):
                    continue
                spd = str(it.get("spdNo") or "").strip()
                if not spd:
                    continue
                stat = str(it.get("slStatCd") or "").strip().upper()
                market_all_spds.add(spd)
                # END/SOUT 상태는 이미 죽은 상품 — orphan 판정 제외
                # (stale 판정에는 포함 — 품절 매핑이 stale 로 오판되던 원인)
                if stat in ("END", "SOUT", "DELETED"):
                    continue
                market_spds.add(spd)
                market_info[spd] = {
                    "spd_no": spd,
                    "name": str(it.get("spdNm") or "")[:80],
                    "sl_stat_cd": stat,
                }
            if len(data) < PAGE_SIZE:
                break
            page += 1
            if page > 500:
                logger.warning("[롯데ON 유령정리] 500페이지 초과 — 중단")
                break
            await asyncio.sleep(0.3)

        if error_msg:
            per_account.append(
                {
                    "account_id": account.id,
                    "label": account.account_label,
                    "error": error_msg,
                }
            )
            continue

        total_market += len(market_spds)

        orphan_spds = market_spds - account_db_spds
        # stale 은 END/SOUT 포함 전체 목록 기준 — 판매중 목록만으로 판정하면
        # 품절/판매종료 매핑이 대량 오판된다 (실측: 계정당 수백~1,300건).
        stale_spds = account_db_spds - market_all_spds

        orphans = [market_info[s] for s in orphan_spds if s in market_info]
        stale_db = [db_spd_map[s] for s in stale_spds if s in db_spd_map]

        total_orphans += len(orphans)
        total_stale_db += len(stale_db)

        deleted_here: list[str] = []
        failed: list[dict] = []
        stale_cleared: list[str] = []

        if not dry_run:
            remaining = max_delete - total_deleted
            if remaining > 0 and orphans:
                BATCH = 50
                target_orphans = orphans[:remaining]
                for i in range(0, len(target_orphans), BATCH):
                    batch = target_orphans[i : i + BATCH]
                    payload = [{"spdNo": o["spd_no"], "slStatCd": "END"} for o in batch]
                    try:
                        res = await client.change_status(payload)
                        data = (res or {}).get("data") or []
                        if isinstance(data, list) and data:
                            for idx, item in enumerate(data):
                                rc = (item or {}).get("resultCode", "")
                                spd = batch[idx]["spd_no"] if idx < len(batch) else ""
                                if rc in ("", "0000", "00", "SUCCESS"):
                                    deleted_here.append(spd)
                                else:
                                    failed.append(
                                        {
                                            "spd_no": spd,
                                            "error": str(
                                                (item or {}).get("resultMessage", rc)
                                            )[:200],
                                        }
                                    )
                        else:
                            for o in batch:
                                deleted_here.append(o["spd_no"])
                    except Exception as e:
                        for o in batch:
                            failed.append(
                                {"spd_no": o["spd_no"], "error": str(e)[:200]}
                            )
                    await asyncio.sleep(0.5)
                total_deleted += len(deleted_here)

            # stale DB 정리 — clear_stale 옵트인일 때만 (기본 OFF).
            # 목록 조회가 페이징 도중 조용히 끊기면 정상 매핑이 대량 stale 오판되어
            # 무조건 클리어 시 등록기록이 소실된다 (11번가 1,159건 실사고와 동일 구조).
            if stale_db and clear_stale:
                # 조회 부실 가드 — 마켓 전체 조회수가 DB 매핑수의 절반 미만이면 스킵
                if len(market_all_spds) < len(account_db_spds) // 2:
                    logger.warning(
                        f"[롯데ON 유령정리] {account.id} 마켓 조회 부실 의심 "
                        f"(조회 {len(market_all_spds)} < 매핑 {len(account_db_spds)}/2) "
                        f"— stale 정리 스킵"
                    )
                else:
                    db_ids_to_clear = [s["db_id"] for s in stale_db if s.get("db_id")]
                    if db_ids_to_clear:
                        clear_q = select(SambaCollectedProduct).where(
                            SambaCollectedProduct.id.in_(db_ids_to_clear)
                        )
                        for prod in (await session.execute(clear_q)).scalars().all():
                            nos = dict(prod.market_product_nos or {})
                            changed = False
                            for k in (account.id, f"{account.id}_origin"):
                                if k in nos:
                                    nos.pop(k, None)
                                    changed = True
                            if changed:
                                prod.market_product_nos = nos
                                flag_modified(prod, "market_product_nos")
                            regs = list(prod.registered_accounts or [])
                            if account.id in regs:
                                prod.registered_accounts = [
                                    a for a in regs if a != account.id
                                ]
                                flag_modified(prod, "registered_accounts")
                                changed = True
                            if changed:
                                session.add(prod)
                                stale_cleared.append(str(prod.id))
                        if stale_cleared:
                            await session.commit()
                            total_stale_cleared += len(stale_cleared)
                            logger.info(
                                f"[롯데ON 유령정리] {account.id} stale DB 정리 {len(stale_cleared)}건"
                            )

        per_account.append(
            {
                "account_id": account.id,
                "label": account.account_label,
                "market_count": len(market_spds),
                "orphan_count": len(orphans),
                "orphans": orphans[:100],
                "stale_db_count": len(stale_db),
                "stale_db": stale_db[:100],
                "stale_cleared": stale_cleared,
                "deleted": deleted_here,
                "failed": failed,
            }
        )

    return {
        "ok": True,
        "dry_run": dry_run,
        "total_market": total_market,
        "total_orphans": total_orphans,
        "total_stale_db": total_stale_db,
        "total_deleted": total_deleted,
        "total_stale_cleared": total_stale_cleared,
        "max_delete": max_delete,
        "accounts": per_account,
    }


@router.get("")
async def list_shipments(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_read_session_dependency),
    tenant_id: Optional[str] = Depends(get_optional_tenant_id),
):
    from sqlmodel import select

    from backend.domain.samba.shipment.model import SambaShipment

    # tenant_id가 있으면 해당 테넌트 전송 이력만 조회
    if tenant_id is not None:
        stmt = (
            select(SambaShipment)
            .order_by(SambaShipment.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        from sqlalchemy import or_

        stmt = stmt.where(
            or_(
                SambaShipment.tenant_id == tenant_id,
                SambaShipment.tenant_id == None,  # noqa: E711
            )
        )
        if status:
            stmt = stmt.where(SambaShipment.status == status)
        result = await session.execute(stmt)
        return result.scalars().all()
    svc = _get_service(session)
    return await svc.list_shipments(skip=skip, limit=limit, status=status)


@router.get("/product/{product_id}")
async def list_by_product(
    product_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    return await _get_service(session).list_by_product(product_id)


@router.get("/{shipment_id}")
async def get_shipment(
    shipment_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    svc = _get_service(session)
    s = await svc.get_shipment(shipment_id)
    if not s:
        raise HTTPException(404, "전송 기록을 찾을 수 없습니다")
    return s


@router.post("/start", status_code=201)
async def start_shipment(
    body: ShipmentStartRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_service(session)
    result = await svc.start_update(
        body.product_ids,
        body.update_items,
        body.target_account_ids,
        skip_unchanged=body.skip_unchanged,
    )
    return result


@router.post("/market-delete")
async def market_delete(
    request: Request,
    body: MarketDeleteRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """선택된 상품을 대상 마켓에서 판매중지/삭제."""
    svc = _get_service(session)
    return await svc.delete_from_markets(
        body.product_ids,
        body.target_account_ids,
        current_idx=body.current_idx,
        total_count=body.total_count,
        log_to_buffer=body.log_to_buffer,
        disconnect_checker=request.is_disconnected,
    )


@router.post("/market-delete-by-account")
async def market_delete_by_account(
    body: MarketDeleteByAccountRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """특정 마켓 계정에 등록된 모든 상품을 마켓에서 삭제."""
    svc = _get_service(session)
    try:
        return await svc.delete_all_by_account(body.account_id, dry_run=body.dry_run)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{shipment_id}/retry")
async def retry_shipment(
    shipment_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    svc = _get_service(session)
    result = await svc.retransmit(shipment_id)
    if not result:
        raise HTTPException(404, "전송 기록을 찾을 수 없습니다")
    return result


# ==================== 그룹상품 ====================


class GroupPreviewRequest(BaseModel):
    product_ids: list[str] = []
    search_filter_ids: list[str] = []
    account_id: str


class GroupPreviewProduct(BaseModel):
    id: str
    name: str
    color: Optional[str]
    sale_price: Optional[float]
    thumbnail: Optional[str]
    existing_product_no: Optional[str]


class GroupPreviewGroup(BaseModel):
    group_key: str
    group_name: str
    products: list[GroupPreviewProduct]


class GroupPreviewResponse(BaseModel):
    groups: list[GroupPreviewGroup]
    singles: list[GroupPreviewProduct]
    delete_count: int
    group_count: int
    single_count: int


@router.post("/group-preview")
async def group_preview(
    body: GroupPreviewRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """전송 대상 상품에서 그룹핑 가능한 상품을 감지하여 미리보기 반환."""
    from collections import defaultdict

    from backend.domain.samba.collector.grouping import group_products_by_key
    from backend.domain.samba.collector.repository import (
        SambaCollectedProductRepository,
    )

    repo = SambaCollectedProductRepository(session)
    products = []

    # search_filter_ids가 제공되면 해당 필터의 상품을 모두 조회
    product_ids = list(body.product_ids)
    if body.search_filter_ids:
        for sf_id in body.search_filter_ids:
            filter_products = await repo.filter_by_async(
                search_filter_id=sf_id, limit=10000
            )
            product_ids.extend([p.id for p in filter_products])

    for pid in product_ids:
        p = await repo.get_async(pid)
        if p:
            products.append(p.model_dump())

    # search_filter_id별로 분리 후 그룹핑 (다른 검색그룹끼리는 묶지 않음)
    by_filter: dict[str, list[dict]] = defaultdict(list)
    for p in products:
        sf_id = p.get("search_filter_id") or "_none"
        by_filter[sf_id].append(p)

    all_groups: dict[str, list[dict]] = {}
    all_singles: list[dict] = []
    for sf_id, sf_products in by_filter.items():
        r = group_products_by_key(sf_products)
        all_groups.update(r["groups"])
        all_singles.extend(r["singles"])

    # 그룹별 미리보기 구성
    groups = []
    delete_count = 0
    for key, items in all_groups.items():
        first_name = items[0].get("name", "")
        group_name = (
            first_name.split(" - ", 1)[0].strip() if " - " in first_name else first_name
        )

        group_products = []
        for item in items:
            market_nos = item.get("market_product_nos") or {}
            existing_no = market_nos.get(body.account_id)
            if existing_no:
                if isinstance(existing_no, dict):
                    existing_no = str(existing_no.get("originProductNo", ""))
                else:
                    existing_no = str(existing_no)
                delete_count += 1
            else:
                existing_no = None
            item_images = item.get("images") or []
            group_products.append(
                GroupPreviewProduct(
                    id=item["id"],
                    name=item.get("name", ""),
                    color=item.get("color"),
                    sale_price=item.get("sale_price"),
                    thumbnail=item_images[0] if item_images else None,
                    existing_product_no=existing_no,
                )
            )
        groups.append(
            GroupPreviewGroup(
                group_key=key,
                group_name=group_name,
                products=group_products,
            )
        )

    singles = []
    for item in all_singles:
        item_images = item.get("images") or []
        market_nos = item.get("market_product_nos") or {}
        existing = market_nos.get(body.account_id)
        if existing and isinstance(existing, dict):
            existing = str(existing.get("originProductNo", ""))
        elif existing:
            existing = str(existing)
        else:
            existing = None
        singles.append(
            GroupPreviewProduct(
                id=item["id"],
                name=item.get("name", ""),
                color=item.get("color"),
                sale_price=item.get("sale_price"),
                thumbnail=item_images[0] if item_images else None,
                existing_product_no=existing,
            )
        )

    return GroupPreviewResponse(
        groups=groups,
        singles=singles,
        delete_count=delete_count,
        group_count=len(groups),
        single_count=len(singles),
    )


class GroupSendItem(BaseModel):
    group_key: str
    product_ids: list[str]


class GroupSendRequest(BaseModel):
    groups: list[GroupSendItem]
    singles: list[str]
    account_id: str


@router.post("/group-send")
async def group_send(
    body: GroupSendRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """그룹상품 + 단일상품 전송."""
    svc = _get_service(session)
    results = []

    # 1. 그룹상품 전송
    for group in body.groups:
        try:
            result = await svc.transmit_group(
                product_ids=group.product_ids,
                account_id=body.account_id,
            )
            results.append(
                {"group_key": group.group_key, "status": "success", **result}
            )
        except Exception as e:
            results.append(
                {"group_key": group.group_key, "status": "error", "error": str(e)}
            )

    # 2. 단일상품 전송 (기존 방식)
    single_results = {}
    if body.singles:
        single_results = await svc.start_update(
            product_ids=body.singles,
            update_items=["price", "stock", "image", "description"],
            target_account_ids=[body.account_id],
        )

    return {
        "group_results": results,
        "single_results": single_results,
    }
