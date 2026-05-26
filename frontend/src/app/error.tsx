"use client";

import { useEffect } from "react";

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

/**
 * 전역 error boundary — 사용자에게 "오류 발생" 화면 노출 차단.
 * 배포 직후 SSR mismatch / chunk hash 변동 등 일시적 오류는 즉시 자동 reload.
 * 60초 가드로 무한 loop 방지.
 *
 * SaaS UX 룰 (2026-05-26 사용자 요구): "오류 화면 자체가 뜨면 안 됨."
 * → render 시 빈 화면(null) 반환 + 즉시 reload. 사용자는 깜빡임만 봄.
 */
export default function Error({ error, reset }: ErrorProps) {
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const key = "samba.errorReloadAt";
      const last = Number(window.sessionStorage.getItem(key) || "0");
      const now = Date.now();
      if (now - last > 60_000) {
        window.sessionStorage.setItem(key, String(now));
        window.location.reload();
        return;
      }
      // 60초 내 재발 시 reset 시도 (무한 reload 방지)
      reset();
    } catch {
      try {
        reset();
      } catch {
        /* ignore */
      }
    }
    console.error("Application error (silent reload):", error);
  }, [error, reset]);

  // 사용자에게 오류 화면 노출 X — 빈 화면 후 reload 발생.
  return null;
}
