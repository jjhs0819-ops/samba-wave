"""Windows 호환 스킬 트리거 평가 스크립트.

run_eval.py의 select.select()가 Windows에서 소켓 전용이라 WinError 10038 발생.
이 스크립트는 subprocess.communicate()로 대체하여 Windows에서도 동작한다.
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

SKILL_PATH = Path("C:/Users/canno/workspace/samba-wave/skills/order-collector")
PROJECT_ROOT = Path("C:/Users/canno/workspace/samba-wave")
EVAL_SET_PATH = Path("C:/Users/canno/workspace/samba-wave/skills/order-collector-workspace/trigger-eval.json")
MODEL = "claude-opus-4-6"
TIMEOUT = 45  # 초


def parse_skill_description(skill_path: Path) -> tuple[str, str]:
    """SKILL.md에서 name과 description 추출."""
    content = (skill_path / "SKILL.md").read_text(encoding="utf-8")
    name = ""
    desc = ""
    in_frontmatter = False
    in_desc = False
    desc_lines = []

    for line in content.split("\n"):
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            else:
                break
        if in_frontmatter:
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("description:"):
                in_desc = True
                rest = line.split(":", 1)[1].strip()
                if rest and rest != ">":
                    desc_lines.append(rest)
            elif in_desc and (line.startswith("  ") or line.startswith("\t")):
                desc_lines.append(line.strip())
            else:
                in_desc = False

    desc = " ".join(desc_lines)
    return name, desc


def run_single_query(query: str, skill_name: str, description: str) -> bool:
    """단일 쿼리를 claude -p로 실행하여 스킬 트리거 여부 확인.

    Windows 호환: subprocess.communicate() 사용 (select.select 대신).
    """
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name}-skill-{unique_id}"
    commands_dir = PROJECT_ROOT / ".claude" / "commands"
    command_file = commands_dir / f"{clean_name}.md"

    try:
        commands_dir.mkdir(parents=True, exist_ok=True)
        indented_desc = "\n  ".join(description.split("\n"))
        command_content = (
            f"---\n"
            f"description: |\n"
            f"  {indented_desc}\n"
            f"---\n\n"
            f"# {skill_name}\n\n"
            f"This skill handles: {description}\n"
        )
        command_file.write_text(command_content, encoding="utf-8")

        cmd = [
            "claude",
            "-p", query,
            "--output-format", "json",
            "--model", MODEL,
        ]

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=str(PROJECT_ROOT),
            env=env,
        )

        output = result.stdout
        # JSON 출력에서 tool_use 확인
        try:
            data = json.loads(output)
            # result 형식: {"type": "result", "result": "...", ...}
            result_text = str(data.get("result", ""))
            # Skill 도구 호출 또는 Read 도구로 스킬 파일 읽기 시도 확인
            if clean_name in output or skill_name in output:
                return True
            return False
        except json.JSONDecodeError:
            # 텍스트 출력에서 스킬 이름 검색
            return clean_name in output or f"/{skill_name}" in output

    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT: {query[:50]}...", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)
        return False
    finally:
        if command_file.exists():
            command_file.unlink()


def main():
    eval_set = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    name, description = parse_skill_description(SKILL_PATH)

    print(f"스킬: {name}")
    print(f"설명: {description[:80]}...")
    print(f"평가 쿼리: {len(eval_set)}개")
    print("=" * 60)

    results = []
    correct = 0

    for i, item in enumerate(eval_set):
        query = item["query"]
        should_trigger = item["should_trigger"]
        expected_label = "TRIGGER" if should_trigger else "NO-TRIGGER"

        print(f"\n[{i+1}/{len(eval_set)}] {expected_label}: {query[:60]}...")
        triggered = run_single_query(query, name, description)
        actual_label = "TRIGGERED" if triggered else "NOT-TRIGGERED"

        passed = (triggered == should_trigger)
        if passed:
            correct += 1
            status = "PASS"
        else:
            status = "FAIL"

        print(f"  → {actual_label} [{status}]")

        results.append({
            "query": query,
            "should_trigger": should_trigger,
            "triggered": triggered,
            "passed": passed,
        })

    print("\n" + "=" * 60)
    print(f"결과: {correct}/{len(eval_set)} 통과 ({correct/len(eval_set)*100:.0f}%)")

    should_trigger_items = [r for r in results if r["should_trigger"]]
    should_not_items = [r for r in results if not r["should_trigger"]]

    tp = sum(1 for r in should_trigger_items if r["triggered"])
    fn = sum(1 for r in should_trigger_items if not r["triggered"])
    tn = sum(1 for r in should_not_items if not r["triggered"])
    fp = sum(1 for r in should_not_items if r["triggered"])

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0

    print(f"Precision: {precision:.0%} | Recall: {recall:.0%}")
    print(f"True Positive: {tp} | False Negative: {fn}")
    print(f"True Negative: {tn} | False Positive: {fp}")

    # 결과 저장
    output_path = EVAL_SET_PATH.parent / "trigger-eval-results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "skill_name": name,
            "description": description,
            "total": len(eval_set),
            "correct": correct,
            "accuracy": correct / len(eval_set),
            "precision": precision,
            "recall": recall,
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    main()
