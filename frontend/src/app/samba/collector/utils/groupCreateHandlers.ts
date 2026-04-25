'use client'

import { Dispatch, SetStateAction, MutableRefObject } from 'react'
import { collectorApi, proxyApi } from '@/lib/samba/api/commerce'
import { showAlert } from '@/components/samba/Modal'
import { fmtNum } from '@/lib/samba/styles'

interface CreateGroupArgs {
  collectUrl: string
  selectedSite: string
  setCollecting: Dispatch<SetStateAction<boolean>>
  addLog: (msg: string) => void
  setPendingKeyword: Dispatch<SetStateAction<string>>
  setBrandSearchResults: Dispatch<SetStateAction<Array<{ brandCode: string; brandName: string }>>>
  setSelectedBrandCodes: Dispatch<SetStateAction<Set<string>>>
  setBrandModalAction: Dispatch<SetStateAction<'scan' | 'create'>>
  setShowMusinsaBrandModal: Dispatch<SetStateAction<boolean>>
  executeCreateGroup: (brandCode?: string) => Promise<void> | void
}

export async function performHandleCreateGroup(args: CreateGroupArgs) {
  const {
    collectUrl, selectedSite, setCollecting, addLog,
    setPendingKeyword, setBrandSearchResults, setSelectedBrandCodes,
    setBrandModalAction, setShowMusinsaBrandModal, executeCreateGroup,
  } = args
  const input = collectUrl.trim()
  if (!input) return

  if (selectedSite === 'MUSINSA') {
    let isUrl = false
    let hasBrand = false
    try {
      const parsed = new URL(input)
      isUrl = true
      hasBrand = !!parsed.searchParams.get('brand')
    } catch { /* 평문 키워드 */ }

    if (!isUrl && !hasBrand) {
      try {
        setCollecting(true)
        addLog(`브랜드 검색 중: ${input}`)
        const res = await proxyApi.brandSearch(input)
        if (res.brands && res.brands.length > 0) {
          if (res.brands.length === 1) {
            addLog(`브랜드 자동 선택: ${res.brands[0].brandName} (${res.brands[0].brandCode})`)
            await executeCreateGroup(res.brands[0].brandCode)
            return
          }
          setPendingKeyword(input)
          setBrandSearchResults(res.brands)
          setSelectedBrandCodes(new Set())
          setBrandModalAction('create')
          setShowMusinsaBrandModal(true)
          setCollecting(false)
          return
        }
        addLog('매칭 브랜드 없음 → 키워드 검색으로 진행')
      } catch { /* ignore */ }
      setCollecting(false)
    }
  }
  await executeCreateGroup()
}

interface BrandConfirmArgs {
  codes: Set<string>
  setShowMusinsaBrandModal: Dispatch<SetStateAction<boolean>>
  setBrandSearchResults: Dispatch<SetStateAction<Array<{ brandCode: string; brandName: string }>>>
  setDetectedBrandCode: Dispatch<SetStateAction<string>>
  brandModalAction: 'scan' | 'create'
  setBrandScanning: Dispatch<SetStateAction<boolean>>
  pendingKeyword: string
  pendingScanGf: MutableRefObject<string>
  addLog: (msg: string) => void
  setBrandCategories: Dispatch<SetStateAction<Array<{ categoryCode: string; path: string; count: number; category1: string; category2: string; category3: string }>>>
  setBrandTotal: Dispatch<SetStateAction<number>>
  setBrandSelectedCats: Dispatch<SetStateAction<Set<string>>>
  executeCreateGroup: (brandCode?: string) => Promise<void> | void
}

export async function performHandleBrandConfirm(args: BrandConfirmArgs) {
  const {
    codes, setShowMusinsaBrandModal, setBrandSearchResults, setDetectedBrandCode,
    brandModalAction, setBrandScanning, pendingKeyword, pendingScanGf,
    addLog, setBrandCategories, setBrandTotal, setBrandSelectedCats,
    executeCreateGroup,
  } = args
  setShowMusinsaBrandModal(false)
  setBrandSearchResults([])
  const brandList = [...codes]
  if (brandList.length > 0) setDetectedBrandCode(brandList[0])

  if (brandModalAction === 'scan') {
    setBrandScanning(true)
    try {
      const keyword = pendingKeyword
      const gf = pendingScanGf.current
      addLog(`[카테고리스캔] 무신사 "${keyword}" 스캔 시작... (${fmtNum(brandList.length)}개 브랜드)`)
      const allCategories: Array<{ categoryCode: string; path: string; count: number; category1: string; category2: string; category3: string }> = []
      let totalCount = 0
      for (const code of brandList.length > 0 ? brandList : ['']) {
        const res = await collectorApi.brandScan(code, gf, keyword)
        allCategories.push(...res.categories)
        totalCount += res.total
        if (code) addLog(`[카테고리스캔] ${keyword || code}: ${fmtNum(res.groupCount)}개 카테고리, ${fmtNum(res.total)}건`)
      }
      setBrandCategories(allCategories)
      setBrandTotal(totalCount)
      setBrandSelectedCats(new Set(allCategories.map(c => c.categoryCode)))
      addLog(`[카테고리스캔] 합계: ${fmtNum(allCategories.length)}개 카테고리, 총 ${fmtNum(totalCount)}건`)
    } catch (e) {
      addLog(`[카테고리스캔] 무신사 스캔 실패: ${e instanceof Error ? e.message : '오류'}`)
      showAlert(e instanceof Error ? e.message : '스캔 실패', 'error')
    }
    setBrandScanning(false)
  } else {
    for (const code of brandList.length > 0 ? brandList : [undefined]) {
      await executeCreateGroup(code)
    }
  }
}
