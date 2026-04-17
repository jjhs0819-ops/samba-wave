"""프로덕션 카테고리 매핑 학습 데이터.

export_mappings_to_rules.py 스크립트로 자동 생성됨. 직접 편집 금지.
소스코드를 공유받은 모든 테넌트가 이 룰을 즉시 활용 가능.

생성 일시: 미생성 (export 스크립트 실행 필요)
총 건수: 0
"""

# (source_site, target_market) → {source_category: target_category}
EXPORTED_RULES: dict[tuple[str, str], dict[str, str]] = {}
