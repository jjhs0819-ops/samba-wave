"use client";

import { useEffect, useState, useCallback } from "react";
import { productApi, type SambaProduct } from "@/lib/samba/api";

export default function ProductsPage() {
  const [products, setProducts] = useState<SambaProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", source_url: "", source_price: 0, cost: 0, margin_rate: 30, category: "", description: "" });

  const loadProducts = useCallback(async () => {
    setLoading(true);
    try {
      const data = searchQuery
        ? await productApi.search(searchQuery)
        : await productApi.list(0, 200);
      setProducts(data);
    } catch {
      // ignore
    }
    setLoading(false);
  }, [searchQuery]);

  useEffect(() => { loadProducts(); }, [loadProducts]);

  const handleSubmit = async () => {
    try {
      if (editingId) {
        await productApi.update(editingId, form);
      } else {
        await productApi.create(form);
      }
      setShowForm(false);
      setEditingId(null);
      setForm({ name: "", source_url: "", source_price: 0, cost: 0, margin_rate: 30, category: "", description: "" });
      loadProducts();
    } catch (e) {
      alert(e instanceof Error ? e.message : "저장 실패");
    }
  };

  const handleEdit = (p: SambaProduct) => {
    setEditingId(p.id);
    setForm({
      name: p.name,
      source_url: p.source_url || "",
      source_price: p.source_price,
      cost: p.cost,
      margin_rate: p.margin_rate,
      category: p.category || "",
      description: p.description || "",
    });
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (!confirm("삭제하시겠습니까?")) return;
    await productApi.delete(id);
    loadProducts();
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">상품관리</h2>
        <button
          onClick={() => { setShowForm(true); setEditingId(null); setForm({ name: "", source_url: "", source_price: 0, cost: 0, margin_rate: 30, category: "", description: "" }); }}
          className="px-4 py-2 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00]"
        >
          + 상품 추가
        </button>
      </div>

      {/* Search */}
      <input
        type="text"
        placeholder="상품명, 소싱처, 브랜드 검색..."
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        className="w-full px-3 py-2 bg-[#111] border border-[#1A1A1A] rounded-lg text-sm text-[#E5E5E5] placeholder:text-[#555] focus:outline-none focus:border-[#FF8C00]"
      />

      {/* Form Modal */}
      {showForm && (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4 space-y-3">
          <h3 className="font-semibold text-sm">{editingId ? "상품 수정" : "상품 추가"}</h3>
          <div className="grid grid-cols-2 gap-3">
            <FormInput label="상품명" value={form.name} onChange={(v) => setForm({ ...form, name: v })} />
            <FormInput label="카테고리" value={form.category} onChange={(v) => setForm({ ...form, category: v })} />
            <FormInput label="소싱 URL" value={form.source_url} onChange={(v) => setForm({ ...form, source_url: v })} />
            <FormInput label="설명" value={form.description} onChange={(v) => setForm({ ...form, description: v })} />
            <FormInput label="소싱가" value={String(form.source_price)} onChange={(v) => setForm({ ...form, source_price: Number(v) })} type="number" />
            <FormInput label="원가" value={String(form.cost)} onChange={(v) => setForm({ ...form, cost: Number(v) })} type="number" />
            <FormInput label="마진율(%)" value={String(form.margin_rate)} onChange={(v) => setForm({ ...form, margin_rate: Number(v) })} type="number" />
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 text-sm text-[#999] hover:text-white">취소</button>
            <button onClick={handleSubmit} className="px-4 py-1.5 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00]">저장</button>
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
                <th className="text-left px-4 py-2.5">상품명</th>
                <th className="text-left px-4 py-2.5">카테고리</th>
                <th className="text-right px-4 py-2.5">소싱가</th>
                <th className="text-right px-4 py-2.5">원가</th>
                <th className="text-right px-4 py-2.5">마진율</th>
                <th className="text-left px-4 py-2.5">상태</th>
                <th className="text-right px-4 py-2.5">작업</th>
              </tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr key={p.id} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                  <td className="px-4 py-2.5">{p.name}</td>
                  <td className="px-4 py-2.5 text-[#888]">{p.category || "-"}</td>
                  <td className="px-4 py-2.5 text-right">₩{p.source_price.toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-right">₩{p.cost.toLocaleString()}</td>
                  <td className="px-4 py-2.5 text-right text-[#51CF66]">{p.margin_rate}%</td>
                  <td className="px-4 py-2.5">
                    <span className="px-2 py-0.5 rounded text-xs" style={{ background: "rgba(81,207,102,0.15)", color: "#51CF66" }}>
                      {p.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right space-x-2">
                    <button onClick={() => handleEdit(p)} className="text-[#4C9AFF] hover:underline text-xs">수정</button>
                    <button onClick={() => handleDelete(p.id)} className="text-[#FF6B6B] hover:underline text-xs">삭제</button>
                  </td>
                </tr>
              ))}
              {products.length === 0 && (
                <tr><td colSpan={7} className="px-4 py-8 text-center text-[#555]">상품이 없습니다</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FormInput({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
}) {
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
