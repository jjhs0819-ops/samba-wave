#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""카카오톡 '나에게 보내기' 배포 알림 헬퍼.

Git Bash(Windows)에서 한글을 쉘 변수로 전달하면 CP949로 깨지므로
모든 한글 라벨은 이 파일에 하드코딩하고, 쉘에서는 ASCII 인자만 전달한다.

사용법:
  python deploy/kakao_notify.py \
    --status success|fail \
    --sha <git-sha> \
    --branch <branch> \
    --message <"추가 메시지"> \
    [--api-key <KAKAO_API_KEY>] \
    [--refresh-token <KAKAO_REFRESH_TOKEN>]

환경변수 KAKAO_API_KEY, KAKAO_REFRESH_TOKEN 가 설정되어 있으면 인자 생략 가능.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request


def get_access_token(api_key: str, refresh_token: str) -> str:
    """refresh_token으로 access_token 재발급."""
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": api_key,
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://kauth.kakao.com/oauth/token",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[kakao] 토큰 재발급 실패: {e}", file=sys.stderr)
        return ""
    return body.get("access_token", "")


def send_memo(
    access_token: str, status: str, sha: str, branch: str, message: str
) -> bool:
    """나에게 보내기 API 호출."""
    icon = "✅" if status != "fail" else "❌"
    status_label = (
        "성공" if status == "success" else ("실패" if status == "fail" else status)
    )
    text = f"{icon} 배포 {status_label}\n커밋: {sha}\n브랜치: {branch}"
    if message:
        text += f"\n\n{message}"

    template_object = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": "https://api.samba-wave.co.kr/api/v1/health"},
    }
    data = urllib.parse.urlencode(
        {"template_object": json.dumps(template_object, ensure_ascii=False)}
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        data=data,
        headers={"Authorization": f"Bearer {access_token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except Exception as e:
        print(f"[kakao] 메시지 전송 실패: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True, choices=["success", "fail"])
    parser.add_argument("--sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--message", default="")
    # 구조화된 인자 (ASCII만 허용) — 쉘 로케일과 무관하게 안전하게 전달
    parser.add_argument("--elapsed", type=int, default=0, help="소요 시간(초)")
    parser.add_argument(
        "--exit-code", type=int, default=0, help="배포 실패 시 종료 코드"
    )
    parser.add_argument(
        "--failure-reason",
        default="",
        choices=["", "healthcheck", "build", "push", "ssh", "generic"],
        help="실패 원인 키 (한글 메시지는 스크립트 내부에서 생성)",
    )
    parser.add_argument("--api-key", default=os.environ.get("KAKAO_API_KEY", ""))
    parser.add_argument(
        "--refresh-token", default=os.environ.get("KAKAO_REFRESH_TOKEN", "")
    )
    args = parser.parse_args()

    if not args.api_key or not args.refresh_token:
        # 키 없으면 조용히 종료 (deploy.sh와 동일 동작)
        return 0

    token = get_access_token(args.api_key, args.refresh_token)
    if not token:
        return 0

    # 구조화 인자 → 한글 메시지 조합 (쉘에서 한글을 전달하지 않기 위함)
    reason_map = {
        "healthcheck": "헬스체크 실패 — 최신 리비전이 서빙되지 않음",
        "build": "Docker 빌드 실패",
        "push": "Artifact Registry 푸시 실패",
        "ssh": "VM SSH 배포 실패",
        "generic": "배포 중 오류 발생",
    }
    parts: list[str] = []
    if args.failure_reason and args.failure_reason in reason_map:
        parts.append(reason_map[args.failure_reason])
    if args.exit_code:
        parts.append(f"종료 코드: {args.exit_code}")
    if args.elapsed:
        parts.append(f"소요 {args.elapsed}초")
    if args.message:
        parts.append(args.message)

    composed_message = "\n".join(parts)

    ok = send_memo(
        access_token=token,
        status=args.status,
        sha=args.sha,
        branch=args.branch,
        message=composed_message,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
