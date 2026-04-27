"use client"

import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import { collectorApi, proxyApi, type SambaSearchFilter } from '@/lib/samba/api/commerce'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtTime } from '@/lib/samba/utils'
import { fmtNum } from '@/lib/samba/styles'

// AI 비용 사용 내역 타입
type AiUsage = { calls: number; tokens: number; cost: number; date: string }

// AI 이미지 변환 스코프 (대표/추가/상세)
type AiImgScope = { thumbnail: boolean; additional: boolean; detail: boolean }

// AI 모델 프리셋 항목 타입
type AiPreset = { key: string; label: string; desc: string; image: string | null }

type Props = {
  // 상태값
  lastAiUsage: AiUsage | null
  aiImgScope: AiImgScope
  aiImgMode: string
  aiModelPreset: string
  aiPresetList: AiPreset[]
  aiImgTransforming: boolean
  imgFiltering: boolean
  imgFilterScopes: Set<string>
  selectedIds: Set<string>
  displayedFilters: SambaSearchFilter[]
  tree: SambaSearchFilter[]
  aiJobAbortRef: MutableRefObject<boolean>

  // 세터
  setAiImgScope: Dispatch<SetStateAction<AiImgScope>>
  setAiImgMode: Dispatch<SetStateAction<string>>
  setAiModelPreset: Dispatch<SetStateAction<string>>
  setAiImgTransforming: Dispatch<SetStateAction<boolean>>
  setImgFiltering: Dispatch<SetStateAction<boolean>>
  setImgFilterScopes: Dispatch<SetStateAction<Set<string>>>
  setSelectedIds: Dispatch<SetStateAction<Set<string>>>
  setSelectAll: Dispatch<SetStateAction<boolean>>
  setLastAiUsage: Dispatch<SetStateAction<AiUsage | null>>
  setAiJobModal: Dispatch<SetStateAction<boolean>>
  setAiJobTitle: Dispatch<SetStateAction<string>>
  setAiJobLogs: Dispatch<SetStateAction<string[]>>
  setAiJobDone: Dispatch<SetStateAction<boolean>>

  // 콜백
  load: () => void
  loadTree: () => void
}

export default function AiToolsPanel(props: Props) {
  const {
    lastAiUsage,
    aiImgScope,
    aiImgMode,
    aiModelPreset,
    aiPresetList,
    aiImgTransforming,
    imgFiltering,
    imgFilterScopes,
    selectedIds,
    displayedFilters,
    tree,
    aiJobAbortRef,
    setAiImgScope,
    setAiImgMode,
    setAiModelPreset,
    setAiImgTransforming,
    setImgFiltering,
    setImgFilterScopes,
    setSelectedIds,
    setSelectAll,
    setLastAiUsage,
    setAiJobModal,
    setAiJobTitle,
    setAiJobLogs,
    setAiJobDone,
    load,
    loadTree,
  } = props

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '0.7fr 1.3fr 1fr', gap: '8px', marginTop: '1.25rem' }}>
      {/* AI 비용 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(81,207,102,0.08)', border: '1px solid rgba(81,207,102,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.8125rem', color: '#51CF66', fontWeight: 600 }}>AI 비용</span>
        {lastAiUsage ? (
          <>
            <span style={{ fontSize: '0.78rem', color: '#E5E5E5' }}>{fmtNum(lastAiUsage.calls)}건</span>
            <span style={{ fontSize: '0.78rem', color: '#888' }}>·</span>
            <span style={{ fontSize: '0.78rem', color: '#FFB84D' }}>₩{fmtNum(lastAiUsage.cost)}</span>
            <span style={{ fontSize: '0.7rem', color: '#555' }}>{lastAiUsage.date}</span>
          </>
        ) : (
          <span style={{ fontSize: '0.78rem', color: '#555' }}>사용 내역 없음</span>
        )}
      </div>
      {/* AI 이미지 변환 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.8125rem', color: '#FF8C00', fontWeight: 600 }}>AI 이미지 변환</span>
        {([['thumbnail', '대표'], ['additional', '추가'], ['detail', '상세']] as const).map(([key, label]) => (
          <label key={key} style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
            <input type="checkbox" checked={aiImgScope[key]}
              onChange={() => setAiImgScope(prev => ({ ...prev, [key]: !prev[key] }))}
              style={{ accentColor: '#FF8C00', width: '13px', height: '13px' }} />
            <span style={{ fontSize: '0.78rem', color: '#E5E5E5' }}>{label}</span>
          </label>
        ))}
        <select value={aiImgMode} onChange={e => setAiImgMode(e.target.value)} style={{ background: '#1A1A1A', border: '1px solid #333', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', fontSize: '0.78rem' }}>
          <option value="background">배경 제거</option>
          <option value="model_to_product">모델→상품</option>
          <option value="scene">연출컷</option>
          <option value="model">모델 착용</option>
        </select>
        {aiImgMode === 'model' && (
          <select
            value={aiModelPreset}
            onChange={e => setAiModelPreset(e.target.value)}
            style={{ background: '#1A1A1A', border: '1px solid #333', color: '#E5E5E5', borderRadius: '4px', padding: '2px 6px', fontSize: '0.78rem' }}
          >
            <option value="auto">자동 (성별·연령 판별)</option>
            {['여성', '남성', '키즈 여아', '키즈 남아'].map(group => {
              const groupPresets = aiPresetList.filter(p => {
                if (group === '여성') return p.key.startsWith('female_')
                if (group === '남성') return p.key.startsWith('male_')
                if (group === '키즈 여아') return p.key.startsWith('kids_girl_')
                return p.key.startsWith('kids_boy_')
              })
              if (!groupPresets.length) return null
              return (
                <optgroup key={group} label={group}>
                  {groupPresets.map(p => (
                    <option key={p.key} value={p.key}>{p.label.replace(/^.*—\s*/, '')}</option>
                  ))}
                </optgroup>
              )
            })}
          </select>
        )}
        <span style={{ fontSize: '0.78rem', color: '#888' }}>({fmtNum(selectedIds.size)}개 그룹)</span>
        <button
          onClick={async () => {
            if (selectedIds.size === 0) { showAlert('검색그룹을 선택해주세요'); return }
            // displayedFilters와 교집합으로 실제 대상 결정
            const activeIds = [...selectedIds].filter(id => displayedFilters.some(f => f.id === id))
            if (activeIds.length === 0) { showAlert('현재 필터에 해당하는 그룹이 없습니다'); return }
            if (!aiImgScope.thumbnail && !aiImgScope.additional && !aiImgScope.detail) { showAlert('변환 대상 이미지를 선택해주세요 (대표/추가/상세)'); return }
            // 그룹에 속한 상품 조회 → AI 미변환 상품만 추출
            type ProductItem = { id: string; name?: string; images: string[]; detail_images: string[]; tags: string[] }
            const productIds: string[] = []
            const productDetails = new Map<string, ProductItem>()
            let skippedAi = 0
            for (const gid of activeIds) {
              try {
                const products = await collectorApi.listProducts(0, 10000, gid)
                if (Array.isArray(products)) {
                  for (const p of products) {
                    if ((p.tags || []).includes('__ai_image__')) { skippedAi++; continue }
                    productIds.push(p.id)
                    productDetails.set(p.id, { id: p.id, name: p.name || '', images: p.images || [], detail_images: p.detail_images || [], tags: p.tags || [] })
                  }
                }
              } catch { /* 스킵 */ }
            }
            if (productIds.length === 0) { showAlert(skippedAi > 0 ? `모든 상품이 이미 AI 변환 완료 (${fmtNum(skippedAi)}건 스킵)` : '선택된 그룹에 상품이 없습니다'); return }
            const skipMsg = skippedAi > 0 ? `\n(AI 변환 완료 ${fmtNum(skippedAi)}건 스킵)` : ''
            const scopeLabel = [aiImgScope.thumbnail && '대표', aiImgScope.additional && '추가', aiImgScope.detail && '상세'].filter(Boolean).join('+')
            const ok = await showConfirm(`${fmtNum(activeIds.length)}개 그룹 (${fmtNum(productIds.length)}개 상품)의 ${scopeLabel} 이미지를 변환하시겠습니까?${skipMsg}`)
            if (!ok) return
            const ts = fmtTime
            setAiImgTransforming(true)
            aiJobAbortRef.current = false
            setAiJobTitle(`AI 이미지변환 (${fmtNum(productIds.length)}개)`)
            setAiJobLogs([])
            setAiJobDone(false)
            setAiJobModal(true)
            const addLog = (msg: string) => setAiJobLogs(prev => [...prev, msg])
            const startTime = ts()
            addLog(`시작: ${startTime} (${fmtNum(productIds.length)}개 상품)`)
            let success = 0
            let fail = 0
            if (aiImgMode === 'background') {
              // 배경제거: 백엔드 job queue 일괄 제출 + 폴링
              addLog(`[${ts()}] 배경 제거 큐 제출 중... (${fmtNum(productIds.length)}개 상품)`)
              try {
                let batchRes: Awaited<ReturnType<typeof proxyApi.transformImages>> | null = null
                for (let attempt = 0; attempt <= 2; attempt++) {
                  if (attempt > 0) {
                    const delay = attempt === 1 ? 2000 : 4000
                    addLog(`[${ts()}] 큐 등록 재시도 ${attempt}/2 (${delay / 1000}초 후)...`)
                    await new Promise(r => setTimeout(r, delay))
                  }
                  try { batchRes = await proxyApi.transformImages(productIds, aiImgScope, 'background'); break }
                  catch { if (attempt === 2) throw new Error('Failed to fetch') }
                }
                const batchResVal = batchRes!
                if (!batchResVal.success || !batchResVal.job_id) {
                  fail = productIds.length
                  addLog(`큐 등록 실패: ${batchResVal.message}`)
                } else {
                  const jid = batchResVal.job_id
                  addLog(`[${ts()}] 큐 등록 완료 — 워커 처리 대기 중...`)
                  let pollCount = 0
                  const maxPolls = 720
                  let lastLoggedCur = -1
                  let lastLoggedStatus = ''
                  while (pollCount < maxPolls && !aiJobAbortRef.current) {
                    await new Promise(r => setTimeout(r, 5000))
                    pollCount++
                    try {
                      const st = await proxyApi.bgJobStatus(jid)
                      const cur = st.current ?? 0
                      const tot = st.total ?? productIds.length
                      setAiJobTitle(`배경제거 [${fmtNum(cur)}/${fmtNum(tot)}]`)
                      // 진행 중일 때만 — 상태 또는 current가 바뀔 때만 로그
                      if (st.status === 'running' && (cur !== lastLoggedCur || st.status !== lastLoggedStatus)) {
                        const curId = productIds[cur] ?? productIds[cur - 1]
                        const curName = (productDetails.get(curId)?.name || curId || '').slice(0, 20)
                        addLog(`[${ts()}] ${curName} ${fmtNum(cur)}/${fmtNum(tot)} 진행중`)
                        lastLoggedCur = cur
                        lastLoggedStatus = st.status
                      }
                      if (st.status === 'completed') {
                        success = st.total_transformed || 0
                        fail = st.total_failed || 0
                        addLog(`[${ts()}] 완료 — 성공 ${fmtNum(success)}개 / 실패 ${fmtNum(fail)}개`)
                        break
                      }
                      if (st.status === 'failed' || st.status === 'not_found') {
                        fail = productIds.length
                        addLog(`[${ts()}] 워커 처리 실패`)
                        break
                      }
                    } catch { /* 폴링 오류 무시 */ }
                  }
                  if (aiJobAbortRef.current) addLog(`⛔ 사용자 중단`)
                  else if (pollCount >= maxPolls) { addLog(`타임아웃 (60분 초과)`); fail = productIds.length - success }
                }
              } catch (e) {
                fail = productIds.length
                addLog(`오류: ${e instanceof Error ? e.message : ''}`)
              }
            } else {
              for (let i = 0; i < productIds.length; i++) {
                if (aiJobAbortRef.current) { addLog(`\n⛔ 사용자 중단 (${fmtNum(i)}/${fmtNum(productIds.length)})`); break }
                const label = productIds[i].slice(-8)
                setAiJobTitle(`AI 이미지변환 [${fmtNum(i + 1)}/${fmtNum(productIds.length)}]`)
                try {
                  const res = await proxyApi.transformImages([productIds[i]], aiImgScope, aiImgMode, aiModelPreset)
                  if (res.success) { success++; addLog(`[${ts()}] [${fmtNum(i + 1)}/${fmtNum(productIds.length)}] ${label} — 완료`) }
                  else { fail++; addLog(`[${ts()}] [${fmtNum(i + 1)}/${fmtNum(productIds.length)}] ${label} — 실패: ${res.message}`) }
                } catch (e) { fail++; addLog(`[${ts()}] [${fmtNum(i + 1)}/${fmtNum(productIds.length)}] ${label} — 오류: ${e instanceof Error ? e.message : ''}`) }
              }
            }
            const endTime = ts()
            setAiJobTitle(`AI 이미지변환 완료 (${fmtNum(success)}/${fmtNum(productIds.length)})`)
            addLog(`\n완료: 성공 ${fmtNum(success)}개 / 실패 ${fmtNum(fail)}개`)
            addLog(`시작 ${startTime} → 종료 ${endTime}`)
            setAiJobDone(true)
            setAiImgTransforming(false)
            const cnt = success
            setLastAiUsage({ calls: cnt, tokens: cnt * 2000, cost: cnt * 3, date: new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit' }) })
            setSelectedIds(new Set()); setSelectAll(false)
          }}
          disabled={aiImgTransforming || selectedIds.size === 0}
          style={{ marginLeft: 'auto', background: aiImgTransforming ? '#333' : 'rgba(255,140,0,0.15)', border: '1px solid rgba(255,140,0,0.35)', color: aiImgTransforming ? '#888' : '#FF8C00', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.78rem', cursor: aiImgTransforming ? 'not-allowed' : 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
        >{aiImgTransforming ? '변환중...' : '변환 실행'}</button>
      </div>

      {/* 이미지 필터링 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.625rem', padding: '0.5rem 1rem', background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)', borderRadius: '8px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.8125rem', color: '#818CF8', fontWeight: 600 }}>이미지 필터링</span>
        {([['images', '대표'], ['detail_images', '추가'], ['detail', '상세']] as const).map(([key, label]) => (
          <label key={key} style={{ display: 'flex', alignItems: 'center', gap: '4px', cursor: 'pointer' }}>
            <input type="checkbox" checked={imgFilterScopes.has(key)}
              onChange={() => setImgFilterScopes(prev => {
                const next = new Set(prev)
                if (next.has(key)) next.delete(key); else next.add(key)
                return next
              })}
              style={{ accentColor: '#818CF8', width: '13px', height: '13px' }} />
            <span style={{ fontSize: '0.78rem', color: '#E5E5E5' }}>{label}</span>
          </label>
        ))}
        <button
          onClick={async () => {
            if (selectedIds.size === 0) { showAlert('검색그룹을 선택해주세요'); return }
            if (imgFilterScopes.size === 0) { showAlert('필터링 대상을 선택해주세요'); return }
            // displayedFilters와 교집합으로 실제 대상 결정
            const activeGroupIds = [...selectedIds].filter(id => displayedFilters.some(f => f.id === id))
            if (activeGroupIds.length === 0) { showAlert('현재 필터에 해당하는 그룹이 없습니다'); return }
            const scopeLabel = [...imgFilterScopes].map(s => s === 'images' ? '대표' : s === 'detail_images' ? '추가' : '상세').join('+')
            const ok = await showConfirm(`선택된 ${fmtNum(activeGroupIds.length)}개 그룹의 ${scopeLabel} 이미지를 필터링하시겠습니까?\n(모델컷/연출컷/배너를 자동 제거합니다)`)
            if (!ok) return
            const scope = imgFilterScopes.has('images') && imgFilterScopes.has('detail_images') && imgFilterScopes.has('detail') ? 'all' : imgFilterScopes.has('images') && imgFilterScopes.has('detail_images') ? 'images' : imgFilterScopes.has('detail') ? 'detail' : [...imgFilterScopes][0] || 'images'
            setImgFiltering(true)
            aiJobAbortRef.current = false
            setAiJobTitle(`이미지 필터링 (${fmtNum(activeGroupIds.length)}개 그룹)`)
            setAiJobLogs([])
            setAiJobDone(false)
            setAiJobModal(true)
            const addLog = (msg: string) => setAiJobLogs(prev => [...prev, msg])
            const ts = fmtTime
            const startTime = ts()
            let success = 0
            let fail = 0
            let totalTall = 0
            let totalVisionRemoved = 0
            try {
              // 그룹별로 상품 목록을 가져와 상품관리와 동일하게 개별 처리
              const groupIds = activeGroupIds
              let totalProducts = 0
              let processedProducts = 0
              for (let gi = 0; gi < groupIds.length; gi++) {
                if (aiJobAbortRef.current) { addLog(`\n⛔ 사용자 중단`); break }
                const gid = groupIds[gi]
                const groupLabel = tree.find(t => t.id === gid)?.keyword?.slice(0, 20) || gid.slice(-8)
                addLog(`\n[그룹 ${fmtNum(gi + 1)}/${fmtNum(groupIds.length)}] ${groupLabel} — 상품 조회중...`)
                try {
                  const { items: products } = await collectorApi.scrollProducts({ search_filter_id: gid, limit: 10000 })
                  totalProducts += products.length
                  addLog(`[그룹 ${fmtNum(gi + 1)}/${fmtNum(groupIds.length)}] ${groupLabel} — ${fmtNum(products.length)}개 상품`)
                  if (gi === 0 && products.length > 0) addLog(`\n시작: ${startTime} (${fmtNum(totalProducts)}개 상품)\n`)
                  for (let i = 0; i < products.length; i++) {
                    if (aiJobAbortRef.current) { addLog(`\n⛔ 사용자 중단 (${fmtNum(processedProducts)}/${fmtNum(totalProducts)})`); break }
                    const prod = products[i]
                    const prodName = prod.name?.slice(0, 25) || '이름없음'
                    const prodNo = prod.site_product_id || prod.id.slice(-8)
                    const prodBrand = prod.brand || '-'
                    const label = `${prodBrand} / ${prodNo} / ${prodName}${prod.name && prod.name.length > 25 ? '...' : ''}`
                    processedProducts++
                    setAiJobTitle(`이미지 필터링 [${fmtNum(processedProducts)}/${fmtNum(totalProducts)}] ${prodBrand} / ${prodNo}`)
                    try {
                      const steps: string[] = []
                      // 1) 프론트에서 추가이미지 비율 체크 (세로 2배 이상 → 제거)
                      if (scope === 'detail_images' || scope === 'images' || scope === 'all') {
                        const imgs = prod.images || []
                        if (imgs.length > 1) {
                          const tallCheck = await Promise.all(imgs.slice(1).map(url =>
                            new Promise<boolean>(resolve => {
                              const img = new window.Image()
                              img.onload = () => {
                                const isTall = img.naturalHeight > img.naturalWidth * 2
                                resolve(isTall)
                              }
                              img.onerror = () => resolve(false)
                              img.src = url
                              setTimeout(() => resolve(false), 10000)
                            })
                          ))
                          const tallUrls = imgs.slice(1).filter((_, idx) => tallCheck[idx])
                          if (tallUrls.length > 0) {
                            const kept = imgs.filter(u => !tallUrls.includes(u))
                            await collectorApi.updateProduct(prod.id, { images: kept })
                            totalTall += tallUrls.length
                            steps.push(`긴이미지 ${fmtNum(tallUrls.length)}장 제거`)
                          }
                        }
                      }
                      // 2) 백엔드 이미지 필터링 (CLIP)
                      const r = await proxyApi.filterProductImages([prod.id], '', scope)
                      if (r.success) {
                        success++
                        const removed = r.total_removed || 0
                        totalVisionRemoved += removed
                        if (removed > 0) steps.push(`CLIP ${removed}장 제거`)
                        else steps.push('CLIP 변동없음')
                        addLog(`[${ts()}] [${fmtNum(processedProducts)}/${fmtNum(totalProducts)}] ${label} — ${steps.join(' → ')}`)
                      } else { fail++; addLog(`[${ts()}] [${fmtNum(processedProducts)}/${fmtNum(totalProducts)}] ${label} — ${steps.length > 0 ? steps.join(' → ') + ' → ' : ''}실패`) }
                    } catch (e) { fail++; addLog(`[${ts()}] [${fmtNum(processedProducts)}/${fmtNum(totalProducts)}] ${label} — 오류: ${e instanceof Error ? e.message : ''}`) }
                  }
                } catch (e) {
                  addLog(`[그룹 ${fmtNum(gi + 1)}/${fmtNum(groupIds.length)}] ${groupLabel} — 상품 조회 실패: ${e instanceof Error ? e.message : ''}`)
                }
              }
              const summary = [`성공 ${fmtNum(success)}개`, `실패 ${fmtNum(fail)}개`]
              if (totalTall > 0) summary.push(`긴이미지 ${fmtNum(totalTall)}장 제거`)
              if (totalVisionRemoved > 0) summary.push(`CLIP ${fmtNum(totalVisionRemoved)}장 제거`)
              const endTime = ts()
              setAiJobTitle(`이미지 필터링 완료 (${fmtNum(success)}/${fmtNum(totalProducts)})`)
              addLog(`\n완료: ${summary.join(' / ')}`)
              addLog(`시작 ${startTime} → 종료 ${endTime}`)
            } catch (e) { addLog(`오류: ${e instanceof Error ? e.message : '오류'}`) }
            finally {
              setAiJobDone(true)
              setImgFiltering(false)
              const apiCalls = success + fail
              setLastAiUsage({ calls: apiCalls, tokens: apiCalls * 1000, cost: apiCalls * 15, date: new Date().toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit' }) })
              setSelectedIds(new Set()); setSelectAll(false)
              load(); loadTree()
            }
          }}
          disabled={imgFiltering || selectedIds.size === 0}
          style={{ marginLeft: 'auto', background: imgFiltering ? '#333' : 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.35)', color: imgFiltering ? '#888' : '#818CF8', padding: '0.3rem 0.875rem', borderRadius: '6px', fontSize: '0.78rem', cursor: imgFiltering ? 'not-allowed' : 'pointer', fontWeight: 600, whiteSpace: 'nowrap' }}
        >{imgFiltering ? '필터링중...' : `필터링 실행 (${fmtNum(selectedIds.size)}개)`}</button>
      </div>
    </div>
  )
}
