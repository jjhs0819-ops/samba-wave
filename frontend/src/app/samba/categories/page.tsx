"use client";

import { useEffect, useState, useCallback } from "react";
import { categoryApi } from "@/lib/samba/api";

interface Mapping {
  id: string;
  source_site: string;
  source_category: string;
  target_mappings?: Record<string, string>;
  created_at: string;
}

export default function CategoriesPage() {
  const [mappings, setMappings] = useState<Mapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ source_site: "", source_category: "" });

  // Suggest
  const [suggestQuery, setSuggestQuery] = useState("");
  const [suggestMarket, setSuggestMarket] = useState("smartstore");
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setMappings((await categoryApi.listMappings().catch(() => [])) as Mapping[]);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async () => {
    await categoryApi.createMapping(form);
    setShowForm(false);
    setForm({ source_site: "", source_category: "" });
    load();
  };

  const handleDelete = async (id: string) => {
    if (!confirm("삭제?")) return;
    await categoryApi.deleteMapping(id);
    load();
  };

  const handleSuggest = async () => {
    if (!suggestQuery) return;
    const result = await categoryApi.suggest(suggestQuery, suggestMarket).catch(() => []);
    setSuggestions(result);
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">카테고리 매핑</h2>
        <button onClick={() => setShowForm(true)} className="px-4 py-2 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00]">+ 매핑 추가</button>
      </div>

      {showForm && (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <FI label="소싱사이트" value={form.source_site} onChange={(v) => setForm({ ...form, source_site: v })} />
            <FI label="소싱 카테고리" value={form.source_category} onChange={(v) => setForm({ ...form, source_category: v })} />
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 text-sm text-[#999]">취소</button>
            <button onClick={handleCreate} className="px-4 py-1.5 bg-[#FF8C00] text-white text-sm rounded-lg font-medium">저장</button>
          </div>
        </div>
      )}

      {/* Category Suggestion */}
      <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3 text-[#999]">카테고리 추천</h3>
        <div className="flex items-end gap-3">
          <FI label="소싱 카테고리" value={suggestQuery} onChange={setSuggestQuery} />
          <div>
            <label className="text-xs text-[#666] mb-1 block">마켓</label>
            <select value={suggestMarket} onChange={(e) => setSuggestMarket(e.target.value)}
              className="px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5]">
              {["smartstore","gmarket","coupang","ssg","kream"].map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <button onClick={handleSuggest} className="px-4 py-1.5 bg-[#4C9AFF] text-white text-sm rounded-lg font-medium mb-0.5">추천</button>
        </div>
        {suggestions.length > 0 && (
          <div className="mt-3 space-y-1">
            {suggestions.map((s, i) => (
              <div key={i} className="text-sm text-[#CCC] px-2 py-1 bg-[#0A0A0A] rounded">{s}</div>
            ))}
          </div>
        )}
      </div>

      {/* Mappings Table */}
      {loading ? <p className="text-sm text-[#666]">로딩 중...</p> : (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#666] border-b border-[#1A1A1A] bg-[#0E0E0E]">
                <th className="text-left px-4 py-2.5">소싱사이트</th>
                <th className="text-left px-4 py-2.5">소싱 카테고리</th>
                <th className="text-left px-4 py-2.5">마켓 매핑</th>
                <th className="text-right px-4 py-2.5">작업</th>
              </tr>
            </thead>
            <tbody>
              {mappings.map((m) => (
                <tr key={m.id} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                  <td className="px-4 py-2.5 text-[#4C9AFF]">{m.source_site}</td>
                  <td className="px-4 py-2.5">{m.source_category}</td>
                  <td className="px-4 py-2.5 text-xs text-[#888]">
                    {m.target_mappings ? Object.entries(m.target_mappings).map(([k, v]) => `${k}: ${v}`).join(" | ") : "-"}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button onClick={() => handleDelete(m.id)} className="text-[#FF6B6B] text-xs hover:underline">삭제</button>
                  </td>
                </tr>
              ))}
              {mappings.length === 0 && (
                <tr><td colSpan={4} className="px-4 py-8 text-center text-[#555]">카테고리 매핑이 없습니다</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FI({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div>
      <label className="text-xs text-[#666] mb-1 block">{label}</label>
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5] focus:outline-none focus:border-[#FF8C00]" />
    </div>
  );
}
