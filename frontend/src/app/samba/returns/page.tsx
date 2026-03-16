"use client";

import { useEffect, useState, useCallback } from "react";
import { returnApi, type SambaReturn } from "@/lib/samba/api";

const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  requested: { label: "요청됨", bg: "rgba(255,211,61,0.15)", text: "#FFD93D" },
  approved: { label: "승인됨", bg: "rgba(76,154,255,0.15)", text: "#4C9AFF" },
  rejected: { label: "거절됨", bg: "rgba(255,107,107,0.15)", text: "#FF6B6B" },
  completed: { label: "완료됨", bg: "rgba(81,207,102,0.15)", text: "#51CF66" },
  cancelled: { label: "취소됨", bg: "rgba(100,100,100,0.2)", text: "#888" },
};

const TYPE_LABELS: Record<string, string> = {
  return: "반품",
  exchange: "교환",
  cancel: "취소",
};

export default function ReturnsPage() {
  const [returns, setReturns] = useState<SambaReturn[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    order_id: "",
    type: "return",
    reason: "",
    quantity: 1,
    requested_amount: 0,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [data, st] = await Promise.all([
        returnApi.list().catch(() => []),
        returnApi.getStats().catch(() => ({})),
      ]);
      setReturns(data);
      setStats(st);
    } catch {
      // ignore
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSubmit = async () => {
    try {
      await returnApi.create({
        order_id: form.order_id,
        type: form.type,
        reason: form.reason,
        quantity: form.quantity,
        requested_amount: form.requested_amount || undefined,
      });
      setShowForm(false);
      setForm({ order_id: "", type: "return", reason: "", quantity: 1, requested_amount: 0 });
      load();
    } catch (e) {
      alert(e instanceof Error ? e.message : "저장 실패");
    }
  };

  const handleApprove = async (id: string) => {
    await returnApi.approve(id);
    load();
  };

  const handleReject = async (id: string) => {
    const reason = prompt("거절 사유를 입력하세요:");
    if (!reason) return;
    await returnApi.reject(id, reason);
    load();
  };

  const handleComplete = async (id: string) => {
    await returnApi.complete(id);
    load();
  };

  const handleCancel = async (id: string) => {
    if (!confirm("취소하시겠습니까?")) return;
    await returnApi.cancel(id);
    load();
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">반품/교환 관리</h2>
        <button
          onClick={() => setShowForm(true)}
          className="px-4 py-2 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00]"
        >
          + 반품/교환 등록
        </button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="전체" value={stats.total ?? 0} />
        <StatCard label="요청됨" value={stats.requested ?? 0} color="#FFD93D" />
        <StatCard label="승인됨" value={stats.approved ?? 0} color="#4C9AFF" />
        <StatCard label="완료됨" value={stats.completed ?? 0} color="#51CF66" />
      </div>

      {/* Create Form */}
      {showForm && (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4 space-y-3">
          <h3 className="font-semibold text-sm">반품/교환 등록</h3>
          <div className="grid grid-cols-2 gap-3">
            <FI label="주문 ID" value={form.order_id} onChange={(v) => setForm({ ...form, order_id: v })} />
            <div>
              <label className="text-xs text-[#666] mb-1 block">유형</label>
              <select
                value={form.type}
                onChange={(e) => setForm({ ...form, type: e.target.value })}
                className="w-full px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5]"
              >
                <option value="return">반품</option>
                <option value="exchange">교환</option>
                <option value="cancel">취소</option>
              </select>
            </div>
            <FI label="사유" value={form.reason} onChange={(v) => setForm({ ...form, reason: v })} />
            <FI label="수량" value={String(form.quantity)} onChange={(v) => setForm({ ...form, quantity: Number(v) })} type="number" />
            <FI label="요청 금액" value={String(form.requested_amount)} onChange={(v) => setForm({ ...form, requested_amount: Number(v) })} type="number" />
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 text-sm text-[#999]">취소</button>
            <button onClick={handleSubmit} className="px-4 py-1.5 bg-[#FF8C00] text-white text-sm rounded-lg font-medium">저장</button>
          </div>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <p className="text-sm text-[#666]">로딩 중...</p>
      ) : (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#666] border-b border-[#1A1A1A] bg-[#0E0E0E]">
                <th className="text-left px-4 py-2.5">주문 ID</th>
                <th className="text-left px-4 py-2.5">유형</th>
                <th className="text-left px-4 py-2.5">사유</th>
                <th className="text-right px-4 py-2.5">수량</th>
                <th className="text-right px-4 py-2.5">요청금액</th>
                <th className="text-left px-4 py-2.5">상태</th>
                <th className="text-left px-4 py-2.5">등록일</th>
                <th className="text-right px-4 py-2.5">작업</th>
              </tr>
            </thead>
            <tbody>
              {returns.map((r) => {
                const st = STATUS_MAP[r.status] || { label: r.status, bg: "rgba(100,100,100,0.2)", text: "#888" };
                return (
                  <tr key={r.id} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                    <td className="px-4 py-2.5 text-[#FF8C00]">{r.order_id}</td>
                    <td className="px-4 py-2.5">{TYPE_LABELS[r.type] || r.type}</td>
                    <td className="px-4 py-2.5 text-[#888]">{r.reason || "-"}</td>
                    <td className="px-4 py-2.5 text-right">{r.quantity}</td>
                    <td className="px-4 py-2.5 text-right">
                      {r.requested_amount ? `\u20A9${r.requested_amount.toLocaleString()}` : "-"}
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className="px-2 py-0.5 rounded text-xs font-medium"
                        style={{ background: st.bg, color: st.text }}
                      >
                        {st.label}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-[#555]">{r.created_at?.slice(0, 10) || "-"}</td>
                    <td className="px-4 py-2.5 text-right">
                      <ActionButtons
                        status={r.status}
                        onApprove={() => handleApprove(r.id)}
                        onReject={() => handleReject(r.id)}
                        onComplete={() => handleComplete(r.id)}
                        onCancel={() => handleCancel(r.id)}
                      />
                    </td>
                  </tr>
                );
              })}
              {returns.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-[#555]">
                    반품/교환 내역이 없습니다
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ActionButtons({
  status,
  onApprove,
  onReject,
  onComplete,
  onCancel,
}: {
  status: string;
  onApprove: () => void;
  onReject: () => void;
  onComplete: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex gap-1.5 justify-end">
      {status === "requested" && (
        <>
          <button onClick={onApprove} className="text-[#4C9AFF] text-xs hover:underline">승인</button>
          <button onClick={onReject} className="text-[#FF6B6B] text-xs hover:underline">거절</button>
          <button onClick={onCancel} className="text-[#888] text-xs hover:underline">취소</button>
        </>
      )}
      {status === "approved" && (
        <>
          <button onClick={onComplete} className="text-[#51CF66] text-xs hover:underline">완료</button>
          <button onClick={onCancel} className="text-[#888] text-xs hover:underline">취소</button>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value, color = "#FF8C00" }: { label: string; value: number; color?: string }) {
  return (
    <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4">
      <p className="text-xs text-[#666] mb-1">{label}</p>
      <p className="text-xl font-bold" style={{ color }}>{value}</p>
    </div>
  );
}

function FI({ label, value, onChange, type = "text" }: { label: string; value: string; onChange: (v: string) => void; type?: string }) {
  return (
    <div>
      <label className="text-xs text-[#666] mb-1 block">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5] focus:outline-none focus:border-[#FF8C00]"
      />
    </div>
  );
}
