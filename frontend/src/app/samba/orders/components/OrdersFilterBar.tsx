'use client'

import React, { Dispatch, SetStateAction } from 'react'
import { type SambaMarketAccount } from '@/lib/samba/api/commerce'
import { type SambaSourcingAccount } from '@/lib/samba/api/operations'
import { PERIOD_BUTTONS } from '@/lib/samba/constants'
import { inputStyle, fmtNum } from '@/lib/samba/styles'
import { getPeriodStart, getPeriodEnd } from '@/lib/samba/utils'
import { STATUS_MAP } from '../constants'

const MARKET_STATUS_OPTIONS = [
  '주문접수',
  '배송대기중',
  '상품준비',
  '출고지연',
  '배송중',
  '배송완료',
  '취소요청',
  '취소완료',
  '반품요청',
  '반품완료',
  '교환요청',
  '교환완료',
]

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
  inputFilter: string
  setInputFilter: Dispatch<SetStateAction<string>>
  statusFilter: string
  setStatusFilter: Dispatch<SetStateAction<string>>
  sortBy: string
  setSortBy: Dispatch<SetStateAction<string>>
  pageSize: number
  setPageSize: Dispatch<SetStateAction<number>>
  accounts: SambaMarketAccount[]
  sourcingAccounts: SambaSourcingAccount[]
  siteOptions: Array<{ value: string; label: string }>
}

export default function OrdersFilterBar(props: Props) {
  const {
    isProductMode,
    period, setPeriod, customStart, setCustomStart, customEnd, setCustomEnd,
    startLocked, setStartLocked, dateLocked, setDateLocked,
    syncAccountId, setSyncAccountId, syncing, handleFetch,
    bulkStatus, setBulkStatus, bulkUpdating, handleBulkAction, selectedIdsSize,
    filteredOrdersCount, filteredOrdersTotalSale,
    searchCategory, setSearchCategory, searchText, setSearchText, loadOrders,
    marketFilter, setMarketFilter, siteFilter, setSiteFilter,
    accountFilter, setAccountFilter, marketStatus, setMarketStatus,
    inputFilter, setInputFilter, statusFilter, setStatusFilter,
    sortBy, setSortBy, pageSize, setPageSize,
    accounts, sourcingAccounts, siteOptions,
  } = props

  return (
    <>
      {!isProductMode && (
        <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.625rem 0.875rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', alignItems: 'center' }}>
            {PERIOD_BUTTONS.map(pb => (
              <button
                key={pb.key}
                onClick={() => {
                  if (dateLocked) return
                  setPeriod(pb.key)
                  if (!startLocked) {
                    const start = getPeriodStart(pb.key)
                    setCustomStart(start ? start.toLocaleDateString('sv-SE') : '')
                  }
                  setCustomEnd(getPeriodEnd(pb.key).toLocaleDateString('sv-SE'))
                }}
                style={{
                  padding: '0.22rem 0.55rem',
                  borderRadius: '5px',
                  fontSize: '0.75rem',
                  background: period === pb.key ? 'rgba(80,80,80,0.8)' : 'rgba(50,50,50,0.8)',
                  border: period === pb.key ? '1px solid #666' : '1px solid #3D3D3D',
                  color: period === pb.key ? '#fff' : '#C5C5C5',
                  cursor: dateLocked ? 'not-allowed' : 'pointer',
                  opacity: dateLocked && period !== pb.key ? 0.5 : 1,
                }}
              >
                {pb.label}
              </button>
            ))}
            <input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)} style={{ ...inputStyle, width: '160px', padding: '0.22rem 0.4rem', fontSize: '0.75rem', ...(startLocked ? { borderColor: '#C0392B', color: '#FF8C00' } : {}) }} />
            <button onClick={() => setStartLocked(prev => !prev)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', background: startLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: startLocked ? '1px solid #C0392B' : '1px solid #3D3D3D', color: startLocked ? '#fff' : '#C5C5C5' }}>?쒖옉怨좎젙</button>
            <span style={{ color: '#555', fontSize: '0.75rem' }}>~</span>
            <input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)} style={{ ...inputStyle, width: '160px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
            <button onClick={() => setDateLocked(prev => !prev)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', background: dateLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: dateLocked ? '1px solid #C0392B' : '1px solid #3D3D3D', color: dateLocked ? '#fff' : '#C5C5C5' }}>?좎쭨怨좎젙</button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap' }}>
            <select value={syncAccountId} onChange={e => setSyncAccountId(e.target.value)} style={{ ...inputStyle, width: '200px', padding: '0.22rem 0.4rem', fontSize: '0.72rem', minWidth: '200px' }}>
              <option value="">?꾩껜留덉폆蹂닿린</option>
              {(() => {
                const marketTypes = [...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()]
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
            <button onClick={handleFetch} disabled={syncing} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: 'rgba(50,50,50,0.9)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: syncing ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>{syncing ? '주문수집 중...' : '가져오기'}</button>
            <select value={bulkStatus} onChange={e => setBulkStatus(e.target.value)} style={{ ...inputStyle, width: '130px', padding: '0.22rem 0.4rem', fontSize: '0.72rem', minWidth: '130px' }}>
              <option value="">?쇨큵 ?묒뾽 ?좏깮</option>
              <option value="pending">?곹깭: ?湲?</option>
              <option value="wait_ship">?곹깭: 諛곗넚?湲?</option>
              <option value="arrived">?곹깭: ?낃퀬</option>
              <option value="shipped">?곹깭: 諛쒖넚?꾨즺</option>
              <option value="delivered">?곹깭: 諛곗넚?꾨즺</option>
              <option value="cancelled">?곹깭: 痍⑥냼?꾨즺</option>
              <option value="confirm">二쇰Ц?뺤씤</option>
              <option value="approve_cancel">痍⑥냼?뺤씤</option>
              <option value="delete">??젣</option>
            </select>
            <button onClick={handleBulkAction} disabled={bulkUpdating || !bulkStatus || selectedIdsSize === 0} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: selectedIdsSize > 0 && bulkStatus ? '#C0392B' : 'rgba(50,50,50,0.9)', border: '1px solid #3D3D3D', color: selectedIdsSize > 0 && bulkStatus ? '#fff' : '#666', borderRadius: '4px', cursor: bulkUpdating || !bulkStatus || selectedIdsSize === 0 ? 'not-allowed' : 'pointer' }}>{bulkUpdating ? '泥섎━ 以?..' : `?쇨큵 ?ㅽ뻾 (${fmtNum(selectedIdsSize)})`}</button>
          </div>
        </div>
      )}

      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.72rem', color: '#aaa' }}>
          <span style={{ color: '#FF8C00', fontWeight: 600 }}>{fmtNum(filteredOrdersCount)}</span>嫄?/
          <span style={{ color: '#FF8C00', fontWeight: 600 }}> {fmtNum(filteredOrdersTotalSale)}</span>
        </span>
        <select style={{ ...inputStyle, width: '90px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={searchCategory} onChange={e => setSearchCategory(e.target.value)}>
          <option value="product">?곹뭹紐?</option>
          <option value="customer">怨좉컼紐?</option>
          <option value="product_id">?곹뭹ID</option>
          <option value="order_number">二쇰Ц踰덊샇</option>
        </select>
        <input style={{ ...inputStyle, width: '160px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={searchText} onChange={e => setSearchText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') loadOrders() }} />
        <button onClick={loadOrders} style={{ background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', padding: '0.22rem 0.75rem', borderRadius: '5px', fontSize: '0.75rem', border: 'none', cursor: 'pointer' }}>검색</button>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', flexWrap: 'wrap' }}>
          <select style={{ ...inputStyle, width: '140px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={marketFilter} onChange={e => setMarketFilter(e.target.value)}>
            <option value="">?꾩껜 留덉폆</option>
            {(() => {
              const marketTypes = [...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()]
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
          <select style={{ ...inputStyle, width: '120px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={siteFilter} onChange={e => setSiteFilter(e.target.value)}>
            <option value="">?꾩껜 ?뚯떛泥?</option>
            {siteOptions.map(site => <option key={site.value} value={site.value}>{site.label}</option>)}
          </select>
          <select style={{ ...inputStyle, width: '140px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={accountFilter} onChange={e => setAccountFilter(e.target.value)}>
            <option value="">?꾩껜 ?뚯떛怨꾩젙</option>
            {[...new Set(sourcingAccounts.map(sa => sa.site_name))].sort().map(site => (
              <optgroup key={site} label={site}>
                {sourcingAccounts.filter(sa => sa.site_name === site).map(sa => (
                  <option key={sa.id} value={sa.id}>{sa.account_label ? `${sa.account_label}(${sa.username})` : sa.username}</option>
                ))}
              </optgroup>
            ))}
          </select>
          <select style={{ ...inputStyle, width: '120px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={marketStatus} onChange={e => setMarketStatus(e.target.value)}>
            <option value="">諛곗넚?곹깭</option>
            {MARKET_STATUS_OPTIONS.map(status => <option key={status} value={status}>{status}</option>)}
          </select>
          <select style={{ ...inputStyle, width: '120px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={inputFilter} onChange={e => setInputFilter(e.target.value)}>
            <option value="no_price">가격X</option>
            <option value="no_stock">재고X</option>
            <option value="">?낅젰?꾪꽣</option>
            <option value="has_order">?뚯떛二쇰Ц踰덊샇 ?덉쓬</option>
            <option value="no_order">?뚯떛二쇰Ц踰덊샇 ?놁쓬</option>
            <option value="has_invoice">?≪옣?낅젰</option>
            <option value="no_invoice">?≪옣誘몄엯??</option>
            <option value="registered">?깅줉?곹뭹</option>
            <option value="unregistered">誘몃벑濡앹긽??</option>
            <option value="direct">吏곷같</option>
            <option value="kkadaegi">源뚮?湲?</option>
            <option value="gift">?좊Ъ</option>
            <option value="staff_a">吏곸썝A</option>
            <option value="staff_b">吏곸썝B</option>
          </select>
          <select style={{ ...inputStyle, width: '140px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">?꾩껜 二쇰Ц?곹깭</option>
            <option value="cancel_return_excluded">痍⑥냼/諛섑뭹/援먰솚 ?쒖쇅</option>
            {Object.entries(STATUS_MAP).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          <select value={sortBy} onChange={e => setSortBy(e.target.value)} style={{ ...inputStyle, width: '100px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }}>
            <option value="date_desc">理쒖떊??</option>
            <option value="date_asc">?ㅻ옒?쒖닚</option>
            <option value="profit_desc">?댁씡?믪쓬</option>
            <option value="profit_asc">?댁씡??쓬</option>
            <option value="price_desc">留ㅼ텧?믪쓬</option>
            <option value="price_asc">留ㅼ텧??쓬</option>
          </select>
          <select style={{ ...inputStyle, width: '92px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
            <option value={20}>20媛?</option>
            <option value={50}>50媛?</option>
            <option value={100}>100媛?</option>
            <option value={200}>200媛?</option>
            <option value={500}>500媛?</option>
          </select>
        </div>
      </div>
    </>
  )
}



