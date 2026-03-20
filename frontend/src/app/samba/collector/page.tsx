"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  collectorApi,
  policyApi,
  API_BASE,
  type SambaSearchFilter,
  type SambaPolicy,
  type RefreshResult,
} from "@/lib/samba/api";
import { showAlert, showConfirm } from '@/components/samba/Modal'

const SITES = [
  { id: 'MUSINSA', label: '무신사' },
  { id: 'KREAM', label: 'KREAM' },
  { id: 'FashionPlus', label: '패션플러스' },
  { id: 'Nike', label: 'Nike' },
  { id: 'Adidas', label: 'Adidas' },
  { id: 'ABCmart', label: 'ABC마트' },
  { id: 'GrandStage', label: '그랜드스테이지' },
  { id: 'OKmall', label: 'OKmall' },
  { id: 'LOTTEON', label: '롯데ON' },
  { id: 'GSShop', label: 'GSShop' },
  { id: 'ElandMall', label: '이랜드몰' },
  { id: 'SSF', label: 'SSF샵' },
]

const SITE_COLORS: Record<string, string> = {
  MUSINSA: '#4C9AFF',
  KREAM: '#51CF66',
  FashionPlus: '#CC5DE8',
  Nike: '#FF6B6B',
  Adidas: '#FFD93D',
  ABCmart: '#FF8C00',
  GrandStage: '#20C997',
  OKmall: '#F06595',
  LOTTEON: '#E10044',
  GSShop: '#6B5CE7',
  ElandMall: '#4ECDC4',
  SSF: '#845EF7',
}

const SITE_OPTIONS: Record<string, { id: string; label: string }[]> = {
  MUSINSA: [
    { id: 'excludePreorder', label: '예약배송 수집제외' },
    { id: 'excludeBoutique', label: '부티끄 수집제외' },
    { id: 'maxDiscount', label: '최대혜택가' },
  ],
  KREAM: [],
}

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
  const router = useRouter();
  const [filters, setFilters] = useState<SambaSearchFilter[]>([]);
  const [policies, setPolicies] = useState<SambaPolicy[]>([]);
  const [loading, setLoading] = useState(true);

  // URL collect
  const [collectUrl, setCollectUrl] = useState("");
  const [collecting, setCollecting] = useState(false);
  const [collectDetailImages, setCollectDetailImages] = useState(false);
  const [collectLog, setCollectLog] = useState<string[]>(["[대기] 수집 결과가 여기에 표시됩니다..."]);
  const [selectedSite, setSelectedSite] = useState("MUSINSA");
  const [checkedOptions, setCheckedOptions] = useState<Record<string, boolean>>({
    excludePreorder: true,
    excludeBoutique: true,
    maxDiscount: true,
  });

  // 일괄 갱신
  const [refreshing, setRefreshing] = useState(false)
  const [refreshResult, setRefreshResult] = useState<RefreshResult | null>(null)
  const [showRefreshModal, setShowRefreshModal] = useState(false)
  // AI 비용 추적
  const [lastAiUsage, setLastAiUsage] = useState<{ calls: number; tokens: number; cost: number; date: string } | null>(null)

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
  const collectAbortRef = useRef<AbortController | null>(null);

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

  // 프록시 & 무신사 인증 상태 확인
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/samba/collector/proxy-status`)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "ok") { setProxyStatus("ok"); setProxyText(data.message || "프록시 서버 정상 작동 중"); }
        else { setProxyStatus("error"); setProxyText(data.message || "프록시 서버 연결 실패"); }
      })
      .catch(() => { setProxyStatus("error"); setProxyText("백엔드 서버 연결 실패"); });

    fetch(`${API_BASE}/api/v1/samba/collector/musinsa-auth-status`)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "ok") { setMusinsaAuth("ok"); setMusinsaAuthText(data.message || "무신사 인증 완료"); }
        else { setMusinsaAuth("error"); setMusinsaAuthText(data.message || "무신사 인증 필요"); }
      })
      .catch(() => { setMusinsaAuth("error"); setMusinsaAuthText("백엔드 서버 연결 실패"); });
  }, []);

  const addLog = useCallback((msg: string) => {
    const time = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setCollectLog((prev) => [...prev, `[${time}] ${msg}`]);
    setTimeout(() => {
      if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
    }, 50);
  }, []);

  // URL → 그룹 생성만 (수집 X)
  const handleCreateGroup = async () => {
    if (!collectUrl.trim()) return;
    setCollecting(true);
    addLog(`그룹 생성 중: ${collectUrl}`);
    try {
      const site = selectedSite;

      // URL에서 키워드 추출 (소싱처별 파라미터)
      let keyword = ""
      try {
        const parsed = new URL(collectUrl)
        keyword = parsed.searchParams.get("keyword")
          || parsed.searchParams.get("searchWord")
          || parsed.searchParams.get("q")
          || parsed.searchParams.get("query")
          || parsed.searchParams.get("kwd")
          || parsed.searchParams.get("tq")
          || parsed.searchParams.get("tab")
          || ""
      } catch {
        // URL이 아닌 경우 검색어 자체를 키워드로 사용
        keyword = collectUrl.trim()
      }

      // 그룹이름 자동 생성: 소싱처_키워드
      const groupName = keyword ? `${site}_${keyword.replace(/\s+/g, '_')}` : `${site}_${new Date().toLocaleDateString("ko-KR")}`;

      // 무신사 옵션 URL 파라미터로 저장
      let keywordUrl = collectUrl;
      if (site === "MUSINSA") {
        try {
          const u = new URL(collectUrl);
          if (checkedOptions['excludePreorder']) u.searchParams.set("excludePreorder", "1");
          if (checkedOptions['excludeBoutique']) u.searchParams.set("excludeBoutique", "1");
          if (checkedOptions['maxDiscount']) u.searchParams.set("maxDiscount", "1");
          keywordUrl = u.toString();
        } catch { /* URL 파싱 실패 시 원본 유지 */ }
      }

      const created = await collectorApi.createFilter({
        source_site: site,
        name: groupName,
        keyword: keywordUrl,
        requested_count: 100,
      });

      addLog(`그룹 생성 완료: "${created.name}" (${site})`);
      setCollectUrl("");
      load();
    } catch (e) {
      addLog(`그룹 생성 실패: ${e instanceof Error ? e.message : "오류"}`);
    }
    setCollecting(false);
  };

  const handleDeleteSelectedGroups = async () => {
    if (selectedIds.size === 0) return;
    if (!await showConfirm(`선택된 ${selectedIds.size}개 그룹을 삭제하시겠습니까?`)) return;
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
    const abort = new AbortController();
    collectAbortRef.current = abort;
    setCollecting(true);
    addLog(`${selectedIds.size}개 그룹 상품수집 시작...`);
    for (const id of selectedIds) {
      if (abort.signal.aborted) break;
      const f = filters.find((x) => x.id === id);
      if (!f) continue;
      addLog(`[${f.name}] 수집 요청 중...`);
      try {
        const res = await fetch(
          `${API_BASE}/api/v1/samba/collector/collect-filter/${id}`,
          { method: "POST", signal: abort.signal }
        );

        if (!res.ok) {
          const errData = await res.json().catch(() => null);
          addLog(`[${f.name}] 수집 실패: ${errData?.detail || `HTTP ${res.status}`}`);
          continue;
        }

        // SSE 스트리밍 수신
        const reader = res.body?.getReader();
        if (!reader) {
          addLog(`[${f.name}] 스트리밍 응답 없음`);
          continue;
        }

        const decoder = new TextDecoder();
        let buffer = '';
        let finalData: Record<string, unknown> | null = null;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            const match = line.match(/^data:\s*(.+)$/m);
            if (!match) continue;
            try {
              const evt = JSON.parse(match[1]);
              if (evt.event === 'log' || evt.event === 'product') {
                addLog(`[${f.name}] ${evt.message}`);
              } else if (evt.event === 'done') {
                finalData = evt;
              }
            } catch { /* JSON 파싱 실패 무시 */ }
          }
        }

        if (finalData) {
          addLog(`[${f.name}] 수집 완료: ${finalData.saved || 0}건 저장, ${finalData.enriched || 0}건 보강`);
          const enrichedCount = finalData.enriched || 0
          if (enrichedCount > 0) {
            setLastAiUsage(prev => ({
              calls: (prev?.calls || 0) + enrichedCount,
              tokens: (prev?.tokens || 0) + enrichedCount * 1800,
              cost: (prev?.cost || 0) + enrichedCount * 15,
              date: new Date().toLocaleTimeString(),
            }))
          }
        }
      } catch (e) {
        if ((e as Error).name === 'AbortError') {
          addLog('수집이 중단되었습니다.');
          break;
        }
        addLog(`[${f.name}] 수집 오류: ${(e as Error).message}`);
      }
    }
    setCollecting(false);
    collectAbortRef.current = null;
    load();
  };

  const handleStopCollect = () => {
    collectAbortRef.current?.abort();
    addLog('수집 중단 요청...');
  };

  const handleClearLog = () => { setCollectLog(["로그가 초기화되었습니다."]); };
  const handleCopyLog = () => { navigator.clipboard.writeText(collectLog.join("\n")).catch(() => {}); };

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
    setSelectedIds(checked ? new Set(displayedFilters.map((f) => f.id)) : new Set());
  };

  const handlePolicyApply = async (filterId: string, policyId: string) => {
    try {
      await collectorApi.updateFilter(filterId, { applied_policy_id: policyId } as Partial<SambaSearchFilter>)
    } catch (e) {
      console.error('정책 적용 실패:', e)
      showAlert('정책 적용에 실패했습니다.', 'error')
      return
    }
    load();
  };

  // 그룹이름 수정
  const handleUpdateGroupName = async (filterId: string, newName: string) => {
    if (!newName.trim()) return;
    try {
      await collectorApi.updateFilter(filterId, { name: newName.trim() })
    } catch (e) {
      console.error('그룹이름 수정 실패:', e)
      showAlert('그룹이름 수정에 실패했습니다.', 'error')
      return
    }
    load();
  };

  // 요청상품수 수정
  const handleUpdateRequestedCount = async (filterId: string, count: number) => {
    if (isNaN(count) || count < 1) return;
    try {
      await collectorApi.updateFilter(filterId, { requested_count: count })
    } catch (e) {
      console.error('요청수 변경 실패:', e)
      showAlert('요청수 변경에 실패했습니다.', 'error')
      return
    }
    load();
  };

  // 수집상품수 클릭 → 상품관리 이동
  const handleGoToProducts = (f: SambaSearchFilter) => {
    const count = (f as unknown as Record<string, number>).collected_count ?? 0;
    if (count === 0) return;
    router.push(`/samba/products?search_filter_id=${f.id}&group_name=${encodeURIComponent(f.name)}`);
  };

  // 일괄 갱신 핸들러
  const handleRefresh = async () => {
    setRefreshing(true)
    addLog('일괄 갱신 시작...')
    try {
      // 선택된 그룹이 있으면 해당 그룹의 상품만, 없으면 전체
      const result = await collectorApi.refresh(undefined, true)
      setRefreshResult(result)
      setShowRefreshModal(true)
      addLog(
        `갱신 완료: ${result.refreshed}건 갱신, ${result.changed}건 변동, ` +
        `${result.sold_out}건 품절, ${result.retransmitted}건 재전송`
      )
      load()
    } catch (e) {
      addLog(`갱신 실패: ${e instanceof Error ? e.message : '오류'}`)
      showAlert('일괄 갱신에 실패했습니다.', 'error')
    }
    setRefreshing(false)
  }

  // Filter and sort
  let displayedFilters = [...filters];
  if (siteFilter) displayedFilters = displayedFilters.filter((f) => f.source_site === siteFilter);
  const [sortField, sortDir] = sortBy.split("_");
  displayedFilters.sort((a, b) => {
    const va = sortField === "lastCollectedAt" ? (a.last_collected_at || "") : (a.created_at || "");
    const vb = sortField === "lastCollectedAt" ? (b.last_collected_at || "") : (b.created_at || "");
    return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
  });

  const allSites = [...new Set(filters.map((f) => f.source_site))].sort();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0" }}>
      {/* 프록시 상태 배너 */}
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

      {/* 무신사 인증 배너 */}
      <div style={{
        background: "rgba(20,20,20,0.6)", border: "1px solid #2D2D2D", borderRadius: "8px",
        fontSize: "0.78rem", marginBottom: "12px", overflow: "hidden",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "6px 14px" }}>
          <span style={{
            width: "8px", height: "8px", borderRadius: "50%", flexShrink: 0,
            background: musinsaAuth === "ok" ? "#51CF66" : musinsaAuth === "error" ? "#FF6B6B" : "#555",
          }} />
          <span style={{ color: musinsaAuth === "ok" ? "#51CF66" : "#888" }}>{musinsaAuthText}</span>
        </div>
      </div>

      {/* 소싱처 선택 + URL 입력 영역 */}
      <div style={{
        background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
        padding: "1.25rem", marginBottom: "1rem",
      }}>
        {/* 소싱처 선택 버튼 */}
        <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "0.875rem" }}>
          {/* 1행: 소싱처 버튼 전체 */}
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
            {SITES.map((site) => (
              <button
                key={site.id}
                onClick={() => {
                  setSelectedSite(site.id)
                  setCollectUrl("")
                  setCheckedOptions(site.id === 'MUSINSA'
                    ? { excludePreorder: true, excludeBoutique: true, maxDiscount: true }
                    : {}
                  )
                }}
                style={{
                  padding: "0.35rem 0.875rem", borderRadius: "20px", fontSize: "0.8rem",
                  fontWeight: selectedSite === site.id ? 700 : 400, cursor: "pointer",
                  border: selectedSite === site.id ? "1px solid #FF8C00" : "1px solid #3D3D3D",
                  background: selectedSite === site.id ? "rgba(255,140,0,0.15)" : "transparent",
                  color: selectedSite === site.id ? "#FF8C00" : "#C5C5C5",
                  transition: "all 0.15s",
                }}
              >{site.label}</button>
            ))}
          </div>
          {/* 2행: 선택된 소싱처 검색 조건 체크박스 (동적) */}
          {(SITE_OPTIONS[selectedSite] || []).length > 0 && (
            <div style={{ display: "flex", gap: "14px", paddingLeft: "4px" }}>
              {(SITE_OPTIONS[selectedSite] || []).map((opt) => (
                <label key={opt.id} style={{ display: "flex", alignItems: "center", gap: "5px", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={!!checkedOptions[opt.id]}
                    onChange={(e) => setCheckedOptions((prev) => ({ ...prev, [opt.id]: e.target.checked }))}
                    style={{ accentColor: "#FF8C00", width: "13px", height: "13px", cursor: "pointer" }}
                  />
                  <span style={{ fontSize: "0.78rem", color: "#999" }}>{opt.label}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        {/* URL 입력 */}
        <div style={{ display: "flex", gap: "0.75rem", marginBottom: "0.625rem" }}>
          <input
            type="url"
            value={collectUrl}
            onChange={(e) => setCollectUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleCreateGroup()}
            placeholder={
              selectedSite === "MUSINSA" ? "https://www.musinsa.com/search/goods?keyword=나이키" :
              selectedSite === "KREAM" ? "https://kream.co.kr/search?keyword=나이키" :
              "URL을 입력하세요"
            }
            style={{
              flex: 1, padding: "0.75rem 1rem", fontSize: "0.875rem",
              background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
              color: "#E5E5E5", outline: "none",
            }}
          />
          <button
            onClick={handleCreateGroup}
            disabled={collecting}
            style={{
              background: "linear-gradient(135deg, #FF8C00, #FFB84D)", color: "#fff",
              padding: "0.75rem 1.5rem", borderRadius: "8px", fontWeight: 600,
              whiteSpace: "nowrap", cursor: collecting ? "not-allowed" : "pointer",
              border: "none", opacity: collecting ? 0.6 : 1,
            }}
          >
            {collecting ? "생성중..." : "그룹 생성"}
          </button>
        </div>
        <p style={{ fontSize: "0.8rem", color: "#888", marginTop: "4px" }}>
          ** URL 입력 후 그룹 생성 → 하단 검색그룹에서 상품수집 실행
        </p>
      </div>

      {/* 수집 로그 */}
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
            {collecting && (
              <button onClick={handleStopCollect} style={{
                fontSize: "0.75rem", color: "#FF6B6B", background: "rgba(255,100,100,0.1)",
                border: "1px solid rgba(255,100,100,0.4)", padding: "2px 10px", borderRadius: "4px", cursor: "pointer",
              }}>수집 중단</button>
            )}
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
            fontFamily: "monospace", fontSize: "0.78rem", color: "#8A95B0", zoom: "0.7",
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

      {/* 검색그룹 목록 */}
      <div style={{ marginTop: "1.5rem" }}>
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
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              style={{
                background: refreshing ? "rgba(76,154,255,0.05)" : "rgba(76,154,255,0.1)",
                border: "1px solid rgba(76,154,255,0.35)",
                color: "#4C9AFF", padding: "0.3rem 0.75rem", borderRadius: "6px",
                fontSize: "0.8rem", cursor: refreshing ? "not-allowed" : "pointer",
                opacity: refreshing ? 0.6 : 1,
              }}
            >
              {refreshing ? '갱신중...' : '일괄 갱신'}
            </button>
            {/* AI 비용 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', padding: '0.25rem 0.625rem', background: 'rgba(167,139,250,0.08)', border: '1px solid rgba(167,139,250,0.2)', borderRadius: '6px' }}>
              <span style={{ fontSize: '0.72rem', color: '#A78BFA', fontWeight: 600 }}>AI 비용</span>
              <span style={{ fontSize: '0.72rem', color: '#E5E5E5' }}>
                예상 <span style={{ color: '#FFB84D', fontWeight: 700 }}>₩15</span>
                <span style={{ color: '#888' }}> (1회)</span>
              </span>
            </div>
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

        <div style={{
          marginBottom: "0.75rem", padding: "0.5rem 0.875rem", borderRadius: "8px",
          background: "rgba(255,140,0,0.05)", border: "1px solid rgba(255,140,0,0.2)",
          fontSize: "0.8rem", color: "#888",
        }}>
          ※ 정책 우선순위: <span style={{ color: "#FF8C00" }}>[상품별 개별정책]</span> → <span style={{ color: "#FF8C00" }}>[카테고리 정책]</span> 순으로 적용됩니다
        </div>

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
                displayedFilters.map((f) => {
                  const collectedCount = (f as unknown as Record<string, number>).collected_count ?? 0;
                  return (
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
                          fontSize: "0.75rem",
                          background: `${SITE_COLORS[f.source_site] || '#FF8C00'}15`,
                          border: `1px solid ${SITE_COLORS[f.source_site] || '#FF8C00'}50`,
                          color: SITE_COLORS[f.source_site] || '#FF8C00',
                          padding: "0.125rem 0.5rem", borderRadius: "4px", cursor: "pointer",
                        }}>
                          {f.source_site}
                        </span>
                      </td>
                      {/* 그룹이름 - 수정 가능 인풋 */}
                      <td style={{ padding: "0.5rem 0.75rem" }}>
                        <input
                          key={f.id + f.name}
                          defaultValue={f.name}
                          onBlur={(e) => {
                            if (e.target.value !== f.name) handleUpdateGroupName(f.id, e.target.value);
                          }}
                          style={{
                            background: "transparent", border: "1px solid #3D3D3D",
                            color: "#E5E5E5", fontSize: "0.8125rem", padding: "0.15rem 0.4rem",
                            borderRadius: "4px", width: "100%", outline: "none",
                            transition: "border-color 0.15s",
                          }}
                          onFocus={(e) => { e.currentTarget.style.borderColor = "#FF8C00"; }}
                          onBlurCapture={(e) => { e.currentTarget.style.borderColor = "#3D3D3D"; }}
                        />
                      </td>
                      <td style={{ padding: "0.5rem 0.75rem", maxWidth: "360px" }}>
                        {f.keyword ? (
                          <a
                            href={f.keyword}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              color: "#7EB5D0", fontSize: "0.75rem", fontFamily: "monospace",
                              display: "block", overflow: "hidden", textOverflow: "ellipsis",
                              whiteSpace: "nowrap", maxWidth: "320px",
                              textDecoration: "underline", textUnderlineOffset: "2px",
                            }}
                          >
                            {f.keyword}
                          </a>
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
                      {/* 수집상품수 - 클릭 시 상품관리 이동 */}
                      <td style={{ padding: "0.5rem 0.75rem", textAlign: "center", fontSize: "0.8125rem", color: "#C5C5C5" }}>
                        <span
                          onClick={() => handleGoToProducts(f)}
                          style={{
                            color: collectedCount > 0 ? "#FF8C00" : "#555",
                            fontWeight: 600,
                            cursor: collectedCount > 0 ? "pointer" : "default",
                            textDecoration: collectedCount > 0 ? "underline" : "none",
                            textUnderlineOffset: "2px",
                          }}
                        >
                          {collectedCount}
                        </span>개
                      </td>
                      {/* 요청상품수 - 수정 가능 인풋 */}
                      <td style={{ padding: "0.5rem 0.75rem", textAlign: "center" }}>
                        <input
                          key={f.id + (f.requested_count ?? 100)}
                          type="text"
                          inputMode="numeric"
                          pattern="[0-9]*"
                          defaultValue={f.requested_count ?? 100}
                          onBlur={(e) => {
                            const v = parseInt(e.target.value, 10);
                            if (!isNaN(v) && v !== (f.requested_count ?? 100)) handleUpdateRequestedCount(f.id, v);
                          }}
                          style={{
                            width: "60px", textAlign: "center",
                            background: "transparent", border: "1px solid #3D3D3D",
                            color: "#4C9AFF", fontSize: "0.8125rem", fontWeight: 600,
                            padding: "0.15rem 0.25rem", borderRadius: "4px", outline: "none",
                            transition: "border-color 0.15s",
                          }}
                          onFocus={(e) => { e.currentTarget.style.borderColor = "#4C9AFF"; }}
                          onBlurCapture={(e) => { e.currentTarget.style.borderColor = "#3D3D3D"; }}
                        />
                      </td>
                      <td style={{ padding: "0.5rem 0.75rem", textAlign: "center" }}>
                        <span style={{ fontSize: "0.72rem", color: "#888" }}>{fmtDate(f.created_at)}</span>
                      </td>
                      <td style={{ padding: "0.5rem 0.75rem", textAlign: "center" }}>
                        <span style={{ fontSize: "0.72rem", color: "#888" }}>{fmtDate(f.last_collected_at)}</span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 갱신 결과 모달 */}
      {showRefreshModal && refreshResult && (
        <div
          onClick={() => setShowRefreshModal(false)}
          style={{
            position: "fixed", inset: 0, zIndex: 9999,
            background: "rgba(0,0,0,0.6)", display: "flex",
            alignItems: "center", justifyContent: "center",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#1A1A1A", border: "1px solid #2D2D2D",
              borderRadius: "12px", padding: "1.5rem", minWidth: "360px",
              maxWidth: "440px",
            }}
          >
            <h3 style={{
              fontSize: "1rem", fontWeight: 700, color: "#E5E5E5",
              marginBottom: "1rem", margin: 0, paddingBottom: "0.75rem",
              borderBottom: "1px solid #2D2D2D",
            }}>
              일괄 갱신 결과
            </h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.625rem", marginTop: "1rem" }}>
              {[
                { label: "전체 대상", value: refreshResult.total, color: "#C5C5C5" },
                { label: "갱신 완료", value: refreshResult.refreshed, color: "#51CF66" },
                { label: "가격/재고 변동", value: refreshResult.changed, color: "#FFD93D" },
                { label: "품절 전환", value: refreshResult.sold_out, color: "#FF6B6B" },
                { label: "자동 재전송", value: refreshResult.retransmitted, color: "#4C9AFF" },
                { label: "확장앱 필요", value: refreshResult.needs_extension.length, color: "#CC5DE8" },
                { label: "오류", value: refreshResult.errors, color: "#FF6B6B" },
              ].map((item) => (
                <div key={item.label} style={{
                  display: "flex", justifyContent: "space-between",
                  alignItems: "center", padding: "0.375rem 0",
                }}>
                  <span style={{ fontSize: "0.85rem", color: "#999" }}>{item.label}</span>
                  <span style={{ fontSize: "0.95rem", fontWeight: 700, color: item.color }}>
                    {item.value}건
                  </span>
                </div>
              ))}
            </div>
            <button
              onClick={() => setShowRefreshModal(false)}
              style={{
                width: "100%", marginTop: "1.25rem", padding: "0.625rem",
                background: "rgba(255,140,0,0.15)", border: "1px solid rgba(255,140,0,0.35)",
                color: "#FF8C00", borderRadius: "8px", fontSize: "0.85rem",
                fontWeight: 600, cursor: "pointer",
              }}
            >
              확인
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
