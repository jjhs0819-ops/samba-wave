"""WordPress REST API v2 클라이언트 — Application Password(Basic Auth) 인증 방식."""

from __future__ import annotations

import base64
from typing import Optional

import httpx

from backend.utils.logger import logger


class WordPressClient:
    """WordPress REST API v2 비동기 클라이언트.

    인증 방식: Application Password (Basic Auth, base64 인코딩).
    """

    def __init__(self, site_url: str, username: str, app_password: str) -> None:
        # 후행 슬래시 제거 후 API 베이스 URL 구성
        self.site_url = site_url.rstrip('/')
        self.api_url = f'{self.site_url}/wp-json/wp/v2'

        # Basic Auth 헤더 — "username:app_password" 를 base64 인코딩
        credentials = f'{username}:{app_password}'
        encoded = base64.b64encode(credentials.encode()).decode()
        self._auth_header = f'Basic {encoded}'

        self._client = httpx.AsyncClient(
            timeout=30,
            headers={
                'Authorization': self._auth_header,
                'Accept': 'application/json',
            },
        )

    # ------------------------------------------------------------------
    # 연결 테스트
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict:
        """WordPress 사이트 연결 및 인증 상태를 확인한다.

        Returns:
            성공: {"ok": True, "name": 사이트명, "url": 사이트주소}
            실패: {"ok": False, "error": 오류메시지}
        """
        try:
            resp = await self._client.get(f'{self.site_url}/wp-json')
            resp.raise_for_status()
            data = resp.json()
            return {
                'ok': True,
                'name': data.get('name', ''),
                'url': data.get('url', self.site_url),
            }
        except httpx.HTTPStatusError as e:
            logger.warning('WordPress 연결 실패 (HTTP %s): %s', e.response.status_code, e)
            return {'ok': False, 'error': f'HTTP {e.response.status_code}'}
        except Exception as e:
            logger.warning('WordPress 연결 오류: %s', e)
            return {'ok': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # 포스트 작성
    # ------------------------------------------------------------------

    async def create_post(
        self,
        title: str,
        content: str,
        status: str = 'publish',
        categories: Optional[list[int]] = None,
        tags: Optional[list[str]] = None,
        excerpt: Optional[str] = None,
        featured_media: Optional[int] = None,
    ) -> dict:
        """WordPress 포스트를 생성한다.

        Args:
            title: 포스트 제목
            content: 포스트 본문 (HTML 가능)
            status: 발행 상태 ("publish" | "draft" | "pending" 등)
            categories: 카테고리 ID 목록
            tags: 태그 이름 목록 (이름 → ID 자동 변환)
            excerpt: 요약문
            featured_media: 대표 이미지 미디어 ID

        Returns:
            {"id": 포스트ID, "link": URL, "status": 상태}
        """
        # 태그 이름 → ID 변환
        tag_ids: list[int] = []
        if tags:
            tag_ids = await self._ensure_tags(tags)

        payload: dict = {
            'title': title,
            'content': content,
            'status': status,
        }
        if categories:
            payload['categories'] = categories
        if tag_ids:
            payload['tags'] = tag_ids
        if excerpt is not None:
            payload['excerpt'] = excerpt
        if featured_media is not None:
            payload['featured_media'] = featured_media

        resp = await self._client.post(f'{self.api_url}/posts', json=payload)
        resp.raise_for_status()
        data = resp.json()

        return {
            'id': data['id'],
            'link': data.get('link', ''),
            'status': data.get('status', status),
        }

    # ------------------------------------------------------------------
    # 카테고리 조회/생성
    # ------------------------------------------------------------------

    async def get_or_create_category(self, name: str) -> int:
        """카테고리 이름으로 ID를 조회하고, 없으면 새로 생성한다.

        Args:
            name: 카테고리 이름

        Returns:
            카테고리 ID
        """
        # 기존 카테고리 검색
        resp = await self._client.get(
            f'{self.api_url}/categories',
            params={'search': name, 'per_page': 10},
        )
        resp.raise_for_status()
        results = resp.json()

        # 이름이 정확히 일치하는 카테고리 탐색
        for cat in results:
            if cat.get('name', '').lower() == name.lower():
                return cat['id']

        # 없으면 신규 생성
        create_resp = await self._client.post(
            f'{self.api_url}/categories',
            json={'name': name},
        )
        create_resp.raise_for_status()
        return create_resp.json()['id']

    # ------------------------------------------------------------------
    # 태그 이름 → ID 변환 (내부 헬퍼)
    # ------------------------------------------------------------------

    async def _ensure_tags(self, tag_names: list[str]) -> list[int]:
        """태그 이름 목록을 ID 목록으로 변환한다. 없는 태그는 자동 생성.

        Args:
            tag_names: 태그 이름 목록 (최대 10개까지 처리)

        Returns:
            태그 ID 목록
        """
        # 최대 10개로 제한
        tag_names = tag_names[:10]
        tag_ids: list[int] = []

        for name in tag_names:
            name = name.strip()
            if not name:
                continue

            # 기존 태그 검색
            resp = await self._client.get(
                f'{self.api_url}/tags',
                params={'search': name, 'per_page': 10},
            )
            resp.raise_for_status()
            results = resp.json()

            matched_id: Optional[int] = None
            for tag in results:
                if tag.get('name', '').lower() == name.lower():
                    matched_id = tag['id']
                    break

            if matched_id is None:
                # 태그 신규 생성
                create_resp = await self._client.post(
                    f'{self.api_url}/tags',
                    json={'name': name},
                )
                create_resp.raise_for_status()
                matched_id = create_resp.json()['id']

            tag_ids.append(matched_id)

        return tag_ids

    # ------------------------------------------------------------------
    # 미디어 업로드
    # ------------------------------------------------------------------

    async def upload_media(self, image_bytes: bytes, filename: str) -> Optional[int]:
        """이미지 바이트를 WordPress 미디어 라이브러리에 업로드한다.

        Args:
            image_bytes: 이미지 바이너리 데이터
            filename: 저장할 파일명 (확장자 포함, 예: "product.jpg")

        Returns:
            업로드된 미디어 ID, 실패 시 None
        """
        # MIME 타입 추론 (단순 확장자 기반)
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
        mime_map: dict[str, str] = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp',
        }
        content_type = mime_map.get(ext, 'application/octet-stream')

        try:
            resp = await self._client.post(
                f'{self.api_url}/media',
                content=image_bytes,
                headers={
                    'Content-Type': content_type,
                    'Content-Disposition': f'attachment; filename="{filename}"',
                },
            )
            resp.raise_for_status()
            return resp.json()['id']
        except httpx.HTTPStatusError as e:
            logger.warning('미디어 업로드 실패 (HTTP %s): %s', e.response.status_code, e)
            return None
        except Exception as e:
            logger.warning('미디어 업로드 오류: %s', e)
            return None

    # ------------------------------------------------------------------
    # 리소스 정리
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """httpx AsyncClient를 종료한다."""
        await self._client.aclose()
