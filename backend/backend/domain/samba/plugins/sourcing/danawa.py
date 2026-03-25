"""다나와 소싱처 플러그인 (스텁)."""

import logging
from typing import TYPE_CHECKING

from backend.domain.samba.plugins.sourcing.stub import GenericStubPlugin

if TYPE_CHECKING:
    from backend.domain.samba.collector.refresher import RefreshResult

logger = logging.getLogger(__name__)


class DanawaPlugin(GenericStubPlugin):
    """다나와 소싱처 플러그인.

    가격비교 사이트 — 최저가/옵션/스펙 수집 예정.
    """

    site_name = "DANAWA"
    concurrency = 3
    request_interval = 1.0
