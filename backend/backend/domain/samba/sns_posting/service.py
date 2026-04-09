"""SNS 자동 포스팅 서비스 — 워드프레스 연동 + 이슈 크롤링 + AI 글생성 통합."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.utils.logger import logger
from backend.domain.samba.sns_posting.model import (
    SambaSnKeywordGroup,
    SambaSnsAutoConfig,
    SambaSnsPost,
    SambaWpSite,
)
from backend.domain.samba.sns_posting.ai_writer import AiWriter
from backend.domain.samba.sns_posting.issue_crawler import IssueCrawler
from backend.domain.samba.sns_posting.wordpress import WordPressClient


class SnsPostingService:
    """SNS 자동 포스팅 서비스.

    워드프레스 사이트 연결, 키워드 그룹 관리, 이슈 크롤링,
    AI 글생성 후 워드프레스 발행까지 통합 처리.
    """

    def __init__(self, session: AsyncSession) -> None:
        # DB 세션 및 외부 의존성 초기화
        self._session = session
        self._crawler = IssueCrawler()
        self._writer: AiWriter | None = None

    async def _get_writer(self) -> AiWriter:
        """Gemma API 키를 로드하여 AiWriter 초기화."""
        if self._writer is None:
            from backend.domain.samba.ai.gemma_client import _get_gemma_api_key

            api_key = await _get_gemma_api_key(self._session)
            self._writer = AiWriter(api_key=api_key)
        return self._writer

    # ------------------------------------------------------------------
    # 워드프레스 사이트 관리
    # ------------------------------------------------------------------

    async def connect_wp(
        self,
        site_url: str,
        username: str,
        app_password: str,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """워드프레스 사이트 연결 테스트 후 DB에 저장한다.

        Args:
            site_url: 워드프레스 사이트 URL
            username: 워드프레스 사용자명
            app_password: Application Password
            tenant_id: 테넌트 ID (멀티테넌시)

        Returns:
            {"ok": True, "site": SambaWpSite} 또는 {"ok": False, "error": 오류메시지}
        """
        client = WordPressClient(site_url, username, app_password)
        try:
            result = await client.test_connection()
        finally:
            await client.close()

        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "연결 실패")}

        # 사이트 정보 DB 저장
        site = SambaWpSite(
            site_url=site_url,
            username=username,
            app_password=app_password,
            site_name=result.get("name", ""),
            tenant_id=tenant_id,
            status="active",
        )
        self._session.add(site)
        await self._session.commit()
        await self._session.refresh(site)

        logger.info("[SnsPostingService] 워드프레스 사이트 연결 성공: %s", site_url)
        return {"ok": True, "site": site}

    async def list_wp_sites(self, tenant_id: Optional[str] = None) -> List[SambaWpSite]:
        """등록된 워드프레스 사이트 목록을 반환한다.

        Args:
            tenant_id: 테넌트 ID (None이면 전체 조회)

        Returns:
            SambaWpSite 목록
        """
        stmt = select(SambaWpSite).order_by(SambaWpSite.created_at.desc())  # type: ignore[attr-defined]
        if tenant_id is not None:
            stmt = stmt.where(SambaWpSite.tenant_id == tenant_id)
        result = await self._session.exec(stmt)
        return list(result.all())

    # ------------------------------------------------------------------
    # 키워드 그룹 관리
    # ------------------------------------------------------------------

    async def save_keyword_group(
        self,
        name: str,
        category: str,
        keywords: List[str],
        tenant_id: Optional[str] = None,
    ) -> SambaSnKeywordGroup:
        """키워드 그룹을 생성하고 저장한다.

        Args:
            name: 그룹 이름
            category: 카테고리 (예: tech, fashion 등)
            keywords: 키워드 목록
            tenant_id: 테넌트 ID

        Returns:
            저장된 SambaSnKeywordGroup
        """
        group = SambaSnKeywordGroup(
            name=name,
            category=category,
            keywords=keywords,
            tenant_id=tenant_id,
            is_active=True,
        )
        self._session.add(group)
        await self._session.commit()
        await self._session.refresh(group)

        logger.info("[SnsPostingService] 키워드 그룹 저장: %s (%s)", name, category)
        return group

    async def list_keyword_groups(
        self, tenant_id: Optional[str] = None
    ) -> List[SambaSnKeywordGroup]:
        """키워드 그룹 목록을 반환한다.

        Args:
            tenant_id: 테넌트 ID (None이면 전체 조회)

        Returns:
            SambaSnKeywordGroup 목록
        """
        stmt = select(SambaSnKeywordGroup).order_by(
            SambaSnKeywordGroup.created_at.desc()
        )  # type: ignore[attr-defined]
        if tenant_id is not None:
            stmt = stmt.where(SambaSnKeywordGroup.tenant_id == tenant_id)
        result = await self._session.exec(stmt)
        return list(result.all())

    async def delete_keyword_group(self, group_id: str) -> bool:
        """키워드 그룹을 삭제한다.

        Args:
            group_id: 삭제할 그룹 ID

        Returns:
            삭제 성공 여부
        """
        stmt = select(SambaSnKeywordGroup).where(SambaSnKeywordGroup.id == group_id)
        result = await self._session.exec(stmt)
        group = result.first()
        if group is None:
            return False

        await self._session.delete(group)
        await self._session.commit()
        logger.info("[SnsPostingService] 키워드 그룹 삭제: %s", group_id)
        return True

    # ------------------------------------------------------------------
    # 이슈 검색
    # ------------------------------------------------------------------

    async def search_issues(
        self,
        category: str,
        keywords: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """카테고리와 키워드로 이슈를 검색한다.

        Args:
            category: 이슈 카테고리
            keywords: 직접 지정할 키워드 목록 (None이면 기본 키워드 사용)

        Returns:
            이슈 목록 [{"title", "link", "pub_date", "description"}, ...]
        """
        issues = await self._crawler.search_issues(
            category=category,
            keywords=keywords,
        )
        return issues

    # ------------------------------------------------------------------
    # 글 생성 및 발행
    # ------------------------------------------------------------------

    async def generate_and_publish(
        self,
        wp_site_id: str,
        issue: Dict[str, Any],
        category: str,
        language: str = "ko",
        product_info: Optional[Dict[str, Any]] = None,
        product_banner_html: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """AI로 글을 생성하고 워드프레스에 발행 후 이력을 저장한다.

        Args:
            wp_site_id: 워드프레스 사이트 ID
            issue: 이슈 딕셔너리 {"title", "link", "description"}
            category: 글 카테고리
            language: 언어 코드 (기본: "ko")
            product_info: 상품 정보 (상품 추천 섹션 생성용)
            product_banner_html: 커스텀 배너 HTML (본문 하단에 삽입)
            tenant_id: 테넌트 ID

        Returns:
            {"ok": True, "post_id": WP포스트ID, "link": URL} 또는 {"ok": False, "error": 오류}
        """
        # 워드프레스 사이트 조회
        stmt = select(SambaWpSite).where(SambaWpSite.id == wp_site_id)
        result = await self._session.exec(stmt)
        wp_site = result.first()
        if wp_site is None:
            return {"ok": False, "error": f"사이트 없음: {wp_site_id}"}

        issue_title = issue.get("title", "")
        issue_description = issue.get("description", "")
        source_url = issue.get("link", "")

        # AI 글 생성
        try:
            writer = await self._get_writer()
            post_data = await writer.generate_post(
                issue_title=issue_title,
                issue_description=issue_description,
                category=category,
                language=language,
                product_info=product_info,
            )
        except Exception as e:
            logger.error("[SnsPostingService] AI 글 생성 실패: %s", e)
            return {"ok": False, "error": f"AI 글 생성 실패: {e}"}

        title = post_data.get("title", issue_title)
        content = post_data.get("content", "")
        tags = post_data.get("tags", [])
        excerpt = post_data.get("excerpt", "")

        # 상품 배너 HTML 삽입 (본문 하단)
        if product_banner_html:
            content = f"{content}\n{product_banner_html}"

        # 워드프레스 발행
        client = WordPressClient(
            wp_site.site_url,
            wp_site.username,
            wp_site.app_password,
        )
        try:
            # 카테고리 ID 확보
            cat_id = await client.get_or_create_category(category)
            wp_result = await client.create_post(
                title=title,
                content=content,
                status="publish",
                categories=[cat_id],
                tags=tags,
                excerpt=excerpt,
            )
            wp_post_id = wp_result.get("id")
            post_link = wp_result.get("link", "")
        except Exception as e:
            logger.error("[SnsPostingService] 워드프레스 발행 실패: %s", e)
            # 발행 실패 이력 저장
            failed_post = SambaSnsPost(
                tenant_id=tenant_id,
                wp_site_id=wp_site_id,
                title=title,
                content=content,
                category=category,
                source_url=source_url,
                language=language,
                status="failed",
            )
            self._session.add(failed_post)
            await self._session.commit()
            return {"ok": False, "error": f"워드프레스 발행 실패: {e}"}
        finally:
            await client.close()

        # 발행 성공 이력 저장
        sns_post = SambaSnsPost(
            tenant_id=tenant_id,
            wp_site_id=wp_site_id,
            wp_post_id=wp_post_id,
            title=title,
            content=content,
            category=category,
            source_url=source_url,
            language=language,
            status="published",
            published_at=datetime.now(tz=timezone.utc),
        )
        self._session.add(sns_post)
        await self._session.commit()

        logger.info("[SnsPostingService] 발행 성공: %s → %s", title[:40], post_link)
        return {"ok": True, "post_id": wp_post_id, "link": post_link, "title": title}

    # ------------------------------------------------------------------
    # 자동 포스팅 스트리밍
    # ------------------------------------------------------------------

    async def auto_posting_stream(
        self,
        wp_site_id: str,
        tenant_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """자동 포스팅 SSE 스트리밍 제너레이터.

        키워드 그룹을 순회하며 이슈 검색 → AI 글 생성 → 워드프레스 발행을 반복.
        SambaSnsAutoConfig 설정의 interval_minutes, max_daily_posts를 준수.

        Args:
            wp_site_id: 대상 워드프레스 사이트 ID
            tenant_id: 테넌트 ID

        Yields:
            SSE 형식 문자열 (log / success / fail / done / error 이벤트)
        """
        # 자동 포스팅 설정 조회
        cfg_stmt = select(SambaSnsAutoConfig).where(
            SambaSnsAutoConfig.wp_site_id == wp_site_id
        )
        if tenant_id is not None:
            cfg_stmt = cfg_stmt.where(SambaSnsAutoConfig.tenant_id == tenant_id)
        cfg_result = await self._session.exec(cfg_stmt)
        config = cfg_result.first()

        if config is None:
            yield self._sse(
                "error",
                {"message": "자동 포스팅 설정이 없습니다. 먼저 설정을 저장하세요."},
            )
            return

        # is_running 플래그 활성화
        config.is_running = True
        config.updated_at = datetime.now(tz=timezone.utc)
        self._session.add(config)
        await self._session.commit()

        yield self._sse("log", {"message": f"자동 포스팅 시작 — 사이트: {wp_site_id}"})

        interval_seconds = config.interval_minutes * 60
        max_daily = config.max_daily_posts
        language = config.language
        banner_html = (
            config.product_banner_html if config.include_product_banner else None
        )

        # 오늘 발행 수 초기화 (자정 기준)
        today_count = 0

        try:
            while True:
                # is_running 상태 재확인 (stop 요청 감지)
                await self._session.refresh(config)
                if not config.is_running:
                    yield self._sse("done", {"message": "자동 포스팅 중지됨"})
                    break

                # 일일 최대 발행 수 도달 확인
                if today_count >= max_daily:
                    yield self._sse(
                        "done",
                        {
                            "message": f"일일 최대 발행 수({max_daily}건) 도달. 자동 포스팅 종료."
                        },
                    )
                    config.is_running = False
                    config.updated_at = datetime.now(tz=timezone.utc)
                    self._session.add(config)
                    await self._session.commit()
                    break

                # 활성 키워드 그룹 조회
                kg_stmt = select(SambaSnKeywordGroup).where(
                    SambaSnKeywordGroup.is_active == True  # noqa: E712
                )
                if tenant_id is not None:
                    kg_stmt = kg_stmt.where(SambaSnKeywordGroup.tenant_id == tenant_id)
                kg_result = await self._session.exec(kg_stmt)
                keyword_groups = list(kg_result.all())

                if not keyword_groups:
                    yield self._sse(
                        "error", {"message": "활성 키워드 그룹이 없습니다."}
                    )
                    config.is_running = False
                    config.updated_at = datetime.now(tz=timezone.utc)
                    self._session.add(config)
                    await self._session.commit()
                    break

                # 키워드 그룹 순회
                for kg in keyword_groups:
                    # 루프마다 is_running 재확인
                    await self._session.refresh(config)
                    if not config.is_running:
                        break

                    yield self._sse(
                        "log", {"message": f"키워드 그룹 [{kg.name}] 이슈 검색 중..."}
                    )

                    # 이슈 검색
                    try:
                        issues = await self._crawler.search_issues(
                            category=kg.category,
                            keywords=list(kg.keywords) if kg.keywords else None,
                            max_results=5,
                        )
                    except Exception as e:
                        yield self._sse(
                            "log", {"message": f"이슈 검색 실패 [{kg.name}]: {e}"}
                        )
                        continue

                    if not issues:
                        yield self._sse(
                            "log",
                            {"message": f"[{kg.name}] 검색 결과 없음. 다음 그룹으로."},
                        )
                        continue

                    # 첫 번째 이슈로 글 생성 및 발행
                    issue = issues[0]
                    yield self._sse(
                        "log", {"message": f"글 생성 중: {issue['title'][:50]}"}
                    )

                    pub_result = await self.generate_and_publish(
                        wp_site_id=wp_site_id,
                        issue=issue,
                        category=kg.category,
                        language=language,
                        product_banner_html=banner_html,
                        tenant_id=tenant_id,
                    )

                    if pub_result.get("ok"):
                        today_count += 1
                        # today_count 업데이트
                        config.today_count = today_count
                        config.last_posted_at = datetime.now(tz=timezone.utc)
                        config.updated_at = datetime.now(tz=timezone.utc)
                        self._session.add(config)
                        await self._session.commit()

                        yield self._sse(
                            "success",
                            {
                                "message": f"발행 성공: {pub_result.get('title', '')[:40]}",
                                "link": pub_result.get("link", ""),
                                "today_count": today_count,
                            },
                        )
                    else:
                        yield self._sse(
                            "fail",
                            {
                                "message": f"발행 실패: {pub_result.get('error', '')}",
                            },
                        )

                    # 그룹 간 인터벌 대기
                    yield self._sse(
                        "log", {"message": f"{interval_seconds}초 대기 중..."}
                    )
                    await asyncio.sleep(interval_seconds)

                    # 일일 한도 재확인
                    if today_count >= max_daily:
                        break

        except asyncio.CancelledError:
            yield self._sse("done", {"message": "자동 포스팅 스트림 취소됨"})
        except Exception as e:
            logger.error("[SnsPostingService] auto_posting_stream 오류: %s", e)
            yield self._sse("error", {"message": f"자동 포스팅 오류: {e}"})
        finally:
            # 스트리밍 종료 시 is_running 해제
            try:
                await self._session.refresh(config)
                if config.is_running:
                    config.is_running = False
                    config.updated_at = datetime.now(tz=timezone.utc)
                    self._session.add(config)
                    await self._session.commit()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 발행 이력 조회
    # ------------------------------------------------------------------

    async def list_posts(
        self,
        page: int = 1,
        size: int = 50,
        status: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> List[SambaSnsPost]:
        """발행된 SNS 포스트 목록을 페이지네이션으로 반환한다.

        Args:
            page: 페이지 번호 (1부터)
            size: 페이지당 건수
            status: 상태 필터 (published / draft / failed)
            tenant_id: 테넌트 ID

        Returns:
            SambaSnsPost 목록
        """
        stmt = select(SambaSnsPost).order_by(SambaSnsPost.created_at.desc())  # type: ignore[attr-defined]
        if tenant_id is not None:
            stmt = stmt.where(SambaSnsPost.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(SambaSnsPost.status == status)

        offset = (page - 1) * size
        stmt = stmt.offset(offset).limit(size)

        result = await self._session.exec(stmt)
        return list(result.all())

    # ------------------------------------------------------------------
    # 대시보드
    # ------------------------------------------------------------------

    async def get_dashboard(self, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """자동 포스팅 대시보드 통계를 반환한다.

        Args:
            tenant_id: 테넌트 ID

        Returns:
            {"today_posts": 오늘발행수, "total_posts": 전체, "success_count": 성공,
             "success_rate": 성공률%, "is_running": 실행상태}
        """
        from sqlalchemy import func

        # 오늘 날짜 (UTC 기준)
        now_utc = datetime.now(tz=timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

        # 전체 포스트 수
        total_stmt = select(func.count()).select_from(SambaSnsPost)
        if tenant_id is not None:
            total_stmt = total_stmt.where(SambaSnsPost.tenant_id == tenant_id)
        total_result = await self._session.exec(total_stmt)
        total_posts = total_result.one()

        # 성공 포스트 수
        success_stmt = (
            select(func.count())
            .select_from(SambaSnsPost)
            .where(SambaSnsPost.status == "published")
        )
        if tenant_id is not None:
            success_stmt = success_stmt.where(SambaSnsPost.tenant_id == tenant_id)
        success_result = await self._session.exec(success_stmt)
        success_count = success_result.one()

        # 오늘 발행 수 (published_at 기준)
        today_stmt = (
            select(func.count())
            .select_from(SambaSnsPost)
            .where(SambaSnsPost.published_at >= today_start)
        )
        if tenant_id is not None:
            today_stmt = today_stmt.where(SambaSnsPost.tenant_id == tenant_id)
        today_result = await self._session.exec(today_stmt)
        today_posts = today_result.one()

        # 성공률 계산
        success_rate = (
            round(success_count / total_posts * 100, 1) if total_posts > 0 else 0.0
        )

        # 실행 상태 (하나라도 is_running=True인 설정이 있으면 True)
        running_stmt = select(SambaSnsAutoConfig).where(
            SambaSnsAutoConfig.is_running == True  # noqa: E712
        )
        if tenant_id is not None:
            running_stmt = running_stmt.where(SambaSnsAutoConfig.tenant_id == tenant_id)
        running_result = await self._session.exec(running_stmt)
        is_running = running_result.first() is not None

        return {
            "today_posts": today_posts,
            "total_posts": total_posts,
            "success_count": success_count,
            "success_rate": success_rate,
            "is_running": is_running,
        }

    # ------------------------------------------------------------------
    # 자동 포스팅 설정 저장
    # ------------------------------------------------------------------

    async def save_auto_config(
        self,
        wp_site_id: str,
        interval_minutes: int = 20,
        max_daily_posts: int = 150,
        language: str = "ko",
        include_product_banner: bool = True,
        product_banner_html: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> SambaSnsAutoConfig:
        """자동 포스팅 설정을 저장한다 (없으면 생성, 있으면 업데이트).

        Args:
            wp_site_id: 대상 워드프레스 사이트 ID
            interval_minutes: 포스팅 간격 (분)
            max_daily_posts: 일일 최대 발행 수
            language: 언어 코드
            include_product_banner: 상품 배너 포함 여부
            product_banner_html: 커스텀 배너 HTML
            tenant_id: 테넌트 ID

        Returns:
            저장된 SambaSnsAutoConfig
        """
        # 기존 설정 조회
        stmt = select(SambaSnsAutoConfig).where(
            SambaSnsAutoConfig.wp_site_id == wp_site_id
        )
        if tenant_id is not None:
            stmt = stmt.where(SambaSnsAutoConfig.tenant_id == tenant_id)
        result = await self._session.exec(stmt)
        config = result.first()

        if config is None:
            # 신규 생성
            config = SambaSnsAutoConfig(
                wp_site_id=wp_site_id,
                interval_minutes=interval_minutes,
                max_daily_posts=max_daily_posts,
                language=language,
                include_product_banner=include_product_banner,
                product_banner_html=product_banner_html,
                tenant_id=tenant_id,
                is_running=False,
            )
        else:
            # 기존 업데이트
            config.interval_minutes = interval_minutes
            config.max_daily_posts = max_daily_posts
            config.language = language
            config.include_product_banner = include_product_banner
            config.product_banner_html = product_banner_html
            config.updated_at = datetime.now(tz=timezone.utc)

        self._session.add(config)
        await self._session.commit()
        await self._session.refresh(config)

        logger.info("[SnsPostingService] 자동 포스팅 설정 저장: site=%s", wp_site_id)
        return config

    async def stop_auto_posting(
        self,
        wp_site_id: str,
        tenant_id: Optional[str] = None,
    ) -> bool:
        """자동 포스팅 중지 플래그를 설정한다.

        Args:
            wp_site_id: 워드프레스 사이트 ID
            tenant_id: 테넌트 ID

        Returns:
            설정 존재 여부
        """
        stmt = select(SambaSnsAutoConfig).where(
            SambaSnsAutoConfig.wp_site_id == wp_site_id
        )
        if tenant_id is not None:
            stmt = stmt.where(SambaSnsAutoConfig.tenant_id == tenant_id)
        result = await self._session.exec(stmt)
        config = result.first()

        if config is None:
            return False

        config.is_running = False
        config.updated_at = datetime.now(tz=timezone.utc)
        self._session.add(config)
        await self._session.commit()

        logger.info("[SnsPostingService] 자동 포스팅 중지: site=%s", wp_site_id)
        return True

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _sse(event: str, data: Dict[str, Any]) -> str:
        """SSE 형식 문자열을 생성한다.

        Args:
            event: 이벤트 타입 (log, success, fail, done, error 등)
            data: 전송할 데이터 딕셔너리

        Returns:
            "data: {...}\n\n" 형식의 SSE 문자열
        """
        return f"data: {json.dumps({**data, 'event': event}, ensure_ascii=False)}\n\n"
