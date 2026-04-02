"""SNS 자동 포스팅 API 라우터 — 워드프레스 연동 + 이슈 크롤링 + 자동 포스팅 스트리밍."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_session_dependency
from backend.domain.samba.sns_posting.service import SnsPostingService

router = APIRouter(prefix="/sns", tags=["samba-sns-posting"])


# ------------------------------------------------------------------
# Pydantic 요청 모델
# ------------------------------------------------------------------


class WpConnectRequest(BaseModel):
    """워드프레스 연결 요청."""

    site_url: str
    username: str
    app_password: str


class KeywordGroupRequest(BaseModel):
    """키워드 그룹 생성 요청."""

    name: str
    category: str
    keywords: List[str]


class IssueSearchRequest(BaseModel):
    """이슈 검색 요청."""

    category: str
    keywords: Optional[List[str]] = None


class PublishRequest(BaseModel):
    """단건 글 생성 및 발행 요청."""

    wp_site_id: str
    issue: dict
    category: str
    language: str = "ko"
    product_info: Optional[dict] = None


class AutoConfigRequest(BaseModel):
    """자동 포스팅 설정 저장 요청."""

    wp_site_id: str
    interval_minutes: int = 20
    max_daily_posts: int = 150
    language: str = "ko"
    include_product_banner: bool = True
    product_banner_html: Optional[str] = None


# ------------------------------------------------------------------
# 워드프레스 사이트 관리
# ------------------------------------------------------------------


@router.post("/wordpress/connect")
async def connect_wordpress(
    req: WpConnectRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """워드프레스 사이트를 연결하고 DB에 등록한다."""
    svc = SnsPostingService(session)
    result = await svc.connect_wp(
        site_url=req.site_url,
        username=req.username,
        app_password=req.app_password,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "연결 실패"))
    site = result["site"]
    return {
        "ok": True,
        "site": {
            "id": site.id,
            "site_url": site.site_url,
            "site_name": site.site_name,
            "status": site.status,
            "created_at": site.created_at.isoformat(),
        },
    }


@router.get("/wordpress/sites")
async def list_wordpress_sites(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """등록된 워드프레스 사이트 목록을 반환한다."""
    svc = SnsPostingService(session)
    sites = await svc.list_wp_sites()
    return {
        "items": [
            {
                "id": s.id,
                "site_url": s.site_url,
                "site_name": s.site_name,
                "username": s.username,
                "status": s.status,
                "created_at": s.created_at.isoformat(),
            }
            for s in sites
        ]
    }


# ------------------------------------------------------------------
# 키워드 그룹 관리
# ------------------------------------------------------------------


@router.post("/keywords")
async def create_keyword_group(
    req: KeywordGroupRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """키워드 그룹을 생성한다."""
    svc = SnsPostingService(session)
    group = await svc.save_keyword_group(
        name=req.name,
        category=req.category,
        keywords=req.keywords,
    )
    return {
        "id": group.id,
        "name": group.name,
        "category": group.category,
        "keywords": group.keywords,
        "is_active": group.is_active,
        "created_at": group.created_at.isoformat(),
    }


@router.get("/keywords")
async def list_keyword_groups(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """키워드 그룹 목록을 반환한다."""
    svc = SnsPostingService(session)
    groups = await svc.list_keyword_groups()
    return {
        "items": [
            {
                "id": g.id,
                "name": g.name,
                "category": g.category,
                "keywords": g.keywords,
                "is_active": g.is_active,
                "created_at": g.created_at.isoformat(),
            }
            for g in groups
        ]
    }


@router.delete("/keywords/{group_id}")
async def delete_keyword_group(
    group_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """키워드 그룹을 삭제한다."""
    svc = SnsPostingService(session)
    deleted = await svc.delete_keyword_group(group_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="키워드 그룹을 찾을 수 없습니다.")
    return {"ok": True, "deleted_id": group_id}


# ------------------------------------------------------------------
# 이슈 검색
# ------------------------------------------------------------------


@router.post("/issue-search")
async def search_issues(req: IssueSearchRequest):
    """카테고리와 키워드로 뉴스 이슈를 검색한다."""
    from backend.domain.samba.sns_posting.issue_crawler import IssueCrawler

    crawler = IssueCrawler()
    try:
        issues = await crawler.search_issues(
            category=req.category,
            keywords=req.keywords,
        )
    finally:
        await crawler.close()

    return {"items": issues, "count": len(issues)}


# ------------------------------------------------------------------
# 단건 글 발행
# ------------------------------------------------------------------


@router.post("/publish")
async def publish_post(
    req: PublishRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """이슈 기반으로 AI 글을 생성하고 워드프레스에 발행한다."""
    svc = SnsPostingService(session)
    result = await svc.generate_and_publish(
        wp_site_id=req.wp_site_id,
        issue=req.issue,
        category=req.category,
        language=req.language,
        product_info=req.product_info,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=500, detail=result.get("error", "발행 실패"))
    return result


# ------------------------------------------------------------------
# 자동 포스팅 설정 / 시작 / 중지
# ------------------------------------------------------------------


@router.post("/auto-posting/config")
async def save_auto_config(
    req: AutoConfigRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """자동 포스팅 설정을 저장한다."""
    svc = SnsPostingService(session)
    config = await svc.save_auto_config(
        wp_site_id=req.wp_site_id,
        interval_minutes=req.interval_minutes,
        max_daily_posts=req.max_daily_posts,
        language=req.language,
        include_product_banner=req.include_product_banner,
        product_banner_html=req.product_banner_html,
    )
    return {
        "id": config.id,
        "wp_site_id": config.wp_site_id,
        "interval_minutes": config.interval_minutes,
        "max_daily_posts": config.max_daily_posts,
        "language": config.language,
        "include_product_banner": config.include_product_banner,
        "is_running": config.is_running,
        "updated_at": config.updated_at.isoformat(),
    }


@router.post("/auto-posting/start/{wp_site_id}")
async def start_auto_posting(
    wp_site_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """자동 포스팅을 시작한다 — SSE 스트리밍 응답."""
    svc = SnsPostingService(session)

    async def _event_stream():
        async for chunk in svc.auto_posting_stream(wp_site_id=wp_site_id):
            yield chunk

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.post("/auto-posting/stop/{wp_site_id}")
async def stop_auto_posting(
    wp_site_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """자동 포스팅 실행 상태를 중지로 업데이트한다."""
    svc = SnsPostingService(session)
    stopped = await svc.stop_auto_posting(wp_site_id=wp_site_id)
    if not stopped:
        raise HTTPException(
            status_code=404, detail="자동 포스팅 설정을 찾을 수 없습니다."
        )
    return {"ok": True, "wp_site_id": wp_site_id, "is_running": False}


# ------------------------------------------------------------------
# 발행 이력 / 대시보드
# ------------------------------------------------------------------


@router.get("/posts")
async def list_posts(
    page: int = 1,
    size: int = 50,
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """발행된 SNS 포스트 목록을 반환한다."""
    svc = SnsPostingService(session)
    posts = await svc.list_posts(page=page, size=size, status=status)
    return {
        "items": [
            {
                "id": p.id,
                "wp_site_id": p.wp_site_id,
                "wp_post_id": p.wp_post_id,
                "title": p.title,
                "category": p.category,
                "keyword": p.keyword,
                "source_url": p.source_url,
                "status": p.status,
                "language": p.language,
                "published_at": p.published_at.isoformat() if p.published_at else None,
                "created_at": p.created_at.isoformat(),
            }
            for p in posts
        ],
        "page": page,
        "size": size,
    }


@router.get("/dashboard")
async def get_dashboard(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """자동 포스팅 대시보드 통계를 반환한다."""
    svc = SnsPostingService(session)
    return await svc.get_dashboard()
