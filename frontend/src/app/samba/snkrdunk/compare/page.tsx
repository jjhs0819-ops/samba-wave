'use client'

import { useEffect, useState, useCallback } from 'react'
import { SAMBA_PREFIX, fetchWithAuth } from '@/lib/samba/legacy'
import { useTheme } from '@/lib/samba/useTheme'
import { useThemeStore } from '@/lib/samba/themeStore'

interface CompareItem {
  snkr_id: string
  snkr_name: string
  snkr_image: string
  kream_id: string
  kream_name: string
  kream_image: string
  psa10_price: number
  psa10_stock: number
}

interface CompareResponse {
  total: number
  page: number
  per_page: number
  items: CompareItem[]
}

const PER_PAGE = 20

export default function SnkrdunkComparePage() {
  const c = useTheme()
  const isDark = useThemeStore((s) => s.theme === 'dark')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<CompareResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [cursor, setCursor] = useState(0) // 현재 페이지 내 인덱스
  const [removed, setRemoved] = useState<Set<string>>(new Set())
  const [removing, setRemoving] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set())

  useEffect(() => { document.title = 'SAMBA-스니덩크 매칭검수' }, [])

  const load = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const res = await fetchWithAuth(`${SAMBA_PREFIX}/kream/snkrdunk-compare?page=${p}&per_page=${PER_PAGE}`)
      const json = await res.json() as CompareResponse
      setData(json)
      setCursor(0)
      setRemoved(new Set())
      setConfirmed(new Set())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(page) }, [page, load])

  const items = (data?.items ?? []).filter(it => !removed.has(it.snkr_id))
  const current = items[cursor]
  const totalPages = data ? Math.ceil(data.total / PER_PAGE) : 1

  const handleRemoveMatch = async (item: CompareItem) => {
    if (removing) return
    setRemoving(item.snkr_id)
    try {
      await fetchWithAuth(`${SAMBA_PREFIX}/kream/snkrdunk-compare/${item.snkr_id}/match`, { method: 'DELETE' })
      setRemoved(prev => new Set([...prev, item.snkr_id]))
      // 다음 상품으로
      if (cursor >= items.length - 2) {
        setCursor(Math.max(0, items.length - 2))
      }
    } finally {
      setRemoving(null)
    }
  }

  const handleConfirm = (item: CompareItem) => {
    setConfirmed(prev => new Set([...prev, item.snkr_id]))
    setCursor(prev => Math.min(prev + 1, items.length - 1))
  }

  const prev = () => setCursor(p => Math.max(0, p - 1))
  const next = () => setCursor(p => Math.min(p + 1, items.length - 1))

  const bg = isDark ? 'bg-gray-900 text-white' : 'bg-gray-50 text-gray-900'
  const cardBg = isDark ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
  const subText = isDark ? 'text-gray-400' : 'text-gray-500'

  return (
    <div className={`min-h-screen ${bg} p-4`}>
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-lg font-bold">스니덩크 ↔ 크림 매칭 검수</h1>
          <p className={`text-sm ${subText}`}>
            전체 {data ? fmtNum(data.total) : '-'}개 | 페이지 {page}/{totalPages} | {fmtNum(cursor + 1)}/{fmtNum(items.length)}번째
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1 || loading}
            className="px-3 py-1.5 text-sm rounded border disabled:opacity-40"
          >
            ◀ 이전 페이지
          </button>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages || loading}
            className="px-3 py-1.5 text-sm rounded border disabled:opacity-40"
          >
            다음 페이지 ▶
          </button>
        </div>
      </div>

      {loading && (
        <div className={`text-center py-20 ${subText}`}>크림 이미지 로딩 중...</div>
      )}

      {!loading && current && (
        <>
          {/* 진행 바 */}
          <div className={`w-full h-1 rounded mb-4 ${isDark ? 'bg-gray-700' : 'bg-gray-200'}`}>
            <div
              className="h-1 rounded bg-blue-500 transition-all"
              style={{ width: `${((cursor + 1) / items.length) * 100}%` }}
            />
          </div>

          {/* 비교 카드 */}
          <div className={`border rounded-xl p-6 ${cardBg} shadow-sm`}>
            <div className="grid grid-cols-2 gap-8">
              {/* 스니덩크 */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <span className="px-2 py-0.5 text-xs font-bold bg-orange-500 text-white rounded">SNKRDUNK</span>
                  <a
                    href={`https://snkrdunk.com/apparels/${current.snkr_id}/used`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-blue-500 hover:underline"
                  >
                    #{current.snkr_id} ↗
                  </a>
                </div>
                {current.snkr_image ? (
                  <img
                    src={current.snkr_image}
                    alt={current.snkr_name}
                    className="w-full aspect-square object-contain rounded-lg border mb-3"
                    style={{ maxHeight: 320 }}
                    onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                  />
                ) : (
                  <div className={`w-full aspect-square rounded-lg border mb-3 flex items-center justify-center ${subText}`}>
                    이미지 없음
                  </div>
                )}
                <p className="font-semibold text-sm leading-snug">{current.snkr_name || '-'}</p>
                <p className={`text-xs mt-1 ${subText}`}>
                  PSA10 {fmtNum(current.psa10_price)}엔 / 재고 {fmtNum(current.psa10_stock)}개
                </p>
              </div>

              {/* 크림 */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <span className="px-2 py-0.5 text-xs font-bold bg-green-600 text-white rounded">KREAM</span>
                  <a
                    href={`https://kream.co.kr/products/${current.kream_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-blue-500 hover:underline"
                  >
                    #{current.kream_id} ↗
                  </a>
                </div>
                {current.kream_image ? (
                  <img
                    src={current.kream_image}
                    alt={current.kream_name}
                    className="w-full aspect-square object-contain rounded-lg border mb-3"
                    style={{ maxHeight: 320 }}
                    onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                  />
                ) : (
                  <div className={`w-full aspect-square rounded-lg border mb-3 flex items-center justify-center ${subText}`}>
                    이미지 없음
                  </div>
                )}
                <p className="font-semibold text-sm leading-snug">{current.kream_name || '-'}</p>
              </div>
            </div>

            {/* 버튼 */}
            <div className="flex items-center justify-between mt-6 pt-4 border-t">
              <div className="flex gap-2">
                <button
                  onClick={prev}
                  disabled={cursor <= 0}
                  className="px-4 py-2 rounded border text-sm disabled:opacity-40"
                >
                  ← 이전
                </button>
                <button
                  onClick={next}
                  disabled={cursor >= items.length - 1}
                  className="px-4 py-2 rounded border text-sm disabled:opacity-40"
                >
                  다음 →
                </button>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={() => handleRemoveMatch(current)}
                  disabled={!!removing}
                  className="px-5 py-2 rounded-lg bg-red-500 hover:bg-red-600 text-white text-sm font-medium disabled:opacity-50"
                >
                  {removing === current.snkr_id ? '해제 중...' : '오매칭 — 매칭해제'}
                </button>
                <button
                  onClick={() => handleConfirm(current)}
                  disabled={confirmed.has(current.snkr_id)}
                  className="px-5 py-2 rounded-lg bg-blue-500 hover:bg-blue-600 text-white text-sm font-medium disabled:opacity-50"
                >
                  {confirmed.has(current.snkr_id) ? '확인됨' : '맞음 — 다음'}
                </button>
              </div>
            </div>
          </div>

          {/* 미니 목록 (현재 페이지) */}
          <div className="mt-4 grid grid-cols-5 gap-2">
            {items.map((it, i) => (
              <button
                key={it.snkr_id}
                onClick={() => setCursor(i)}
                className={[
                  'p-2 rounded-lg border text-left text-xs transition-all',
                  i === cursor ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30' : cardBg,
                  confirmed.has(it.snkr_id) ? 'opacity-50' : '',
                ].join(' ')}
              >
                {it.snkr_image && (
                  <img
                    src={it.snkr_image}
                    alt=""
                    className="w-full aspect-square object-contain rounded mb-1"
                    onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                  />
                )}
                <p className="truncate font-medium">{it.snkr_name}</p>
                <p className={`truncate ${subText}`}>#{it.kream_id}</p>
              </button>
            ))}
          </div>
        </>
      )}

      {!loading && items.length === 0 && (
        <div className={`text-center py-20 ${subText}`}>이 페이지 항목 없음</div>
      )}
    </div>
  )
}

function fmtNum(n: number): string {
  return n.toLocaleString()
}
