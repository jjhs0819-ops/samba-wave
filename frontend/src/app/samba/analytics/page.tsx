"use client";

import { useEffect, useState, useCallback } from "react";
import { analyticsApi, type AnalyticsStats } from "@/lib/samba/api";

interface ChannelRow {
  channel_name: string;
  total_sales: number;
  total_orders: number;
  total_profit: number;
}

interface ProductRow {
  product_name: string;
  total_sales: number;
  total_orders: number;
  total_profit: number;
}

interface DailyRow {
  date: string;
  total_sales: number;
  total_orders: number;
  total_profit: number;
}

const EMPTY_STATS: AnalyticsStats = {
  total_sales: 0,
  total_orders: 0,
  total_profit: 0,
  avg_order_value: 0,
  profit_rate: 0,
};

export default function AnalyticsPage() {
  const [todayStats, setTodayStats] = useState<AnalyticsStats>(EMPTY_STATS);
  const [monthStats, setMonthStats] = useState<AnalyticsStats>(EMPTY_STATS);
  const [channels, setChannels] = useState<ChannelRow[]>([]);
  const [products, setProducts] = useState<ProductRow[]>([]);
  const [daily, setDaily] = useState<DailyRow[]>([]);
  const [orderStatus, setOrderStatus] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const now = new Date();
      const startOfMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
      const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;

      const [t, m, ch, pr, d, os] = await Promise.all([
        analyticsApi.today().catch(() => EMPTY_STATS),
        analyticsApi.range(startOfMonth, today).catch(() => EMPTY_STATS),
        analyticsApi.byChannel().catch(() => []),
        analyticsApi.byProduct().catch(() => []),
        analyticsApi.daily(30).catch(() => []),
        analyticsApi.orderStatus().catch(() => ({})),
      ]);

      setTodayStats(t);
      setMonthStats(m);
      setChannels(ch as ChannelRow[]);
      setProducts(pr as ProductRow[]);
      setDaily(d as DailyRow[]);
      setOrderStatus(os);
    } catch {
      // ignore
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-[#666]">로딩 중...</div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-xl font-bold">매출통계</h2>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard label="오늘 매출" value={`\u20A9${todayStats.total_sales.toLocaleString()}`} sub={`${todayStats.total_orders}건`} />
        <KpiCard label="오늘 수익" value={`\u20A9${todayStats.total_profit.toLocaleString()}`} sub={`수익률 ${todayStats.profit_rate.toFixed(1)}%`} color="#51CF66" />
        <KpiCard label="이번달 매출" value={`\u20A9${monthStats.total_sales.toLocaleString()}`} sub={`${monthStats.total_orders}건`} color="#4C9AFF" />
        <KpiCard label="이번달 수익" value={`\u20A9${monthStats.total_profit.toLocaleString()}`} sub={`수익률 ${monthStats.profit_rate.toFixed(1)}%`} color="#CC5DE8" />
      </div>

      {/* Order Status Distribution */}
      {Object.keys(orderStatus).length > 0 && (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3 text-[#999]">주문 상태 분포</h3>
          <div className="grid grid-cols-5 gap-3">
            {Object.entries(orderStatus).map(([status, count]) => (
              <div key={status} className="bg-[#0A0A0A] border border-[#1A1A1A] rounded-lg p-3 text-center">
                <p className="text-xs text-[#666] mb-1">{STATUS_LABEL[status] || status}</p>
                <p className="text-lg font-bold text-[#FF8C00]">{count}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Sales by Channel */}
      <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3 text-[#999]">채널별 매출</h3>
        {channels.length === 0 ? (
          <p className="text-sm text-[#555]">데이터가 없습니다</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#666] border-b border-[#1A1A1A]">
                <th className="text-left py-2 px-4">채널</th>
                <th className="text-right py-2 px-4">주문수</th>
                <th className="text-right py-2 px-4">매출</th>
                <th className="text-right py-2 px-4">수익</th>
              </tr>
            </thead>
            <tbody>
              {channels.map((ch, i) => (
                <tr key={i} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                  <td className="px-4 py-2.5 text-[#FF8C00]">{ch.channel_name || "-"}</td>
                  <td className="px-4 py-2.5 text-right">{ch.total_orders?.toLocaleString() ?? 0}</td>
                  <td className="px-4 py-2.5 text-right">{"\u20A9"}{ch.total_sales?.toLocaleString() ?? 0}</td>
                  <td className="px-4 py-2.5 text-right text-[#51CF66]">{"\u20A9"}{ch.total_profit?.toLocaleString() ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Sales by Product */}
      <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3 text-[#999]">상품별 매출</h3>
        {products.length === 0 ? (
          <p className="text-sm text-[#555]">데이터가 없습니다</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#666] border-b border-[#1A1A1A]">
                <th className="text-left py-2 px-4">상품명</th>
                <th className="text-right py-2 px-4">주문수</th>
                <th className="text-right py-2 px-4">매출</th>
                <th className="text-right py-2 px-4">수익</th>
              </tr>
            </thead>
            <tbody>
              {products.map((pr, i) => (
                <tr key={i} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                  <td className="px-4 py-2.5">{pr.product_name || "-"}</td>
                  <td className="px-4 py-2.5 text-right">{pr.total_orders?.toLocaleString() ?? 0}</td>
                  <td className="px-4 py-2.5 text-right">{"\u20A9"}{pr.total_sales?.toLocaleString() ?? 0}</td>
                  <td className="px-4 py-2.5 text-right text-[#51CF66]">{"\u20A9"}{pr.total_profit?.toLocaleString() ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Daily Trend */}
      <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3 text-[#999]">일별 추이 (최근 30일)</h3>
        {daily.length === 0 ? (
          <p className="text-sm text-[#555]">데이터가 없습니다</p>
        ) : (
          <div className="max-h-[400px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-[#111]">
                <tr className="text-[#666] border-b border-[#1A1A1A]">
                  <th className="text-left py-2 px-4">날짜</th>
                  <th className="text-right py-2 px-4">주문수</th>
                  <th className="text-right py-2 px-4">매출</th>
                  <th className="text-right py-2 px-4">수익</th>
                </tr>
              </thead>
              <tbody>
                {daily.map((d, i) => (
                  <tr key={i} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                    <td className="px-4 py-2.5 text-[#FF8C00]">{d.date}</td>
                    <td className="px-4 py-2.5 text-right">{d.total_orders?.toLocaleString() ?? 0}</td>
                    <td className="px-4 py-2.5 text-right">{"\u20A9"}{d.total_sales?.toLocaleString() ?? 0}</td>
                    <td className="px-4 py-2.5 text-right text-[#51CF66]">{"\u20A9"}{d.total_profit?.toLocaleString() ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

const STATUS_LABEL: Record<string, string> = {
  pending: "대기중",
  shipped: "배송중",
  delivered: "배송완료",
  cancelled: "취소됨",
  returned: "반품됨",
};

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
