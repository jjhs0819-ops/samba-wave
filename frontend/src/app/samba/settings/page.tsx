"use client";

import { useEffect, useState, useCallback } from "react";
import { channelApi, type SambaChannel } from "@/lib/samba/api";

const CHANNEL_TYPES = [
  { value: "open-market", label: "오픈마켓", fee: 8.5 },
  { value: "mall", label: "종합몰", fee: 4.5 },
  { value: "resale", label: "리셀플랫폼", fee: 10 },
  { value: "overseas", label: "해외플랫폼", fee: 15 },
];

export default function SettingsPage() {
  const [channels, setChannels] = useState<SambaChannel[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", type: "open-market", platform: "", fee_rate: 8.5 });

  const loadChannels = useCallback(async () => {
    setLoading(true);
    try {
      setChannels(await channelApi.list());
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadChannels(); }, [loadChannels]);

  const handleSubmit = async () => {
    try {
      if (editingId) {
        await channelApi.update(editingId, form);
      } else {
        await channelApi.create(form);
      }
      setShowForm(false);
      setEditingId(null);
      loadChannels();
    } catch (e) {
      alert(e instanceof Error ? e.message : "저장 실패");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("삭제하시겠습니까?")) return;
    await channelApi.delete(id);
    loadChannels();
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">설정 - 판매처 관리</h2>
        <button
          onClick={() => { setShowForm(true); setEditingId(null); setForm({ name: "", type: "open-market", platform: "", fee_rate: 8.5 }); }}
          className="px-4 py-2 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00]"
        >
          + 판매처 추가
        </button>
      </div>

      {showForm && (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4 space-y-3">
          <h3 className="font-semibold text-sm">{editingId ? "판매처 수정" : "판매처 추가"}</h3>
          <div className="grid grid-cols-2 gap-3">
            <FormInput label="판매처명" value={form.name} onChange={(v) => setForm({ ...form, name: v })} />
            <div>
              <label className="text-xs text-[#666] mb-1 block">유형</label>
              <select
                value={form.type}
                onChange={(e) => {
                  const t = CHANNEL_TYPES.find((ct) => ct.value === e.target.value);
                  setForm({ ...form, type: e.target.value, fee_rate: t?.fee ?? form.fee_rate });
                }}
                className="w-full px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5]"
              >
                {CHANNEL_TYPES.map((ct) => (
                  <option key={ct.value} value={ct.value}>{ct.label}</option>
                ))}
              </select>
            </div>
            <FormInput label="플랫폼 (coupang, ssg ...)" value={form.platform} onChange={(v) => setForm({ ...form, platform: v })} />
            <FormInput label="수수료율(%)" value={String(form.fee_rate)} onChange={(v) => setForm({ ...form, fee_rate: Number(v) })} type="number" />
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
                <th className="text-left px-4 py-2.5">판매처명</th>
                <th className="text-left px-4 py-2.5">유형</th>
                <th className="text-left px-4 py-2.5">플랫폼</th>
                <th className="text-right px-4 py-2.5">수수료율</th>
                <th className="text-left px-4 py-2.5">상태</th>
                <th className="text-right px-4 py-2.5">작업</th>
              </tr>
            </thead>
            <tbody>
              {channels.map((ch) => (
                <tr key={ch.id} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                  <td className="px-4 py-2.5 text-[#FF8C00]">{ch.name}</td>
                  <td className="px-4 py-2.5 text-[#888]">
                    {CHANNEL_TYPES.find((ct) => ct.value === ch.type)?.label || ch.type}
                  </td>
                  <td className="px-4 py-2.5">{ch.platform}</td>
                  <td className="px-4 py-2.5 text-right text-[#FFB84D]">{ch.fee_rate}%</td>
                  <td className="px-4 py-2.5">
                    <span className="px-2 py-0.5 rounded text-xs" style={{ background: "rgba(81,207,102,0.15)", color: "#51CF66" }}>
                      {ch.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right space-x-2">
                    <button
                      onClick={() => { setEditingId(ch.id); setForm({ name: ch.name, type: ch.type, platform: ch.platform, fee_rate: ch.fee_rate }); setShowForm(true); }}
                      className="text-[#4C9AFF] hover:underline text-xs"
                    >수정</button>
                    <button onClick={() => handleDelete(ch.id)} className="text-[#FF6B6B] hover:underline text-xs">삭제</button>
                  </td>
                </tr>
              ))}
              {channels.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-[#555]">판매처가 없습니다</td></tr>
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
