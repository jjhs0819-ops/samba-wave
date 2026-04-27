"""그랜드스테이지 소싱처 플러그인.

GrandStage와 ABCmart는 동일 도메인(a-rt.com)이므로 AbcMartPlugin에 로직을 위임한다.
source_site="GrandStage"인 기존 DB 상품의 refresh 연결을 유지하기 위해 site_name만 별도 선언.
"""

from __future__ import annotations

from backend.domain.samba.plugins.sourcing.abcmart import AbcMartPlugin


class GrandStagePlugin(AbcMartPlugin):
    """그랜드스테이지 소싱처 플러그인 — AbcMartPlugin 위임."""

    site_name = "GrandStage"
