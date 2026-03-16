"use client";

import { useEffect, useState, useCallback } from "react";
import { shipmentApi, accountApi, collectorApi, type SambaShipment, type SambaMarketAccount, type SambaCollectedProduct } from "@/lib/samba/api";

const STATUS_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  pending: { bg: "rgba(100,100,100,0.2)", text: "#888", label: "대기중" },
  updating: { bg: "rgba(76,154,255,0.15)", text: "#4C9AFF", label: "업데이트중" },
  transmitting: { bg: "rgba(255,211,61,0.15)", text: "#FFD93D", label: "전송중" },
  completed: { bg: "rgba(81,207,102,0.15)", text: "#51CF66", label: "완료" },
  partial: { bg: "rgba(255,140,0,0.15)", text: "#FF8C00", label: "부분완료" },
  failed: { bg: "rgba(255,107,107,0.15)", text: "#FF6B6B", label: "실패" },
};

export default function ShipmentsPage() {
  const [shipments, setShipments] = useState<SambaShipment[]>([]);
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([]);
  const [products, setProducts] = useState<SambaCollectedProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [selectedProducts, setSelectedProducts] = useState<string[]>([]);
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([]);
  const [updateItems, setUpdateItems] = useState(["price", "stock"]);

  const load = useCallback(async () => {
    setLoading(true);
    const [s, a, p] = await Promise.all([
      shipmentApi.list(0, 100).catch(() => []),
      accountApi.listActive().catch(() => []),
      collectorApi.listProducts(0, 200, "collected").catch(() => []),
    ]);
    setShipments(s);
    setAccounts(a);
    setProducts(p);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleStart = async () => {
    if (selectedProducts.length === 0 || selectedAccounts.length === 0) {
      alert("상품과 계정을 선택해주세요");
      return;
    }
    await shipmentApi.start(selectedProducts, updateItems, selectedAccounts);
    setShowForm(false);
    setSelectedProducts([]);
    setSelectedAccounts([]);
    load();
  };

  const handleRetry = async (id: string) => {
    await shipmentApi.retry(id);
    load();
  };

  const toggleItem = (arr: string[], setArr: (v: string[]) => void, id: string) => {
    setArr(arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id]);
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">마켓 전송</h2>
        <button onClick={() => setShowForm(!showForm)} className="px-4 py-2 bg-[#FF8C00] text-white text-sm rounded-lg font-medium hover:bg-[#E07B00]">
          + 새 전송
        </button>
      </div>

      {showForm && (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg p-4 space-y-4">
          <div>
            <h3 className="text-sm font-semibold mb-2 text-[#999]">전송할 상품 ({selectedProducts.length}개 선택)</h3>
            <div className="max-h-40 overflow-auto space-y-1">
              {products.map((p) => (
                <label key={p.id} className="flex items-center gap-2 text-xs cursor-pointer hover:bg-[#141414] px-2 py-1 rounded">
                  <input type="checkbox" checked={selectedProducts.includes(p.id)} onChange={() => toggleItem(selectedProducts, setSelectedProducts, p.id)} />
                  <span className="text-[#4C9AFF]">{p.source_site}</span>
                  <span className="truncate">{p.name}</span>
                </label>
              ))}
              {products.length === 0 && <p className="text-xs text-[#555]">수집 상태 상품이 없습니다</p>}
            </div>
          </div>
          <div>
            <h3 className="text-sm font-semibold mb-2 text-[#999]">전송 대상 계정 ({selectedAccounts.length}개 선택)</h3>
            <div className="flex flex-wrap gap-2">
              {accounts.map((a) => (
                <label key={a.id} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer border ${
                  selectedAccounts.includes(a.id) ? "border-[#FF8C00] bg-[#FF8C00]/10 text-[#FF8C00]" : "border-[#1A1A1A] text-[#888]"
                }`}>
                  <input type="checkbox" checked={selectedAccounts.includes(a.id)} onChange={() => toggleItem(selectedAccounts, setSelectedAccounts, a.id)} className="hidden" />
                  {a.account_label}
                </label>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-xs text-[#666]">업데이트 항목:</span>
            {["price", "stock", "image", "description"].map((item) => (
              <label key={item} className="flex items-center gap-1 text-xs cursor-pointer">
                <input type="checkbox" checked={updateItems.includes(item)} onChange={() => toggleItem(updateItems, setUpdateItems, item)} />
                {item}
              </label>
            ))}
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 text-sm text-[#999]">취소</button>
            <button onClick={handleStart} className="px-4 py-1.5 bg-[#FF8C00] text-white text-sm rounded-lg font-medium">전송 시작</button>
          </div>
        </div>
      )}

      {loading ? <p className="text-sm text-[#666]">로딩 중...</p> : (
        <div className="bg-[#111] border border-[#1A1A1A] rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#666] border-b border-[#1A1A1A] bg-[#0E0E0E]">
                <th className="text-left px-4 py-2.5">ID</th>
                <th className="text-left px-4 py-2.5">상품</th>
                <th className="text-left px-4 py-2.5">대상</th>
                <th className="text-left px-4 py-2.5">상태</th>
                <th className="text-left px-4 py-2.5">결과</th>
                <th className="text-right px-4 py-2.5">작업</th>
              </tr>
            </thead>
            <tbody>
              {shipments.map((s) => {
                const st = STATUS_STYLES[s.status] || STATUS_STYLES.pending;
                const results = s.transmit_result || {};
                const successCount = Object.values(results).filter((v) => v === "success").length;
                const failCount = Object.values(results).filter((v) => v === "failed").length;
                return (
                  <tr key={s.id} className="border-b border-[#1A1A1A]/50 hover:bg-[#141414]">
                    <td className="px-4 py-2.5 text-[#666] text-xs font-mono">{s.id.slice(0, 12)}...</td>
                    <td className="px-4 py-2.5">{s.product_id?.slice(0, 12) || "-"}</td>
                    <td className="px-4 py-2.5 text-xs">{(s.target_account_ids || []).length}개 계정</td>
                    <td className="px-4 py-2.5">
                      <span className="px-2 py-0.5 rounded text-xs font-medium" style={{ background: st.bg, color: st.text }}>
                        {st.label}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      {successCount > 0 && <span className="text-green-400 mr-2">{successCount}성공</span>}
                      {failCount > 0 && <span className="text-red-400">{failCount}실패</span>}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      {failCount > 0 && (
                        <button onClick={() => handleRetry(s.id)} className="text-[#4C9AFF] text-xs hover:underline">재시도</button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {shipments.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-[#555]">전송 기록이 없습니다</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
