"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

interface NavItem {
  href: string;
  label: string;
  children?: { href: string; label: string }[];
}

const NAV_ITEMS: NavItem[] = [
  { href: "/samba/collector", label: "상품수집" },
  { href: "/samba/products", label: "상품관리" },
  {
    href: "/samba/policies",
    label: "정책관리",
    children: [
      { href: "/samba/policies", label: "정책관리" },
      { href: "/samba/categories", label: "카테고리 매핑" },
    ],
  },
  { href: "/samba/shipments", label: "상품전송/삭제" },
  { href: "/samba/orders", label: "주문" },
  { href: "/samba/returns", label: "반품·교환·취소" },
  {
    href: "/samba/analytics",
    label: "통계",
    children: [
      { href: "/samba/analytics", label: "매출통계" },
    ],
  },
  { href: "/samba/settings", label: "설정" },
];

export default function SambaLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [openDropdown, setOpenDropdown] = useState<string | null>(null);

  return (
    <div className="flex flex-col min-h-screen" style={{ background: "#0F0F0F", color: "#E5E5E5" }}>
      {/* Header */}
      <header
        className="sticky top-0 z-30"
        style={{
          background: "rgba(15,15,15,0.9)",
          borderBottom: "1px solid #2D2D2D",
          backdropFilter: "blur(10px)",
        }}
      >
        <div className="flex items-center justify-between px-8 py-3">
          {/* Logo */}
          <Link href="/samba" className="flex items-center gap-2 select-none" title="대시보드로 이동">
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="logoGrad" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stopColor="#FF8C00"/>
                  <stop offset="100%" stopColor="#FFB84D"/>
                </linearGradient>
              </defs>
              <rect width="40" height="40" rx="10" fill="#1A1A1A" stroke="#2D2D2D" strokeWidth="1"/>
              <path d="M4 16 Q10 12 16 16 Q22 20 28 16 Q34 12 38 16" stroke="#FF8C00" strokeOpacity="0.25" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
              <path d="M4 21 Q10 17 16 21 Q22 25 28 21 Q34 17 38 21" stroke="#FF8C00" strokeOpacity="0.55" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
              <path d="M4 26 Q10 22 16 26 Q22 30 28 26 Q34 22 38 26" stroke="url(#logoGrad)" strokeWidth="2" fill="none" strokeLinecap="round"/>
              <text x="20" y="15" fontFamily="Arial Black, sans-serif" fontSize="7.5" fontWeight="900" fill="url(#logoGrad)" textAnchor="middle" dominantBaseline="middle" letterSpacing="0.5">SW</text>
            </svg>
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
                        transition: "all 0.3s",
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
                                transition: "all 0.2s",
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
                <Link
                  key={item.href}
                  href={item.href}
                  style={{
                    padding: "0.75rem 1.5rem",
                    fontSize: "0.875rem",
                    fontWeight: 500,
                    color: isActive ? "#FF8C00" : "#E5E5E5",
                    borderBottom: `2px solid ${isActive ? "#FF8C00" : "transparent"}`,
                    transition: "all 0.3s",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = "#FF8C00"; e.currentTarget.style.borderBottomColor = "#FF8C00"; }}
                  onMouseLeave={(e) => {
                    if (!isActive) { e.currentTarget.style.color = "#E5E5E5"; e.currentTarget.style.borderBottomColor = "transparent"; }
                  }}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          {/* Right icons */}
          <div className="flex items-center gap-4">
            <button className="p-2 transition" style={{ color: "#888" }} title="알림">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>
              </svg>
            </button>
            <Link href="/samba/accounts" className="p-2 transition" style={{ color: "#888" }} title="마켓계정">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
              </svg>
            </Link>
            <Link href="/samba/settings" className="p-2 transition" style={{ color: "#888" }} title="설정">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
              </svg>
            </Link>
            <div className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold cursor-pointer" style={{ background: "linear-gradient(135deg, #FF8C00, #E07B00)" }} />
          </div>
        </div>
      </header>

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
    </div>
  );
}
