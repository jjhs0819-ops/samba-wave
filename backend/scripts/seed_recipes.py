"""AI 소싱 랭킹 수집 레시피를 로컬 DB에 삽입한다.

무신사 랭킹 스크래핑 방식 (background-sourcing.js 분석 결과):
- URL: https://www.musinsa.com/ranking/archive?date={YYYYMM}&categoryCode={code}&gf=A
- 수집 방식: 탭을 active로 열고 chrome.scripting.executeScript(world='MAIN') 실행
- DOM 파싱 전략:
  1. document.querySelectorAll('a[href*="/products/"]') → goodsNo 추출
  2. document.body.innerText 를 줄 단위로 파싱 → 순위(숫자 1~200) / 브랜드 / 상품명 / 가격 순서로 패턴 매칭
- 키워드 수집: https://www.musinsa.com/search 로 이동 → 검색창 클릭 후
  body.innerText 에서 "인기 검색어" / "급상승 검색어" 섹션 텍스트 파싱
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트(backend/)를 모듈 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.db.orm import get_write_session
from backend.domain.samba.sourcing_recipe.repository import SourcingRecipeRepository

# ──────────────────────────────────────────────
# 무신사 랭킹 레시피 스텝 정의
# extension/background-sourcing.js 의 handleAiSourcingJob('ranking') 로직 그대로 기술
# ──────────────────────────────────────────────
MUSINSA_RANKING_STEPS = [
    # 1. 랭킹 아카이브 페이지 열기 (확장앱이 active 탭으로 직접 오픈)
    {
        "type": "goto",
        "url": "https://www.musinsa.com/ranking/archive?date={{date}}&categoryCode={{categoryCode}}&gf=A",
        "note": "date=YYYYMM, categoryCode=000(전체) 등 — job 파라미터로 치환",
    },
    # 2. 페이지 렌더링 대기 (waitForTabLoad + 3초 여유)
    {
        "type": "wait",
        "ms": 3000,
        "note": "SPA 렌더링 완료 대기",
    },
    # 3. DOM 스크립트 실행 — world: MAIN (JS 변수 접근 가능)
    {
        "type": "evaluate",
        "resultKey": "items",
        "world": "MAIN",
        "expression": (
            "(() => {"
            "  const links = Array.from(document.querySelectorAll('a[href*=\"/products/\"]'));"
            "  const seen = new Set();"
            "  const goodsNos = [];"
            "  links.forEach(a => {"
            "    const m = a.href.match(/\\/products\\/(\\d+)/);"
            "    if (m && !seen.has(m[1])) { seen.add(m[1]); goodsNos.push(m[1]); }"
            "  });"
            "  const lines = document.body.innerText.split('\\n').map(l => l.trim()).filter(Boolean);"
            "  const items = [];"
            "  let i = 0;"
            "  while (i < lines.length && items.length < 200) {"
            "    const rankMatch = lines[i].match(/^(\\d{1,3})$/);"
            "    if (rankMatch) {"
            "      const rank = parseInt(rankMatch[1], 10);"
            "      if (rank >= 1 && rank <= 200) {"
            "        const brand = (lines[i+1] || '').length < 30 && !/[\\d,]+원|%/.test(lines[i+1] || '') ? lines[i+1] : '';"
            "        const nameIdx = brand ? i+2 : i+1;"
            "        const name = (lines[nameIdx] || '').length >= 3 && !/[\\d,]+원|%/.test(lines[nameIdx] || '') ? lines[nameIdx] : '';"
            "        let price = 0;"
            "        for (let j = nameIdx+1; j <= nameIdx+5 && j < lines.length; j++) {"
            "          const pm = lines[j].match(/([\\d,]+)원/);"
            "          if (pm) { price = parseInt(pm[1].replace(/,/g, ''), 10); break; }"
            "        }"
            "        const goodsNo = goodsNos[items.length] || '';"
            "        if (name) items.push({ rank, brand, name, price, goodsNo });"
            "      }"
            "    }"
            "    i++;"
            "  }"
            "  return items;"
            "})()"
        ),
    },
    # 4. 결과 전송 (확장앱 → 백엔드 POST)
    {
        "type": "post_result",
        "endpoint": "/api/v1/samba/ai-sourcing/collect-result",
        "body": {
            "requestId": "{{job.requestId}}",
            "type": "ranking",
            "data": {
                "items": "{{extracted_items}}",
                "debug": {
                    "title": "document.title",
                    "productLinks": "goodsNos.length",
                    "totalItems": "items.length",
                },
            },
        },
    },
]

# ──────────────────────────────────────────────
# 무신사 인기/급상승 키워드 레시피 스텝 정의
# extension/background-sourcing.js 의 handleAiSourcingJob('keywords') 로직 그대로 기술
# ──────────────────────────────────────────────
MUSINSA_KEYWORDS_STEPS = [
    # 1. 검색 페이지 열기 (active 탭 필요 — 인기검색어는 포커스 없으면 미표시)
    {
        "type": "goto",
        "url": "https://www.musinsa.com/search",
        "active": True,
        "note": "active:true 필수 — 검색창 클릭 이벤트가 포커스 없으면 무시됨",
    },
    # 2. 페이지 로드 대기
    {
        "type": "wait",
        "ms": 2000,
    },
    # 3. 검색 입력창 클릭 — 인기검색어 드롭다운 트리거
    {
        "type": "evaluate",
        "resultKey": "clickResult",
        "world": "MAIN",
        "expression": (
            "(() => {"
            "  const selectors = ["
            "    \"input[type='search']\","
            "    \"input[placeholder*='검색']\","
            "    \"input[name*='search']\","
            "    \"input[aria-label*='검색']\","
            "    '.search-bar input',"
            "    '#search-input',"
            "    'header input',"
            "    \"[class*='search'] button\","
            "    \"button[aria-label*='검색']\""
            "  ];"
            "  for (const sel of selectors) {"
            "    const el = document.querySelector(sel);"
            "    if (el) { el.focus(); el.click(); return sel; }"
            "  }"
            "  return null;"
            "})()"
        ),
    },
    # 4. 드롭다운 렌더링 대기
    {
        "type": "wait",
        "ms": 4000,
    },
    # 5. 키워드 추출
    {
        "type": "evaluate",
        "resultKey": "keywordItems",
        "world": "MAIN",
        "expression": (
            "(() => {"
            "  const text = document.body.innerText;"
            "  const results = [];"
            "  const popularMatch = text.match(/인기\\s*검색어([\\s\\S]*?)(?:급상승\\s*검색어|$)/);"
            "  const trendingMatch = text.match(/급상승\\s*검색어([\\s\\S]*?)(?:어바웃|회사|무신사 스토어|$)/);"
            "  const parseSection = (section, type) => {"
            "    if (!section) return;"
            "    section.split('\\n').forEach(line => {"
            "      const m = line.trim().match(/^(\\d{1,2})\\s+(.{2,30})$/);"
            "      if (m) results.push({ rank: parseInt(m[1], 10), keyword: m[2].trim(), type });"
            "    });"
            "  };"
            "  parseSection(popularMatch ? popularMatch[1] : null, 'popular');"
            "  parseSection(trendingMatch ? trendingMatch[1] : null, 'trending');"
            "  if (results.length === 0) {"
            "    const exclude = /MUSINSA|BEAUTY|SPORTS|OUTLET|BOUTIQUE|KICKS|KIDS|USED|SNAP/i;"
            "    document.querySelectorAll(\"li, [class*='keyword'], [class*='search-rank'], [class*='popular']\").forEach(el => {"
            "      const m = el.innerText.trim().match(/^(\\d{1,2})\\s*(.{2,25})$/);"
            "      if (m && !exclude.test(m[2]) && results.length < 20)"
            "        results.push({ rank: parseInt(m[1], 10), keyword: m[2].trim(), type: 'popular' });"
            "    });"
            "  }"
            "  return results;"
            "})()"
        ),
    },
    # 6. 결과 전송
    {
        "type": "post_result",
        "endpoint": "/api/v1/samba/ai-sourcing/collect-result",
        "body": {
            "requestId": "{{job.requestId}}",
            "type": "keywords",
            "data": {"keywordItems": "{{extracted_keywords}}"},
        },
    },
]


async def main() -> None:
    """레시피 2개를 DB에 upsert."""
    async with get_write_session() as session:
        repo = SourcingRecipeRepository(session)

        # 무신사 랭킹 레시피
        ranking = await repo.upsert(
            "musinsa_ranking",
            "1.0.0",
            MUSINSA_RANKING_STEPS,
        )
        print(f"[OK] {ranking.site_name} v{ranking.version} (id={ranking.id})")

        # 무신사 키워드 레시피
        keywords = await repo.upsert(
            "musinsa_keywords",
            "1.0.0",
            MUSINSA_KEYWORDS_STEPS,
        )
        print(f"[OK] {keywords.site_name} v{keywords.version} (id={keywords.id})")

    print("seed 완료.")


if __name__ == "__main__":
    asyncio.run(main())
