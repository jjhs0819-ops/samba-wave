"""ESM Plus 지마켓/옥션 카테고리 매핑 빌더.

전체 카테고리 트리를 수집하고 이름경로 기반으로 옥션↔지마켓 매핑 테이블을 생성한다.

실행:
  cd backend
  python -m scripts.build_esm_categories

소요 시간: 약 20~30분 (API rate limit 대응)
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main():
  from backend.domain.samba.proxy.esmplus import ESMPlusClient

  # 설정
  HOSTING_ID = "hlccorp"
  SECRET_KEY = "M2U0NWFhMmYtZGY0MS00Yjdk"
  SELLER_ID = "unclehg"
  DELAY = 0.5  # API 호출 간격 (초)

  print("=" * 60)
  print("ESM Plus 카테고리 매핑 빌더")
  print("=" * 60)

  # 지마켓 트리 수집
  print("\n[1/4] 지마켓 카테고리 수집 시작...")
  t0 = time.time()
  g_client = ESMPlusClient(HOSTING_ID, SECRET_KEY, SELLER_ID, site="gmarket")
  g_tree = await g_client.fetch_category_tree(delay=DELAY)
  g_time = time.time() - t0
  print(f"  → 지마켓: {len(g_tree)}개 leaf 카테고리 ({g_time:.0f}초)")

  # 옥션 트리 수집
  print("\n[2/4] 옥션 카테고리 수집 시작...")
  t0 = time.time()
  a_client = ESMPlusClient(HOSTING_ID, SECRET_KEY, SELLER_ID, site="auction")
  a_tree = await a_client.fetch_category_tree(delay=DELAY)
  a_time = time.time() - t0
  print(f"  → 옥션: {len(a_tree)}개 leaf 카테고리 ({a_time:.0f}초)")

  # 매핑 생성 (이름경로 기반)
  print("\n[3/4] 이름경로 기반 매핑 생성...")

  # 역방향 맵: code → path
  g_code_to_path = {code: path for path, code in g_tree.items()}
  a_code_to_path = {code: path for path, code in a_tree.items()}

  # 옥션→지마켓 매핑
  a2g: dict[str, str] = {}
  for path, a_code in a_tree.items():
    if path in g_tree:
      a2g[a_code] = g_tree[path]

  # 지마켓→옥션 매핑
  g2a: dict[str, str] = {}
  for path, g_code in g_tree.items():
    if path in a_tree:
      g2a[g_code] = a_tree[path]

  # 통계
  total_a = len(a_tree)
  total_g = len(g_tree)
  matched = len(a2g)
  print(f"  → 옥션→지마켓: {matched}/{total_a} 매핑 ({matched/total_a*100:.1f}%)")
  print(f"  → 지마켓→옥션: {len(g2a)}/{total_g} 매핑 ({len(g2a)/total_g*100:.1f}%)")

  # 매핑 안 되는 카테고리 샘플
  unmatched_a = [path for path in a_tree if path not in g_tree]
  if unmatched_a:
    print(f"\n  매핑 안 되는 옥션 카테고리 (상위 10개):")
    for p in unmatched_a[:10]:
      print(f"    - {p}")

  # 파일 저장
  print("\n[4/4] 결과 저장...")
  output_dir = Path(__file__).resolve().parent.parent / "backend" / "domain" / "samba" / "category"

  # 지마켓 트리
  g_file = output_dir / "esm_gmarket_cats.json"
  with open(g_file, "w", encoding="utf-8") as f:
    json.dump(g_tree, f, ensure_ascii=False, indent=2)
  print(f"  → {g_file.name}: {len(g_tree)}개")

  # 옥션 트리
  a_file = output_dir / "esm_auction_cats.json"
  with open(a_file, "w", encoding="utf-8") as f:
    json.dump(a_tree, f, ensure_ascii=False, indent=2)
  print(f"  → {a_file.name}: {len(a_tree)}개")

  # 옥션→지마켓 매핑
  a2g_file = output_dir / "esm_auction_to_gmarket.json"
  with open(a2g_file, "w", encoding="utf-8") as f:
    json.dump(a2g, f, ensure_ascii=False, indent=2)
  print(f"  → {a2g_file.name}: {len(a2g)}개")

  # 지마켓→옥션 매핑
  g2a_file = output_dir / "esm_gmarket_to_auction.json"
  with open(g2a_file, "w", encoding="utf-8") as f:
    json.dump(g2a, f, ensure_ascii=False, indent=2)
  print(f"  → {g2a_file.name}: {len(g2a)}개")

  print("\n" + "=" * 60)
  print(f"완료! 총 소요 시간: {g_time + a_time:.0f}초")
  print("=" * 60)

  # DB 저장 안내
  print("\nDB 저장은 백엔드 서버에서 API로 호출하세요:")
  print("  POST /api/v1/samba/category/esm/build")


if __name__ == "__main__":
  asyncio.run(main())
