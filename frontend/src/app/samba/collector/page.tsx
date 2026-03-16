"use client";

import { useEffect, useState, useCallback } from "react";
import {
  collectorApi,
  type SambaSearchFilter,
  type SambaCollectedProduct,
} from "@/lib/samba/api";

const SITES = ["ABCmart","FOLDERStyle","GrandStage","GSShop","KREAM","LOTTEON","MUSINSA","Nike","OliveYoung","SSG"];

export default function CollectorPage() {
  const [filters, setFilters] = useState<SambaSearchFilter[]>([]);
  const [products, setProducts] = useState<SambaCollectedProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQ, setSearchQ] = useState("");
  const [showFilterForm, setShowFilterForm] = useState(false);
  const [filterForm, setFilterForm] = useState({ source_site: "MUSINSA", name: "", keyword: "" });

  const load = useCallback(async () => {
    setLoading(true);
    const [f, p] = await Promise.all([
      collectorApi.listFilters().catch(() => []),
      searchQ
        ? collectorApi.searchProducts(searchQ).catch(() => [])
        : collectorApi.listProducts(0, 100).catch(() => []),
    ]);
    setFilters(f);
    setProducts(p);
    setLoading(false);
  }, [searchQ]);

  useEffect(() => { load(); }, [load]);

  const handleCreateFilter = async () => {
    await collectorApi.createFilter(filterForm);
    setShowFilterForm(false);
    setFilterForm({ source_site: "MUSINSA", name: "", keyword: "" });
    load();
  };

  const handleDeleteFilter = async (id: string) => {
    if (!confirm("삭제?")) return;
    await collectorApi.deleteFilter(id);
    load();
  };

  const handleDeleteProduct = async (id: string) => {
    await collectorApi.deleteProduct(id);
    load();
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">상품수집</h2>
        <button onClick={() => setShowFilterForm(true)} className="px-4 py-2 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00]">
          + 수집 필터
        </button>
      </div>

      {/* Filter Form */}
      {showFilterForm && (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4 space-y-3">
          <h3 className="text-sm font-semibold">수집 필터 추가</h3>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-[#666] mb-1 block">소싱사이트</label>
              <select value={filterForm.source_site} onChange={(e) => setFilterForm({ ...filterForm, source_site: e.target.value })}
                className="w-full px-2.5 py-1.5 bg-[#0A0A0A] border border-[#1A1A1A] rounded text-sm text-[#E5E5E5]">
                {SITES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <FI label="필터명" value={filterForm.name} onChange={(v) => setFilterForm({ ...filterForm, name: v })} />
            <FI label="검색 키워드" value={filterForm.keyword} onChange={(v) => setFilterForm({ ...filterForm, keyword: v })} />
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowFilterForm(false)} className="px-3 py-1.5 text-sm text-[#999]">취소</button>
            <button onClick={handleCreateFilter} className="px-4 py-1.5 bg-[#FF8C00] text-white text-sm rounded-lg font-medium">저장</button>
          </div>
        </div>
      )}

      {/* Active Filters */}
      {filters.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {filters.map((f) => (
            <div key={f.id} className="flex items-center gap-2 px-3 py-1.5 bg-[#111] border border-[#1A1A1A] rounded-lg text-xs">
              <span className="text-[#FF8C00]">{f.source_site}</span>
              <span className="text-[#CCC]">{f.name}</span>
              {f.keyword && <span className="text-[#666]">({f.keyword})</span>}
              <button onClick={() => handleDeleteFilter(f.id)} className="text-[#FF6B6B] hover:text-red-400 ml-1">×</button>
            </div>
          ))}
        </div>
      )}

      {/* Search */}
      <input type="text" placeholder="수집 상품 검색..." value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
        className="w-full px-3 py-2 bg-[#111] border border-[#1A1A1A] rounded-lg text-sm text-[#E5E5E5] placeholder:text-[#555] focus:outline-none focus:border-[#FF8C00]" />

      {/* Products Table */}
      {loading ? <p className="text-sm text-[#666]">로딩 중...</p> : (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg overflow-hidden">
          <div className="px-4 py-2 border-b border-[#1A1A1A] text-xs text-[#666]">
            수집 상품 {products.length}건
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#666] border-b border-[#1A1A1A] bg-[#0E0E0E]">
                <th className="text-left px-4 py-2">소싱처</th>
                <th className="text-left px-4 py-2">상품명</th>
                <th className="text-right px-4 py-2">소싱가</th>
                <th className="text-right px-4 py-2">판매가</th>
                <th className="text-left px-4 py-2">상태</th>
                <th className="text-right px-4 py-2">작업</th>
              </tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr key={p.id} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                  <td className="px-4 py-2 text-[#4C9AFF]">{p.source_site}</td>
                  <td className="px-4 py-2 max-w-xs truncate">{p.name}</td>
                  <td className="px-4 py-2 text-right">₩{p.original_price.toLocaleString()}</td>
                  <td className="px-4 py-2 text-right text-[#FF8C00]">₩{p.sale_price.toLocaleString()}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      p.status === "registered" ? "bg-green-900/30 text-green-400" :
                      p.status === "saved" ? "bg-blue-900/30 text-blue-400" :
                      "bg-gray-800 text-gray-400"
                    }`}>{p.status}</span>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button onClick={() => handleDeleteProduct(p.id)} className="text-[#FF6B6B] text-xs hover:underline">삭제</button>
                  </td>
                </tr>
              ))}
              {products.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-[#555]">수집 상품이 없습니다</td></tr>
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
