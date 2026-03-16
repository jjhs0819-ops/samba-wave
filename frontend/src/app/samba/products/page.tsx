"use client";

import { useEffect, useState, useCallback } from "react";
import {
  collectorApi,
  policyApi,
  type SambaCollectedProduct,
  type SambaPolicy,
} from "@/lib/samba/api";

const MARKETS = [
  { id: "coupang", name: "쿠팡" },
  { id: "ssg", name: "신세계몰" },
  { id: "smartstore", name: "스마트스토어" },
  { id: "11st", name: "11번가" },
  { id: "gmarket", name: "지마켓" },
  { id: "auction", name: "옥션" },
  { id: "gsshop", name: "GS샵" },
  { id: "lotteon", name: "롯데ON" },
  { id: "lottehome", name: "롯데홈쇼핑" },
  { id: "homeand", name: "홈앤쇼핑" },
  { id: "hmall", name: "HMALL" },
  { id: "kream", name: "KREAM" },
];

function fmt(n: number): string {
  return n.toLocaleString();
}

export default function ProductsPage() {
  const [allProducts, setAllProducts] = useState<SambaCollectedProduct[]>([]);
  const [products, setProducts] = useState<SambaCollectedProduct[]>([]);
  const [policies, setPolicies] = useState<SambaPolicy[]>([]);
  const [loading, setLoading] = useState(true);

  // Filters
  const [searchType, setSearchType] = useState("name");
  const [searchQ, setSearchQ] = useState("");
  const [siteFilter, setSiteFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sortBy, setSortBy] = useState("collect-desc");
  const [pageSize, setPageSize] = useState(20);
  const [viewMode, setViewMode] = useState<"card" | "image">("card");

  // Selection
  const [selectAll, setSelectAll] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Log line
  const [logLine, setLogLine] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, pol] = await Promise.all([
        collectorApi.listProducts(0, 500).catch((e) => { console.error("listProducts error:", e); return []; }),
        policyApi.list().catch((e) => { console.error("listPolicies error:", e); return []; }),
      ]);
      console.log("loaded products:", p.length, "policies:", pol.length);
      setAllProducts(p);
      setPolicies(pol);
    } catch (e) {
      console.error("load error:", e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  // Apply filters / sort / pagination whenever dependencies change
  useEffect(() => {
    let filtered = [...allProducts];

    // Search
    if (searchQ.trim()) {
      const q = searchQ.toLowerCase();
      if (searchType === "name") {
        filtered = filtered.filter((p) => p.name.toLowerCase().includes(q));
      } else if (searchType === "brand") {
        filtered = filtered.filter((p) => (p.brand || "").toLowerCase().includes(q));
      } else if (searchType === "filter") {
        filtered = filtered.filter((p) => (p.search_filter_id || "").toLowerCase().includes(q));
      } else if (searchType === "no") {
        filtered = filtered.filter((p) => p.id.toLowerCase().includes(q) || (p.site_product_id || "").includes(q));
      } else if (searchType === "policy") {
        const matchPols = policies.filter((pol) => pol.name.toLowerCase().includes(q));
        const polIds = new Set(matchPols.map((pol) => pol.id));
        filtered = filtered.filter((p) => p.applied_policy_id && polIds.has(p.applied_policy_id));
      }
    }

    // Site filter
    if (siteFilter) filtered = filtered.filter((p) => p.source_site === siteFilter);

    // Status filter
    if (statusFilter) filtered = filtered.filter((p) => p.status === statusFilter);

    // Sort
    const isCollect = sortBy.startsWith("collect");
    const isDesc = sortBy.endsWith("desc");
    filtered.sort((a, b) => {
      const aD = isCollect ? (a.created_at || "") : (a.created_at || "");
      const bD = isCollect ? (b.created_at || "") : (b.created_at || "");
      return isDesc ? bD.localeCompare(aD) : aD.localeCompare(bD);
    });

    // Pagination
    if (pageSize > 0) filtered = filtered.slice(0, pageSize);

    setProducts(filtered);
  }, [allProducts, searchQ, searchType, siteFilter, statusFilter, sortBy, pageSize, policies]);

  const totalCount = (() => {
    let filtered = [...allProducts];
    if (searchQ.trim()) {
      const q = searchQ.toLowerCase();
      if (searchType === "name") filtered = filtered.filter((p) => p.name.toLowerCase().includes(q));
      else if (searchType === "brand") filtered = filtered.filter((p) => (p.brand || "").toLowerCase().includes(q));
    }
    if (siteFilter) filtered = filtered.filter((p) => p.source_site === siteFilter);
    if (statusFilter) filtered = filtered.filter((p) => p.status === statusFilter);
    return filtered.length;
  })();

  const allSites = [...new Set(allProducts.map((p) => p.source_site))].sort();

  const handleSearch = () => {
    // triggers re-render via useEffect
  };

  const handleDelete = async (id: string) => {
    if (!confirm("삭제하시겠습니까?")) return;
    await collectorApi.deleteProduct(id).catch(() => {});
    load();
  };

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!confirm(`선택된 ${selectedIds.size}개 상품을 삭제하시겠습니까?`)) return;
    for (const id of selectedIds) {
      await collectorApi.deleteProduct(id).catch(() => {});
    }
    setSelectedIds(new Set());
    setSelectAll(false);
    load();
  };

  const handlePolicyChange = async (productId: string, policyId: string) => {
    await collectorApi.updateProduct(productId, { applied_policy_id: policyId || undefined } as Partial<SambaCollectedProduct>).catch(() => {});
    load();
  };

  const handleEnrich = async (productId: string) => {
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || (process.env.NODE_ENV === 'production' ? 'https://samba-wave-production.up.railway.app' : 'http://localhost:28080')
      const res = await fetch(`${apiBase}/api/v1/samba/collector/enrich/${productId}`, { method: "POST" });
      const data = await res.json();
      if (res.ok && data.success) {
        load();
      } else {
        alert(data.detail || "상세 보강 실패");
      }
    } catch {
      alert("상세 보강 실패");
    }
  };

  const handleToggleMarket = async (productId: string, marketId: string) => {
    const product = allProducts.find((p) => p.id === productId);
    if (!product) return;
    const currentEnabled = ((product as unknown as Record<string, unknown>).market_enabled as Record<string, boolean>) || {};
    const isOn = currentEnabled[marketId] !== false;
    const newEnabled = { ...currentEnabled, [marketId]: !isOn };
    await collectorApi.updateProduct(productId, { market_enabled: newEnabled } as unknown as Partial<SambaCollectedProduct>).catch(() => {});
    // Optimistic update
    setAllProducts((prev) =>
      prev.map((p) =>
        p.id === productId ? { ...p, market_enabled: newEnabled } as unknown as SambaCollectedProduct : p
      )
    );
  };

  const handleSelectAll = (checked: boolean) => {
    setSelectAll(checked);
    if (checked) {
      setSelectedIds(new Set(products.map((p) => p.id)));
    } else {
      setSelectedIds(new Set());
    }
  };

  const handleCheckboxToggle = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0" }}>
      {/* KPI stat cards */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.25rem" }}>
        <div style={{
          background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "12px",
          padding: "1.75rem", borderLeft: "3px solid #FF8C00",
          display: "flex", flexDirection: "column", gap: "4px",
        }}>
          <p style={{ fontSize: "0.75rem", color: "#888", fontWeight: 500, letterSpacing: "0.04em", textTransform: "uppercase", margin: 0 }}>수집상품 수</p>
          <p style={{ fontSize: "1.625rem", fontWeight: 800, color: "#E5E5E5", letterSpacing: "-0.02em", margin: 0 }}>
            {allProducts.length}<span style={{ fontSize: "1rem", color: "#888", fontWeight: 500 }}>개</span>
          </p>
          <p style={{ fontSize: "0.75rem", color: "#666", margin: 0 }}>등록된 상품</p>
        </div>
        <div style={{
          background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "12px",
          padding: "1.75rem", borderLeft: "3px solid #FFB84D",
          display: "flex", flexDirection: "column", gap: "4px",
        }}>
          <p style={{ fontSize: "0.75rem", color: "#888", fontWeight: 500, letterSpacing: "0.04em", textTransform: "uppercase", margin: 0 }}>판매상품 수</p>
          <p style={{ fontSize: "1.625rem", fontWeight: 800, color: "#51CF66", letterSpacing: "-0.02em", margin: 0 }}>
            {allProducts.filter((p) => p.status === "registered").length}<span style={{ fontSize: "1rem", color: "#888", fontWeight: 500 }}>개</span>
          </p>
          <p style={{ fontSize: "0.75rem", color: "#666", margin: 0 }}>판매중인 상품</p>
        </div>
      </div>

      {/* Filter area */}
      <div style={{
        background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
        padding: "1rem", marginBottom: "1rem", fontSize: "0.875rem",
      }}>
        {/* Row 1: Date + site + status filters */}
        <div style={{ display: "flex", gap: "0.75rem", marginBottom: "0.75rem", flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span style={{ color: "#888", whiteSpace: "nowrap", fontSize: "0.8125rem" }}>등록일자</span>
            <input type="date" style={{
              width: "140px", padding: "0.375rem 0.5rem", fontSize: "0.8125rem",
              background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "6px",
              color: "#E5E5E5",
            }} />
            <span style={{ color: "#888" }}>~</span>
            <input type="date" style={{
              width: "140px", padding: "0.375rem 0.5rem", fontSize: "0.8125rem",
              background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "6px",
              color: "#E5E5E5",
            }} />
          </div>
          <select
            value={siteFilter}
            onChange={(e) => setSiteFilter(e.target.value)}
            style={{
              padding: "0.375rem 0.625rem", fontSize: "0.8125rem",
              background: "rgba(22,22,22,0.95)", border: "1px solid #353535",
              color: "#C5C5C5", borderRadius: "6px", width: "auto",
            }}
          >
            <option value="">소싱사이트</option>
            {allSites.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={{
              padding: "0.375rem 0.625rem", fontSize: "0.8125rem",
              background: "rgba(22,22,22,0.95)", border: "1px solid #353535",
              color: "#C5C5C5", borderRadius: "6px", width: "auto",
            }}
          >
            <option value="">판매현황</option>
            <option value="registered">마켓등록</option>
            <option value="collected">미등록</option>
          </select>
          <select style={{
            padding: "0.375rem 0.625rem", fontSize: "0.8125rem",
            background: "rgba(22,22,22,0.95)", border: "1px solid #353535",
            color: "#C5C5C5", borderRadius: "6px", width: "auto",
          }}>
            <option>판매상태</option>
          </select>
        </div>
        {/* Row 2: Search type + input + search button */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "nowrap", marginTop: "0.5rem" }}>
          <select
            value={searchType}
            onChange={(e) => setSearchType(e.target.value)}
            style={{
              padding: "0.375rem 0.5rem", fontSize: "0.8125rem",
              background: "#1E1E1E", border: "1px solid #3D3D3D", borderRadius: "6px",
              color: "#C5C5C5", width: "120px", flexShrink: 0,
            }}
          >
            <option value="name">상품명</option>
            <option value="filter">검색그룹</option>
            <option value="no">상품번호</option>
            <option value="policy">적용정책</option>
            <option value="brand">브랜드</option>
          </select>
          <input
            type="text"
            placeholder="검색어를 입력하세요."
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            style={{
              flex: 1, minWidth: "160px", maxWidth: "260px",
              padding: "0.375rem 0.625rem", fontSize: "0.8125rem",
              background: "#1E1E1E", border: "1px solid #3D3D3D", borderRadius: "6px",
              color: "#C5C5C5", outline: "none",
            }}
          />
          <button
            onClick={handleSearch}
            style={{
              background: "rgba(255,140,0,0.15)", border: "1px solid #FF8C00",
              color: "#FF8C00", padding: "0.375rem 0.75rem", borderRadius: "6px",
              fontSize: "0.8125rem", whiteSpace: "nowrap", flexShrink: 0, cursor: "pointer",
            }}
          >
            검색결과
          </button>
        </div>
      </div>

      {/* Product log line (hidden by default) */}
      {logLine && (
        <div style={{
          background: "#0A0A0A", border: "1px solid #1E1E1E", borderRadius: "6px",
          padding: "5px 12px", fontSize: "0.73rem", color: "#888", fontFamily: "monospace",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", marginBottom: "0.5rem",
        }}>
          {logLine}
        </div>
      )}

      {/* Result header + action bar */}
      <div style={{
        background: "rgba(18,18,18,0.95)", border: "1px solid #2A2A2A", borderRadius: "8px",
        padding: "8px 14px", marginBottom: "1rem",
        display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "8px",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "5px", cursor: "pointer", margin: 0 }}>
            <input
              type="checkbox"
              checked={selectAll}
              onChange={(e) => handleSelectAll(e.target.checked)}
              style={{ accentColor: "#FF8C00", width: "13px", height: "13px", cursor: "pointer" }}
            />
            <span style={{ fontSize: "0.8rem", color: "#666", whiteSpace: "nowrap" }}>전체선택</span>
          </label>
          <span style={{ fontSize: "0.875rem", color: "#E5E5E5", fontWeight: 600, whiteSpace: "nowrap" }}>
            상품관리 <span style={{ color: "#FF8C00" }}>( 총 <span>{totalCount}</span>개 검색 )</span>
          </span>
          <button style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid rgba(81,207,102,0.35)", borderRadius: "5px",
            color: "#51CF66", background: "rgba(81,207,102,0.08)", cursor: "pointer", whiteSpace: "nowrap",
          }}>AI이미지 변경</button>
          <button style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid rgba(81,207,102,0.35)", borderRadius: "5px",
            color: "#51CF66", background: "rgba(81,207,102,0.08)", cursor: "pointer", whiteSpace: "nowrap",
          }}>AI상품명변경</button>
          <button style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid rgba(76,154,255,0.35)", borderRadius: "5px",
            color: "#4C9AFF", background: "rgba(76,154,255,0.08)", cursor: "pointer", whiteSpace: "nowrap",
          }}>AI태그</button>
          <button style={{
            fontSize: "0.78rem", padding: "4px 12px",
            border: "1px solid rgba(76,154,255,0.35)", borderRadius: "5px",
            color: "#4C9AFF", background: "rgba(76,154,255,0.08)", cursor: "pointer", whiteSpace: "nowrap",
          }}>상품전송</button>
          <button
            onClick={handleBulkDelete}
            style={{
              fontSize: "0.78rem", padding: "4px 12px",
              border: "1px solid rgba(255,107,107,0.35)", borderRadius: "5px",
              color: "#FF6B6B", background: "rgba(255,107,107,0.08)", cursor: "pointer", whiteSpace: "nowrap",
            }}
          >삭제</button>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <button
            onClick={() => setViewMode("card")}
            style={{
              fontSize: "0.75rem", padding: "0.25rem 0.75rem", borderRadius: "6px", cursor: "pointer",
              border: viewMode === "card" ? "1px solid #FF8C00" : "1px solid #3D3D3D",
              color: viewMode === "card" ? "#FF8C00" : "#C5C5C5",
              background: viewMode === "card" ? "rgba(255,140,0,0.15)" : "transparent",
            }}
          >건별보기</button>
          <button
            onClick={() => setViewMode("image")}
            style={{
              fontSize: "0.75rem", padding: "0.25rem 0.75rem", borderRadius: "6px", cursor: "pointer",
              border: viewMode === "image" ? "1px solid #FF8C00" : "1px solid #3D3D3D",
              color: viewMode === "image" ? "#FF8C00" : "#C5C5C5",
              background: viewMode === "image" ? "rgba(255,140,0,0.15)" : "transparent",
            }}
          >이미지만보기</button>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            style={{
              width: "auto", padding: "0.25rem 0.5rem", fontSize: "0.75rem",
              background: "#1A1A1A", border: "1px solid #3D3D3D", color: "#C5C5C5", borderRadius: "6px",
            }}
          >
            <option value="collect-desc">수집일 최신순</option>
            <option value="collect-asc">수집일 오래된순</option>
            <option value="update-desc">업데이트일 최신순</option>
            <option value="update-asc">업데이트일 오래된순</option>
          </select>
          <select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            style={{
              width: "auto", padding: "0.25rem 0.5rem", fontSize: "0.75rem",
              background: "#1A1A1A", border: "1px solid #3D3D3D", color: "#C5C5C5", borderRadius: "6px",
            }}
          >
            <option value={20}>20개씩</option>
            <option value={50}>50개씩</option>
            <option value={100}>100개씩</option>
            <option value={0}>전체</option>
          </select>
        </div>
      </div>

      {/* Product list */}
      {loading ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "#555", fontSize: "0.9rem" }}>로딩 중...</div>
      ) : products.length === 0 ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "#555", fontSize: "0.9rem" }}>
          등록된 상품이 없습니다
        </div>
      ) : viewMode === "image" ? (
        /* Image grid view */
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "8px" }}>
          {products.map((p) => (
            <div key={p.id} style={{
              background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
              overflow: "hidden", cursor: "pointer",
            }}>
              <ProductImage src={p.images?.[0]} name={p.name} size={140} />
              <div style={{ padding: "6px 8px" }}>
                <p style={{ fontSize: "0.7rem", color: "#C5C5C5", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", margin: 0 }}>{p.name}</p>
                <p style={{ fontSize: "0.75rem", color: "#FF8C00", fontWeight: 600, margin: 0 }}>₩{fmt(p.sale_price)}</p>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Card view - matching original product-card style */
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {products.map((p, idx) => (
            <ProductCard
              key={p.id}
              product={p}
              idx={idx}
              policies={policies}
              selectedIds={selectedIds}
              onCheckboxToggle={handleCheckboxToggle}
              onDelete={handleDelete}
              onPolicyChange={handlePolicyChange}
              onToggleMarket={handleToggleMarket}
              onEnrich={handleEnrich}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ====== Product Card Component ====== */

interface ProductCardProps {
  product: SambaCollectedProduct;
  idx: number;
  policies: SambaPolicy[];
  selectedIds: Set<string>;
  onCheckboxToggle: (id: string, checked: boolean) => void;
  onDelete: (id: string) => void;
  onPolicyChange: (productId: string, policyId: string) => void;
  onToggleMarket: (productId: string, marketId: string) => void;
  onEnrich: (productId: string) => void;
}

function ProductCard({
  product: p, idx, policies, selectedIds,
  onCheckboxToggle, onDelete, onPolicyChange, onToggleMarket, onEnrich,
}: ProductCardProps) {
  const cost = p.sale_price || p.original_price || 0;
  const policy = policies.find((pol) => pol.id === p.applied_policy_id);
  const pricing = (policy?.pricing || {}) as Record<string, number>;
  const marginRate = pricing.marginRate || 15;
  const extraCharge = pricing.extraCharge || 0;
  const shippingCost = pricing.shippingCost || 0;
  const feeRate = pricing.feeRate || 0;

  // Market price calculation matching original formula
  let base = cost;
  if (shippingCost > 0) base += shippingCost;
  let marketPrice = base > 0 ? Math.ceil(base / (1 - marginRate / 100)) : 0;
  if (feeRate > 0 && marketPrice > 0) marketPrice = Math.ceil(marketPrice / (1 - feeRate / 100));
  if (extraCharge > 0) marketPrice += extraCharge;
  const profit = marketPrice - cost;

  const isActive = p.status !== "inactive" && p.status !== "collected";
  const statusColor = isActive ? "#51CF66" : "#888";
  const statusBg = isActive ? "rgba(81,207,102,0.12)" : "rgba(100,100,100,0.15)";
  const statusText = p.status === "registered" ? "등록됨" : p.status === "saved" ? "저장됨" : "수집됨";

  const regDate = p.created_at ? p.created_at.slice(0, 10) : "-";
  const no = String(idx + 1).padStart(3, "0");

  // Formula string
  const formulaParts = [`₩${fmt(cost)}`];
  if (shippingCost > 0) formulaParts.push(`+₩${fmt(shippingCost)}`);
  formulaParts.push(`÷(1-${marginRate}%)`);
  if (feeRate > 0) formulaParts.push(`÷(1-${feeRate}%)`);
  formulaParts.push(`= ₩${fmt(marketPrice)}`);
  const formulaStr = formulaParts.join(" ");

  // Policy basis text
  const policyBasis = [
    `마진 ${marginRate}%`,
    feeRate ? `수수료 ${feeRate}%` : "",
    shippingCost ? `배송비 ₩${fmt(shippingCost)}` : "",
    extraCharge ? `추가 ₩${fmt(extraCharge)}` : "",
  ].filter(Boolean).join(" · ");

  const marketEnabled = ((p as unknown as Record<string, unknown>).market_enabled as Record<string, boolean>) || {};

  const tdLabel: React.CSSProperties = { padding: "6px 8px", color: "#555", fontSize: "0.75rem", whiteSpace: "nowrap", verticalAlign: "middle" };
  const tdVal: React.CSSProperties = { padding: "6px 8px", verticalAlign: "middle" };

  return (
    <div style={{
      background: "rgba(22,22,22,0.9)", border: "1px solid #2A2A2A", borderRadius: "10px",
      overflow: "hidden",
    }}>
      {/* Card header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "7px 14px", background: "rgba(15,15,15,0.8)", borderBottom: "1px solid #222",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", fontSize: "0.75rem", color: "#666" }}>
          <input
            type="checkbox"
            checked={selectedIds.has(p.id)}
            onChange={(e) => onCheckboxToggle(p.id, e.target.checked)}
            style={{ accentColor: "#FF8C00", width: "13px", height: "13px", cursor: "pointer" }}
          />
          <span style={{ color: "#444" }}>No.{no}</span>
          {p.source_site && (
            <span style={{
              fontSize: "0.7rem", color: "#FF8C00", background: "rgba(255,140,0,0.1)",
              border: "1px solid rgba(255,140,0,0.25)", borderRadius: "4px",
              padding: "2px 8px", whiteSpace: "nowrap",
            }}>{p.source_site}</span>
          )}
          <span>수집 <span style={{ color: "#888" }}>{regDate}</span></span>
          <span style={{
            padding: "2px 10px", borderRadius: "4px", fontSize: "0.72rem", fontWeight: 500,
            background: statusBg, color: statusColor,
          }}>
            {statusText}
          </span>
        </div>
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "4px", cursor: "pointer" }}>
            <input type="checkbox" style={{ accentColor: "#51CF66", width: "12px", height: "12px", cursor: "pointer" }} />
            <span style={{ fontSize: "0.7rem", color: "#888" }}>재고잠금</span>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "4px", cursor: "pointer" }}>
            <input type="checkbox" style={{ accentColor: "#FF8C00", width: "12px", height: "12px", cursor: "pointer" }} />
            <span style={{ fontSize: "0.7rem", color: "#888" }}>삭제잠금</span>
          </label>
          <button style={{
            fontSize: "0.7rem", padding: "3px 10px",
            border: "1px solid rgba(255,140,0,0.3)", borderRadius: "5px",
            color: "#FF8C00", background: "rgba(255,140,0,0.08)", cursor: "pointer",
          }}>수정</button>
          <button
            onClick={() => onDelete(p.id)}
            style={{
              fontSize: "0.7rem", padding: "3px 10px",
              border: "1px solid rgba(255,107,107,0.3)", borderRadius: "5px",
              color: "#FF6B6B", background: "rgba(255,107,107,0.08)", cursor: "pointer",
            }}
          >삭제</button>
        </div>
      </div>

      {/* Card body */}
      <div style={{ display: "flex", gap: "0", padding: "14px" }}>
        {/* Left: Image section */}
        <div style={{
          width: "130px", flexShrink: 0, display: "flex", flexDirection: "column",
          alignItems: "center", gap: "8px", paddingRight: "14px", borderRight: "1px solid #222",
        }}>
          <ProductImage src={p.images?.[0]} name={p.name} size={110} />
          <button style={{
            fontSize: "0.68rem", color: "#666", background: "transparent",
            border: "1px solid #2D2D2D", borderRadius: "4px", padding: "3px 10px",
            cursor: "pointer", width: "100%",
          }}>이미지 변경</button>
          {p.source_site && (
            <span style={{
              fontSize: "0.7rem", color: "#FF8C00", background: "rgba(255,140,0,0.1)",
              border: "1px solid rgba(255,140,0,0.25)", borderRadius: "4px",
              padding: "2px 8px", width: "100%", textAlign: "center",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>{p.source_site}</span>
          )}
        </div>

        {/* Right: Detail info */}
        <div style={{ flex: 1, paddingLeft: "16px" }}>
          {/* Action button bar */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: "3px", marginBottom: "8px" }}>
            <button style={{
              fontSize: "0.72rem", padding: "3px 9px", background: "#1E1E1E",
              color: "#999", border: "1px solid #2D2D2D", borderRadius: "3px", cursor: "pointer", whiteSpace: "nowrap",
            }}>가격변경이력</button>
            <button style={{
              fontSize: "0.72rem", padding: "3px 9px", background: "#1E1E1E",
              color: "#999", border: "1px solid #2D2D2D", borderRadius: "3px", cursor: "pointer", whiteSpace: "nowrap",
            }}>원문링크</button>
            <button
              onClick={() => onEnrich(p.id)}
              style={{
              fontSize: "0.72rem", padding: "3px 9px", background: "#1E1E1E",
              color: "#999", border: "1px solid #2D2D2D", borderRadius: "3px", cursor: "pointer", whiteSpace: "nowrap",
            }}>업데이트</button>
            <button style={{
              fontSize: "0.72rem", padding: "3px 9px", background: "#1E1E1E",
              color: "#FF6B6B", border: "1px solid rgba(255,107,107,0.2)", borderRadius: "3px", cursor: "pointer", whiteSpace: "nowrap",
            }}>마켓삭제</button>
          </div>

          {/* Detail table */}
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8125rem" }}>
            <colgroup>
              <col style={{ width: "80px" }} />
              <col />
            </colgroup>
            <tbody>
              {/* 원 상품명 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>원 상품명</td>
                <td style={tdVal}>
                  <span style={{ color: "#D1D9EE", fontWeight: 500 }}>{p.name}</span>
                </td>
              </tr>
              {/* 등록 상품명 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>등록 상품명</td>
                <td style={tdVal}>
                  <span style={{ color: "#D1D9EE", fontSize: "0.8rem" }}>{p.name}</span>
                </td>
              </tr>
              {/* 영문 상품명 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>영문 상품명</td>
                <td style={tdVal}>
                  <input type="text" placeholder="영문 상품명 (English)" defaultValue={(p as unknown as Record<string, string>).name_en || ""}
                    style={{ width: "100%", padding: "3px 7px", fontSize: "0.8rem", background: "#1A1A1A", border: "1px solid #2D2D2D", color: "#C5C5C5", borderRadius: "4px", outline: "none" }} />
                </td>
              </tr>
              {/* 일문 상품명 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>일문 상품명</td>
                <td style={tdVal}>
                  <input type="text" placeholder="일문 상품명 (日本語)" defaultValue={(p as unknown as Record<string, string>).name_ja || ""}
                    style={{ width: "100%", padding: "3px 7px", fontSize: "0.8rem", background: "#1A1A1A", border: "1px solid #2D2D2D", color: "#C5C5C5", borderRadius: "4px", outline: "none" }} />
                </td>
              </tr>
              {/* 브랜드 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>브랜드</td>
                <td style={tdVal}>
                  <span style={{ color: "#888", fontSize: "0.8rem" }}>{p.brand || "-"}</span>
                </td>
              </tr>
              {/* Normal price */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>정상가</td>
                <td style={tdVal}>
                  <span style={{ color: "#C5C5C5", fontWeight: 600 }}>
                    {p.original_price > 0 ? `₩${fmt(p.original_price)}` : "-"}
                  </span>
                  {p.original_price > 0 && p.sale_price < p.original_price && (
                    <span style={{ color: "#FF6B6B", fontSize: "0.72rem", marginLeft: "6px" }}>
                      {Math.round((1 - p.sale_price / p.original_price) * 100)}% 할인 → ₩{fmt(p.sale_price)}
                    </span>
                  )}
                </td>
              </tr>
              {/* Cost price (best benefit) */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>원가</td>
                <td style={tdVal}>
                  <span style={{ color: "#FFB84D", fontWeight: 600 }}>₩{fmt(cost)}</span>
                  <span style={{ color: "#444", fontSize: "0.72rem", marginLeft: "6px" }}>최대혜택가</span>
                </td>
              </tr>
              {/* Market price */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>마켓가격</td>
                <td style={tdVal}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", width: "100%" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap", whiteSpace: "nowrap" }}>
                      <span style={{ color: "#FFB84D", fontWeight: 600 }}>₩{fmt(marketPrice)}</span>
                      <span style={{ color: "#888", fontSize: "0.75rem" }}>+₩{fmt(profit)}</span>
                      {policyBasis && (
                        <span style={{ color: "#555", fontSize: "0.71rem", borderLeft: "1px solid #2D2D2D", paddingLeft: "6px" }}>
                          {policyBasis}
                        </span>
                      )}
                    </div>
                    <span style={{ marginLeft: "auto", fontSize: "0.7rem", color: "#3A3A3A", fontFamily: "monospace", whiteSpace: "nowrap", paddingLeft: "12px" }}>
                      {formulaStr}
                    </span>
                  </div>
                </td>
              </tr>
              {/* 카테고리 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>카테고리</td>
                <td style={tdVal}>
                  <span style={{ fontSize: "0.8rem", color: "#C5C5C5" }}>{p.category || "-"}</span>
                </td>
              </tr>
              {/* 상품정보 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={{ ...tdLabel, verticalAlign: "top", paddingTop: "10px" }}>상품정보</td>
                <td style={tdVal}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 16px", fontSize: "0.78rem" }}>
                    {(p as unknown as Record<string, string>).origin && <span style={{ color: "#888" }}>제조국 <span style={{ color: "#C5C5C5" }}>{(p as unknown as Record<string, string>).origin}</span></span>}
                    {(p as unknown as Record<string, string>).manufacturer && <span style={{ color: "#888" }}>제조사 <span style={{ color: "#C5C5C5" }}>{(p as unknown as Record<string, string>).manufacturer}</span></span>}
                    {!(p as unknown as Record<string, string>).origin && !(p as unknown as Record<string, string>).manufacturer && <span style={{ color: "#444" }}>정보 없음</span>}
                  </div>
                </td>
              </tr>
              {/* 검색그룹 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>검색그룹</td>
                <td style={tdVal}>
                  {p.search_filter_id ? (
                    <span style={{ background: "rgba(255,140,0,0.08)", border: "1px solid rgba(255,140,0,0.25)", color: "rgba(255,180,100,0.85)", fontSize: "0.72rem", padding: "1px 8px", borderRadius: "10px" }}>
                      {p.search_filter_id}
                    </span>
                  ) : <span style={{ color: "#444", fontSize: "0.75rem" }}>-</span>}
                </td>
              </tr>
              {/* 태그 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>태그</td>
                <td style={tdVal}>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", alignItems: "center" }}>
                    <input type="text" placeholder={`태그는 ','로 구분입력`}
                      style={{ fontSize: "0.7rem", padding: "2px 7px", border: "1px solid #2D2D2D", borderRadius: "4px", color: "#C5C5C5", background: "#1A1A1A", outline: "none", width: "160px" }} />
                    <button style={{ fontSize: "0.68rem", padding: "2px 7px", border: "1px solid rgba(100,100,255,0.3)", borderRadius: "4px", color: "#8B8FD4", background: "rgba(100,100,255,0.08)", cursor: "pointer", whiteSpace: "nowrap" }}>추가</button>
                  </div>
                </td>
              </tr>
              {/* 적용정책 */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>적용정책</td>
                <td style={tdVal}>
                  <select
                    value={p.applied_policy_id || ""}
                    onChange={(e) => onPolicyChange(p.id, e.target.value)}
                    style={{
                      background: "rgba(22,22,22,0.9)", border: "1px solid #2D2D2D",
                      color: "#C5C5C5", borderRadius: "4px", padding: "2px 6px",
                      fontSize: "0.75rem", outline: "none",
                    }}
                  >
                    <option value="">기본 (그룹 정책)</option>
                    {policies.map((pol) => (
                      <option key={pol.id} value={pol.id}>{pol.name}</option>
                    ))}
                  </select>
                </td>
              </tr>
              {/* Options */}
              <tr style={{ borderBottom: "1px solid #1E1E1E" }}>
                <td style={tdLabel}>옵션</td>
                <td style={tdVal}>
                  {p.options && p.options.length > 0 ? (
                    <OptionPanel options={p.options} />
                  ) : (
                    <span style={{ color: "#444", fontSize: "0.75rem" }}>※ 옵션 미설정 -- 단일상품</span>
                  )}
                </td>
              </tr>
              {/* Market ON/OFF switches */}
              <tr>
                <td style={tdLabel}>ON-OFF</td>
                <td style={tdVal}>
                  <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center" }}>
                    {MARKETS.map((m) => {
                      const on = marketEnabled[m.id] !== false;
                      return (
                        <span key={m.id} style={{ display: "inline-flex", alignItems: "center", gap: "4px", marginRight: "10px", marginBottom: "2px" }}>
                          <button
                            onClick={() => onToggleMarket(p.id, m.id)}
                            style={{
                              width: "32px", height: "18px", borderRadius: "9px",
                              border: "none", cursor: "pointer", position: "relative",
                              background: on ? "#FF8C00" : "#333", transition: "background 0.2s",
                              padding: 0,
                            }}
                          >
                            <span style={{
                              position: "absolute", top: "2px",
                              left: on ? "14px" : "2px",
                              width: "14px", height: "14px", borderRadius: "50%",
                              background: "#fff", transition: "left 0.2s",
                            }} />
                          </button>
                          <span style={{ fontSize: "0.7rem", color: on ? "#C5C5C5" : "#555" }}>{m.name}</span>
                        </span>
                      );
                    })}
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

/* ====== Option Panel Component ====== */

function OptionPanel({ options }: { options: unknown[] }) {
  const [open, setOpen] = useState(false);
  const [selectAll, setSelectAll] = useState(true);
  const opts = options as Record<string, unknown>[];

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span style={{ color: "#888", fontSize: "0.78rem" }}>{opts.length}개 옵션</span>
        <button
          onClick={() => setOpen(!open)}
          style={{
            fontSize: "0.7rem", padding: "2px 8px",
            border: "1px solid #2D2D2D", borderRadius: "4px",
            color: "#888", background: "transparent", cursor: "pointer",
          }}
        >
          {open ? "접기" : "펼치기"}
        </button>
      </div>
      {open && (
        <div style={{ marginTop: "8px" }}>
          {/* 상단 버튼 + 안내문구 */}
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.5rem" }}>
            <button style={{ padding: "0.3rem 0.75rem", fontSize: "0.8rem", background: "linear-gradient(135deg,#FF8C00,#FFB84D)", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer" }}>선택옵션수정</button>
            <button style={{ padding: "0.3rem 0.75rem", fontSize: "0.8rem", background: "rgba(50,50,50,0.8)", color: "#C5C5C5", border: "1px solid #3D3D3D", borderRadius: "4px", cursor: "pointer" }}>옵션담기</button>
          </div>
          <p style={{ fontSize: "0.72rem", color: "#888", marginBottom: "0.75rem", lineHeight: 1.5 }}>
            ※ 옵션별로 가격 및 재고 수정이 가능합니다. 가격/재고를 수정하시면 해외 가격/재고는 무시되고, 수정하신 가격/재고로 반영됩니다.<br />
            ※ 체크박스에 체크되어 있는 상품만 마켓으로 전송됩니다. 전송을 원하지 않는 옵션은 체크를 해제하신 후 옵션저장 버튼을 클릭해주세요.
          </p>

          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #2D2D2D" }}>
                <th style={{ width: "36px", padding: "0.5rem", textAlign: "center" }}>
                  <input type="checkbox" checked={selectAll} onChange={(e) => setSelectAll(e.target.checked)} style={{ cursor: "pointer", accentColor: "#FF8C00" }} />
                </th>
                <th style={{ padding: "0.5rem", textAlign: "left", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                  옵션명
                  <button style={{ marginLeft: "0.4rem", fontSize: "0.7rem", padding: "1px 6px", background: "rgba(255,140,0,0.15)", color: "#FF8C00", border: "1px solid rgba(255,140,0,0.3)", borderRadius: "3px", cursor: "pointer" }}>옵션명변경</button>
                  <button style={{ marginLeft: "0.3rem", fontSize: "0.7rem", padding: "1px 6px", background: "rgba(255,255,255,0.05)", color: "#C5C5C5", border: "1px solid #3D3D3D", borderRadius: "3px", cursor: "pointer" }}>옵션추가</button>
                </th>
                <th style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                  원가<br /><span style={{ fontSize: "0.7rem", color: "#555", fontWeight: 400 }}>(일반배송)</span>
                </th>
                <th style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                  상품가
                  <button style={{ marginLeft: "0.3rem", fontSize: "0.7rem", padding: "1px 6px", background: "rgba(255,255,255,0.05)", color: "#C5C5C5", border: "1px solid #3D3D3D", borderRadius: "3px", cursor: "pointer" }}>가격수정</button>
                </th>
                <th style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                  옵션재고
                  <button style={{ marginLeft: "0.3rem", fontSize: "0.7rem", padding: "1px 6px", background: "rgba(255,255,255,0.05)", color: "#C5C5C5", border: "1px solid #3D3D3D", borderRadius: "3px", cursor: "pointer" }}>재고수정</button>
                </th>
                <th style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.8rem", color: "#999", fontWeight: 500 }}>
                  마켓전송가격<br /><span style={{ fontSize: "0.7rem", color: "#666" }}>(마켓수수료 포함가격)</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {opts.map((o, idx) => {
                const isBrandDelivery = o.isBrandDelivery === true;
                const stock = o.stock !== undefined && o.stock !== null ? Number(o.stock) : -1;
                const isSoldOut = !isBrandDelivery && (o.isSoldOut === true || stock === 0);
                const optionCost = isSoldOut ? 0 : Number(o.price || 0);
                const optionSalePrice = Math.ceil(optionCost * 1.15); // 기본 15% 마진
                const isChecked = !isSoldOut;

                let stockDisplay: React.ReactNode;
                if (isBrandDelivery) {
                  stockDisplay = <span style={{ color: "#6B8AFF", fontWeight: 600, fontSize: "0.78rem" }}>브랜드배송</span>;
                } else if (isSoldOut) {
                  stockDisplay = <span style={{ color: "#FF6B6B", fontWeight: 600 }}>품절</span>;
                } else if (stock < 0 || stock >= 999) {
                  stockDisplay = (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                      <input type="number" placeholder="직접입력" style={{ width: "70px", background: "rgba(255,255,255,0.05)", border: "1px solid #3D3D3D", color: "#E5E5E5", borderRadius: "4px", padding: "2px 6px", textAlign: "right", fontSize: "0.875rem" }} />
                      <span style={{ fontSize: "0.72rem", color: "#51CF66" }}>{stock >= 999 ? "충분" : "재고있음"}</span>
                    </span>
                  );
                } else {
                  stockDisplay = (
                    <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                      <input type="number" defaultValue={stock} style={{ width: "60px", background: "rgba(255,255,255,0.05)", border: "1px solid #3D3D3D", color: "#E5E5E5", borderRadius: "4px", padding: "2px 6px", textAlign: "right", fontSize: "0.875rem" }} />
                      <span>개</span>
                    </span>
                  );
                }

                return (
                  <tr key={idx} style={{ borderBottom: "1px solid rgba(45,45,45,0.5)", opacity: isSoldOut ? 0.5 : 1 }}>
                    <td style={{ padding: "0.5rem", textAlign: "center" }}>
                      <input type="checkbox" defaultChecked={isChecked} style={{ cursor: "pointer", accentColor: "#FF8C00" }} />
                    </td>
                    <td style={{ padding: "0.5rem", fontSize: "0.875rem", color: "#E5E5E5" }}>
                      {String(o.name || o.value || `옵션${idx + 1}`)}
                    </td>
                    <td style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.875rem", color: "#C5C5C5" }}>
                      {optionCost > 0 ? `₩${optionCost.toLocaleString()}` : "-"}
                    </td>
                    <td style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.875rem", color: "#E5E5E5" }}>
                      <input type="number" defaultValue={optionSalePrice} style={{ width: "100px", background: "rgba(255,255,255,0.05)", border: "1px solid #3D3D3D", color: "#E5E5E5", borderRadius: "4px", padding: "2px 6px", textAlign: "right", fontSize: "0.875rem" }} />
                      <span>원</span>
                    </td>
                    <td style={{ padding: "0.5rem", textAlign: "right", fontSize: "0.875rem", color: "#E5E5E5" }}>
                      {stockDisplay}
                    </td>
                    <td style={{ padding: "0.5rem", textAlign: "right" }}>
                      <span style={{ color: "#555", fontSize: "0.75rem" }}>미계산</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ====== Product Image Component ====== */

function ProductImage({ src, name, size = 110 }: { src?: string; name: string; size?: number }) {
  const [error, setError] = useState(false);
  const firstChar = (name || "?")[0];

  if (!src || error) {
    return (
      <div style={{
        width: size, height: size, minWidth: size, borderRadius: "8px",
        border: "1px dashed #3D3D3D", display: "flex", alignItems: "center",
        justifyContent: "center", background: "#1A1A1A",
      }}>
        <span style={{ fontSize: size * 0.45, color: "#FF8C00", fontFamily: "sans-serif" }}>{firstChar}</span>
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={name}
      onError={() => setError(true)}
      style={{
        width: size, height: size, minWidth: size, objectFit: "cover",
        borderRadius: "8px", border: "1px solid #2D2D2D",
      }}
    />
  );
}
