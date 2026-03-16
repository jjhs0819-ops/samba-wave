"use client";

import { useEffect, useState } from "react";
import { productApi, orderApi, type SambaProduct, type SambaOrder } from "@/lib/samba/api";

export default function SambaDashboard() {
  const [products, setProducts] = useState<SambaProduct[]>([]);
  const [orders, setOrders] = useState<SambaOrder[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      productApi.list(0, 100).catch(() => []),
      orderApi.list(0, 100).catch(() => []),
    ]).then(([p, o]) => {
      setProducts(p);
      setOrders(o);
      setLoading(false);
    });
  }, []);

  const totalSales = orders.reduce((s, o) => s + (o.sale_price || 0), 0);
  const totalProfit = orders.reduce((s, o) => s + (o.profit || 0), 0);
  const sellingCount = products.filter(
    (p) => (p.registered_accounts || []).length > 0
  ).length;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-[#666]">로딩 중...</div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-xl font-bold">대시보드</h2>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard label="총 매출" value={`₩${totalSales.toLocaleString()}`} sub={`${orders.length}건 누적`} />
        <KpiCard label="총 수익" value={`₩${totalProfit.toLocaleString()}`} sub="필터 기준" color="#51CF66" />
        <KpiCard label="수집 상품" value={`${products.length}개`} sub="전체" />
        <KpiCard label="판매중" value={`${sellingCount}개`} sub="마켓 등록" color="#4C9AFF" />
      </div>

      {/* Recent Orders */}
      <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3 text-[#999]">최근 주문</h3>
        {orders.length === 0 ? (
          <p className="text-sm text-[#555]">주문이 없습니다</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#666] border-b border-[#1A1A1A]">
                <th className="text-left py-2">주문번호</th>
                <th className="text-left py-2">상품</th>
                <th className="text-left py-2">고객</th>
                <th className="text-right py-2">금액</th>
                <th className="text-left py-2">상태</th>
              </tr>
            </thead>
            <tbody>
              {orders.slice(0, 10).map((o) => (
                <tr key={o.id} className="border-b border-[#1A1A1A]/50">
                  <td className="py-2 text-[#FF8C00]">{o.order_number}</td>
                  <td className="py-2">{o.product_name || "-"}</td>
                  <td className="py-2">{o.customer_name || "-"}</td>
                  <td className="py-2 text-right">₩{o.sale_price.toLocaleString()}</td>
                  <td className="py-2">
                    <StatusBadge status={o.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function KpiCard({
  label,
  value,
  sub,
  color = "#FF8C00",
}: {
  label: string;
  value: string;
  sub: string;
  color?: string;
}) {
  return (
    <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4">
      <p className="text-xs text-[#666] mb-1">{label}</p>
      <p className="text-xl font-bold" style={{ color }}>{value}</p>
      <p className="text-xs text-[#555] mt-1">{sub}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { bg: string; text: string; label: string }> = {
    pending: { bg: "rgba(255,211,61,0.15)", text: "#FFD93D", label: "대기중" },
    shipped: { bg: "rgba(76,154,255,0.15)", text: "#4C9AFF", label: "배송중" },
    delivered: { bg: "rgba(81,207,102,0.15)", text: "#51CF66", label: "배송완료" },
    cancelled: { bg: "rgba(255,107,107,0.15)", text: "#FF6B6B", label: "취소됨" },
  };
  const s = map[status] || { bg: "rgba(100,100,100,0.2)", text: "#888", label: status };
  return (
    <span
      className="px-2 py-0.5 rounded text-xs font-medium"
      style={{ background: s.bg, color: s.text }}
    >
      {s.label}
    </span>
  );
}
