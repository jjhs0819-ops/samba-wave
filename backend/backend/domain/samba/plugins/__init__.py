import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

MARKET_PLUGINS: dict[str, "MarketPlugin"] = {}  # noqa: F821
SOURCING_PLUGINS: dict[str, "SourcingPlugin"] = {}  # noqa: F821
# 플러그인에서 자동 생성 — market_type → policy_key (한글 표시명)
MARKET_TYPE_TO_POLICY_KEY: dict[str, str] = {}


def discover_plugins():
    """플러그인 자동 탐색 및 등록."""
    from .market_base import MarketPlugin
    from .sourcing_base import SourcingPlugin

    # 마켓 플러그인 탐색
    markets_dir = Path(__file__).parent / "markets"
    for _, name, _ in pkgutil.iter_modules([str(markets_dir)]):
        try:
            mod = importlib.import_module(f".markets.{name}", package=__package__)
        except Exception as e:
            logger.warning(f"[플러그인] markets/{name} 로드 실패 — 스킵: {e}")
            continue
        for attr in dir(mod):
            cls = getattr(mod, attr)
            if (
                isinstance(cls, type)
                and issubclass(cls, MarketPlugin)
                and cls is not MarketPlugin
                and hasattr(cls, "market_type")
            ):
                instance = cls()
                MARKET_PLUGINS[instance.market_type] = instance

    # 소싱 플러그인 탐색
    sourcing_dir = Path(__file__).parent / "sourcing"
    for _, name, _ in pkgutil.iter_modules([str(sourcing_dir)]):
        try:
            mod = importlib.import_module(f".sourcing.{name}", package=__package__)
        except Exception as e:
            logger.warning(f"[플러그인] sourcing/{name} 로드 실패 — 스킵: {e}")
            continue
        for attr in dir(mod):
            cls = getattr(mod, attr)
            if (
                isinstance(cls, type)
                and issubclass(cls, SourcingPlugin)
                and cls is not SourcingPlugin
                and hasattr(cls, "site_name")
            ):
                instance = cls()
                SOURCING_PLUGINS[instance.site_name] = instance

    # market_type → policy_key 매핑 자동 생성
    MARKET_TYPE_TO_POLICY_KEY.clear()
    for mt, plugin in MARKET_PLUGINS.items():
        if hasattr(plugin, "policy_key") and plugin.policy_key:
            MARKET_TYPE_TO_POLICY_KEY[mt] = plugin.policy_key

    logger.info(
        f"[플러그인] 마켓 {len(MARKET_PLUGINS)}개, 소싱 {len(SOURCING_PLUGINS)}개 등록 완료"
    )


discover_plugins()
