"use client";

import { useEffect, useState, useCallback } from "react";
import { policyApi, type SambaPolicy, type PricePreview } from "@/lib/samba/api";

export default function PoliciesPage() {
  const [policies, setPolicies] = useState<SambaPolicy[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "새 정책", site_name: "" });

  // Price preview
  const [previewPolicyId, setPreviewPolicyId] = useState<string | null>(null);
  const [previewCost, setPreviewCost] = useState(100000);
  const [previewFeeRate, setPreviewFeeRate] = useState(8.5);
  const [preview, setPreview] = useState<PricePreview | null>(null);

  const loadPolicies = useCallback(async () => {
    setLoading(true);
    try {
      setPolicies(await policyApi.list());
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadPolicies(); }, [loadPolicies]);

  const handleSubmit = async () => {
    try {
      if (editingId) {
        await policyApi.update(editingId, form);
      } else {
        await policyApi.create(form);
      }
      setShowForm(false);
      setEditingId(null);
      loadPolicies();
    } catch (e) {
      alert(e instanceof Error ? e.message : "저장 실패");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("삭제하시겠습니까?")) return;
    await policyApi.delete(id);
    loadPolicies();
  };

  const handlePreview = async () => {
    if (!previewPolicyId) return;
    try {
      setPreview(await policyApi.calculatePrice(previewPolicyId, previewCost, previewFeeRate));
    } catch {
      setPreview(null);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">정책관리</h2>
        <button
          onClick={() => { setShowForm(true); setEditingId(null); setForm({ name: "새 정책", site_name: "" }); }}
          className="px-4 py-2 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00]"
        >
          + 정책 추가
        </button>
      </div>

      {showForm && (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4 space-y-3">
          <h3 className="font-semibold text-sm">{editingId ? "정책 수정" : "정책 추가"}</h3>
          <div className="grid grid-cols-2 gap-3">
            <FormInput label="정책명" value={form.name} onChange={(v) => setForm({ ...form, name: v })} />
            <FormInput label="소싱사이트" value={form.site_name} onChange={(v) => setForm({ ...form, site_name: v })} />
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 text-sm text-[#999]">취소</button>
            <button onClick={handleSubmit} className="px-4 py-1.5 bg-[#FF8C00] text-white text-sm rounded-lg font-medium">저장</button>
          </div>
        </div>
      )}

      {/* Price Calculator */}
      <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4">
        <h3 className="font-semibold text-sm mb-3 text-[#999]">가격 계산 미리보기</h3>
        <div className="flex items-end gap-3">
          <div>
            <label className="text-xs text-[#666] mb-1 block">정책 선택</label>
            <select
              value={previewPolicyId || ""}
              onChange={(e) => setPreviewPolicyId(e.target.value || null)}
              className="px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5]"
            >
              <option value="">선택</option>
              {policies.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <FormInput label="원가" value={String(previewCost)} onChange={(v) => setPreviewCost(Number(v))} type="number" />
          <FormInput label="수수료율(%)" value={String(previewFeeRate)} onChange={(v) => setPreviewFeeRate(Number(v))} type="number" />
          <button onClick={handlePreview} className="px-4 py-1.5 bg-[#4C9AFF] text-white text-sm rounded-lg font-medium mb-0.5">계산</button>
        </div>
        {preview && (
          <div className="mt-3 flex gap-6 text-sm">
            <div>원가: <span className="text-[#E5E5E5]">₩{preview.cost.toLocaleString()}</span></div>
            <div>판매가: <span className="text-[#FF8C00] font-bold">₩{preview.market_price.toLocaleString()}</span></div>
            <div>수익: <span className="text-[#51CF66]">₩{preview.profit.toLocaleString()}</span></div>
            <div>수익률: <span className="text-[#51CF66]">{preview.profit_rate}%</span></div>
          </div>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <p className="text-sm text-[#666]">로딩 중...</p>
      ) : (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#666] border-b border-[#1A1A1A] bg-[#0E0E0E]">
                <th className="text-left px-4 py-2.5">정책명</th>
                <th className="text-left px-4 py-2.5">소싱사이트</th>
                <th className="text-left px-4 py-2.5">마진율</th>
                <th className="text-left px-4 py-2.5">추가요금</th>
                <th className="text-left px-4 py-2.5">생성일</th>
                <th className="text-right px-4 py-2.5">작업</th>
              </tr>
            </thead>
            <tbody>
              {policies.map((p) => {
                const pricing = (p.pricing || {}) as Record<string, unknown>;
                return (
                  <tr key={p.id} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                    <td className="px-4 py-2.5 text-[#FF8C00]">{p.name}</td>
                    <td className="px-4 py-2.5 text-[#888]">{p.site_name || "-"}</td>
                    <td className="px-4 py-2.5 text-[#51CF66]">{String(pricing.marginRate ?? 15)}%</td>
                    <td className="px-4 py-2.5">₩{Number(pricing.extraCharge ?? 0).toLocaleString()}</td>
                    <td className="px-4 py-2.5 text-[#666]">{new Date(p.created_at).toLocaleDateString("ko-KR")}</td>
                    <td className="px-4 py-2.5 text-right space-x-2">
                      <button
                        onClick={() => { setEditingId(p.id); setForm({ name: p.name, site_name: p.site_name || "" }); setShowForm(true); }}
                        className="text-[#4C9AFF] hover:underline text-xs"
                      >수정</button>
                      <button onClick={() => handleDelete(p.id)} className="text-[#FF6B6B] hover:underline text-xs">삭제</button>
                    </td>
                  </tr>
                );
              })}
              {policies.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-[#555]">정책이 없습니다</td></tr>
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
