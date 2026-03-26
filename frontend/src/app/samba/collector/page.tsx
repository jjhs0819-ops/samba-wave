"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  collectorApi,
  policyApi,
  proxyApi,
  aiSourcingApi,
  API_BASE,
  type SambaSearchFilter,
  type SambaPolicy,
  type RefreshResult,
  type AISourcingResult,
  type AISourcingCombination,
} from "@/lib/samba/api";
import { showAlert, showConfirm } from '@/components/samba/Modal'

const SITES = [
  { id: 'MUSINSA', label: '무신사' },
  { id: 'KREAM', label: 'KREAM' },
  { id: 'DANAWA', label: '다나와' },
  { id: 'FashionPlus', label: '패션플러스' },
  { id: 'Nike', label: 'Nike' },
  { id: 'Adidas', label: 'Adidas' },
  { id: 'ABCmart', label: 'ABC마트' },
  { id: 'GrandStage', label: '그랜드스테이지' },
  { id: 'OKmall', label: 'OKmall' },
  { id: 'SSG', label: '신세계몰' },
  { id: 'LOTTEON', label: '롯데ON' },
  { id: 'GSShop', label: 'GSShop' },
  { id: 'ElandMall', label: '이랜드몰' },
  { id: 'SSF', label: 'SSF샵' },
]

const SITE_COLORS: Record<string, string> = {
  MUSINSA: '#4C9AFF',
  KREAM: '#51CF66',
  DANAWA: '#FF922B',
  FashionPlus: '#CC5DE8',
  Nike: '#FF6B6B',
  Adidas: '#FFD93D',
  ABCmart: '#FF8C00',
  GrandStage: '#20C997',
  OKmall: '#F06595',
  SSG: '#FF5A2E',
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
  SSG: [
    { id: 'maxDiscount', label: '최대혜택가' },
  ],
  LOTTEON: [
    { id: 'maxDiscount', label: '최대혜택가' },
  ],
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

  // AI 이미지 변환
  const [aiImgScope, setAiImgScope] = useState({ thumbnail: true, additional: false, detail: false })
  const [aiImgMode, setAiImgMode] = useState('background')
  const [aiModelPreset, setAiModelPreset] = useState('female_v1')
  const [aiImgTransforming, setAiImgTransforming] = useState(false)
  const [presetZoomImg, setPresetZoomImg] = useState<string | null>(null)

  // 이미지 필터링 (모델컷/연출컷/배너 제거)
  const [imgFiltering, setImgFiltering] = useState(false)
  const [imgFilterScope, setImgFilterScope] = useState<'images' | 'detail' | 'all'>('images')

  // Proxy & auth status
  const [proxyStatus, setProxyStatus] = useState<"checking" | "ok" | "error">("checking");
  const [proxyText, setProxyText] = useState("프록시 서버 확인 중...");
  const [musinsaAuth, setMusinsaAuth] = useState<"checking" | "ok" | "error">("checking");
  const [musinsaAuthText, setMusinsaAuthText] = useState("인증 상태 확인 중...");

  // 트리 + 드릴다운
  const [tree, setTree] = useState<SambaSearchFilter[]>([])
  const [drillSite, setDrillSite] = useState<string | null>(null)
  const [drillBrand, setDrillBrand] = useState<string | null>(null)
  const [drillGroup, setDrillGroup] = useState<string | null>(null)
  const [drillEntry, setDrillEntry] = useState<'site' | 'brand' | null>('site')

  // Group table filters
  const [siteFilter, setSiteFilter] = useState("");
  const [aiFilter, setAiFilter] = useState("");
  const [collectFilter, setCollectFilter] = useState("")
  const [marketRegFilter, setMarketRegFilter] = useState("")
  const [tagRegFilter, setTagRegFilter] = useState("")
  const [policyRegFilter, setPolicyRegFilter] = useState("")
  const [sortBy, setSortBy] = useState("lastCollectedAt_desc");
  const [selectAll, setSelectAll] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // AI 소싱기 상태
  const [showAiSourcingModal, setShowAiSourcingModal] = useState(false)
  const [aiSourcingStep, setAiSourcingStep] = useState<'config' | 'analyzing' | 'confirm'>('config')
  const [aiMonth, setAiMonth] = useState(new Date().getMonth() + 1) // 현재월
  const [aiMainCategory, setAiMainCategory] = useState('패션의류')
  const [aiExcelFile, setAiExcelFile] = useState<File | null>(null)
  const [aiTargetCount, setAiTargetCount] = useState(10000)
  const [aiAnalyzing, setAiAnalyzing] = useState(false)
  const [aiLogs, setAiLogs] = useState<string[]>([])
  const [aiResult, setAiResult] = useState<AISourcingResult | null>(null)
  const [aiSelectedCombos, setAiSelectedCombos] = useState<Set<number>>(new Set())
  const [aiExcludedBrands, setAiExcludedBrands] = useState<Set<string>>(new Set())
  const [aiExcludedKeywords, setAiExcludedKeywords] = useState<Set<string>>(new Set())
  const [aiMinCount, setAiMinCount] = useState(0) // 최소 상품수 필터
  const [aiCreating, setAiCreating] = useState(false)
  const [aiSourceSite, setAiSourceSite] = useState('MUSINSA') // 수집 소싱처 선택

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

  const loadTree = useCallback(async () => {
    try {
      const data = await collectorApi.getFilterTree()
      setTree(data)
    } catch { /* 트리 로드 실패 무시 */ }
  }, [])

  useEffect(() => { load(); loadTree(); }, [load, loadTree]);

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
      load(); loadTree();
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
    load(); loadTree();
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
          const saved = finalData.saved || 0
          addLog(`[${f.name}] 수집 완료: ${saved}건 저장`);
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
    load(); loadTree();
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
    load(); loadTree();
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
    load(); loadTree();
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
    load(); loadTree();
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
    const filterIds = selectedIds.size > 0 ? [...selectedIds] : undefined
    addLog(filterIds ? `선택된 ${filterIds.length}개 그룹 갱신 시작...` : '전체 일괄 갱신 시작...')
    try {
      const result = await collectorApi.refresh(undefined, true, filterIds)
      setRefreshResult(result)
      setShowRefreshModal(true)
      addLog(
        `갱신 완료: ${result.refreshed}건 갱신, ${result.changed}건 변동, ` +
        `${result.sold_out}건 품절, ${result.retransmitted}건 재전송`
      )
      load(); loadTree()
    } catch (e) {
      addLog(`갱신 실패: ${e instanceof Error ? e.message : '오류'}`)
      showAlert('일괄 갱신에 실패했습니다.', 'error')
    }
    setRefreshing(false)
  }

  // Filter and sort
  let displayedFilters = [...filters];
  if (siteFilter) displayedFilters = displayedFilters.filter((f) => f.source_site === siteFilter);
  if (aiFilter) {
    displayedFilters = displayedFilters.filter((f) => {
      const r = f as unknown as Record<string, number>
      const aiTagCount = r.ai_tagged_count ?? 0
      const aiImgCount = r.ai_image_count ?? 0
      switch (aiFilter) {
        case 'ai_tag_yes': return aiTagCount > 0
        case 'ai_tag_no': return aiTagCount === 0
        case 'ai_img_yes': return aiImgCount > 0
        case 'ai_img_no': return aiImgCount === 0
        default: return true
      }
    })
  }
  if (collectFilter) {
    displayedFilters = displayedFilters.filter((f) => {
      const r = f as unknown as Record<string, number>
      const cnt = r.collected_count ?? 0
      if (collectFilter === 'collected') return cnt > 0
      if (collectFilter === 'uncollected') return cnt === 0
      return true
    })
  }
  if (marketRegFilter) {
    displayedFilters = displayedFilters.filter((f) => {
      const r = f as unknown as Record<string, number>
      const cnt = r.market_registered_count ?? 0
      const total = r.collected_count ?? 0
      if (marketRegFilter === 'registered') return cnt > 0 && cnt >= total
      if (marketRegFilter === 'partial') return cnt > 0 && cnt < total
      if (marketRegFilter === 'unregistered') return cnt === 0
      return true
    })
  }
  if (tagRegFilter) {
    displayedFilters = displayedFilters.filter((f) => {
      const r = f as unknown as Record<string, number>
      const cnt = r.tag_applied_count ?? 0
      const total = r.collected_count ?? 0
      if (tagRegFilter === 'registered') return cnt > 0 && cnt >= total
      if (tagRegFilter === 'partial') return cnt > 0 && cnt < total
      if (tagRegFilter === 'unregistered') return cnt === 0
      return true
    })
  }
  if (policyRegFilter) {
    displayedFilters = displayedFilters.filter((f) => {
      const r = f as unknown as Record<string, number>
      const cnt = r.policy_applied_count ?? 0
      const total = r.collected_count ?? 0
      if (policyRegFilter === 'registered') return cnt > 0 && cnt >= total
      if (policyRegFilter === 'partial') return cnt > 0 && cnt < total
      if (policyRegFilter === 'unregistered') return cnt === 0
      return true
    })
  }
  const [sortField, sortDir] = sortBy.split("_");
  displayedFilters.sort((a, b) => {
    const va = sortField === "lastCollectedAt" ? (a.last_collected_at || "") : (a.created_at || "");
    const vb = sortField === "lastCollectedAt" ? (b.last_collected_at || "") : (b.created_at || "");
    return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
  });

  // 그룹명에서 브랜드/카테고리 파싱: "MUSINSA_나이키_운동화" → {brand:"나이키", category:"운동화"}
  const parseGroupName = (name: string, site: string) => {
    // 사이트 접두사 제거
    let rest = name
    const prefixes = [site + '_', site.toLowerCase() + '_', '무신사_']
    for (const p of prefixes) {
      if (rest.toLowerCase().startsWith(p.toLowerCase())) {
        rest = rest.slice(p.length)
        break
      }
    }
    // _로 분리
    const parts = rest.split('_')
    if (parts.length >= 2) {
      return { brand: parts[0], category: parts.slice(1).join('_') }
    }
    // 공백으로 분리 시도
    const spaceParts = rest.split(' ')
    if (spaceParts.length >= 2) {
      return { brand: spaceParts[0], category: spaceParts.slice(1).join(' ') }
    }
    return { brand: rest, category: '' }
  }


  return (
    <div style={{ color: '#E5E5E5' }}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0', padding: '0.5rem 1rem' }}>
      {/* 프록시 + 무신사 인증 상태 (1줄) */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '16px', padding: '6px 14px',
        borderRadius: '8px', marginBottom: '12px',
        background: 'rgba(255,140,0,0.07)', border: '1px solid rgba(255,140,0,0.2)',
        fontSize: '0.78rem',
      }}>
        <span style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
          background: proxyStatus === 'ok' ? '#51CF66' : proxyStatus === 'error' ? '#FF6B6B' : '#555',
        }} />
        <span style={{ color: proxyStatus === 'ok' ? '#51CF66' : '#888' }}>{proxyText}</span>
        <span style={{ color: '#2D2D2D' }}>|</span>
        <span style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
          background: musinsaAuth === 'ok' ? '#51CF66' : musinsaAuth === 'error' ? '#FF6B6B' : '#555',
        }} />
        <span style={{ color: musinsaAuth === 'ok' ? '#51CF66' : '#888' }}>{musinsaAuthText}</span>
        <button
          onClick={() => {
            setProxyStatus('checking')
            setProxyText('프록시 서버 확인 중...')
            fetch(`${API_BASE}/api/v1/samba/collector/proxy-status`)
              .then(r => r.json())
              .then(data => {
                if (data.status === 'ok') { setProxyStatus('ok'); setProxyText(data.message || '프록시 서버 정상 작동 중') }
                else { setProxyStatus('error'); setProxyText(data.message || '프록시 서버 연결 실패') }
              })
              .catch(() => { setProxyStatus('error'); setProxyText('백엔드 서버 연결 실패') })
          }}
          style={{
            marginLeft: 'auto', background: 'transparent', border: '1px solid #3D3D3D',
            color: '#888', padding: '2px 10px', borderRadius: '4px', fontSize: '0.72rem', cursor: 'pointer',
          }}
        >재확인</button>
      </div>

      {/* 소싱처 선택 + URL 입력 영역 */}
      <div style={{
        background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
        padding: "1.25rem", marginBottom: "1rem",
      }}>
        {/* 소싱처 선택 버튼 */}
        <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "0.875rem" }}>
          {/* 1행: 소싱처 버튼 + AI소싱기 */}
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
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
            <button
              onClick={() => {
                setShowAiSourcingModal(true)
                setAiSourcingStep('config')
                setAiResult(null)
                setAiLogs([])
                setAiSelectedCombos(new Set())
                setAiExcludedBrands(new Set())
                setAiExcludedKeywords(new Set())
              }}
              style={{
                marginLeft: 'auto', padding: '0.6rem 1.2rem', borderRadius: '6px',
                background: 'linear-gradient(135deg, #6C5CE7, #A29BFE)',
                color: '#fff', fontWeight: 600, fontSize: '0.82rem',
                border: 'none', cursor: 'pointer', whiteSpace: 'nowrap',
              }}
            >
              AI 소싱기
            </button>
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
              flex: 1, padding: "0.6rem 0.8rem", fontSize: "0.82rem",
              background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "6px",
              color: "#E5E5E5", outline: "none",
            }}
          />
          <button
            onClick={handleCreateGroup}
            disabled={collecting}
            style={{
              background: "linear-gradient(135deg, #FF8C00, #FFB84D)", color: "#fff",
              padding: "0.6rem 1.2rem", borderRadius: "6px", fontWeight: 600, fontSize: "0.82rem",
              whiteSpace: "nowrap", cursor: collecting ? "not-allowed" : "pointer",
              border: "none", opacity: collecting ? 0.6 : 1,
            }}
          >
            {collecting ? "생성중..." : "그룹 생성"}
          </button>
        </div>
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

      {/* AI비용 + AI이미지변환 + 이미지필터링 — 3단 나란히 배치 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '8px', marginTop: '1.25rem' }}>
        {/* AI 비용 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(81,207,102,0.08)', border: '1px solid rgba(81,207,102,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8125rem', color: '#51CF66', fontWeight: 600 }}>AI 비용</span>
          {lastAiUsage ? (
            <>
              <span style={{ fontSize: '0.78rem', color: '#E5E5E5' }}>{lastAiUsage.calls}건</span>
              <span style={{ fontSize: '0.78rem', color: '#888' }}>·</span>
              <span style={{ fontSize: '0.78rem', color: '#FFB84D' }}>₩{lastAiUsage.cost.toLocaleString()}</span>
              <span style={{ fontSize: '0.7rem', color: '#555' }}>{lastAiUsage.date}</span>
            </>
          ) : (
            <span style={{ fontSize: '0.78rem', color: '#555' }}>사용 내역 없음</span>
          )}
        </div>
        {/* AI 이미지 변환 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8125rem', color: '#FF8C00', fontWeight: 600 }}>AI 이미지 변환</span>
          <select value={aiImgMode} onChange={e => setAiImgMode(e.target.value)} style={{ background: '#1A1A1A', border: '1px solid #333', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', fontSize: '0.78rem' }}>
            <option value="background">배경 제거</option>
            <option value="scene">연출컷</option>
            <option value="model">모델 착용</option>
          </select>
          {aiImgMode === 'model' && (
            <select value={aiModelPreset} onChange={e => setAiModelPreset(e.target.value)} style={{ background: '#1A1A1A', border: '1px solid #333', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', fontSize: '0.78rem' }}>
              <optgroup label="여성"><option value="female_v1">청순 아이돌</option><option value="female_v2">시크 단발</option><option value="female_v3">건강 웨이브</option></optgroup>
              <optgroup label="남성"><option value="male_v1">깔끔 아이돌</option><option value="male_v2">스포티 근육</option><option value="male_v3">부드러운 중머리</option></optgroup>
              <optgroup label="키즈 여아"><option value="kids_girl_v1">긴머리 활발</option><option value="kids_girl_v2">단발 쾌활</option><option value="kids_girl_v3">양갈래 귀여움</option></optgroup>
              <optgroup label="키즈 남아"><option value="kids_boy_v1">활발 밝은</option><option value="kids_boy_v2">장난꾸러기</option><option value="kids_boy_v3">차분한</option></optgroup>
            </select>
          )}
          <span style={{ fontSize: '0.78rem', color: '#888' }}>({selectedIds.size}개 그룹)</span>
          <button
            onClick={async () => {
              if (selectedIds.size === 0) { showAlert('검색그룹을 선택해주세요'); return }
              const ok = await showConfirm(`선택된 ${selectedIds.size}개 그룹의 상품 이미지를 변환하시겠습니까?`)
              if (!ok) return
              setAiImgTransforming(true)
              try {
                const res = await proxyApi.transformByGroups([...selectedIds], { thumbnail: true, additional: true, detail: true }, aiImgMode, aiModelPreset)
                if (res.success) {
                  showAlert(res.message, 'success')
                  const cnt = res.total_transformed || 0
                  setLastAiUsage({ calls: cnt, tokens: cnt * 2000, cost: cnt * 3, date: new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit' }) })
                } else showAlert(res.message, 'error')
              } catch (e) { showAlert(`변환 실패: ${e instanceof Error ? e.message : '오류'}`, 'error') }
              finally { setAiImgTransforming(false); setSelectedIds(new Set()); setSelectAll(false) }
            }}
            disabled={aiImgTransforming || selectedIds.size === 0}
            style={{ marginLeft: 'auto', background: aiImgTransforming ? '#333' : 'rgba(255,140,0,0.15)', border: '1px solid rgba(255,140,0,0.35)', color: aiImgTransforming ? '#888' : '#FF8C00', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.78rem', cursor: aiImgTransforming ? 'not-allowed' : 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
          >{aiImgTransforming ? '변환중...' : `변환 실행 (${selectedIds.size}개)`}</button>
        </div>

        {/* 이미지 필터링 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8125rem', color: '#818CF8', fontWeight: 600 }}>이미지 필터링</span>
          {(['images', 'detail', 'all'] as const).map(s => (
            <label key={s} style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
              <input type="radio" name="collectorImgFilterScope" checked={imgFilterScope === s}
                onChange={() => setImgFilterScope(s)}
                style={{ accentColor: '#818CF8', width: '13px', height: '13px' }} />
              <span style={{ fontSize: '0.78rem', color: '#E5E5E5' }}>
                {s === 'images' ? '대표+추가' : s === 'detail' ? '상세이미지' : '전체'}
              </span>
            </label>
          ))}
          <button
            onClick={async () => {
              if (selectedIds.size === 0) { showAlert('검색그룹을 선택해주세요'); return }
              const scopeLabel = imgFilterScope === 'images' ? '대표+추가이미지' : imgFilterScope === 'detail' ? '상세이미지' : '전체 이미지'
              const ok = await showConfirm(`선택된 ${selectedIds.size}개 그룹의 ${scopeLabel}를 필터링하시겠습니까?\n(모델컷/연출컷/배너를 자동 제거합니다)`)
              if (!ok) return
              setImgFiltering(true)
              try {
                let totalProcessed = 0, totalErrors = 0
                for (const gid of [...selectedIds]) {
                  try {
                    const r = await proxyApi.filterProductImages([], gid, imgFilterScope)
                    if (r.success) { totalProcessed += r.total || 0; totalErrors += Object.keys(r.errors || {}).length }
                  } catch { totalErrors++ }
                }
                if (totalErrors > 0) showAlert(`필터링: ${totalProcessed}개 완료, ${totalErrors}개 실패`, 'info')
                else showAlert(`필터링 완료 — ${totalProcessed}개 처리`, 'success')
              } catch (e) { showAlert(`필터링 오류: ${e instanceof Error ? e.message : '오류'}`, 'error') }
              finally { setImgFiltering(false); setSelectedIds(new Set()); setSelectAll(false) }
            }}
            disabled={imgFiltering || selectedIds.size === 0}
            style={{ marginLeft: 'auto', background: imgFiltering ? '#333' : 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.35)', color: imgFiltering ? '#888' : '#818CF8', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.78rem', cursor: imgFiltering ? 'not-allowed' : 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
          >{imgFiltering ? '필터링중...' : `필터링 실행 (${selectedIds.size}개)`}</button>
        </div>
      </div>

      {/* 검색그룹 드릴다운 */}
      <div style={{ marginTop: '1rem' }}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          marginBottom: '0.75rem', flexWrap: 'wrap', gap: '8px',
        }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', margin: 0 }}>검색그룹 목록</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
            <select value={collectFilter} onChange={e => setCollectFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: collectFilter ? '#F59E0B' : '#888', cursor: 'pointer' }}>
              <option value="">상품수집</option>
              <option value="collected">수집</option>
              <option value="uncollected">미수집</option>
            </select>
            <select value={marketRegFilter} onChange={e => setMarketRegFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: marketRegFilter ? '#4C9AFF' : '#888', cursor: 'pointer' }}>
              <option value="">마켓등록</option>
              <option value="registered">등록</option>
              <option value="partial">부분등록</option>
              <option value="unregistered">미등록</option>
            </select>
            <select value={tagRegFilter} onChange={e => setTagRegFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: tagRegFilter ? '#51CF66' : '#888', cursor: 'pointer' }}>
              <option value="">태그등록</option>
              <option value="registered">등록</option>
              <option value="partial">부분등록</option>
              <option value="unregistered">미등록</option>
            </select>
            <select value={policyRegFilter} onChange={e => setPolicyRegFilter(e.target.value)}
              style={{ fontSize: '0.78rem', padding: '0.3rem 0.5rem', background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '6px', color: policyRegFilter ? '#FF8C00' : '#888', cursor: 'pointer' }}>
              <option value="">정책등록</option>
              <option value="registered">등록</option>
              <option value="partial">부분등록</option>
              <option value="unregistered">미등록</option>
            </select>
            <button
              onClick={handleDeleteSelectedGroups}
              style={{
                background: 'rgba(255,100,100,0.1)', border: '1px solid rgba(255,100,100,0.3)',
                color: '#FF6B6B', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
              }}
            >
              그룹 삭제
            </button>
            <button
              onClick={handleCollectGroups}
              style={{
                background: 'rgba(255,140,0,0.1)', border: '1px solid rgba(255,140,0,0.35)',
                color: '#FF8C00', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
              }}
            >
              상품수집
            </button>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              style={{
                background: refreshing ? 'rgba(76,154,255,0.05)' : 'rgba(76,154,255,0.1)',
                border: '1px solid rgba(76,154,255,0.35)',
                color: '#4C9AFF', padding: '0.3rem 0.75rem', borderRadius: '6px',
                fontSize: '0.8rem', cursor: refreshing ? 'not-allowed' : 'pointer',
                opacity: refreshing ? 0.6 : 1,
              }}
            >
              {refreshing ? '갱신중...' : '일괄 갱신'}
            </button>
            <button
              onClick={async () => {
                const targetIds = selectedIds.size > 0 ? [...selectedIds] : displayedFilters.map(f => f.id)
                if (targetIds.length === 0) { showAlert('검색그룹이 없습니다'); return }
                const ok = await showConfirm(`${selectedIds.size > 0 ? '선택된' : '전체'} ${targetIds.length}개 그룹의 상품에 AI 태그를 생성하시겠습니까?`)
                if (!ok) return
                try {
                  const res = await proxyApi.generateAiTagsByGroups(targetIds)
                  if (res.success) {
                    showAlert(res.message, 'success')
                    setLastAiUsage({ calls: res.api_calls || 0, tokens: (res.input_tokens || 0) + (res.output_tokens || 0), cost: res.cost_krw || 0, date: new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit' }) })
                    load(); loadTree()
                    setSelectedIds(new Set()); setSelectAll(false)
                  } else showAlert(res.message, 'error')
                } catch (e) {
                  showAlert(`태그 생성 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
                }
              }}
              style={{
                background: 'rgba(255,140,0,0.1)', border: '1px solid rgba(255,140,0,0.35)',
                color: '#FF8C00', padding: '0.3rem 0.75rem', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer',
              }}
            >
              AI태그
            </button>
          </div>
        </div>

        <div style={{
          marginBottom: '0.75rem', padding: '0.5rem 0.875rem', borderRadius: '8px',
          background: 'rgba(255,140,0,0.05)', border: '1px solid rgba(255,140,0,0.2)',
          fontSize: '0.8rem', color: '#888',
        }}>
          ※ 정책 우선순위: <span style={{ color: '#FF8C00' }}>[상품별 개별정책]</span> → <span style={{ color: '#FF8C00' }}>[카테고리 정책]</span> 순으로 적용됩니다
          <span style={{ float: 'right', color: '#E5E5E5', fontWeight: 600 }}>
            수집 <span style={{ color: '#FF8C00' }}>{filters.reduce((s, f) => s + ((f as unknown as Record<string, number>).collected_count ?? 0), 0).toLocaleString()}</span>
            <span style={{ color: '#555' }}> / </span>
            요청 <span style={{ color: '#FFB84D' }}>{filters.filter(f => !f.is_folder).reduce((s, f) => s + (f.requested_count ?? 0), 0).toLocaleString()}</span>
          </span>
        </div>

        {/* 검색그룹 드릴다운 — 사이트 > 브랜드 > 카테고리 > 상세(링크/정책/스스브랜드/수집/요청/생성일) */}
        {(() => {
          // 헬퍼: 사이트 하위 모든 리프 그룹
          const getAllLeaves = (node: SambaSearchFilter | undefined): SambaSearchFilter[] => {
            if (!node) return []
            const result: SambaSearchFilter[] = []
            const walk = (n: SambaSearchFilter) => {
              if (!n.is_folder) result.push(n)
              ;(n.children || []).forEach(walk)
            }
            ;(node.children || []).forEach(walk)
            return result
          }
          // 전체 사이트별 리프 + 브랜드/카테고리 파싱 (크로스 필터용)
          const allLeafInfosRaw = tree.flatMap(s =>
            getAllLeaves(s).map(l => {
              const parsed = parseGroupName(l.name, s.source_site || '')
              return { ...l, _siteId: s.id, _siteSite: s.source_site || '', _brand: parsed.brand, _category: parsed.category }
            })
          )
          // 상품수집 드롭박스 필터 적용
          const allLeafInfos = collectFilter
            ? allLeafInfosRaw.filter(l => {
                const cnt = (l as unknown as Record<string, number>).collected_count ?? 0
                return collectFilter === 'collected' ? cnt > 0 : cnt === 0
              })
            : allLeafInfosRaw
          // 크로스 필터: 사이트 목록 (선택된 브랜드 기준 필터)
          const baseSites = collectFilter
            ? tree.filter(s => allLeafInfos.some(l => l._siteId === s.id))
            : tree
          const filteredSites = drillBrand
            ? baseSites.filter(s => allLeafInfos.some(l => l._siteId === s.id && l._brand === drillBrand))
            : baseSites
          // 크로스 필터: 브랜드 목록 (선택된 사이트 기준 필터)
          const brandLeaves = drillSite
            ? allLeafInfos.filter(l => l._siteId === drillSite)
            : allLeafInfos
          const brandMap = new Map<string, number>()
          brandLeaves.forEach(l => brandMap.set(l._brand, (brandMap.get(l._brand) || 0) + 1))
          const brands = Array.from(brandMap.entries()).sort((a, b) => a[0].localeCompare(b[0], 'ko'))
          // 카테고리 그룹 (사이트+브랜드 교차 필터)
          let catLeaves = allLeafInfos
          if (drillSite) catLeaves = catLeaves.filter(l => l._siteId === drillSite)
          if (drillBrand) catLeaves = catLeaves.filter(l => l._brand === drillBrand)
          const catGroups = (drillSite && drillBrand) ? catLeaves.sort((a, b) => a._category.localeCompare(b._category, 'ko')) : []
          // 선택된 그룹 상세
          const selectedFilter = drillGroup ? filters.find(fl => fl.id === drillGroup) : null
          const selectedCount = selectedFilter ? ((selectedFilter as unknown as Record<string, number>).collected_count ?? 0) : 0

          const colStyle = { flex: 1, minWidth: '120px', borderRight: '1px solid #2D2D2D', maxHeight: '320px', overflowY: 'auto' as const }
          const detColStyle = { flex: 1, minWidth: '80px', borderRight: '1px solid #2D2D2D', maxHeight: '320px', overflowY: 'auto' as const, padding: '0.5rem 0.5rem' }
          const itemSt = (sel: boolean) => ({
            padding: '0.5rem 0.75rem', fontSize: '0.8125rem',
            color: sel ? '#FF8C00' : '#C5C5C5', cursor: 'pointer' as const,
            background: sel ? 'rgba(255,140,0,0.08)' : 'transparent',
            transition: 'background 0.15s',
            display: 'flex' as const, alignItems: 'center' as const, gap: '4px',
          })

          return (
            <div style={{
              background: 'rgba(30,30,30,0.5)', border: '1px solid #2D2D2D',
              borderRadius: '8px', overflow: 'hidden', marginBottom: '1rem',
            }}>
              {/* 헤더 */}
              <div style={{ display: 'flex', borderBottom: '1px solid #2D2D2D', background: 'rgba(255,255,255,0.03)' }}>
                {['사이트', '브랜드', '카테고리', '링크', '정책', '수집', '요청', '생성일/최근수집'].map((h, i) => (
                  <div key={h} style={{
                    flex: 1, minWidth: i < 3 ? '120px' : '80px', padding: '0.5rem 0.5rem',
                    fontSize: '0.72rem', fontWeight: 600,
                    color: (i === 0 && (drillEntry === 'site' || drillSite)) || (i === 1 && (drillEntry === 'brand' || drillBrand)) || (i === 2 && drillGroup) ? '#FF8C00' : '#888',
                    borderRight: i < 7 ? '1px solid #2D2D2D' : 'none',
                    cursor: i < 3 ? 'pointer' : 'default',
                  }}
                  onClick={() => {
                    if (i === 0) { setDrillEntry('site'); setDrillSite(null); setDrillBrand(null); setDrillGroup(null) }
                    else if (i === 1) { setDrillEntry('brand'); setDrillSite(null); setDrillBrand(null); setDrillGroup(null) }
                    else if (i === 2) { setDrillGroup(null) }
                  }}
                  >{h}</div>
                ))}
              </div>

              {/* 컬럼 */}
              <div style={{ display: 'flex' }}>
                {/* 1. 사이트: 사이트 헤더 클릭 시 전체 표시 / 브랜드 선택 시 연관만 표시 */}
                <div style={colStyle}>
                  {(drillEntry === 'site' || drillBrand) ? (
                    filteredSites.length === 0 ? (
                      <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8rem' }}>그룹 없음</div>
                    ) : filteredSites.map(s => (
                      <div key={s.id} style={itemSt(drillSite === s.id)}
                        onClick={() => { setDrillSite(drillSite === s.id ? null : s.id); setDrillGroup(null) }}
                        onMouseEnter={e => { if (drillSite !== s.id) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                        onMouseLeave={e => { if (drillSite !== s.id) e.currentTarget.style.background = 'transparent' }}
                      >
                        {s.source_site || s.name}
                        <span style={{ marginLeft: 'auto', fontSize: '0.62rem', color: '#555' }}>
                          {drillBrand
                            ? allLeafInfos.filter(l => l._siteId === s.id && l._brand === drillBrand).length
                            : getAllLeaves(s).length}
                        </span>
                      </div>
                    ))
                  ) : null}
                </div>
                {/* 2. 브랜드: 브랜드 헤더 클릭 시 전체 표시 / 사이트 선택 시 연관만 표시 */}
                <div style={colStyle}>
                  {(drillEntry === 'brand' || drillSite) ? (
                    brands.length > 0 ? brands.map(([brand, count]) => (
                      <div key={brand} style={itemSt(drillBrand === brand)}
                        onClick={() => { setDrillBrand(drillBrand === brand ? null : brand); setDrillGroup(null) }}
                        onMouseEnter={e => { if (drillBrand !== brand) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                        onMouseLeave={e => { if (drillBrand !== brand) e.currentTarget.style.background = 'transparent' }}
                      >
                        {brand}
                        <span style={{ marginLeft: 'auto', fontSize: '0.62rem', color: '#555' }}>{count}</span>
                      </div>
                    )) : <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8rem' }}>브랜드 없음</div>
                  ) : null}
                </div>
                {/* 3. 카테고리: 사이트 또는 브랜드 선택 후 연관 표시 */}
                <div style={colStyle}>
                  {(drillSite || drillBrand) ? (catGroups.length > 0 ? catGroups.map(g => (
                    <div key={g.id} style={itemSt(drillGroup === g.id)}
                      onClick={() => { setDrillGroup(g.id); setSelectedIds(new Set([g.id])) }}
                      onMouseEnter={e => { if (drillGroup !== g.id) e.currentTarget.style.background = 'rgba(255,255,255,0.03)' }}
                      onMouseLeave={e => { if (drillGroup !== g.id) e.currentTarget.style.background = 'transparent' }}
                    >
                      {g._category || g.name}
                      <span style={{ marginLeft: 'auto', fontSize: '0.62rem', color: '#FF8C00' }}>{g.collected_count ?? 0}</span>
                    </div>
                  )) : <div style={{ padding: '0.75rem', color: '#555', fontSize: '0.8rem' }}>항목 없음</div>
                  ) : null}
                </div>
                {/* 4. 링크 + 삭제 체크 */}
                <div style={detColStyle}>
                  {selectedFilter ? (() => {
                    // 소싱 URL 결정: category_filter(저장된 URL) > 사이트별 검색URL 생성
                    const storedUrl = (selectedFilter as unknown as Record<string, string>).category_filter || ''
                    const kw = selectedFilter.keyword || ''
                    const site = selectedFilter.source_site || ''
                    const siteSearchUrls: Record<string, string> = {
                      MUSINSA: 'https://www.musinsa.com/search/musinsa/integration?q=',
                      KREAM: 'https://kream.co.kr/search?keyword=',
                      ABCmart: 'https://abcmart.a-rt.com/search?q=',
                    }
                    // keyword가 이미 URL이면 그대로 사용
                    const kwIsUrl = kw.startsWith('http://') || kw.startsWith('https://')
                    const linkUrl = storedUrl || (kwIsUrl ? kw : (siteSearchUrls[site] ? siteSearchUrls[site] + encodeURIComponent(kw) : ''))
                    return (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        {linkUrl ? (
                          <a href={linkUrl} target="_blank" rel="noopener noreferrer" style={{
                            color: '#7EB5D0', fontSize: '0.7rem', wordBreak: 'break-all',
                            textDecoration: 'underline', textUnderlineOffset: '2px', flex: 1,
                          }}>{kw || linkUrl.replace(/https?:\/\/[^/]+/, '').slice(0, 40)}...</a>
                        ) : <span style={{ color: '#555', fontSize: '0.75rem', flex: 1 }}>-</span>}
                        <button
                          onClick={async () => {
                            if (!await showConfirm(`"${selectedFilter.name}" 그룹을 삭제하시겠습니까?`)) return
                            await collectorApi.deleteFilter(selectedFilter.id)
                            setDrillGroup(null)
                            load(); loadTree()
                          }}
                          style={{
                            background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)',
                            color: '#FF6B6B', fontSize: '0.6rem', padding: '1px 5px', borderRadius: '3px',
                            cursor: 'pointer', flexShrink: 0,
                          }}
                        >삭제</button>
                      </div>
                    )
                  })() : <span style={{ color: '#444', fontSize: '0.75rem' }}>선택</span>}
                </div>
                {/* 5. 정책 */}
                <div style={detColStyle}>
                  {selectedFilter ? (
                    <select
                      key={selectedFilter.id}
                      defaultValue={(selectedFilter as unknown as Record<string, string>).applied_policy_id || ''}
                      onChange={e => handlePolicyApply(selectedFilter.id, e.target.value)}
                      style={{
                        width: '100%', padding: '0.2rem 0.2rem', fontSize: '0.72rem',
                        background: 'rgba(22,22,22,0.95)', border: '1px solid #353535',
                        color: '#C5C5C5', borderRadius: '4px',
                      }}
                    >
                      <option value="">정책 선택</option>
                      {policies.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>선택</span>}
                </div>
                {/* 6. 수집 */}
                <div style={detColStyle}>
                  {selectedFilter ? (
                    <span onClick={() => handleGoToProducts(selectedFilter)} style={{
                      color: selectedCount > 0 ? '#FF8C00' : '#555', fontWeight: 600, fontSize: '0.82rem',
                      cursor: selectedCount > 0 ? 'pointer' : 'default',
                      textDecoration: selectedCount > 0 ? 'underline' : 'none',
                    }}>{selectedCount}</span>
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
                {/* 8. 요청 */}
                <div style={detColStyle}>
                  {selectedFilter ? (
                    <input
                      key={selectedFilter.id + (selectedFilter.requested_count ?? 100)}
                      type="text" inputMode="numeric" pattern="[0-9]*"
                      defaultValue={selectedFilter.requested_count ?? 100}
                      onBlur={e => {
                        const v = parseInt(e.target.value, 10)
                        if (!isNaN(v) && v !== (selectedFilter.requested_count ?? 100)) handleUpdateRequestedCount(selectedFilter.id, v)
                      }}
                      style={{
                        width: '50px', textAlign: 'center', background: 'transparent',
                        border: '1px solid #3D3D3D', color: '#4C9AFF', fontSize: '0.78rem',
                        fontWeight: 600, padding: '0.1rem 0.2rem', borderRadius: '4px', outline: 'none',
                      }}
                      onFocus={e => { e.currentTarget.style.borderColor = '#4C9AFF' }}
                      onBlurCapture={e => { e.currentTarget.style.borderColor = '#3D3D3D' }}
                    />
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
                {/* 9. 생성일/최근수집 */}
                <div style={{ ...detColStyle, borderRight: 'none' }}>
                  {selectedFilter ? (
                    <div style={{ fontSize: '0.68rem', color: '#888' }}>
                      {fmtDate(selectedFilter.created_at)}<br />{fmtDate(selectedFilter.last_collected_at)}
                    </div>
                  ) : <span style={{ color: '#444', fontSize: '0.75rem' }}>-</span>}
                </div>
              </div>
            </div>
          )
        })()}
      </div>

      {/* 프리셋 이미지 확대 모달 */}
      {presetZoomImg && (
        <div
          onClick={() => setPresetZoomImg(null)}
          style={{
            position: 'fixed', inset: 0, zIndex: 10000,
            background: 'rgba(0,0,0,0.85)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'pointer',
          }}
        >
          <img
            src={presetZoomImg}
            alt="모델 프리셋"
            onClick={e => e.stopPropagation()}
            onError={e => { (e.target as HTMLImageElement).alt = '이미지 없음' }}
            style={{
              maxWidth: '90vw', maxHeight: '90vh',
              objectFit: 'contain', borderRadius: '8px',
              cursor: 'default',
            }}
          />
          <button
            onClick={() => setPresetZoomImg(null)}
            style={{
              position: 'absolute', top: '20px', right: '20px',
              background: 'rgba(0,0,0,0.5)', border: '1px solid #555',
              color: '#ccc', fontSize: '1.2rem', padding: '4px 10px',
              borderRadius: '6px', cursor: 'pointer',
            }}
          >✕</button>
        </div>
      )}

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

      {/* ═══ AI 소싱기 모달 ═══ */}
      {showAiSourcingModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9999,
          background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => !aiAnalyzing && setShowAiSourcingModal(false)}>
          <div onClick={e => e.stopPropagation()} style={{
            background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px',
            width: aiSourcingStep === 'confirm' ? '900px' : '560px',
            maxHeight: '85vh', overflow: 'auto',
          }}>
            {/* 헤더 */}
            <div style={{
              padding: '16px 20px', borderBottom: '1px solid #2D2D2D',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '1.1rem' }}>🤖</span>
                <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>AI 소싱기</span>
                <span style={{ fontSize: '0.75rem', color: '#888', marginLeft: '4px' }}>
                  {aiSourcingStep === 'config' ? '1/3 데이터소스 설정' :
                   aiSourcingStep === 'analyzing' ? '2/3 분석 중' : '3/3 결과 확인'}
                </span>
              </div>
              {!aiAnalyzing && (
                <button onClick={() => setShowAiSourcingModal(false)} style={{
                  background: 'none', border: 'none', color: '#888', fontSize: '1.2rem', cursor: 'pointer',
                }}>✕</button>
              )}
            </div>

            {/* STEP 1: 월 + 대카테고리 설정 */}
            {aiSourcingStep === 'config' && (
              <div style={{ padding: '20px' }}>
                {/* 월 + 대카테고리 (핵심 2개 입력) */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
                  <div>
                    <label style={{ fontSize: '0.82rem', color: '#C5C5C5', fontWeight: 600, display: 'block', marginBottom: '6px' }}>분석 월 (작년)</label>
                    <select value={aiMonth} onChange={e => setAiMonth(Number(e.target.value))} style={{
                      width: '100%', padding: '10px 12px', background: '#111', border: '1px solid #2D2D2D',
                      borderRadius: '6px', color: '#E5E5E5', fontSize: '0.9rem', cursor: 'pointer',
                    }}>
                      {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                        <option key={m} value={m}>{m}월</option>
                      ))}
                    </select>
                    <span style={{ fontSize: '0.7rem', color: '#555', marginTop: '4px', display: 'block' }}>
                      {new Date().getFullYear() - 1}년 {aiMonth}월 데이터
                    </span>
                  </div>
                  <div>
                    <label style={{ fontSize: '0.82rem', color: '#C5C5C5', fontWeight: 600, display: 'block', marginBottom: '6px' }}>대 카테고리</label>
                    <select value={aiMainCategory} onChange={e => setAiMainCategory(e.target.value)} style={{
                      width: '100%', padding: '10px 12px', background: '#111', border: '1px solid #2D2D2D',
                      borderRadius: '6px', color: '#E5E5E5', fontSize: '0.9rem', cursor: 'pointer',
                    }}>
                      <option value="패션의류">패션의류</option>
                      <option value="패션잡화">패션잡화</option>
                      <option value="스포츠/레저">스포츠/레저</option>
                      <option value="패션전체">패션전체 (의류+잡화)</option>
                    </select>
                  </div>
                </div>

                {/* 수집 소싱처 선택 */}
                <div style={{ marginBottom: '16px' }}>
                  <label style={{ fontSize: '0.82rem', color: '#C5C5C5', fontWeight: 600, display: 'block', marginBottom: '8px' }}>수집 소싱처</label>
                  <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                    {SITES.map(s => (
                      <button key={s.id} onClick={() => setAiSourceSite(s.id)} style={{
                        padding: '6px 14px', borderRadius: '6px', fontSize: '0.78rem', cursor: 'pointer',
                        fontWeight: aiSourceSite === s.id ? 700 : 400,
                        background: aiSourceSite === s.id ? 'rgba(255,140,0,0.15)' : '#111',
                        border: aiSourceSite === s.id ? '1px solid #FF8C00' : '1px solid #2D2D2D',
                        color: aiSourceSite === s.id ? '#FF8C00' : '#888',
                      }}>{s.label}</button>
                    ))}
                  </div>
                </div>

                {/* 자동 조회 범위 */}
                <div style={{
                  background: 'rgba(108,92,231,0.08)', border: '1px solid rgba(108,92,231,0.25)',
                  borderRadius: '8px', padding: '12px 14px', marginBottom: '16px', fontSize: '0.78rem',
                }}>
                  <div style={{ color: '#A29BFE', fontWeight: 600, marginBottom: '6px' }}>자동 조회 범위</div>
                  <div style={{ color: '#999', lineHeight: 1.6 }}>
                    <span style={{ color: '#4C9AFF' }}>무신사</span>:{' '}
                    {aiMainCategory === '패션의류' ? '상의, 아우터, 바지, 원피스/스커트, 속옷/슬립웨어' :
                     aiMainCategory === '패션잡화' ? '가방, 신발, 시계/주얼리, 패션소품' :
                     aiMainCategory === '스포츠/레저' ? '스포츠/레저' : '전체 10개 카테고리'}
                    <br />
                    <span style={{ color: '#51CF66' }}>네이버 데이터랩</span>:{' '}
                    {aiMainCategory === '패션전체' ? '패션의류 + 패션잡화' : aiMainCategory} 인기검색어 TOP 500
                  </div>
                </div>

                {/* 엑셀 업로드 + 최소 상품수 */}
                <div style={{
                  display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px',
                }}>
                  <div style={{
                    background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '14px',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                      <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>판매 엑셀 (선택)</span>
                      <span style={{ fontSize: '0.72rem', color: '#888' }}>정확도 향상</span>
                    </div>
                    <input type="file" accept=".xlsx,.xlsm,.xls,.csv"
                      onChange={e => setAiExcelFile(e.target.files?.[0] || null)}
                      style={{ fontSize: '0.8rem', color: '#888' }}
                    />
                    {aiExcelFile && (
                      <span style={{ fontSize: '0.75rem', color: '#FFB84D', display: 'block', marginTop: '4px' }}>
                        {aiExcelFile.name}
                      </span>
                    )}
                  </div>
                  <div style={{
                    background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '14px',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                      <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>최소 상품수</span>
                      <span style={{ fontSize: '0.72rem', color: '#888' }}>미만 그룹 배제</span>
                    </div>
                    <input
                      type="text"
                      inputMode="numeric"
                      value={aiMinCount || ''}
                      onChange={e => setAiMinCount(Number(e.target.value.replace(/[^0-9]/g, '')) || 0)}
                      placeholder="0"
                      style={{
                        width: '100%', padding: '6px 10px', background: '#0A0A0A', border: '1px solid #3D3D3D',
                        borderRadius: '6px', color: '#FFB84D', fontSize: '0.9rem', fontWeight: 600,
                      }}
                    />
                  </div>
                </div>

                {/* 시작 버튼 */}
                <button
                  onClick={async () => {
                    setAiSourcingStep('analyzing')
                    setAiAnalyzing(true)
                    setAiLogs([`[시작] ${new Date().getFullYear() - 1}년 ${aiMonth}월 / ${aiMainCategory} 분석 시작...`])
                    let gotResult = false
                    try {
                      const resp = await aiSourcingApi.analyzeFull({
                        month: aiMonth,
                        main_category: aiMainCategory,
                        target_count: aiTargetCount,
                        file: aiExcelFile || undefined,
                      })
                      // HTTP 에러 체크
                      if (!resp.ok) {
                        const errText = await resp.text()
                        throw new Error(`서버 오류 (${resp.status}): ${errText.slice(0, 200)}`)
                      }
                      const reader = resp.body?.getReader()
                      if (!reader) throw new Error('스트리밍 응답 없음')
                      const decoder = new TextDecoder()
                      let buffer = ''
                      const processLine = (line: string) => {
                        if (line.startsWith('event: ')) return
                        if (!line.startsWith('data: ')) return
                        try {
                          const payload = JSON.parse(line.slice(6))
                          if (typeof payload === 'string') {
                            setAiLogs(prev => [...prev, payload])
                          } else if (payload.brands && payload.combinations) {
                            gotResult = true
                            const result = payload as AISourcingResult
                            setAiResult(result)
                            // IP위험 브랜드 표시만 (제외하지 않음 — 사용자가 판단)
                            setAiExcludedBrands(new Set())
                setAiExcludedKeywords(new Set())
                            // 전체 조합 기본 선택
                            const all = new Set<number>()
                            result.combinations.forEach((_c: AISourcingCombination, i: number) => {
                              all.add(i)
                            })
                            setAiSelectedCombos(all)
                          } else if (payload.step) {
                            setAiLogs(prev => [...prev, `[${payload.step}] ${payload.count}개 처리`])
                          } else if (payload.message) {
                            setAiLogs(prev => [...prev, payload.message])
                          }
                        } catch { /* JSON 파싱 실패 무시 */ }
                      }
                      while (true) {
                        const { done, value } = await reader.read()
                        if (done) break
                        buffer += decoder.decode(value, { stream: true })
                        const lines = buffer.split('\n')
                        buffer = lines.pop() || ''
                        for (const line of lines) processLine(line)
                      }
                      // 남은 버퍼 처리
                      if (buffer.trim()) processLine(buffer.trim())
                      // 결과가 있을 때만 confirm 단계로 전환
                      if (gotResult) {
                        setAiSourcingStep('confirm')
                      } else {
                        setAiLogs(prev => [...prev, '[오류] 분석 결과를 받지 못했습니다. 백엔드 로그를 확인해주세요.'])
                      }
                    } catch (err) {
                      setAiLogs(prev => [...prev, `[오류] ${err instanceof Error ? err.message : '분석 실패'}`])
                    }
                    setAiAnalyzing(false)
                  }}
                  style={{
                    width: '100%', padding: '10px', borderRadius: '8px',
                    background: 'linear-gradient(135deg, #6C5CE7, #A29BFE)',
                    color: '#fff', fontWeight: 700, fontSize: '0.9rem',
                    border: 'none', cursor: 'pointer',
                  }}
                >
                  AI 분석 시작
                </button>
              </div>
            )}

            {/* STEP 2: 분석 중 */}
            {aiSourcingStep === 'analyzing' && (
              <div style={{ padding: '20px' }}>
                <div style={{
                  background: '#080A10', borderRadius: '8px', padding: '14px',
                  height: '300px', overflowY: 'auto', fontFamily: 'monospace',
                  fontSize: '0.62rem', lineHeight: 1.5, color: '#8A95B0',
                }}>
                  {aiLogs.map((line, i) => (
                    <p key={i} style={{
                      margin: 0,
                      color: line.includes('완료') || line.includes('성공') ? '#51CF66'
                        : line.includes('오류') || line.includes('실패') ? '#FF6B6B'
                        : line.includes('시작') ? '#4C9AFF' : '#8A95B0',
                    }}>{line}</p>
                  ))}
                </div>
                {!aiAnalyzing && (
                  <div style={{ marginTop: '12px', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                    {aiResult && (
                      <button onClick={() => setAiSourcingStep('confirm')} style={{
                        padding: '8px 20px', borderRadius: '6px',
                        background: 'rgba(81,207,102,0.2)', border: '1px solid rgba(81,207,102,0.5)',
                        color: '#51CF66', cursor: 'pointer', fontWeight: 600,
                      }}>결과 확인 →</button>
                    )}
                    <button onClick={() => setShowAiSourcingModal(false)} style={{
                      padding: '8px 20px', borderRadius: '6px',
                      background: 'transparent', border: '1px solid #3D3D3D',
                      color: '#888', cursor: 'pointer',
                    }}>닫기</button>
                  </div>
                )}
              </div>
            )}

            {/* STEP 3: 결과 확인 + 컨펌 */}
            {aiSourcingStep === 'confirm' && aiResult && (
              <div style={{ padding: '20px' }}>
                {/* 요약 */}
                <div style={{
                  display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '10px', marginBottom: '16px',
                }}>
                  {[
                    { label: '발견 브랜드', value: aiResult.summary.total_brands_found, color: '#4C9AFF' },
                    { label: '발견 키워드쌍', value: aiResult.summary.total_pairs || 0, color: '#E5A0FF' },
                    { label: 'IP안전', value: aiResult.summary.safe_brands, color: '#51CF66' },
                    { label: '생성 그룹', value: aiResult.summary.total_combinations, color: '#FFB84D' },
                    { label: '예상 상품', value: aiResult.summary.total_estimated_products.toLocaleString(), color: '#A29BFE' },
                  ].map(s => (
                    <div key={s.label} style={{
                      background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px',
                      padding: '10px', textAlign: 'center',
                    }}>
                      <div style={{ fontSize: '1.1rem', fontWeight: 700, color: s.color }}>{s.value}</div>
                      <div style={{ fontSize: '0.72rem', color: '#888' }}>{s.label}</div>
                    </div>
                  ))}
                </div>

                {/* 선택된 소싱처 표시 */}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px',
                  background: 'rgba(255,140,0,0.06)', border: '1px solid rgba(255,140,0,0.2)',
                  borderRadius: '8px', padding: '8px 14px',
                }}>
                  <span style={{ fontSize: '0.78rem', color: '#FF8C00', fontWeight: 600 }}>수집 소싱처: {SITES.find(s => s.id === aiSourceSite)?.label || aiSourceSite}</span>
                  <span style={{ fontSize: '0.7rem', color: '#666' }}>그룹명: {aiSourceSite}_브랜드_키워드</span>
                </div>

                {/* 근거 데이터 */}
                {(() => {
                  // 소싱처별 브랜드 + 키워드 그룹핑
                  const sourceMap: Record<string, { brands: string[]; keywords: string[] }> = {}
                  aiResult.brands.forEach(b => {
                    const src = b.source || '기타'
                    if (!sourceMap[src]) sourceMap[src] = { brands: [], keywords: [] }
                    if (!sourceMap[src].brands.includes(b.brand)) sourceMap[src].brands.push(b.brand)
                    ;[...(b.keywords || []), ...(b.categories || [])].forEach(kw => {
                      if (kw && !sourceMap[src].keywords.includes(kw)) sourceMap[src].keywords.push(kw)
                    })
                  })
                  const entries = Object.entries(sourceMap)
                  if (entries.length === 0) return null
                  return (
                    <div style={{ marginBottom: '14px', padding: '12px 14px', background: '#111', border: '1px solid #2D2D2D', borderRadius: '8px', maxHeight: '300px', overflowY: 'auto' }}>
                      <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '8px', fontWeight: 600 }}>분석 근거 <span style={{ color: '#555', fontWeight: 400 }}>— 클릭하여 제외</span></div>
                      {entries.map(([src, data]) => (
                        <div key={src} style={{ marginBottom: '6px', fontSize: '0.78rem', lineHeight: 1.8, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '2px' }}>
                          <span style={{ color: '#FFB84D', fontWeight: 600 }}>{src}</span>
                          <span style={{ color: '#666' }}> : </span>
                          {data.brands.map(brand => {
                            const excluded = aiExcludedBrands.has(brand)
                            return (
                              <span key={brand}
                                onClick={() => {
                                  const next = new Set(aiExcludedBrands)
                                  if (excluded) {
                                    next.delete(brand)
                                    const addIdxs = new Set(aiSelectedCombos)
                                    aiResult.combinations.forEach((c, i) => {
                                      if (c.brand === brand) addIdxs.add(i)
                                    })
                                    setAiSelectedCombos(addIdxs)
                                  } else {
                                    next.add(brand)
                                    const removeIdxs = new Set(aiSelectedCombos)
                                    aiResult.combinations.forEach((c, i) => {
                                      if (c.brand === brand) removeIdxs.delete(i)
                                    })
                                    setAiSelectedCombos(removeIdxs)
                                  }
                                  setAiExcludedBrands(next)
                                }}
                                style={{
                                  cursor: 'pointer', marginRight: '6px', padding: '1px 6px', borderRadius: '4px',
                                  background: excluded ? 'rgba(255,107,107,0.1)' : 'rgba(255,255,255,0.05)',
                                  color: excluded ? '#FF6B6B' : '#E5E5E5',
                                  textDecoration: excluded ? 'line-through' : 'none',
                                  opacity: excluded ? 0.5 : 1, transition: 'all 0.15s',
                                }}
                              >{brand}</span>
                            )
                          })}
                          {data.keywords.length > 0 && (
                            <>
                              <span style={{ color: '#666' }}> / </span>
                              {data.keywords.map(kw => {
                                // 키워드 제외 시 해당 키워드를 가진 조합 체크 해제
                                const kwExcluded = aiExcludedBrands.has(`__kw__${kw}`)
                                return (
                                  <span key={kw}
                                    onClick={() => {
                                      const kwKey = `__kw__${kw}`
                                      const next = new Set(aiExcludedBrands)
                                      if (kwExcluded) {
                                        next.delete(kwKey)
                                        const addIdxs = new Set(aiSelectedCombos)
                                        aiResult.combinations.forEach((c, i) => {
                                          if ((c.keyword || c.category) === kw) addIdxs.add(i)
                                        })
                                        setAiSelectedCombos(addIdxs)
                                      } else {
                                        next.add(kwKey)
                                        const removeIdxs = new Set(aiSelectedCombos)
                                        aiResult.combinations.forEach((c, i) => {
                                          if ((c.keyword || c.category) === kw) removeIdxs.delete(i)
                                        })
                                        setAiSelectedCombos(removeIdxs)
                                      }
                                      setAiExcludedBrands(next)
                                    }}
                                    style={{
                                      cursor: 'pointer', marginRight: '6px', padding: '1px 6px', borderRadius: '4px',
                                      background: kwExcluded ? 'rgba(255,107,107,0.1)' : 'rgba(76,154,255,0.08)',
                                      color: kwExcluded ? '#FF6B6B' : '#4C9AFF',
                                      textDecoration: kwExcluded ? 'line-through' : 'none',
                                      opacity: kwExcluded ? 0.5 : 1, transition: 'all 0.15s',
                                    }}
                                  >{kw}</span>
                                )
                              })}
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  )
                })()}

                {/* IP위험 브랜드 — 취소선 표시, 클릭으로 제외/포함 전환 */}
                {(() => {
                  const unsafeBrands = aiResult.brands.filter(b => !b.is_safe)
                  if (unsafeBrands.length === 0) return null
                  return (
                    <div style={{ marginBottom: '14px', padding: '12px 14px', background: 'rgba(255,107,107,0.04)', border: '1px solid rgba(255,107,107,0.15)', borderRadius: '8px' }}>
                      <div style={{ fontSize: '0.75rem', color: '#FF6B6B', marginBottom: '8px', fontWeight: 600 }}>
                        IP위험 브랜드 ({unsafeBrands.length}개)
                        {aiExcludedBrands.size > 0 && <span style={{ color: '#888', fontWeight: 400 }}> — {aiExcludedBrands.size}개 제외</span>}
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {unsafeBrands.map(b => {
                          const excluded = aiExcludedBrands.has(b.brand)
                          return (
                            <span key={b.brand}
                              onClick={() => {
                                const next = new Set(aiExcludedBrands)
                                if (excluded) {
                                  next.delete(b.brand)
                                  const addIdxs = new Set(aiSelectedCombos)
                                  aiResult.combinations.forEach((c, i) => {
                                    if (c.brand === b.brand) addIdxs.add(i)
                                  })
                                  setAiSelectedCombos(addIdxs)
                                } else {
                                  next.add(b.brand)
                                  const removeIdxs = new Set(aiSelectedCombos)
                                  aiResult.combinations.forEach((c, i) => {
                                    if (c.brand === b.brand) removeIdxs.delete(i)
                                  })
                                  setAiSelectedCombos(removeIdxs)
                                }
                                setAiExcludedBrands(next)
                              }}
                              title={b.safety_reason}
                              style={{
                                fontSize: '0.75rem', padding: '3px 10px', borderRadius: '12px', cursor: 'pointer',
                                background: excluded ? 'rgba(255,107,107,0.12)' : 'rgba(255,107,107,0.06)',
                                border: `1px solid rgba(255,107,107,${excluded ? '0.4' : '0.2'})`,
                                color: '#FF6B6B',
                                textDecoration: 'line-through',
                                opacity: excluded ? 0.5 : 1,
                                transition: 'all 0.15s',
                              }}
                            >
                              {b.brand}
                            </span>
                          )
                        })}
                      </div>
                      <div style={{ fontSize: '0.68rem', color: '#666', marginTop: '6px' }}>
                        취소선 = IP위험 · 클릭하여 제외 (흐리게 처리됨)
                      </div>
                    </div>
                  )
                })()}

                {/* 조합 테이블 */}
                <div style={{ maxHeight: '350px', overflowY: 'auto', marginBottom: '12px' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #2D2D2D', position: 'sticky', top: 0, background: '#1A1A1A' }}>
                        <th style={{ padding: '8px 6px', textAlign: 'left', width: '36px' }}>
                          <input type="checkbox"
                            checked={(() => {
                              const selectable = aiResult.combinations.filter(c => !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`) && c.estimated_count >= aiMinCount)
                              const selectedSelectable = selectable.filter((c, i) => aiSelectedCombos.has(aiResult.combinations.indexOf(c)))
                              return selectable.length > 0 && selectedSelectable.length === selectable.length
                            })()}
                            onChange={e => {
                              if (e.target.checked) {
                                const all = new Set<number>()
                                aiResult.combinations.forEach((c, i) => {
                                  if (!aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`) && c.estimated_count >= aiMinCount) all.add(i)
                                })
                                setAiSelectedCombos(all)
                              } else {
                                setAiSelectedCombos(new Set())
                              }
                            }}
                            style={{ accentColor: '#FF8C00' }}
                          />
                        </th>
                        <th style={{ padding: '8px 6px', textAlign: 'left', color: '#888' }}>소싱처</th>
                        <th style={{ padding: '8px 6px', textAlign: 'left', color: '#888' }}>브랜드</th>
                        <th style={{ padding: '8px 6px', textAlign: 'left', color: '#888' }}>키워드</th>
                        <th style={{ padding: '8px 6px', textAlign: 'right', color: '#888' }}>예상상품수</th>
                        <th style={{ padding: '8px 6px', textAlign: 'center', color: '#888' }}>
                          <span>IP안전</span>
                          {aiResult.combinations.some(c => !c.is_safe && aiSelectedCombos.has(aiResult.combinations.indexOf(c))) && (
                            <button
                              onClick={() => {
                                const next = new Set(aiSelectedCombos)
                                aiResult.combinations.forEach((c, i) => {
                                  if (!c.is_safe) next.delete(i)
                                })
                                setAiSelectedCombos(next)
                              }}
                              style={{
                                marginLeft: '4px', fontSize: '0.65rem', padding: '1px 6px', borderRadius: '3px',
                                background: 'rgba(255,107,107,0.12)', border: '1px solid rgba(255,107,107,0.3)',
                                color: '#FF6B6B', cursor: 'pointer',
                              }}
                            >위험 해제</button>
                          )}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {aiResult.combinations.map((combo, idx) => {
                        const isExcluded = aiExcludedBrands.has(combo.brand) || aiExcludedBrands.has(`__kw__${combo.keyword || combo.category}`)
                        if (combo.estimated_count < aiMinCount) return null
                        return (
                          <tr key={idx} style={{
                            borderBottom: '1px solid #1D1D1D',
                            background: isExcluded ? 'rgba(255,107,107,0.04)' : aiSelectedCombos.has(idx) ? 'rgba(108,92,231,0.06)' : 'transparent',
                            opacity: isExcluded ? 0.4 : 1,
                          }}>
                            <td style={{ padding: '6px' }}>
                              <input type="checkbox"
                                checked={aiSelectedCombos.has(idx)}
                                disabled={isExcluded}
                                onChange={e => {
                                  const next = new Set(aiSelectedCombos)
                                  e.target.checked ? next.add(idx) : next.delete(idx)
                                  setAiSelectedCombos(next)
                                }}
                                style={{ accentColor: '#FF8C00' }}
                              />
                            </td>
                            <td style={{ padding: '6px', color: SITE_COLORS[combo.source_site] || '#888' }}>
                              {combo.source_site}
                            </td>
                            <td style={{ padding: '6px', color: !combo.is_safe ? '#FF6B6B' : isExcluded ? '#888' : '#E5E5E5', fontWeight: 500, textDecoration: !combo.is_safe ? 'line-through' : 'none' }}>{combo.brand}</td>
                            <td style={{ padding: '6px', color: '#C5C5C5' }}>{combo.keyword || combo.category}</td>
                            <td style={{ padding: '6px', textAlign: 'right', color: '#FFB84D', fontWeight: 600 }}>
                              {combo.estimated_count.toLocaleString()}
                            </td>
                            <td style={{ padding: '6px', textAlign: 'center' }}>
                              {combo.is_safe
                                ? <span style={{ color: '#51CF66', fontSize: '0.85rem' }}>안전</span>
                                : <span style={{ color: '#FF6B6B', fontSize: '0.85rem' }}>위험</span>
                              }
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                {/* 선택 요약 + 버튼 */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontSize: '0.82rem', color: '#888' }}>
                    {aiResult.combinations.filter((c, i) => aiSelectedCombos.has(i) && !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`)).length}개 선택 / 예상{' '}
                    {aiResult.combinations
                      .filter((c, i) => aiSelectedCombos.has(i) && !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`))
                      .reduce((s, c) => s + c.estimated_count, 0)
                      .toLocaleString()}개 상품
                  </span>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button onClick={() => {
                      setAiSourcingStep('config')
                      setAiResult(null)
                    }} style={{
                      padding: '8px 16px', borderRadius: '6px',
                      background: 'transparent', border: '1px solid #3D3D3D',
                      color: '#888', cursor: 'pointer',
                    }}>다시 설정</button>
                    <button
                      onClick={async () => {
                        const selected = aiResult.combinations
                          .filter((c, i) => aiSelectedCombos.has(i) && !aiExcludedBrands.has(c.brand) && !aiExcludedBrands.has(`__kw__${c.keyword || c.category}`) && c.estimated_count >= aiMinCount)
                          .map(c => ({ ...c, source_site: aiSourceSite }))
                        if (selected.length === 0) return showAlert('조합을 선택해주세요', 'error')
                        const totalEst = selected.reduce((s, c) => s + c.estimated_count, 0)
                        const site = SITES.find(s => s.id === aiSourceSite)
                        const ok = await showConfirm(
                          `${selected.length}개 검색그룹을 생성하시겠습니까?\n소싱처: ${site?.label || aiSourceSite}\n예상 상품수: ${totalEst.toLocaleString()}개`
                        )
                        if (!ok) return
                        setAiCreating(true)
                        try {
                          const res = await aiSourcingApi.createGroups(selected)
                          showAlert(`${res.created}개 검색그룹 생성 완료`, 'success')
                          setShowAiSourcingModal(false)
                          load(); loadTree()
                        } catch (err) {
                          showAlert(`그룹 생성 실패: ${err instanceof Error ? err.message : '오류'}`, 'error')
                        }
                        setAiCreating(false)
                      }}
                      disabled={aiCreating || aiSelectedCombos.size === 0}
                      style={{
                        padding: '8px 20px', borderRadius: '6px',
                        background: aiCreating ? 'rgba(108,92,231,0.1)' : 'linear-gradient(135deg, #6C5CE7, #A29BFE)',
                        color: '#fff', fontWeight: 700, fontSize: '0.85rem',
                        border: 'none', cursor: aiCreating ? 'not-allowed' : 'pointer',
                        opacity: aiSelectedCombos.size === 0 ? 0.5 : 1,
                      }}
                    >
                      {aiCreating ? '생성중...' : `${aiSelectedCombos.size}개 그룹 생성`}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
    </div>
  );
}
