"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { collectorApi, type SambaSearchFilter, type SambaPolicy } from "@/lib/samba/api/commerce";
import { showAlert, showConfirm } from "@/components/samba/Modal";
import { fmtNum } from "@/lib/samba/styles";
import { SOURCING_SEARCH_URLS } from "@/lib/samba/constants";
import { useTheme } from "@/lib/samba/useTheme";

interface Props {
  filters: SambaSearchFilter[];
  policies: SambaPolicy[];
  onReload: () => void;
}

export default function FilterConditionsTable({ filters, policies, onReload }: Props) {
  const c = useTheme();
  const router = useRouter();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");

  const handleRename = async (id: string) => {
    const name = editingName.trim();
    setEditingId(null);
    if (!name) return;
    try {
      await collectorApi.updateFilter(id, { name });
      onReload();
    } catch (e) {
      showAlert(`이름 수정 실패: ${e instanceof Error ? e.message : ""}`, "error");
    }
  };

  const handlePolicyChange = async (id: string, policyId: string) => {
    try {
      await collectorApi.updateFilter(id, { applied_policy_id: policyId || undefined });
      onReload();
    } catch (e) {
      showAlert(`정책 적용 실패: ${e instanceof Error ? e.message : ""}`, "error");
    }
  };

  const handleDuplicate = async (f: SambaSearchFilter) => {
    try {
      await collectorApi.duplicateFilter(f);
      showAlert("필터를 복사했습니다.", "success");
      onReload();
    } catch (e) {
      showAlert(`필터 복사 실패: ${e instanceof Error ? e.message : ""}`, "error");
    }
  };

  const handleDelete = async (f: SambaSearchFilter) => {
    if (!(await showConfirm(`"${f.name}" 필터를 삭제하시겠습니까?`))) return;
    try {
      await collectorApi.deleteFilter(f.id);
      onReload();
    } catch (e) {
      showAlert(`삭제 실패: ${e instanceof Error ? e.message : ""}`, "error");
    }
  };

  const cols = ["소싱사이트", "필터이름", "상품정책적용", "필터세부설정", "검색필터", "저장상품(휴지통/매출)", "추가기능", "최근수집일자"];

  return (
    <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: "8px", overflow: "hidden" }}>
      <div style={{ display: "flex", borderBottom: `1px solid ${c.border}`, background: c.surfaceAlt }}>
        {cols.map((h) => (
          <div key={h} style={{ flex: 1, padding: "0.5rem", fontSize: "0.72rem", fontWeight: 600, color: c.textMuted, textAlign: "center" }}>
            {h}
          </div>
        ))}
      </div>
      {filters.map((f) => {
        const kw = f.keyword || "";
        const kwIsUrl = kw.startsWith("http://") || kw.startsWith("https://");
        const linkUrl = kwIsUrl ? kw : (SOURCING_SEARCH_URLS[f.source_site] ? SOURCING_SEARCH_URLS[f.source_site] + encodeURIComponent(kw) : "");
        return (
          <div key={f.id} style={{ display: "flex", borderBottom: `1px solid ${c.border}`, alignItems: "center" }}>
            <div style={{ flex: 1, padding: "0.5rem", fontSize: "0.8rem", textAlign: "center" }}>{f.source_site}</div>
            <div style={{ flex: 1, padding: "0.5rem", fontSize: "0.8rem", textAlign: "center" }}>
              {editingId === f.id ? (
                <input
                  autoFocus
                  defaultValue={f.name}
                  onChange={(e) => setEditingName(e.target.value)}
                  onBlur={() => handleRename(f.id)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleRename(f.id); }}
                  style={{ width: "100%", fontSize: "0.8rem", padding: "2px 4px" }}
                />
              ) : (
                <span style={{ cursor: "pointer" }} onClick={() => { setEditingId(f.id); setEditingName(f.name); }}>{f.name}</span>
              )}
            </div>
            <div style={{ flex: 1, padding: "0.5rem", textAlign: "center" }}>
              <select
                defaultValue={f.applied_policy_id || ""}
                onChange={(e) => handlePolicyChange(f.id, e.target.value)}
                style={{ width: "100%", fontSize: "0.75rem", padding: "2px 4px" }}
              >
                <option value="">정책 선택</option>
                {policies.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <div style={{ flex: 1, padding: "0.5rem", textAlign: "center", fontSize: "0.75rem", color: c.textMuted }}>
              {f.min_price || f.max_price ? `${fmtNum(f.min_price ?? 0)}~${fmtNum(f.max_price ?? 0)}` : "-"}
            </div>
            <div style={{ flex: 1, padding: "0.5rem", textAlign: "center" }}>
              {linkUrl ? (
                <a href={linkUrl} target="_blank" rel="noopener noreferrer" style={{ fontSize: "0.72rem", color: c.link }}>바로가기</a>
              ) : <span style={{ color: c.textMuted, fontSize: "0.72rem" }}>-</span>}
            </div>
            <div style={{ flex: 1, padding: "0.5rem", textAlign: "center", fontSize: "0.75rem" }}>
              <span
                style={{ cursor: "pointer", color: c.primary, textDecoration: "underline" }}
                onClick={() => router.push(`/samba/products?search_filter_id=${f.id}`)}
              >{fmtNum(f.collected_count ?? 0)}</span>
              {" / "}{fmtNum(f.trashed_count ?? 0)}
              {" ("}{fmtNum(f.revenue_sum ?? 0)}원{")"}
            </div>
            <div style={{ flex: 1, padding: "0.5rem", textAlign: "center", display: "flex", gap: "4px", justifyContent: "center" }}>
              <button onClick={() => handleDuplicate(f)} style={{ fontSize: "0.7rem", padding: "2px 8px" }}>필터복사</button>
              <button onClick={() => handleDelete(f)} style={{ fontSize: "0.7rem", padding: "2px 8px", color: c.danger }}>삭제</button>
            </div>
            <div style={{ flex: 1, padding: "0.5rem", textAlign: "center", fontSize: "0.7rem", color: c.textMuted }}>
              {f.last_collected_at ? new Date(f.last_collected_at).toLocaleDateString("ko-KR") : "-"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
