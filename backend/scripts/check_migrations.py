"""마이그레이션 누락 검증 스크립트

모델에 정의된 테이블/컬럼과 alembic 마이그레이션 체인이 동기화되어 있는지 검사.
autogenerate diff가 있으면 exit 1 → 푸시 차단.

사용법:
  cd backend
  python scripts/check_migrations.py
"""

import subprocess
import sys


def main():
    # alembic check — autogenerate diff가 있으면 exit 1
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("✓ 모델과 마이그레이션이 동기화되어 있습니다.")
        sys.exit(0)

    # diff 발견
    print("✗ 마이그레이션 누락 감지!")
    print()
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    print()
    print("해결 방법:")
    print("  cd backend")
    print('  alembic revision --autogenerate -m "변경 내용 설명"')
    print("  생성된 파일 검토 후 커밋에 포함")
    sys.exit(1)


if __name__ == "__main__":
    main()
