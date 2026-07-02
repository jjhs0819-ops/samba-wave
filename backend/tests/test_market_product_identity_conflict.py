"""#534 회귀테스트 — 마켓 상품 identity 충돌(같은 account+상품번호를 다른 cp 2개 점유).

배경:
- `samba_collected_product.market_product_nos` = {account_id: product_no}.
- 서로 다른 수집상품(cp) 2개가 같은 (account_id, product_no)를 가지면
  판매링크가 가리키는 상품 ≠ 주문 소싱이 가리키는 상품 → 오연결·원가/수익 오차 사고.
  (실사고: ABCmart 1010115077(black,79,900) / 1010115078(lime,55,000) 두 cp가
   같은 롯데홈 계정+상품번호 3345477663 에 매핑 → 고객은 black 보고 주문했으나
   소싱은 lime 을 가리킴, cost 31,250 오차.)

수정(A):
- `_index_mpn_row`: by_account 정확 인덱스에서 다른 cp 가 같은 (account,no) 점유 시
  entry["ambiguous"]=True 표시.
- 주문 매칭 step1(by_account): ambiguous 면 자동매칭 보류(오연결 방지) + 경고 로그.
- /link 엔드포인트: 복수 cp 점유 상품번호는 mpn_map 에서 제외.

테스트 방식:
- order.py 는 모듈 최상단 순환참조로 cold import 불가(다른 order 테스트와 동일 제약).
  → 소스 정적 계약 검증으로 fix 라인 제거/변형 회귀 PR 을 차단한다.
"""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ORDER_PY = BACKEND_ROOT / "backend/api/v1/routers/samba/order.py"


def _src() -> str:
    return ORDER_PY.read_text(encoding="utf-8")


class TestByAccountAmbiguityFlag:
    """by_account 정확 인덱스가 다른 cp 충돌을 ambiguous 로 표시."""

    def test_conflict_marks_ambiguous(self) -> None:
        src = _src()
        idx = src.find("_existing_acc = by_account.get(_acc_key)")
        assert idx != -1, "by_account 정확 인덱스 빌드 블록 미발견"
        block = src[idx : idx + 1500]
        assert '_existing_acc["ambiguous"] = True' in block, (
            "#534 회귀 — 다른 cp 가 같은 (account,no) 점유 시 ambiguous 표시 누락 "
            "(오연결 방지 가드 제거됨)"
        )

    def test_same_cp_reindex_preserves_ambiguous(self) -> None:
        """같은 cp 재반영 시 기존 ambiguous 플래그가 유실되면 안 됨."""
        src = _src()
        assert "_prev_ambig = bool(_existing_acc and _existing_acc.get(" in src, (
            "#534 회귀 — 증분 재반영 시 ambiguous 플래그 보존 로직 누락"
        )


class TestOrderMatchByAccountGuard:
    """주문 매칭 step1(by_account)이 ambiguous 를 거부."""

    def test_step1_has_ambiguous_guard(self) -> None:
        src = _src()
        idx = src.find('_cand = _mpn_by_account.get(f"{_ch_id}:{_pid}")')
        assert idx != -1, "step1 by_account 매칭 블록 미발견"
        block = src[idx : idx + 400]
        assert 'not _cand.get("ambiguous")' in block, (
            "#534 회귀 — step1 정확매칭에 ambiguous 가드 누락 → 충돌 시 오연결"
        )


class TestLinkEndpointConflictExclusion:
    """/link 엔드포인트가 복수 cp 점유 상품번호를 매핑서 제외."""

    def test_link_excludes_conflicts(self) -> None:
        src = _src()
        assert "_mpn_conflicts" in src, (
            "#534 회귀 — /link 충돌 상품번호 제외 로직 누락 (last-wins 오연결 복귀)"
        )
        assert "mpn_map.pop(_ck, None)" in src, "#534 회귀 — 충돌 키 제거 누락"


class TestIssueReferenced:
    def test_issue_number_in_comments(self) -> None:
        src = _src()
        assert src.count("#534") >= 3, "#534 출처 주석 누락 — 추후 제거 PR 맥락 보존용"
