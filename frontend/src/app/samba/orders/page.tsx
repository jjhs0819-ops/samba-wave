"use client";

import { useEffect, useState, useCallback } from "react";
import { orderApi, channelApi, type SambaOrder, type SambaChannel } from "@/lib/samba/api";

const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  pending: { label: "대기중", bg: "rgba(255,211,61,0.15)", text: "#FFD93D" },
  shipped: { label: "배송중", bg: "rgba(76,154,255,0.15)", text: "#4C9AFF" },
  delivered: { label: "배송완료", bg: "rgba(81,207,102,0.15)", text: "#51CF66" },
  cancelled: { label: "취소됨", bg: "rgba(255,107,107,0.15)", text: "#FF6B6B" },
  returned: { label: "반품됨", bg: "rgba(200,100,200,0.15)", text: "#CC5DE8" },
};

export default function OrdersPage() {
  const [orders, setOrders] = useState<SambaOrder[]>([]);
  const [channels, setChannels] = useState<SambaChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    channel_id: "", product_name: "", customer_name: "", customer_phone: "",
    sale_price: 0, cost: 0, fee_rate: 0, notes: "",
  });

  const loadOrders = useCallback(async () => {
    setLoading(true);
    try {
      const data = searchQuery
        ? await orderApi.search(searchQuery)
        : await orderApi.list(0, 200);
      setOrders(data);
    } catch {
      // ignore
    }
    setLoading(false);
  }, [searchQuery]);

  useEffect(() => { loadOrders(); }, [loadOrders]);
  useEffect(() => { channelApi.list().then(setChannels).catch(() => {}); }, []);

  const handleSubmit = async () => {
    try {
      const ch = channels.find((c) => c.id === form.channel_id);
      await orderApi.create({ ...form, channel_name: ch?.name, fee_rate: form.fee_rate || ch?.fee_rate || 0 });
      setShowForm(false);
      setForm({ channel_id: "", product_name: "", customer_name: "", customer_phone: "", sale_price: 0, cost: 0, fee_rate: 0, notes: "" });
      loadOrders();
    } catch (e) {
      alert(e instanceof Error ? e.message : "저장 실패");
    }
  };

  const handleStatusChange = async (id: string, status: string) => {
    await orderApi.updateStatus(id, status);
    loadOrders();
  };

  const handleDelete = async (id: string) => {
    if (!confirm("삭제하시겠습니까?")) return;
    await orderApi.delete(id);
    loadOrders();
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">주문관리</h2>
        <button
          onClick={() => setShowForm(true)}
          className="px-4 py-2 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00]"
        >
          + 주문 추가
        </button>
      </div>

      <input
        type="text"
        placeholder="주문번호, 고객명, 전화번호 검색..."
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        className="w-full px-3 py-2 bg-[#111] border border-[#1A1A1A] rounded-lg text-sm text-[#E5E5E5] placeholder:text-[#555] focus:outline-none focus:border-[#FF8C00]"
      />

      {showForm && (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4 space-y-3">
          <h3 className="font-semibold text-sm">주문 추가</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-[#666] mb-1 block">판매처</label>
              <select
                value={form.channel_id}
                onChange={(e) => setForm({ ...form, channel_id: e.target.value })}
                className="w-full px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5]"
              >
                <option value="">선택</option>
                {channels.map((ch) => (
                  <option key={ch.id} value={ch.id}>{ch.name}</option>
                ))}
              </select>
            </div>
            <FormInput label="상품명" value={form.product_name} onChange={(v) => setForm({ ...form, product_name: v })} />
            <FormInput label="고객명" value={form.customer_name} onChange={(v) => setForm({ ...form, customer_name: v })} />
            <FormInput label="전화번호" value={form.customer_phone} onChange={(v) => setForm({ ...form, customer_phone: v })} />
            <FormInput label="판매가" value={String(form.sale_price)} onChange={(v) => setForm({ ...form, sale_price: Number(v) })} type="number" />
            <FormInput label="원가" value={String(form.cost)} onChange={(v) => setForm({ ...form, cost: Number(v) })} type="number" />
            <FormInput label="수수료율(%)" value={String(form.fee_rate)} onChange={(v) => setForm({ ...form, fee_rate: Number(v) })} type="number" />
            <FormInput label="메모" value={form.notes} onChange={(v) => setForm({ ...form, notes: v })} />
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 text-sm text-[#999]">취소</button>
            <button onClick={handleSubmit} className="px-4 py-1.5 bg-[#FF8C00] text-white text-sm rounded-lg font-medium">저장</button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-[#666]">로딩 중...</p>
      ) : (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#666] border-b border-[#1A1A1A] bg-[#0E0E0E]">
                <th className="text-left px-4 py-2.5">주문번호</th>
                <th className="text-left px-4 py-2.5">상품</th>
                <th className="text-left px-4 py-2.5">고객</th>
                <th className="text-right px-4 py-2.5">판매가</th>
                <th className="text-right px-4 py-2.5">수익</th>
                <th className="text-left px-4 py-2.5">상태</th>
                <th className="text-right px-4 py-2.5">작업</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((o) => {
                const st = STATUS_MAP[o.status] || { label: o.status, bg: "rgba(100,100,100,0.2)", text: "#888" };
                return (
                  <tr key={o.id} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                    <td className="px-4 py-2.5 text-[#FF8C00]">{o.order_number}</td>
                    <td className="px-4 py-2.5">{o.product_name || "-"}</td>
                    <td className="px-4 py-2.5">{o.customer_name || "-"}</td>
                    <td className="px-4 py-2.5 text-right">₩{o.sale_price.toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-right text-[#51CF66]">₩{o.profit.toLocaleString()}</td>
                    <td className="px-4 py-2.5">
                      <select
                        value={o.status}
                        onChange={(e) => handleStatusChange(o.id, e.target.value)}
                        className="bg-transparent text-xs font-medium px-1 py-0.5 rounded"
                        style={{ background: st.bg, color: st.text }}
                      >
                        {Object.entries(STATUS_MAP).map(([k, v]) => (
                          <option key={k} value={k}>{v.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <button onClick={() => handleDelete(o.id)} className="text-[#FF6B6B] hover:underline text-xs">삭제</button>
                    </td>
                  </tr>
                );
              })}
              {orders.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-[#555]">주문이 없습니다</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FormInput({ label, value, onChange, type = "text" }: { label: string; value: string; onChange: (v: string) => void; type?: string }) {
  return (
    <div>
      <label className="text-xs text-[#666] mb-1 block">{label}</label>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5] focus:outline-none focus:border-[#FF8C00]" />
    </div>
  );
}
