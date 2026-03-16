"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import {
  collectorApi,
  policyApi,
  type SambaSearchFilter,
  type SambaPolicy,
} from "@/lib/samba/api";

const SITES = ["MUSINSA", "KREAM", "ABCmart", "FOLDERStyle", "GrandStage", "GSShop", "LOTTEON", "Nike", "OliveYoung", "SSG"];

const API_BASE =
  process.env.NEXT_PUBLIC_ENV === "development"
    ? (process.env.NEXT_PUBLIC_API_URL_DEV || "http://localhost:28080")
    : (process.env.NEXT_PUBLIC_API_URL_PROD || "http://localhost:28080");

function fmtDate(iso: string | undefined | null): string {
  if (!iso) return "-";
  const d = new Date(iso);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${y}.${m}.${day} ${h}:${min}`;
}

export default function CollectorPage() {
  const [filters, setFilters] = useState<SambaSearchFilter[]>([]);
  const [policies, setPolicies] = useState<SambaPolicy[]>([]);
  const [loading, setLoading] = useState(true);

  // URL collect
  const [collectUrl, setCollectUrl] = useState("");
  const [collecting, setCollecting] = useState(false);
  const [collectDetailImages, setCollectDetailImages] = useState(false);
  const [collectLog, setCollectLog] = useState<string[]>(["[대기] 수집 결과가 여기에 표시됩니다..."]);

  // Proxy & auth status
  const [proxyStatus, setProxyStatus] = useState<"checking" | "ok" | "error">("checking");
  const [proxyText, setProxyText] = useState("프록시 서버 확인 중...");
  const [musinsaAuth, setMusinsaAuth] = useState<"checking" | "ok" | "error">("checking");
  const [musinsaAuthText, setMusinsaAuthText] = useState("인증 상태 확인 중...");

  // Group table filters
  const [siteFilter, setSiteFilter] = useState("");
  const [sortBy, setSortBy] = useState("lastCollectedAt_desc");
  const [selectAll, setSelectAll] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const logRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [f, pol] = await Promise.all([
      collectorApi.listFilters().catch(() => []),
      policyApi.list().catch(() => []),
    ]);
    setFilters(f);
    setPolicies(pol);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Check proxy status
  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/samba/collector/proxy-status`);
        const data = await res.json();
        if (res.ok && data.status === "ok") {
          setProxyStatus("ok");
          setProxyText(data.message || "프록시 서버 정상 작동 중");
        } else {
          setProxyStatus("error");
          setProxyText(data.message || "프록시 서버 연결 실패");
        }
      } catch {
        setProxyStatus("error");
        setProxyText("백엔드 서버 연결 실패");
      }
    };
    check();
    // Musinsa auth check
    const checkAuth = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/samba/collector/musinsa-auth-status`);
        const data = await res.json();
        if (res.ok && data.status === "ok") {
          setMusinsaAuth("ok");
          setMusinsaAuthText(data.message || "무신사 인증 완료");
        } else {
          setMusinsaAuth("error");
          setMusinsaAuthText(data.message || "무신사 인증 필요");
        }
      } catch {
        setMusinsaAuth("error");
        setMusinsaAuthText("백엔드 서버 연결 실패");
      }
    };
    checkAuth();
  }, []);

  const addLog = useCallback((msg: string) => {
    const time = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setCollectLog((prev) => [...prev, `[${time}] ${msg}`]);
    setTimeout(() => {
      if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    }, 50);
  }, []);

  const handleCollectByUrl = async () => {
    if (!collectUrl.trim()) return;
    setCollecting(true);
    addLog(`수집 시작: ${collectUrl}`);
    try {
      const res = await fetch(`${API_BASE}/api/v1/samba/collector/collect-by-url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: collectUrl,
          collect_detail_images: collectDetailImages,
        }),
      });
      const data = await res.json();
      if (res.ok) {
        if (data.type === "search") {
          addLog(`검색 수집 완료: "${data.keyword}" -- ${data.total_found}건 발견, ${data.saved}건 저장${data.skipped_duplicates ? `, ${data.skipped_duplicates}건 중복 스킵` : ""}`);
        } else {
          addLog(`수집 완료: ${data.product?.name || data.id || "저장됨"}`);
        }
        setCollectUrl("");
        load();
      } else {
        addLog(`수집 실패: ${data.detail || "알 수 없는 오류"}`);
      }
    } catch (e) {
      addLog(`수집 오류: ${e instanceof Error ? e.message : "네트워크 오류"}`);
    }
    setCollecting(false);
  };

  const handleDeleteSelectedGroups = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`선택된 ${selectedIds.size}개 그룹을 삭제하시겠습니까?`)) return;
    for (const id of selectedIds) {
      await collectorApi.deleteFilter(id).catch(() => {});
    }
    setSelectedIds(new Set());
    setSelectAll(false);
    load();
  };

  const handleCollectGroups = async () => {
    if (selectedIds.size === 0) {
      addLog("수집할 그룹을 선택하세요.");
      return;
    }
    addLog(`${selectedIds.size}개 그룹 상품수집 시작...`);
    for (const id of selectedIds) {
      const f = filters.find((x) => x.id === id);
      if (!f) continue;
      addLog(`[${f.name}] 수집 요청 중...`);
      try {
        const res = await fetch(`${API_BASE}/api/v1/samba/collector/collect-filter/${id}`, { method: "POST" });
        const data = await res.json();
        if (res.ok) {
          addLog(`[${f.name}] 수집 완료: ${data.saved || 0}건 저장`);
        } else {
          addLog(`[${f.name}] 수집 실패: ${data.detail || "오류"}`);
        }
      } catch {
        addLog(`[${f.name}] 수집 오류`);
      }
    }
    load();
  };

  const handleClearLog = () => {
    setCollectLog(["로그가 초기화되었습니다."]);
  };

  const handleCopyLog = () => {
    const text = collectLog.join("\n");
    navigator.clipboard.writeText(text).catch(() => {});
  };

  const handleCheckboxToggle = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleSelectAll = (checked: boolean) => {
    setSelectAll(checked);
    if (checked) {
      setSelectedIds(new Set(displayedFilters.map((f) => f.id)));
    } else {
      setSelectedIds(new Set());
    }
  };

  const handlePolicyApply = async (filterId: string, policyId: string) => {
    await collectorApi.updateFilter(filterId, { applied_policy_id: policyId } as Partial<SambaSearchFilter>).catch(() => {});
    load();
  };

  // Filter and sort
  let displayedFilters = [...filters];
  if (siteFilter) {
    displayedFilters = displayedFilters.filter((f) => f.source_site === siteFilter);
  }
  const [sortField, sortDir] = sortBy.split("_");
  displayedFilters.sort((a, b) => {
    const va = (sortField === "lastCollectedAt" ? (a.last_collected_at || "") : (a.created_at || ""));
    const vb = (sortField === "lastCollectedAt" ? (b.last_collected_at || "") : (b.created_at || ""));
    return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
  });

  const allSites = [...new Set(filters.map((f) => f.source_site))].sort();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0" }}>
      {/* Proxy status banner */}
      <div style={{
        display: "flex", alignItems: "center", gap: "10px", padding: "10px 16px",
        borderRadius: "8px", marginBottom: "12px",
        background: "rgba(255,140,0,0.07)", border: "1px solid rgba(255,140,0,0.2)",
        fontSize: "0.82rem",
      }}>
        <span style={{
          width: "8px", height: "8px", borderRadius: "50%", flexShrink: 0,
          background: proxyStatus === "ok" ? "#51CF66" : proxyStatus === "error" ? "#FF6B6B" : "#555",
        }} />
        <span style={{ color: proxyStatus === "ok" ? "#51CF66" : "#888" }}>{proxyText}</span>
        <button
          onClick={() => {
            setProxyStatus("checking");
            setProxyText("프록시 서버 확인 중...");
            fetch(`${API_BASE}/api/v1/samba/collector/proxy-status`)
              .then((r) => r.json())
              .then((data) => {
                if (data.status === "ok") { setProxyStatus("ok"); setProxyText(data.message || "프록시 서버 정상 작동 중"); }
                else { setProxyStatus("error"); setProxyText(data.message || "프록시 서버 연결 실패"); }
              })
              .catch(() => { setProxyStatus("error"); setProxyText("백엔드 서버 연결 실패"); });
          }}
          style={{
            marginLeft: "auto", background: "transparent", border: "1px solid #3D3D3D",
            color: "#888", padding: "2px 10px", borderRadius: "4px", fontSize: "0.75rem", cursor: "pointer",
          }}
        >
          재확인
        </button>
      </div>

      {/* Musinsa auth status */}
      <div style={{
        display: "flex", alignItems: "center", gap: "8px", padding: "6px 14px",
        background: "rgba(20,20,20,0.6)", border: "1px solid #2D2D2D", borderRadius: "8px",
        fontSize: "0.78rem", marginBottom: "12px",
      }}>
        <span style={{
          width: "8px", height: "8px", borderRadius: "50%", flexShrink: 0,
          background: musinsaAuth === "ok" ? "#51CF66" : musinsaAuth === "error" ? "#FF6B6B" : "#555",
        }} />
        <span style={{ color: musinsaAuth === "ok" ? "#51CF66" : "#888" }}>{musinsaAuthText}</span>
      </div>

      {/* URL input area */}
      <div style={{
        background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
        padding: "1.25rem", marginBottom: "1rem",
      }}>
        <div style={{ display: "flex", gap: "0.75rem", marginBottom: "0.625rem" }}>
          <input
            type="url"
            value={collectUrl}
            onChange={(e) => setCollectUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCollectByUrl()}
            placeholder="카테고리/검색결과 페이지 URL (예: https://www.musinsa.com/app/goods/3900000)"
            style={{
              flex: 1, padding: "0.75rem 1rem", fontSize: "0.875rem",
              background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
              color: "#E5E5E5", outline: "none",
            }}
          />
          <button
            onClick={handleCollectByUrl}
            disabled={collecting}
            style={{
              background: "linear-gradient(135deg, #FF8C00, #FFB84D)", color: "#fff",
              padding: "0.75rem 1.5rem", borderRadius: "8px", fontWeight: 600,
              whiteSpace: "nowrap", cursor: collecting ? "not-allowed" : "pointer",
              border: "none", opacity: collecting ? 0.6 : 1,
            }}
          >
            {collecting ? "수집중..." : "그룹 생성"}
          </button>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "16px", marginTop: "4px" }}>
          <p style={{ fontSize: "0.8rem", color: "#888", flex: 1 }}>
            ** URL 입력 후 그룹 생성 -- 하단 검색그룹에서 상품수집을 실행하세요. 무신사 실제수집 시 수집 서버가 필요합니다.
          </p>
          <label style={{ display: "flex", alignItems: "center", gap: "6px", whiteSpace: "nowrap", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={collectDetailImages}
              onChange={(e) => setCollectDetailImages(e.target.checked)}
              style={{ accentColor: "#FF8C00", width: "14px", height: "14px", cursor: "pointer" }}
            />
            <span style={{ fontSize: "0.78rem", color: "#999" }}>상세페이지 이미지 수집</span>
          </label>
        </div>
      </div>

      {/* Collect log */}
      <div style={{
        background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
        overflow: "hidden", marginBottom: "1rem",
      }}>
        <div style={{
          padding: "8px 16px", borderBottom: "1px solid #2D2D2D",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "#C5C5C5" }}>수집 로그</span>
          <div style={{ display: "flex", gap: "4px" }}>
            <button onClick={handleCopyLog} style={{
              fontSize: "0.75rem", color: "#888", background: "transparent",
              border: "1px solid #3D3D3D", padding: "2px 10px", borderRadius: "4px", cursor: "pointer",
            }}>복사</button>
            <button onClick={handleClearLog} style={{
              fontSize: "0.75rem", color: "#888", background: "transparent",
              border: "1px solid #3D3D3D", padding: "2px 10px", borderRadius: "4px", cursor: "pointer",
            }}>초기화</button>
          </div>
        </div>
        <div
          ref={logRef}
          style={{
            height: "160px", overflowY: "auto", padding: "10px 16px",
            fontFamily: "monospace", fontSize: "0.78rem", color: "#8A95B0",
            background: "#080A10", lineHeight: 1.6,
          }}
        >
          {collectLog.map((line, i) => (
            <p key={i} style={{
              color: line.includes("완료") ? "#51CF66"
                : line.includes("실패") || line.includes("오류") ? "#FF6B6B"
                : line.includes("대기") || line.includes("초기화") ? "#555"
                : "#8A95B0",
              margin: 0,
            }}>
              {line}
            </p>
          ))}
        </div>
      </div>

      {/* Search group list section */}
      <div style={{ marginTop: "1.5rem" }}>
        {/* Section title + action buttons */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: "0.75rem", flexWrap: "wrap", gap: "8px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <h3 style={{ fontSize: "1rem", fontWeight: 700, color: "#E5E5E5", margin: 0 }}>검색그룹 목록</h3>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
            <button
              onClick={handleDeleteSelectedGroups}
              style={{
                background: "rgba(255,100,100,0.1)", border: "1px solid rgba(255,100,100,0.3)",
                color: "#FF6B6B", padding: "0.3rem 0.75rem", borderRadius: "6px", fontSize: "0.8rem", cursor: "pointer",
              }}
            >
              그룹 삭제
            </button>
            <button
              onClick={handleCollectGroups}
              style={{
                background: "rgba(255,140,0,0.1)", border: "1px solid rgba(255,140,0,0.35)",
                color: "#FF8C00", padding: "0.3rem 0.75rem", borderRadius: "6px", fontSize: "0.8rem", cursor: "pointer",
              }}
            >
              상품수집
            </button>
            <button style={{
              background: "rgba(81,207,102,0.1)", border: "1px solid rgba(81,207,102,0.3)",
              color: "#51CF66", padding: "0.3rem 0.75rem", borderRadius: "6px", fontSize: "0.8rem", cursor: "pointer",
            }}>
              AI이미지변경
            </button>
            <select style={{
              padding: "0.3rem 0.5rem", fontSize: "0.8rem",
              background: "rgba(22,22,22,0.95)", border: "1px solid #353535",
              color: "#C5C5C5", borderRadius: "6px", width: "auto",
            }}>
              <option>100개씩</option>
              <option>50개씩</option>
            </select>
            <select
              value={siteFilter}
              onChange={(e) => setSiteFilter(e.target.value)}
              style={{
                padding: "0.3rem 0.5rem", fontSize: "0.8rem",
                background: "rgba(22,22,22,0.95)", border: "1px solid #353535",
                color: "#C5C5C5", borderRadius: "6px", width: "auto",
              }}
            >
              <option value="">전체 사이트</option>
              {allSites.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value)}
              style={{
                padding: "0.3rem 0.5rem", fontSize: "0.8rem",
                background: "rgba(22,22,22,0.95)", border: "1px solid #353535",
                color: "#C5C5C5", borderRadius: "6px", width: "auto",
              }}
            >
              <option value="lastCollectedAt_desc">수집일 ▼</option>
              <option value="lastCollectedAt_asc">수집일 ▲</option>
              <option value="createdAt_desc">그룹생성일 ▼</option>
              <option value="createdAt_asc">그룹생성일 ▲</option>
            </select>
          </div>
        </div>

        {/* Policy priority notice */}
        <div style={{
          marginBottom: "0.75rem", padding: "0.5rem 0.875rem", borderRadius: "8px",
          background: "rgba(255,140,0,0.05)", border: "1px solid rgba(255,140,0,0.2)",
          fontSize: "0.8rem", color: "#888",
        }}>
          ※ 정책 우선순위: <span style={{ color: "#FF8C00" }}>[상품별 개별정책]</span> → <span style={{ color: "#FF8C00" }}>[카테고리 정책]</span> 순으로 적용됩니다
        </div>

        {/* Group table */}
        <div style={{
          background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
          overflow: "hidden",
        }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #2D2D2D" }}>
                <th style={{ width: "36px", padding: "0.75rem", textAlign: "center" }}>
                  <input
                    type="checkbox"
                    checked={selectAll}
                    onChange={(e) => handleSelectAll(e.target.checked)}
                    style={{ accentColor: "#FF8C00", cursor: "pointer" }}
                  />
                </th>
                <th style={{ padding: "0.75rem 0.75rem", textAlign: "center", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>사이트</th>
                <th style={{ padding: "0.75rem 0.75rem", textAlign: "center", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>그룹이름</th>
                <th style={{ padding: "0.75rem 0.75rem", textAlign: "center", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>링크</th>
                <th style={{ padding: "0.75rem 0.75rem", textAlign: "center", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>정책적용</th>
                <th style={{ padding: "0.75rem 0.75rem", textAlign: "center", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>수집상품수</th>
                <th style={{ padding: "0.75rem 0.75rem", textAlign: "center", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>요청상품수</th>
                <th style={{ padding: "0.75rem 0.75rem", textAlign: "center", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>그룹생성일</th>
                <th style={{ padding: "0.75rem 0.75rem", textAlign: "center", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>최근수집일</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9} style={{ padding: "2rem", textAlign: "center", color: "#666" }}>로딩 중...</td>
                </tr>
              ) : displayedFilters.length === 0 ? (
                <tr>
                  <td colSpan={9} style={{ padding: "2rem", textAlign: "center", color: "#666" }}>
                    수집하기를 실행하면 검색그룹이 자동으로 생성됩니다
                  </td>
                </tr>
              ) : (
                displayedFilters.map((f) => (
                  <tr key={f.id} style={{ borderBottom: "1px solid #2D2D2D" }}>
                    <td style={{ padding: "0.5rem 0.75rem", textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(f.id)}
                        onChange={(e) => handleCheckboxToggle(f.id, e.target.checked)}
                        style={{ accentColor: "#FF8C00", cursor: "pointer" }}
                      />
                    </td>
                    <td style={{ padding: "0.5rem 0.75rem" }}>
                      <span style={{
                        fontSize: "0.75rem", background: "rgba(255,140,0,0.1)",
                        border: "1px solid rgba(255,140,0,0.3)", color: "#FF8C00",
                        padding: "0.125rem 0.5rem", borderRadius: "4px", cursor: "pointer",
                      }}>
                        {f.source_site}
                      </span>
                    </td>
                    <td style={{ padding: "0.5rem 0.75rem", fontSize: "0.8125rem", color: "#E5E5E5" }}>
                      {f.name}
                    </td>
                    <td style={{ padding: "0.5rem 0.75rem", maxWidth: "360px" }}>
                      {f.keyword ? (
                        <span style={{
                          color: "#7EB5D0", fontSize: "0.75rem", fontFamily: "monospace",
                          display: "block", overflow: "hidden", textOverflow: "ellipsis",
                          whiteSpace: "nowrap", maxWidth: "320px",
                        }}>
                          {f.keyword}
                        </span>
                      ) : (
                        <span style={{ color: "#555", fontSize: "0.75rem" }}>-</span>
                      )}
                    </td>
                    <td style={{ padding: "0.5rem 0.75rem" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                        <select
                          defaultValue={(f as unknown as Record<string, string>).applied_policy_id || ""}
                          onChange={(e) => handlePolicyApply(f.id, e.target.value)}
                          style={{
                            width: "150px", padding: "0.3rem 0.5rem", fontSize: "0.8125rem",
                            background: "rgba(22,22,22,0.95)", border: "1px solid #353535",
                            color: "#C5C5C5", borderRadius: "5px",
                          }}
                        >
                          <option value="">정책 선택</option>
                          {policies.map((p) => (
                            <option key={p.id} value={p.id}>{p.name}</option>
                          ))}
                        </select>
                      </div>
                    </td>
                    <td style={{ padding: "0.5rem 0.75rem", textAlign: "center", fontSize: "0.8125rem", color: "#C5C5C5" }}>
                      <span style={{ color: "#FF8C00", fontWeight: 600, cursor: "pointer", textDecoration: "underline", textUnderlineOffset: "2px" }}>
                        {(f as unknown as Record<string, number>).collected_count ?? 0}
                      </span>개
                    </td>
                    <td style={{ padding: "0.5rem 0.75rem", textAlign: "center" }}>
                      <span style={{ fontSize: "0.8125rem", color: "#4C9AFF", fontWeight: 600 }}>0</span>
                    </td>
                    <td style={{ padding: "0.5rem 0.75rem", textAlign: "center" }}>
                      <span style={{ fontSize: "0.72rem", color: "#888" }}>{fmtDate(f.created_at)}</span>
                    </td>
                    <td style={{ padding: "0.5rem 0.75rem", textAlign: "center" }}>
                      <span style={{ fontSize: "0.72rem", color: "#888" }}>{fmtDate(f.last_collected_at)}</span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
