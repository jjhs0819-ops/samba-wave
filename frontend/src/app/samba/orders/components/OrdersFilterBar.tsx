'use client'

import React, { Dispatch, SetStateAction } from 'react'
import { type SambaMarketAccount } from '@/lib/samba/api/commerce'
import { type SambaSourcingAccount } from '@/lib/samba/api/operations'
import { PERIOD_BUTTONS } from '@/lib/samba/constants'
import { inputStyle, fmtNum } from '@/lib/samba/styles'
import { getPeriodStart, getPeriodEnd } from '@/lib/samba/utils'
import { STATUS_MAP } from '../constants'

const MARKET_STATUS_OPTIONS = [
  '諛쒖＜誘명솗??, '諛쒖넚?湲?, '寃곗젣?꾨즺', '二쇰Ц?묒닔', '諛곗넚?湲곗쨷',
  '諛곗넚以?, '諛곗넚?꾨즺', '援щℓ?뺤젙', '?≪옣異쒕젰', '?≪옣?낅젰', '異쒓퀬', '?뺤궛?꾨즺',
  '痍⑥냼?붿껌', '痍⑥냼泥섎━以?, '痍⑥냼?꾨즺', '痍⑥냼嫄곕?', '痍⑥냼以?,
  '諛섑뭹?붿껌', '?섍굅以?, '?섍굅?꾨즺', '諛섑뭹?꾨즺', '諛섑뭹嫄곕?',
  '援먰솚?붿껌', '援먰솚泥섎━以?, '援먰솚?꾨즺', '援먰솚嫄곕?',
  '蹂대쪟', '?≪옣?꾩넚?꾨즺',
]

interface Props {
  isProductMode: boolean
  // 湲곌컙 ?꾪꽣
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
  // 媛?몄삤湲?/ ?쇨큵
  syncAccountId: string
  setSyncAccountId: Dispatch<SetStateAction<string>>
  syncing: boolean
  handleFetch: () => void | Promise<void>
  backgroundMode: boolean
  setBackgroundMode: Dispatch<SetStateAction<boolean>>
  bulkStatus: string
  setBulkStatus: Dispatch<SetStateAction<string>>
  bulkUpdating: boolean
  handleBulkAction: () => void | Promise<void>
  selectedIdsSize: number
  // 硫붿씤 ?꾪꽣
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
  // ?곗씠??  accounts: SambaMarketAccount[]
  sourcingAccounts: SambaSourcingAccount[]
}

export default function OrdersFilterBar(props: Props) {
  const {
    isProductMode,
    period, setPeriod, customStart, setCustomStart, customEnd, setCustomEnd,
    startLocked, setStartLocked, dateLocked, setDateLocked,
    syncAccountId, setSyncAccountId, syncing, handleFetch,
    backgroundMode, setBackgroundMode,
    bulkStatus, setBulkStatus, bulkUpdating, handleBulkAction, selectedIdsSize,
    filteredOrdersCount, filteredOrdersTotalSale,
    searchCategory, setSearchCategory, searchText, setSearchText, loadOrders,
    marketFilter, setMarketFilter, siteFilter, setSiteFilter,
    accountFilter, setAccountFilter, marketStatus, setMarketStatus,
    inputFilter, setInputFilter, statusFilter, setStatusFilter,
    sortBy, setSortBy, pageSize, setPageSize,
    accounts, sourcingAccounts,
  } = props

  return (
    <>
      {/* 湲곌컙 ?꾪꽣 諛????곹뭹蹂?紐⑤뱶?먯꽌???④? */}
      {!isProductMode && <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.625rem 0.875rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'nowrap', alignItems: 'center' }}>
          {PERIOD_BUTTONS.map(pb => (
            <button key={pb.key} onClick={() => {
              if (dateLocked) return
              setPeriod(pb.key)
              if (!startLocked) {
                const start = getPeriodStart(pb.key)
                setCustomStart(start ? start.toLocaleDateString('sv-SE') : '')
              }
              setCustomEnd(getPeriodEnd(pb.key).toLocaleDateString('sv-SE'))
            }}
              style={{ padding: '0.22rem 0.55rem', borderRadius: '5px', fontSize: '0.75rem', background: period === pb.key ? 'rgba(80,80,80,0.8)' : 'rgba(50,50,50,0.8)', border: period === pb.key ? '1px solid #666' : '1px solid #3D3D3D', color: period === pb.key ? '#fff' : '#C5C5C5', cursor: dateLocked ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap', opacity: dateLocked && period !== pb.key ? 0.5 : 1 }}
            >{pb.label}</button>
          ))}
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 4px' }} />
          <input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)}
            style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem', ...(startLocked ? { borderColor: '#C0392B', color: '#FF8C00' } : {}) }} />
          <button
            onClick={() => setStartLocked(prev => !prev)}
            style={{
              padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap',
              background: startLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)',
              border: startLocked ? '1px solid #C0392B' : '1px solid #3D3D3D',
              color: startLocked ? '#fff' : '#C5C5C5',
            }}
          >怨좎젙</button>
          <span style={{ color: '#555', fontSize: '0.75rem' }}>~</span>
          <input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)}
            style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
          <button
            onClick={() => setDateLocked(prev => !prev)}
            style={{
              padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap',
              background: dateLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)',
              border: dateLocked ? '1px solid #C0392B' : '1px solid #3D3D3D',
              color: dateLocked ? '#fff' : '#C5C5C5',
            }}
          >怨좎젙</button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
          <select value={syncAccountId} onChange={e => setSyncAccountId(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.72rem', minWidth: '200px' }}>
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
          <button onClick={handleFetch} disabled={syncing} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: 'rgba(50,50,50,0.9)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: syncing ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>{syncing ? '二쇰Ц?섏쭛 以?..' : '媛?몄삤湲?}</button>
          {/* 諛깃렇?쇱슫??紐⑤뱶 ?좉? ???꾩껜留덉폆 ?좏깮 ?쒖뿉留??쒖꽦??(媛쒕퀎/留덉폆??낆? 吏㏃븘??遺덊븘?? */}
          <label
            title="諛깃렇?쇱슫???≪쑝濡??ㅽ뻾 ???섏씠吏 ?댄깉?대룄 怨꾩냽 吏꾪뻾. ?꾩껜留덉폆 ?좏깮 ?쒖뿉留??곸슜."
            style={{ display: 'flex', alignItems: 'center', gap: '3px', fontSize: '0.7rem', color: syncAccountId ? '#555' : '#888', cursor: syncAccountId ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}
          >
            <input
              type="checkbox"
              checked={backgroundMode}
              disabled={syncing || !!syncAccountId}
              onChange={e => setBackgroundMode(e.target.checked)}
              style={{ cursor: syncing || syncAccountId ? 'not-allowed' : 'pointer' }}
            />
            諛깃렇?쇱슫??          </label>
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 2px' }} />
          <select value={bulkStatus} onChange={e => setBulkStatus(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.72rem', minWidth: '110px' }}>
            <option value="">?쇨큵 ?묒뾽 ?좏깮</option>
            <optgroup label="?곹깭 蹂寃?>
              <option value="pending">??二쇰Ц?묒닔</option>
              <option value="wait_ship">??諛곗넚?湲?/option>
              <option value="arrived">???щТ?ㅻ룄李?/option>
              <option value="shipped">??異쒓퀬?꾨즺</option>
              <option value="delivered">??諛곗넚?꾨즺</option>
              <option value="cancelled">??痍⑥냼?꾨즺</option>
            </optgroup>
            <optgroup label="二쇰Ц 泥섎━">
              <option value="confirm">諛쒖＜?뺤씤</option>
              <option value="approve_cancel">痍⑥냼?뱀씤</option>
              <option value="delete">??젣 ?좑툘</option>
            </optgroup>
          </select>
          <button onClick={handleBulkAction} disabled={bulkUpdating || !bulkStatus || selectedIdsSize === 0} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: selectedIdsSize > 0 && bulkStatus ? (bulkStatus === 'delete' ? '#7B2D00' : '#C0392B') : 'rgba(50,50,50,0.9)', border: `1px solid ${selectedIdsSize > 0 && bulkStatus === 'delete' ? '#A83200' : '#3D3D3D'}`, color: selectedIdsSize > 0 && bulkStatus ? '#fff' : '#666', borderRadius: '4px', cursor: bulkUpdating || !bulkStatus || selectedIdsSize === 0 ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}>{bulkUpdating ? '泥섎━ 以?..' : `?ㅽ뻾 (${fmtNum(selectedIdsSize)}嫄?`}</button>
        </div>
      </div>}

      {/* ?꾪꽣 諛?*/}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
        <span style={{ fontSize: '0.72rem', color: '#aaa', whiteSpace: 'nowrap', marginRight: '4px' }}>
          <span style={{ color: '#FF8C00', fontWeight: 600 }}>{fmtNum(filteredOrdersCount)}</span>嫄?/ ??span style={{ color: '#FF8C00', fontWeight: 600 }}>{fmtNum(filteredOrdersTotalSale)}</span>
        </span>
        <select style={{ ...inputStyle, width: '80px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={searchCategory} onChange={e => setSearchCategory(e.target.value)}>
          <option value="product">?곹뭹</option>
          <option value="customer">怨좉컼</option>
          <option value="product_id">?곹뭹踰덊샇</option>
          <option value="order_number">二쇰Ц踰덊샇</option>
        </select>
        <input style={{ ...inputStyle, width: '140px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={searchText} onChange={e => setSearchText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') loadOrders() }} />
        <button onClick={loadOrders} style={{ background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', padding: '0.22rem 0.75rem', borderRadius: '5px', fontSize: '0.75rem', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}>寃??/button>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', flexShrink: 0, alignItems: 'center' }}>
          <select style={{ ...inputStyle, width: '130px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={marketFilter} onChange={e => setMarketFilter(e.target.value)}>
            <option value="">?꾩껜留덉폆蹂닿린</option>
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
          <select style={{ ...inputStyle, width: '110px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={siteFilter} onChange={e => setSiteFilter(e.target.value)}><option value="">?꾩껜?ъ씠?몃낫湲?/option>{['MUSINSA','KREAM','FashionPlus','Nike','Adidas','ABCmart','REXMONDE','SSG','LOTTEON','GSShop','ElandMall','SSF'].map(s => <option key={s} value={s}>{s}</option>)}</select>
          <select style={{ ...inputStyle, width: '130px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={accountFilter} onChange={e => setAccountFilter(e.target.value)}>
            <option value="">二쇰Ц怨꾩젙</option>
            {(() => {
              const allSites = [...new Set(sourcingAccounts.map(sa => sa.site_name))]
              return allSites.sort().map(site => (
                <optgroup key={site} label={site}>
                  {sourcingAccounts.filter(sa => sa.site_name === site).map(sa => (
                    <option key={sa.id} value={sa.id}>{sa.account_label ? `${sa.account_label}(${sa.username})` : sa.username}</option>
                  ))}
                </optgroup>
              ))
            })()}
          </select>
          <select style={{ ...inputStyle, width: '112px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={marketStatus} onChange={e => setMarketStatus(e.target.value)}>
            <option value="">留덉폆?곹깭 蹂닿린</option>
            {MARKET_STATUS_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
          <select style={{ ...inputStyle, width: '118px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={inputFilter} onChange={e => setInputFilter(e.target.value)}>
            <option value="">?낅젰媛?/option>
            <option value="has_order">二쇰Ц踰덊샇?낅젰</option>
            <option value="no_order">二쇰Ц踰덊샇 誘몄엯??/option>
            <option value="direct">吏곷같</option>
            <option value="kkadaegi">源뚮?湲?/option>
            <option value="gift">?좊Ъ</option>
          </select>
          <select style={{ ...inputStyle, width: '130px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="active">?묒닔/?湲??щТ??/option>
            <option value="">?꾩껜 二쇰Ц?곹깭</option>
            {Object.entries(STATUS_MAP).map(([k, v]) => <option key={k} value={k} style={k === 'ship_failed' ? { color: '#FF3232' } : {}}>{v.label}</option>)}
          </select>
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 2px' }} />
          <select value={sortBy} onChange={e => setSortBy(e.target.value)} style={{ ...inputStyle, width: '92px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }}>
            <option value="date_desc">二쇰Ц?쇱옄??/option>
            <option value="date_asc">二쇰Ц?쇱옄??/option>
            <option value="profit_desc">?섏씡??/option>
            <option value="profit_asc">?섏씡??/option>
            <option value="price_desc">?먮ℓ媛??/option>
            <option value="price_asc">?먮ℓ媛??/option>
          </select>
          <select style={{ ...inputStyle, width: '92px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
            <option value={20}>20媛?蹂닿린</option><option value={50}>50媛?蹂닿린</option><option value={100}>100媛?蹂닿린</option><option value={200}>200媛?蹂닿린</option><option value={500}>500媛?蹂닿린</option>
          </select>
        </div>
      </div>
    </>
  )
}
