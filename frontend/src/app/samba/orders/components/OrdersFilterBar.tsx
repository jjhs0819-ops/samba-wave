'use client'

import React, { Dispatch, SetStateAction, useState } from 'react'
import { type SambaMarketAccount } from '@/lib/samba/api/commerce'
import { type SambaSourcingAccount } from '@/lib/samba/api/operations'
import { orderApi } from '@/lib/samba/legacy'
import { PERIOD_BUTTONS } from '@/lib/samba/constants'
import { MARKETS } from '@/lib/samba/markets'
import { makeInputStyle, fmtNum } from '@/lib/samba/styles'
import { useTheme } from '@/lib/samba/useTheme'
import { btn, btnDisabled } from '@/lib/samba/buttons'
import { formatDateInput, getPeriodStart, getPeriodEnd } from '@/lib/samba/utils'
import { showAlert } from '@/components/samba/Modal'
import { STATUS_MAP, STATUS_SELECT_COLORS } from '../constants'

interface Props {
  isProductMode: boolean
  period: string
  setPeriod: Dispatch<SetStateAction<string>>
  customStart: string
  setCustomStart: Dispatch<SetStateAction<string>>
  customEnd: string
  setCustomEnd: Dispatch<SetStateAction<string>>
  startLocked: boolean
  setStartLocked: Dispatch<SetStateAction<boolean>>
  dateLocked: boolean
  setDateLocked: Dispatch<SetStateAction<boolean>>
  syncAccountId: string
  setSyncAccountId: Dispatch<SetStateAction<string>>
  syncing: boolean
  handleFetch: () => void | Promise<void>
  bulkStatus: string
  setBulkStatus: Dispatch<SetStateAction<string>>
  bulkUpdating: boolean
  handleBulkAction: () => void | Promise<void>
  selectedIdsSize: number
  filteredOrdersCount: number
  filteredOrdersTotalSale: number
  autoCancelCount?: number // 현재 페이지 주문 중 소싱처 자동취소 관련 건수 (0이면 미표시)
  searchCategory: string
  setSearchCategory: Dispatch<SetStateAction<string>>
  searchText: string
  setSearchText: Dispatch<SetStateAction<string>>
  loadOrders: () => void | Promise<void>
  marketFilter: string
  setMarketFilter: Dispatch<SetStateAction<string>>
  siteFilter: string
  setSiteFilter: Dispatch<SetStateAction<string>>
  accountFilter: string
  setAccountFilter: Dispatch<SetStateAction<string>>
  marketStatus: string
  setMarketStatus: Dispatch<SetStateAction<string>>
  registrationFilter: string
  setRegistrationFilter: Dispatch<SetStateAction<string>>
  inputFilter: string
  setInputFilter: Dispatch<SetStateAction<string>>
  invoiceFilter: string
  setInvoiceFilter: Dispatch<SetStateAction<string>>
  statusFilter: string
  setStatusFilter: Dispatch<SetStateAction<string>>
  sortBy: string
  setSortBy: Dispatch<SetStateAction<string>>
  pageSize: number
  setPageSize: Dispatch<SetStateAction<number>>
  accounts: SambaMarketAccount[]
  sourcingAccounts: SambaSourcingAccount[]
  siteOptions: Array<{ value: string; label: string }>
  selectedOrderIds: string[]
  // [최저가탐색] 현재 화면 주문접수+소싱주문번호 없음 대상 배치 스캔 (자동 실행 없음 — 버튼 클릭만)
  priceScanning: boolean
  onPriceScoutBatch: () => void | Promise<void>
}

export default function OrdersFilterBar(props: Props) {
  const c = useTheme()
  const {
    isProductMode,
    period, setPeriod, customStart, setCustomStart, customEnd, setCustomEnd,
    startLocked, setStartLocked, dateLocked, setDateLocked,
    syncAccountId, setSyncAccountId, syncing, handleFetch,
    bulkStatus, setBulkStatus, bulkUpdating, handleBulkAction, selectedIdsSize,
    filteredOrdersCount, filteredOrdersTotalSale, autoCancelCount = 0,
    searchCategory, setSearchCategory, searchText, setSearchText, loadOrders,
    marketFilter, setMarketFilter, siteFilter, setSiteFilter,
    accountFilter, setAccountFilter, marketStatus, setMarketStatus,
    registrationFilter, setRegistrationFilter,
    inputFilter, setInputFilter, invoiceFilter, setInvoiceFilter, statusFilter, setStatusFilter,
    sortBy, setSortBy, pageSize, setPageSize,
    accounts, sourcingAccounts, siteOptions,
    selectedOrderIds,
    priceScanning, onPriceScoutBatch,
  } = props

  const [excelDownloading, setExcelDownloading] = useState(false)
  const [excelMenuOpen, setExcelMenuOpen] = useState(false)

  // [바로가기]/[다중] 공용 — 주문번호 검색 프리셋: 올해 + 전체 주문상태 + 나머지 필터 초기화.
  // 날짜고정/시작고정이 걸려 있어도 해제 후 적용 (버튼을 누른 의도가 우선)
  const applyOrderNumberSearchPreset = () => {
    setDateLocked(false)
    setStartLocked(false)
    setPeriod('thisyear')
    const start = getPeriodStart('thisyear')
    setCustomStart(start ? formatDateInput(start) : '')
    setCustomEnd(formatDateInput(getPeriodEnd('thisyear')))
    setSearchCategory('order_number')
    setStatusFilter('')
    setMarketStatus('')
    setRegistrationFilter('')
    setInputFilter('')
    setInvoiceFilter('')
  }

  // 다중 주문번호 조회(#9) — [다중] 토글 ON 시 검색 input이 같은 자리에서 textarea로 전환
  const [multiSearchMode, setMultiSearchMode] = useState(false)
  const toggleMultiSearch = () => {
    const next = !multiSearchMode
    setMultiSearchMode(next)
    // ON 시 주문번호 검색 프리셋 자동 적용 (카테고리 고정 포함). OFF 시엔 되돌리지 않음
    if (next) applyOrderNumberSearchPreset()
  }
  // 조회 실행 — 다중 모드에서 200건 초과 시 안내만 하고 조회는 막지 않음 (백엔드가 앞 200건만 사용)
  const handleSearch = () => {
    if (multiSearchMode) {
      const tokens = [...new Set(searchText.split(/[\s,]+/).filter(Boolean))]
      if (tokens.length > 200) {
        showAlert(`주문번호 ${fmtNum(tokens.length)}건 입력 — 최대 200건까지만 조회됩니다 (앞 200건)`, 'info')
      }
    }
    loadOrders()
  }
  const handleExcelDownload = async (format: 'ub1' | 'lotte' | 'cj' = 'ub1') => {
    if (excelDownloading) return
    setExcelDownloading(true)
    try {
      if (selectedOrderIds.length > 0) {
        await orderApi.downloadExcel({ order_ids: selectedOrderIds, sort_by: sortBy, format })
      } else {
        if (!customStart || !customEnd) {
          showAlert('날짜 범위를 선택해주세요', 'info')
          return
        }
        await orderApi.downloadExcel({
          start: customStart,
          end: customEnd,
          market_filter: marketFilter,
          site_filter: siteFilter,
          account_filter: accountFilter,
          market_status: marketStatus,
          status_filter: statusFilter,
          input_filter: inputFilter,
          invoice_filter: invoiceFilter,
          registration_filter: registrationFilter,
          search_text: searchText,
          search_category: searchCategory,
          sort_by: sortBy,
          format,
        })
      }
    } catch (e) {
      showAlert((e as Error)?.message || '엑셀 다운로드 실패', 'error')
    } finally {
      setExcelDownloading(false)
    }
  }

  return (
    <>
      {!isProductMode && (
        <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '10px', padding: '0.625rem 0.875rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', alignItems: 'center' }}>
            {PERIOD_BUTTONS.map(pb => (
              <button
                key={pb.key}
                onClick={() => {
                  if (dateLocked) return
                  setPeriod(pb.key)
                  if (!startLocked) {
                    const start = getPeriodStart(pb.key)
                    setCustomStart(start ? formatDateInput(start) : '')
                  }
                  setCustomEnd(formatDateInput(getPeriodEnd(pb.key)))
                }}
                style={{
                  padding: '0.22rem 0.55rem',
                  borderRadius: '5px',
                  fontSize: '0.75rem',
                  background: period === pb.key ? '#e3f4f0' : c.btnBg,
                  border: period === pb.key ? '1px solid #a9ddd2' : `1px solid ${c.btnBorder}`,
                  color: period === pb.key ? '#0f6a5b' : c.btnText,
                  cursor: dateLocked ? 'not-allowed' : 'pointer',
                  opacity: dateLocked && period !== pb.key ? 0.5 : 1,
                }}
              >
                {pb.label}
              </button>
            ))}
            <input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)} style={{ ...makeInputStyle(c), width: '160px', padding: '0.22rem 0.4rem', fontSize: '0.75rem', ...(startLocked ? { borderColor: c.danger, color: c.text } : {}) }} />
            <button onClick={() => setStartLocked(prev => !prev)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', background: startLocked ? c.danger : c.btnBg, border: startLocked ? `1px solid ${c.danger}` : `1px solid ${c.btnBorder}`, color: startLocked ? '#fff' : c.btnText }}>시작고정</button>
            <span style={{ color: c.textMuted, fontSize: '0.75rem' }}>~</span>
            <input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)} style={{ ...makeInputStyle(c), width: '160px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
            <button onClick={() => setDateLocked(prev => !prev)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', background: dateLocked ? c.danger : c.btnBg, border: dateLocked ? `1px solid ${c.danger}` : `1px solid ${c.btnBorder}`, color: dateLocked ? '#fff' : c.btnText }}>날짜고정</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap' }}>
            <select value={syncAccountId} onChange={e => setSyncAccountId(e.target.value)} style={{ ...makeInputStyle(c), width: '200px', padding: '0.22rem 0.4rem', fontSize: '0.72rem', minWidth: '200px' }}>
              <option value="">전체마켓보기</option>
              {(() => {
                // 크림을 최상단 고정(전체 다음) + 나머지는 MARKETS 정식 순서
                const marketRank = (t: string) => { if (t === 'kream') return -1; const i = MARKETS.findIndex(m => m.id === t); return i < 0 ? 999 : i }
                const marketTypes = [...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()]
                  .sort((a, b) => marketRank(a[0]) - marketRank(b[0]))
                return marketTypes.flatMap(([type, name]) => [
                  <option key={`type:${type}`} value={`type:${type}`}>{name}</option>,
                  ...accounts
                    .filter(a => a.market_type === type)
                    .map(a => {
                      const accountName = a.account_label?.trim() || a.seller_id?.trim() || a.business_name?.trim() || a.market_name
                      return <option key={a.id} value={a.id}>- {accountName}</option>
                    }),
                ])
              })()}
            </select>
            <button onClick={handleFetch} disabled={syncing} style={{ ...btn('secondary', c), ...(syncing ? btnDisabled : null), padding: '0.22rem 0.65rem', fontSize: '0.75rem', whiteSpace: 'nowrap' }}>{syncing ? '주문수집 중...' : '가져오기'}</button>
            <select value={bulkStatus} onChange={e => setBulkStatus(e.target.value)} style={{ ...makeInputStyle(c), width: '130px', padding: '0.22rem 0.4rem', fontSize: '0.72rem', minWidth: '130px' }}>
              <option value="">일괄 작업 선택</option>
              <option value="pending">주문접수</option>
              <option value="wait_ship">배송대기중</option>
              <option value="ship_failed">송장전송실패</option>
              <option value="shipping">국내배송중</option>
              <option value="delivered">배송완료</option>
              <option value="cancelling">취소중</option>
              <option value="returning">반품중</option>
              <option value="exchanging">교환중</option>
              <option value="cancel_requested">취소요청</option>
              <option value="return_requested">반품요청</option>
              <option value="cancelled">취소완료</option>
              <option value="returned">반품완료</option>
              <option value="exchanged">교환완료</option>
            </select>
            <button onClick={handleBulkAction} disabled={bulkUpdating || !bulkStatus || selectedIdsSize === 0} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: selectedIdsSize > 0 && bulkStatus ? c.danger : c.btnBg, border: `1px solid ${c.btnBorder}`, color: selectedIdsSize > 0 && bulkStatus ? '#fff' : c.textMuted, borderRadius: '4px', cursor: bulkUpdating || !bulkStatus || selectedIdsSize === 0 ? 'not-allowed' : 'pointer' }}>{bulkUpdating ? '처리 중...' : `일괄 실행 (${fmtNum(selectedIdsSize)})`}</button>
          </div>
        </div>
      )}

      <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.72rem', color: c.textSub }}>
          <span style={{ color: c.text, fontWeight: 600 }}>{fmtNum(filteredOrdersCount)}</span>건 /
          <span style={{ color: c.text, fontWeight: 600 }}> {fmtNum(filteredOrdersTotalSale)}원</span>
          {/* 소싱처 자동취소 관련 건수 — 현재 조회된 목록 기준, 0건이면 미표시 */}
          {autoCancelCount > 0 && (
            <span style={{ color: c.warn, fontWeight: 600 }}> · 자동취소 {fmtNum(autoCancelCount)}</span>
          )}
        </span>
        <select disabled={multiSearchMode} title={multiSearchMode ? '다중 모드는 주문번호 카테고리 고정' : undefined} style={{ ...makeInputStyle(c), width: '90px', padding: '0.22rem 0.4rem', fontSize: '0.75rem', ...(multiSearchMode ? { opacity: 0.6, cursor: 'not-allowed' } : {}) }} value={searchCategory} onChange={e => setSearchCategory(e.target.value)}>
          <option value="product">상품명</option>
          <option value="customer">고객명</option>
          <option value="product_id">상품ID</option>
          <option value="order_number">주문번호</option>
          <option value="sourcing_order_number">소싱주문번호</option>
          <option value="tracking_number">송장번호</option>
        </select>
        {multiSearchMode ? (
          // 같은 자리에서 input↔textarea 스왑 — 다중 모드만 200px(주문번호 13자리 확인용), 세로 rows=4
          <textarea
            rows={4}
            style={{ ...makeInputStyle(c), width: '200px', padding: '0.22rem 0.4rem', fontSize: '0.75rem', lineHeight: 1.35, resize: 'vertical', verticalAlign: 'middle' }}
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleSearch() }}
            placeholder={'주문번호 여러 건 붙여넣기\n(줄바꿈·쉼표로 구분, 최대 200건)'}
            title={'Enter=줄바꿈 · Ctrl/Cmd+Enter=조회'}
          />
        ) : (
          <input style={{ ...makeInputStyle(c), width: '86px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={searchText} onChange={e => setSearchText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') handleSearch() }} />
        )}
        <button
          onClick={toggleMultiSearch}
          title="여러 주문번호를 한 번에 조회 (줄바꿈·쉼표·공백 구분)"
          style={{ ...btn(multiSearchMode ? 'accent' : 'secondary', c), padding: '0.22rem 0.5rem', fontSize: '0.72rem' }}
        >
          다중
        </button>
        <button
          onClick={applyOrderNumberSearchPreset}
          title="주문번호 검색용 필터로 한번에 설정 (올해 + 전체 주문상태)"
          style={{ ...btn('secondary', c), padding: '0.22rem 0.5rem', fontSize: '0.72rem' }}
        >
          바로가기
        </button>
        <button onClick={handleSearch} style={{ ...btn('primary', c), padding: '0.22rem 0.75rem', fontSize: '0.75rem' }}>검색</button>
        {/* [최저가탐색] 버튼을 눌러야만 스캔 (자동 실행 금지 — 소싱처 부하) */}
        <button
          onClick={onPriceScoutBatch}
          disabled={priceScanning}
          title="현재 화면의 주문접수 + 소싱주문번호 없는 주문만 소싱처 5곳 최저가 스캔 (최대 50건)"
          style={{ ...btn('accent', c), ...(priceScanning ? btnDisabled : null), padding: '0.22rem 0.65rem', fontSize: '0.75rem', whiteSpace: 'nowrap' }}
        >{priceScanning ? '최저가 스캔 중...' : '최저가 스캔'}</button>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', flexWrap: 'wrap' }}>
          <select style={{ ...makeInputStyle(c), width: '140px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={marketFilter} onChange={e => setMarketFilter(e.target.value)}>
            <option value="">전체 마켓</option>
            {(() => {
              // 크림을 최상단 고정(전체 다음) + 나머지는 MARKETS 정식 순서
              const marketRank = (t: string) => { if (t === 'kream') return -1; const i = MARKETS.findIndex(m => m.id === t); return i < 0 ? 999 : i }
              const marketTypes = [...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()]
                .sort((a, b) => marketRank(a[0]) - marketRank(b[0]))
              return marketTypes.flatMap(([type, name]) => [
                <option key={`type:${type}`} value={`type:${type}`}>{name}</option>,
                ...accounts
                  .filter(a => a.market_type === type)
                  .map(a => {
                    const accountName = a.account_label?.trim() || a.seller_id?.trim() || a.business_name?.trim() || a.market_name
                    return <option key={`acc:${a.id}`} value={`acc:${a.id}`}>- {accountName}</option>
                  }),
              ])
            })()}
          </select>
          <select style={{ ...makeInputStyle(c), width: '97px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={siteFilter} onChange={e => setSiteFilter(e.target.value)}>
            <option value="">전체 소싱처</option>
            {siteOptions.map(site => <option key={site.value} value={site.value}>{site.label}</option>)}
          </select>
          <select style={{ ...makeInputStyle(c), width: '112px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={accountFilter} onChange={e => setAccountFilter(e.target.value)}>
            <option value="">소싱계정</option>
            <option value="etc">기타(미매핑)</option>
            {[...new Set(sourcingAccounts.map(sa => sa.site_name))].sort().map(site => (
              <optgroup key={site} label={site}>
                {sourcingAccounts.filter(sa => sa.site_name === site).map(sa => (
                  <option key={sa.id} value={sa.id}>{sa.account_label ? `${sa.account_label}(${sa.username})` : sa.username}</option>
                ))}
              </optgroup>
            ))}
          </select>
          <select style={{ ...makeInputStyle(c), width: '77px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={marketStatus} onChange={e => setMarketStatus(e.target.value)}>
            <option value="">배송상태</option>
            <option value="결제완료">주문접수</option>
            <option value="배송대기중">배송대기중</option>
            <option value="국내배송중">국내배송중</option>
            <option value="배송완료">배송완료</option>
            <option value="취소요청">취소요청</option>
            <option value="취소완료">취소완료</option>
            <option value="반품요청">반품요청</option>
            <option value="교환요청">교환요청</option>
            <option value="교환완료">교환완료</option>
          </select>
          <select style={{ ...makeInputStyle(c), width: '77px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={registrationFilter} onChange={e => setRegistrationFilter(e.target.value)}>
            <option value="">등록필터</option>
            <option value="registered">등록상품</option>
            <option value="unregistered">미등록상품</option>
          </select>
          <select style={{ ...makeInputStyle(c), width: '84px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={inputFilter} onChange={e => setInputFilter(e.target.value)}>
            <option value="">입력필터</option>
            <option value="has_order">주문번호O</option>
            <option value="no_order">주문번호X</option>
            <option value="direct">직배</option>
            <option value="kkadaegi">까대기</option>
            <option value="gift">선물</option>
            <option value="no_price">가격X</option>
            <option value="no_stock">재고X</option>
            <option value="staff_a">직원A</option>
            <option value="staff_b">직원B</option>
            <option value="auto_cancel_ok">자동취소됨</option>
            <option value="auto_cancel_fail">자동취소실패</option>
            <option value="auto_cancel_any">자동취소(전체)</option>
          </select>
          <select style={{ ...makeInputStyle(c), width: '108px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={invoiceFilter} onChange={e => setInvoiceFilter(e.target.value)}>
            <option value="">송장필터</option>
            <option value="has_invoice">송장입력</option>
            <option value="no_invoice">송장미입력</option>
          </select>
          {/* 주문상태 필터 — 테이블 드롭다운과 같은 STATUS_SELECT_COLORS 로 통일.
              특수 옵션(전체/제외)은 기본색 유지, 상태 선택 시엔 닫힌 상태에서도 상태색 표시 */}
          <select
            style={{
              ...makeInputStyle(c), width: '140px', padding: '0.22rem 0.4rem', fontSize: '0.75rem',
              ...(STATUS_SELECT_COLORS[statusFilter]
                ? { background: STATUS_SELECT_COLORS[statusFilter].bg, color: STATUS_SELECT_COLORS[statusFilter].fg, border: '1px solid rgba(0,0,0,0.35)', fontWeight: 600 }
                : {}),
            }}
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
          >
            <option value="">전체 주문상태</option>
            <option value="cancel_return_excluded">취소/반품/교환/배송 제외</option>
            {Object.entries(STATUS_MAP)
              .filter(([k]) => !['preparing', 'cancel_reject_pending', 'return_completed', 'undeliverable'].includes(k))
              .map(([k, v]) => (
                <option
                  key={k}
                  value={k}
                  style={{ backgroundColor: STATUS_SELECT_COLORS[k]?.bg, color: STATUS_SELECT_COLORS[k]?.fg, fontWeight: k === statusFilter ? 700 : 400 }}
                >{v.label}</option>
              ))}
          </select>
          <select value={sortBy} onChange={e => setSortBy(e.target.value)} style={{ ...makeInputStyle(c), width: '63px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }}>
            <option value="date_desc">최신순</option>
            <option value="date_asc">오래된순</option>
            <option value="profit_desc">마진높음</option>
            <option value="profit_asc">마진낮음</option>
            <option value="price_desc">매출높음</option>
            <option value="price_asc">매출낮음</option>
          </select>
          <select style={{ ...makeInputStyle(c), width: '66px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
            <option value={20}>20개</option>
            <option value={50}>50개</option>
            <option value={100}>100개</option>
            <option value={200}>200개</option>
            <option value={500}>500개</option>
          </select>
          <div style={{ position: 'relative', display: 'inline-block' }}>
            <button
              onClick={() => setExcelMenuOpen(prev => !prev)}
              disabled={excelDownloading}
              style={{
                padding: '0.22rem 0.65rem',
                fontSize: '0.75rem',
                background: selectedOrderIds.length > 0 ? c.success : c.btnBg,
                border: `1px solid ${c.btnBorder}`,
                color: selectedOrderIds.length > 0 ? '#fff' : c.btnText,
                borderRadius: '4px',
                cursor: excelDownloading ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap',
              }}
              title={selectedOrderIds.length > 0 ? `선택 ${fmtNum(selectedOrderIds.length)}건 — 양식 선택 후 다운로드` : '현재 필터 전체 — 양식 선택 후 다운로드'}
            >
              {excelDownloading
                ? '다운로드 중...'
                : selectedOrderIds.length > 0
                  ? `엑셀 다운(${fmtNum(selectedOrderIds.length)}) ▾`
                  : '엑셀 다운 ▾'}
            </button>
            {excelMenuOpen && !excelDownloading && (
              <>
                {/* 외부 클릭 감지용 투명 오버레이 */}
                <div
                  onClick={() => setExcelMenuOpen(false)}
                  style={{
                    position: 'fixed',
                    inset: 0,
                    zIndex: 20,
                    background: 'transparent',
                  }}
                />
                <div
                  style={{
                    position: 'absolute',
                    top: 'calc(100% + 4px)',
                    right: 0,
                    minWidth: '200px',
                    background: c.surface,
                    border: `1px solid ${c.border}`,
                    borderRadius: '6px',
                    boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
                    zIndex: 30,
                    overflow: 'hidden',
                  }}
                >
                  <button
                    onClick={() => {
                      setExcelMenuOpen(false)
                      handleExcelDownload('ub1')
                    }}
                    style={{
                      display: 'block',
                      width: '100%',
                      padding: '0.5rem 0.75rem',
                      fontSize: '0.78rem',
                      textAlign: 'left',
                      background: 'transparent',
                      border: 'none',
                      borderBottom: `1px solid ${c.border}`,
                      color: c.text,
                      cursor: 'pointer',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = c.surfaceAlt }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                  >
                    <div style={{ fontWeight: 600 }}>기본 양식 (UB1 발주)</div>
                    <div style={{ fontSize: '0.68rem', color: c.textMuted, marginTop: '2px' }}>
                      마켓·마켓주문번호·구매가격 등 10컬럼
                    </div>
                  </button>
                  <button
                    onClick={() => {
                      setExcelMenuOpen(false)
                      handleExcelDownload('lotte')
                    }}
                    style={{
                      display: 'block',
                      width: '100%',
                      padding: '0.5rem 0.75rem',
                      fontSize: '0.78rem',
                      textAlign: 'left',
                      background: 'transparent',
                      border: 'none',
                      borderBottom: `1px solid ${c.border}`,
                      color: c.text,
                      cursor: 'pointer',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = c.surfaceAlt }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                  >
                    <div style={{ fontWeight: 600 }}>롯데택배 송장 양식</div>
                    <div style={{ fontSize: '0.68rem', color: c.textMuted, marginTop: '2px' }}>
                      수령자·연락처·주소·상품명·수량·배송메세지 7컬럼
                    </div>
                  </button>
                  <button
                    onClick={() => {
                      setExcelMenuOpen(false)
                      handleExcelDownload('cj')
                    }}
                    style={{
                      display: 'block',
                      width: '100%',
                      padding: '0.5rem 0.75rem',
                      fontSize: '0.78rem',
                      textAlign: 'left',
                      background: 'transparent',
                      border: 'none',
                      color: c.text,
                      cursor: 'pointer',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = c.surfaceAlt }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                  >
                    <div style={{ fontWeight: 600 }}>CJ대한통운 송장 양식</div>
                    <div style={{ fontSize: '0.68rem', color: c.textMuted, marginTop: '2px' }}>
                      수령인·주소·전화번호·상품명 4컬럼
                    </div>
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
