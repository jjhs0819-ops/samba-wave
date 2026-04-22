"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import SambaModal from "@/components/samba/Modal";
import SambaBlockAlert from "@/components/samba/BlockAlert";
import type { SambaUser } from "@/lib/samba/api/operations";
import { STORAGE_KEYS } from "@/lib/samba/constants";
import { getLicenseKey } from "@/hooks/useLicenseCheck";

interface NavItem {
  href: string;
  label: string;
  children?: { href: string; label: string }[];
}

const NAV_ITEMS: NavItem[] = [
  { href: "/samba/collector", label: "상품수집" },
  { href: "/samba/products", label: "상품관리" },
  { href: "/samba/manual-products", label: "수동등록" },
  { href: "/samba/policies", label: "정책관리" },
  { href: "/samba/categories", label: "카테고리매핑" },
  { href: "/samba/shipments", label: "상품전송/삭제" },
  { href: "/samba/warroom", label: "오토튠" },
  { href: "/samba/store-care", label: "스토어케어" },
  { href: "/samba/sns", label: "SNS마케팅" },
  { href: "/samba/orders", label: "주문" },
  { href: "/samba/returns", label: "반품교환" },
  { href: "/samba/cs", label: "CS" },
  { href: "/samba/analytics", label: "매출통계" },
  { href: "/samba/settings", label: "설정" },
];

export default function SambaLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);
  const [currentUser, setCurrentUser] = useState<SambaUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  // 로그인/회원가입/라이선스 페이지는 인증 체크 없이 렌더링
  const isLoginPage = pathname === "/samba/login" || pathname === "/samba/sign-up";
  const isLicensePage = pathname === "/samba/license";

  useEffect(() => {
    if (isLoginPage || isLicensePage) {
      setAuthChecked(true);
      return;
    }
    // 라이선스 키 미등록 시 라이선스 페이지로 이동
    if (!getLicenseKey()) {
      router.replace("/samba/license");
      return;
    }
    const raw = localStorage.getItem(STORAGE_KEYS.SAMBA_USER);
    if (raw) {
      try {
        setCurrentUser(JSON.parse(raw) as SambaUser);
      } catch {
        localStorage.removeItem(STORAGE_KEYS.SAMBA_USER);
        router.replace("/samba/login");
      }
    } else {
      router.replace("/samba/login");
    }
    setAuthChecked(true);
  }, [isLoginPage, isLicensePage, router]);

  // 로그인/라이선스 페이지는 레이아웃 헤더 없이 바로 렌더링
  if (isLoginPage || isLicensePage) {
    return <>{children}</>;
  }

  // 인증 체크 중이거나 미로그인이면 빈 화면 (리다이렉트 중)
  if (!authChecked || !currentUser) {
    return (
      <div className="flex items-center justify-center min-h-screen" style={{ background: "#0F0F0F" }}>
        <p style={{ color: "#555", fontSize: "0.875rem" }}>로딩 중...</p>
      </div>
    );
  }

  const handleLogout = () => {
    localStorage.removeItem(STORAGE_KEYS.SAMBA_USER);
    // 인증 쿠키 제거
    document.cookie = "samba_user=; path=/; max-age=0";
    router.replace("/samba/login");
  };

  return (
    <div className="flex flex-col min-h-screen" style={{ background: "#0F0F0F", color: "#E5E5E5" }}>
      {/* Header */}
      <header
        className="sticky top-0 z-30"
        style={{
          background: "rgba(15,15,15,0.9)",
          borderBottom: "1px solid #2D2D2D",
          backdropFilter: "blur(4px)",
        }}
      >
        <div className="flex items-center justify-between px-8 py-3">
          {/* Logo */}
          <Link href="/samba" className="flex items-center gap-2 select-none" title="대시보드로 이동">
            <img src="/logo.png" alt="SAMBA WAVE Logo" width={40} height={40} className="object-contain" style={{ borderRadius: "8.8px" }} />
            <div>
              <h1 style={{ fontSize: "0.9375rem", fontWeight: 800, color: "#E5E5E5", letterSpacing: "0.08em", lineHeight: 1.1, textTransform: "uppercase" }}>
                SAMBA WAVE
              </h1>
              <p style={{ fontSize: "0.5625rem", color: "#666", letterSpacing: "0.04em", lineHeight: 1 }}>
                무재고 위탁판매 솔루션
              </p>
            </div>
          </Link>

          {/* Navigation */}
          <nav className="flex items-stretch ml-12" style={{ gap: 0 }}>
            {NAV_ITEMS.map((item) => {
              if (item.children) {
                // Dropdown
                const isGroupActive = item.children.some((c) => pathname.startsWith(c.href));
                return (
                  <div
                    key={item.label}
                    className="relative"
                    onMouseEnter={() => setOpenDropdown(item.label)}
                    onMouseLeave={() => setOpenDropdown(null)}
                  >
                    <button
                      className="flex items-center gap-1"
                      style={{
                        padding: "0.75rem 1.5rem",
                        fontSize: "0.875rem",
                        fontWeight: 500,
                        color: isGroupActive ? "#FF8C00" : "#E5E5E5",
                        background: "transparent",
                        borderTop: "none",
                        borderLeft: "none",
                        borderRight: "none",
                        borderBottomWidth: "2px",
                        borderBottomStyle: "solid",
                        borderBottomColor: isGroupActive ? "#FF8C00" : "transparent",
                        cursor: "pointer",
                        transition: "color 0.15s, border-color 0.15s",
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.color = "#FF8C00"; e.currentTarget.style.borderBottomColor = "#FF8C00"; }}
                      onMouseLeave={(e) => {
                        if (!isGroupActive) { e.currentTarget.style.color = "#E5E5E5"; e.currentTarget.style.borderBottomColor = "transparent"; }
                      }}
                    >
                      {item.label} <span style={{ fontSize: "0.625rem", transition: "transform 0.2s", transform: openDropdown === item.label ? "rotate(180deg)" : "none" }}>▼</span>
                    </button>
                    {openDropdown === item.label && (
                      <div
                        style={{
                          position: "absolute",
                          top: "calc(100% + 1px)",
                          left: 0,
                          background: "#1A1A1A",
                          border: "1px solid #2D2D2D",
                          borderRadius: "8px",
                          minWidth: "200px",
                          zIndex: 40,
                          boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
                          overflow: "hidden",
                        }}
                      >
                        {item.children.map((child) => {
                          const isChildActive = pathname === child.href;
                          return (
                            <Link
                              key={child.href}
                              href={child.href}
                              style={{
                                display: "block",
                                padding: "0.625rem 1.25rem",
                                color: isChildActive ? "#FF8C00" : "#C5C5C5",
                                fontSize: "0.8125rem",
                                background: isChildActive ? "rgba(255,140,0,0.12)" : "transparent",
                                transition: "color 0.15s, border-color 0.15s, background 0.15s",
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.color = "#FF8C00"; e.currentTarget.style.background = "rgba(255,140,0,0.08)"; }}
                              onMouseLeave={(e) => {
                                if (!isChildActive) { e.currentTarget.style.color = "#C5C5C5"; e.currentTarget.style.background = "transparent"; }
                              }}
                            >
                              {child.label}
                            </Link>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              }

              // Single nav item
              const isActive =
                item.href === "/samba/products"
                  ? pathname === "/samba/products"
                  : pathname.startsWith(item.href);
              return (
                <div key={item.href} className="relative">
                  <Link
                    href={item.href}
                    style={{
                      display: "block",
                      padding: "0.75rem 1.5rem",
                      fontSize: "0.875rem",
                      fontWeight: 500,
                      color: isActive ? "#FF8C00" : "#E5E5E5",
                      borderBottom: `2px solid ${isActive ? "#FF8C00" : "transparent"}`,
                      transition: "color 0.15s, border-color 0.15s",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.color = "#FF8C00"; e.currentTarget.style.borderBottomColor = "#FF8C00"; }}
                    onMouseLeave={(e) => {
                      if (!isActive) { e.currentTarget.style.color = "#E5E5E5"; e.currentTarget.style.borderBottomColor = "transparent"; }
                    }}
                  >
                    {item.label}
                  </Link>
                </div>
              );
            })}
          </nav>

          {/* 알림 + 계정관리 + 사용자 정보 + 로그아웃 */}
          <div className="flex items-center gap-3">
            {/* 취소 알림 설정 */}
            <button
              title="취소 알림 설정"
              onClick={() => {
                if (pathname.startsWith("/samba/orders")) {
                  window.dispatchEvent(new CustomEvent("open-alarm-setting"))
                } else {
                  router.push("/samba/orders?alarm=1")
                }
              }}
              style={{
                width: "32px",
                height: "32px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: "transparent",
                border: "none",
                borderRadius: "6px",
                cursor: "pointer",
                color: "#FFD93D",
                fontSize: "1.125rem",
                transition: "color 0.15s, border-color 0.15s, background 0.15s",
                position: "relative",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = "#FF8C00"; e.currentTarget.style.background = "rgba(255,140,0,0.08)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = "#FFD93D"; e.currentTarget.style.background = "transparent"; }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.73 21a2 2 0 0 1-3.46 0" />
              </svg>
            </button>
            {/* 계정관리 아이콘 */}
            <Link
              href="/samba/users"
              title="계정관리"
              style={{
                width: "32px",
                height: "32px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                background: pathname.startsWith("/samba/users") ? "rgba(255,140,0,0.12)" : "transparent",
                border: "none",
                borderRadius: "6px",
                cursor: "pointer",
                color: pathname.startsWith("/samba/users") ? "#FF8C00" : "#888",
                fontSize: "1.125rem",
                transition: "color 0.15s, border-color 0.15s, background 0.15s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = "#FF8C00"; e.currentTarget.style.background = "rgba(255,140,0,0.08)"; }}
              onMouseLeave={(e) => {
                if (!pathname.startsWith("/samba/users")) { e.currentTarget.style.color = "#888"; e.currentTarget.style.background = "transparent"; }
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            </Link>
            {/* 구분선 */}
            <div style={{ width: "1px", height: "20px", background: "#333" }} />
            <span style={{ fontSize: "0.8125rem", color: "#AAA" }}>
              {currentUser.name || currentUser.email}
            </span>
            <button
              onClick={handleLogout}
              style={{
                padding: "0.375rem 0.75rem",
                fontSize: "0.75rem",
                color: "#888",
                background: "transparent",
                border: "1px solid #333",
                borderRadius: "6px",
                cursor: "pointer",
                transition: "color 0.15s, border-color 0.15s, background 0.15s",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = "#FF6B6B"; e.currentTarget.style.borderColor = "#FF6B6B"; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = "#888"; e.currentTarget.style.borderColor = "#333"; }}
            >
              로그아웃
            </button>
          </div>
        </div>
      </header>

      {/* 소싱처 접속 차단 알림 배너 */}
      <SambaBlockAlert />

      {/* Main content - full width, gradient background */}
      <main
        className="flex-1"
        style={{
          background: "linear-gradient(135deg, #0F0F0F 0%, #1A1A1A 100%)",
          paddingTop: "2rem",
        }}
      >
        <div style={{ padding: "0 3rem 4rem 3rem", maxWidth: "1600px", margin: "0 auto", width: "100%" }}>
          {children}
        </div>
      </main>
      <SambaModal />
    </div>
  );
}
