"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/samba", label: "대시보드", icon: "📊" },
  { href: "/samba/collector", label: "상품수집", icon: "🔍" },
  { href: "/samba/products", label: "상품관리", icon: "📦" },
  { href: "/samba/orders", label: "주문관리", icon: "🛒" },
  { href: "/samba/policies", label: "정책관리", icon: "💰" },
  { href: "/samba/categories", label: "카테고리", icon: "🗂️" },
  { href: "/samba/shipments", label: "마켓전송", icon: "🚀" },
  { href: "/samba/accounts", label: "마켓계정", icon: "🏪" },
  { href: "/samba/analytics", label: "매출통계", icon: "📈" },
  { href: "/samba/returns", label: "반품/교환", icon: "↩️" },
  { href: "/samba/settings", label: "설정", icon: "⚙️" },
];

export default function SambaLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="flex h-screen bg-[#0A0A0A] text-[#E5E5E5]">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 border-r border-[#1A1A1A] bg-[#0E0E0E] flex flex-col">
        <div className="p-4 border-b border-[#1A1A1A]">
          <h1 className="text-lg font-bold text-[#FF8C00]">SambaWave</h1>
          <p className="text-xs text-[#666] mt-0.5">위탁판매 관리</p>
        </div>
        <nav className="flex-1 py-2">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.href === "/samba"
                ? pathname === "/samba"
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 px-4 py-2.5 text-sm transition-colors ${
                  isActive
                    ? "bg-[#1A1A1A] text-[#FF8C00] font-medium"
                    : "text-[#999] hover:bg-[#141414] hover:text-[#CCC]"
                }`}
              >
                <span className="text-base">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  );
}
