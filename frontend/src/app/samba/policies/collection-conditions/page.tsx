"use client";

import { useCallback, useEffect, useState } from "react";
import { collectorApi, policyApi, type SambaSearchFilter, type SambaPolicy } from "@/lib/samba/api/commerce";
import FilterConditionsTable from "./FilterConditionsTable";

export default function CollectionConditionsPage() {
  const [filters, setFilters] = useState<SambaSearchFilter[]>([]);
  const [policies, setPolicies] = useState<SambaPolicy[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [f, p] = await Promise.all([
        collectorApi.listFilters(),
        policyApi.list(),
      ]);
      setFilters(f.filter((x) => !x.is_folder));
      setPolicies(p);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div style={{ padding: "2rem" }}>로딩 중...</div>;

  return (
    <div style={{ padding: "1rem 0" }}>
      <h2 style={{ fontSize: "1.125rem", fontWeight: 700, marginBottom: "1rem" }}>
        상품수집조건 관리 및 정책적용
      </h2>
      <FilterConditionsTable filters={filters} policies={policies} onReload={load} />
    </div>
  );
}
