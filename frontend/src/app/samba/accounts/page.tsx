"use client";

import { useEffect, useState, useCallback } from "react";
import { accountApi, type SambaMarketAccount } from "@/lib/samba/api/commerce";
import { showAlert, showConfirm } from '@/components/samba/Modal'

import { btn } from '@/lib/samba/buttons'
import { useTheme } from '@/lib/samba/useTheme'

export default function AccountsPage() {
  const c = useTheme()
  useEffect(() => { document.title = 'SAMBA-계정관리' }, [])
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ market_type: "coupang", seller_id: "", business_name: "" });

  const load = useCallback(async () => {
    setLoading(true);
    setAccounts(await accountApi.list().catch(() => []));
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSubmit = async () => {
    try {
      await accountApi.create(form);
      setShowForm(false);
      setForm({ market_type: "coupang", seller_id: "", business_name: "" });
      load();
    } catch (e) { showAlert(e instanceof Error ? e.message : '계정 저장 실패', 'error') }
  };

  const handleToggle = async (id: string) => {
    try { await accountApi.toggle(id); load(); }
    catch (e) { showAlert(e instanceof Error ? e.message : '상태 변경 실패', 'error') }
  };
  const handleDelete = async (id: string) => {
    if (!await showConfirm('삭제하시겠습니까?')) return
    try { await accountApi.delete(id); load(); }
    catch (e) { showAlert(e instanceof Error ? e.message : '삭제 실패', 'error') }
  };

  return (
    <div className="p-6 space-y-4" style={{ color: c.text }}>
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold">마켓 계정 관리</h2>
        <button onClick={() => setShowForm(true)} className="px-4 py-2 text-sm rounded-lg font-medium" style={{ ...btn('primary') }}>+ 계정 추가</button>
      </div>

      {showForm && (
        <div className="rounded-lg p-4 space-y-3" style={{ background: c.surface, border: `1px solid ${c.border}` }}>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs mb-1 block" style={{ color: c.textSub }}>마켓</label>
              <select value={form.market_type} onChange={(e) => setForm({ ...form, market_type: e.target.value })}
                className="w-full px-2.5 py-1.5 rounded text-sm" style={{ background: c.inputBg, border: `1px solid ${c.border}`, color: c.text }}>
                {["smartstore","coupang","11st","gmarket","auction","ssg","lotteon","lottehome","gsshop","homeand","hmall","kream","ktalpha"].map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            <FI label="판매자 ID" value={form.seller_id} onChange={(v) => setForm({ ...form, seller_id: v })} />
            <FI label="사업자명" value={form.business_name} onChange={(v) => setForm({ ...form, business_name: v })} />
          </div>
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 text-sm" style={{ ...btn('ghost') }}>취소</button>
            <button onClick={handleSubmit} className="px-4 py-1.5 text-sm rounded-lg font-medium" style={{ ...btn('primary') }}>저장</button>
          </div>
        </div>
      )}

      {loading ? <p className="text-sm" style={{ color: c.textMuted }}>로딩 중...</p> : (
        <div className="rounded-lg overflow-hidden" style={{ background: c.surface, border: `1px solid ${c.border}` }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: c.textMuted, borderBottom: `1px solid ${c.border}`, background: c.surfaceAlt }}>
                <th className="text-left px-4 py-2.5">마켓</th>
                <th className="text-left px-4 py-2.5">계정</th>
                <th className="text-left px-4 py-2.5">사업자명</th>
                <th className="text-left px-4 py-2.5">상태</th>
                <th className="text-right px-4 py-2.5">작업</th>
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id} style={{ borderBottom: `1px solid ${c.border}` }}>
                  <td className="px-4 py-2.5" style={{ color: c.text }}>{a.market_name || a.market_type}</td>
                  <td className="px-4 py-2.5">{a.account_label}</td>
                  <td className="px-4 py-2.5" style={{ color: c.textMuted }}>{a.business_name || "-"}</td>
                  <td className="px-4 py-2.5">
                    <button onClick={() => handleToggle(a.id)} className="px-2 py-0.5 rounded text-xs font-medium"
                      style={{ background: a.is_active ? 'rgba(56,154,56,0.15)' : 'rgba(216,68,68,0.15)', color: a.is_active ? c.success : c.danger }}>
                      {a.is_active ? "활성" : "비활성"}
                    </button>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <button onClick={() => handleDelete(a.id)} className="text-xs hover:underline" style={{ color: c.danger }}>삭제</button>
                  </td>
                </tr>
              ))}
              {accounts.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-8 text-center" style={{ color: c.textMuted }}>등록된 계정이 없습니다</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FI({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const c = useTheme()
  return (
    <div>
      <label className="text-xs mb-1 block" style={{ color: c.textSub }}>{label}</label>
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)}
        className="w-full px-2.5 py-1.5 rounded text-sm focus:outline-none" style={{ background: c.inputBg, border: `1px solid ${c.border}`, color: c.text }} />
    </div>
  );
}
