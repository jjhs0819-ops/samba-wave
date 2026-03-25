'use client'

import { useEffect, useState, useCallback } from 'react'
import { csInquiryApi, type SambaCSInquiry, type CSReplyTemplate } from '@/lib/samba/api'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { card, inputStyle } from '@/lib/samba/styles'

// 답변 상태 맵
const REPLY_STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  pending: { label: '미답변', bg: 'rgba(255,211,61,0.15)', text: '#FFD93D' },
  replied: { label: '답변완료', bg: 'rgba(81,207,102,0.15)', text: '#51CF66' },
}

// 문의 유형 맵
const INQUIRY_TYPE_MAP: Record<string, { label: string; color: string }> = {
  general: { label: '일반문의', color: '#888' },
  product: { label: '상품문의', color: '#4C9AFF' },
  qna: { label: 'QNA', color: '#FF8C00' },
  call_center: { label: '콜센터문의', color: '#FF6B6B' },
  delivery: { label: '배송문의', color: '#51CF66' },
  exchange_return: { label: '교환/반품', color: '#c084fc' },
}

// 마켓 리스트
const MARKETS = [
  '전체마켓', '스마트스토어', '쿠팡', '11번가', '롯데ON',
  'SSG', '롯데홈쇼핑', 'GS샵', 'KREAM', 'Toss',
]

// 기간 버튼
const PERIOD_BUTTONS = [
  { key: 'today', label: '오늘' },
  { key: '1week', label: '1주일' },
  { key: '15days', label: '15일' },
  { key: '1month', label: '1개월' },
  { key: '3months', label: '3개월' },
  { key: '6months', label: '6개월' },
  { key: 'year', label: '올해' },
  { key: 'all', label: '전체' },
]

export default function CSPage() {
  // 데이터
  const [inquiries, setInquiries] = useState<SambaCSInquiry[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<Record<string, unknown>>({})
  const [templates, setTemplates] = useState<Record<string, CSReplyTemplate>>({})
  const [loading, setLoading] = useState(true)

  // 필터
  const [filterMarket, setFilterMarket] = useState('')
  const [filterType, setFilterType] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [sortDesc, setSortDesc] = useState(true)
  const [pageSize, setPageSize] = useState(30)
  const [page, setPage] = useState(0)

  // 로그 + 기간 + 필터 추가 상태
  const [csLogMessages, setCsLogMessages] = useState<string[]>(['[대기] CS 문의 가져오기 결과가 여기에 표시됩니다...'])
  const [csPeriod, setCsPeriod] = useState('all')
  const [csSyncAccountId, setCsSyncAccountId] = useState('')
  const [csCustomStart, setCsCustomStart] = useState('')
  const [csCustomEnd, setCsCustomEnd] = useState('')
  const [csStartLocked, setCsStartLocked] = useState(false)
  const [csDateLocked, setCsDateLocked] = useState(false)
  const [searchCategory, setSearchCategory] = useState('customer')
  const [csSiteFilter, setCsSiteFilter] = useState('')
  const [csMarketStatus, setCsMarketStatus] = useState('')
  const [csInputFilter, setCsInputFilter] = useState('')

  // 선택
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // 답변 모달
  const [replyModal, setReplyModal] = useState<SambaCSInquiry | null>(null)
  const [replyText, setReplyText] = useState('')
  const [selectedTemplate, setSelectedTemplate] = useState('')

  // 템플릿 관리 모달
  const [showTemplateManager, setShowTemplateManager] = useState(false)

  // 데이터 로드
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [data, st, tpl] = await Promise.all([
        csInquiryApi.list({
          skip: page * pageSize,
          limit: pageSize,
          market: filterMarket || undefined,
          inquiry_type: filterType || undefined,
          reply_status: filterStatus || undefined,
          search: search || undefined,
          sort_desc: sortDesc,
        }).catch(() => ({ items: [], total: 0 })),
        csInquiryApi.getStats().catch(() => ({})),
        csInquiryApi.getTemplates().catch(() => ({})),
      ])
      setInquiries(data.items)
      setTotal(data.total)
      setStats(st)
      setTemplates(tpl)
    } catch {
      // 에러 무시
    }
    setLoading(false)
  }, [filterMarket, filterType, filterStatus, search, sortDesc, pageSize, page])

  useEffect(() => { load() }, [load])

  // 검색
  const handleSearch = () => {
    setPage(0)
    setSearch(searchInput)
  }

  // 전체 선택
  const toggleAll = () => {
    if (selected.size === inquiries.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(inquiries.map(i => i.id)))
    }
  }

  // 개별 선택
  const toggleOne = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  // 선택 삭제
  const handleBatchDelete = async () => {
    if (selected.size === 0) {
      showAlert('삭제할 항목을 선택해주세요', 'error')
      return
    }
    if (!await showConfirm(`${selected.size}건을 삭제하시겠습니까?`)) return
    try {
      await csInquiryApi.batchDelete(Array.from(selected))
      setSelected(new Set())
      load()
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '삭제 실패', 'error')
    }
  }

  // 답변 등록
  const handleReply = async () => {
    if (!replyModal || !replyText.trim()) {
      showAlert('답변 내용을 입력해주세요', 'error')
      return
    }
    try {
      await csInquiryApi.reply(replyModal.id, replyText)
      setReplyModal(null)
      setReplyText('')
      setSelectedTemplate('')
      load()
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '답변 등록 실패', 'error')
    }
  }

  // 템플릿 선택 시 답변란 채우기
  const applyTemplate = (key: string) => {
    setSelectedTemplate(key)
    if (key && templates[key]) {
      setReplyText(templates[key].content)
    }
  }

  // 단건 삭제
  const handleDelete = async (id: string) => {
    if (!await showConfirm('이 문의를 삭제하시겠습니까?')) return
    try {
      await csInquiryApi.delete(id)
      load()
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '삭제 실패', 'error')
    }
  }

  // 날짜 포맷
  const fmtDate = (d?: string) => {
    if (!d) return '-'
    const dt = new Date(d)
    const y = dt.getFullYear()
    const m = String(dt.getMonth() + 1).padStart(2, '0')
    const day = String(dt.getDate()).padStart(2, '0')
    const h = String(dt.getHours()).padStart(2, '0')
    const min = String(dt.getMinutes()).padStart(2, '0')
    return `${y}-${m}-${day}\n[${h}:${min}]`
  }

  const totalPages = Math.ceil(total / pageSize)
  const pendingCount = (stats.pending as number) || 0
  const repliedCount = (stats.replied as number) || 0
  const totalCount = (stats.total as number) || 0

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>CS 관리</h2>
          <p style={{ fontSize: '0.875rem', color: '#888' }}>
            연동하신 마켓의 질문/긴급문의/긴급알림 등에 대한 답변이 가능합니다
          </p>
        </div>
      </div>

      {/* 로그 영역 */}
      <div style={{ border: '1px solid #1C2333', borderRadius: '8px', overflow: 'hidden', marginBottom: '0.75rem' }}>
        <div style={{ padding: '6px 14px', background: '#0D1117', borderBottom: '1px solid #1C2333', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#94A3B8' }}>CS 로그</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button onClick={() => navigator.clipboard.writeText(csLogMessages.join('\n'))} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>복사</button>
            <button onClick={() => setCsLogMessages(['[대기] CS 문의 가져오기 결과가 여기에 표시됩니다...'])} style={{ fontSize: '0.72rem', color: '#555', background: 'transparent', border: '1px solid #1C2333', padding: '1px 8px', borderRadius: '4px', cursor: 'pointer' }}>초기화</button>
          </div>
        </div>
        <div style={{ height: '144px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.788rem', color: '#8A95B0', background: '#080A10', lineHeight: 1.8 }}>
          {csLogMessages.map((msg, i) => <p key={i} style={{ color: '#8A95B0', fontSize: 'inherit', margin: 0 }}>{msg}</p>)}
        </div>
      </div>

      {/* 기간 버튼 + 계정 + 가져오기 + 날짜범위 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '0.5rem', flexWrap: 'wrap' }}>
        {PERIOD_BUTTONS.map(pb => (
          <button key={pb.key} onClick={() => { setCsPeriod(pb.key) }}
            style={{ padding: '0.22rem 0.55rem', borderRadius: '5px', fontSize: '0.75rem', background: csPeriod === pb.key ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: csPeriod === pb.key ? '1px solid #C0392B' : '1px solid #3D3D3D', color: csPeriod === pb.key ? '#fff' : '#C5C5C5', cursor: 'pointer', whiteSpace: 'nowrap' }}
          >{pb.label}</button>
        ))}
        <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 2px' }} />
        <select value={csSyncAccountId} onChange={e => setCsSyncAccountId(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem', minWidth: '140px' }}>
          <option value="">전체 계정</option>
        </select>
        <button onClick={handleSearch} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: 'rgba(50,50,50,0.9)', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap' }}>가져오기</button>
        <button onClick={handleSearch} style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: '#8B1A1A', border: '1px solid #C0392B', color: '#fff', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap' }}>전체마켓 가져오기</button>
        <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 6px' }} />
        <input type="date" value={csCustomStart} onChange={e => setCsCustomStart(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
        <button onClick={() => setCsStartLocked(p => !p)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', background: csStartLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: csStartLocked ? '1px solid #C0392B' : '1px solid #3D3D3D', color: csStartLocked ? '#fff' : '#C5C5C5' }}>고정</button>
        <span style={{ color: '#555', fontSize: '0.75rem' }}>~</span>
        <input type="date" value={csCustomEnd} onChange={e => setCsCustomEnd(e.target.value)} style={{ ...inputStyle, padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
        <button onClick={() => setCsDateLocked(p => !p)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', background: csDateLocked ? '#8B1A1A' : 'rgba(50,50,50,0.8)', border: csDateLocked ? '1px solid #C0392B' : '1px solid #3D3D3D', color: csDateLocked ? '#fff' : '#C5C5C5' }}>고정</button>
      </div>

      {/* 검색 + 필터 드롭다운 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
        <select style={{ ...inputStyle, width: '80px', fontSize: '0.75rem' }} value={searchCategory} onChange={e => setSearchCategory(e.target.value)}>
          <option value="customer">고객</option>
          <option value="order_number">주문번호</option>
          <option value="product_id">상품번호</option>
          <option value="content">문의내용</option>
        </select>
        <input style={{ ...inputStyle, width: '140px' }} value={searchInput} onChange={e => setSearchInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') handleSearch() }} />
        <button onClick={handleSearch} style={{ background: 'linear-gradient(135deg,#FF8C00,#FFB84D)', color: '#fff', padding: '0.22rem 0.75rem', borderRadius: '5px', fontSize: '0.75rem', border: 'none', cursor: 'pointer', whiteSpace: 'nowrap' }}>검색</button>
        <button
          onClick={() => setShowTemplateManager(true)}
          style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '5px', color: '#C5C5C5', cursor: 'pointer', whiteSpace: 'nowrap', marginLeft: '4px' }}
        >
          답변템플릿 관리
        </button>
        <button
          onClick={handleBatchDelete}
          style={{ padding: '0.22rem 0.65rem', fontSize: '0.75rem', background: 'transparent', border: '1px solid #FF6B6B33', borderRadius: '5px', color: '#FF6B6B', cursor: 'pointer', whiteSpace: 'nowrap' }}
        >
          선택삭제
        </button>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', flexShrink: 0, alignItems: 'center' }}>
          <select style={{ ...inputStyle, width: '118px' }} value={filterMarket} onChange={e => { setFilterMarket(e.target.value); setPage(0) }}>
            <option value="">전체마켓보기</option>
            {MARKETS.filter(m => m !== '전체마켓').map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <select style={{ ...inputStyle, width: '110px' }} value={csSiteFilter} onChange={e => setCsSiteFilter(e.target.value)}>
            <option value="">전체사이트보기</option>
            {['MUSINSA','KREAM','FashionPlus','Nike','Adidas','ABCmart','GrandStage','OKmall','SSG','LOTTEON','GSShop','ElandMall','SSF'].map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select style={{ ...inputStyle, width: '112px' }} value={csMarketStatus} onChange={e => setCsMarketStatus(e.target.value)}>
            <option value="">마켓상태 보기</option>
          </select>
          <select style={{ ...inputStyle, width: '118px' }} value={csInputFilter} onChange={e => setCsInputFilter(e.target.value)}>
            <option value="">입력값</option>
          </select>
          <select style={{ ...inputStyle, width: '112px' }} value={filterStatus} onChange={e => { setFilterStatus(e.target.value); setPage(0) }}>
            <option value="">주문상태</option>
            <option value="pending">미답변</option>
            <option value="replied">답변완료</option>
          </select>
          <span style={{ width: '1px', background: '#333', height: '18px', margin: '0 2px' }} />
          <select style={{ ...inputStyle, width: '88px' }} onClick={() => setSortDesc(!sortDesc)}>
            <option>-- 정렬 --</option>
            <option>문의일자▲</option>
            <option>문의일자▼</option>
          </select>
          <select style={{ ...inputStyle, width: '92px' }} value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(0) }}>
            <option value={50}>50개 보기</option><option value={100}>100개 보기</option><option value={200}>200개 보기</option><option value={500}>500개 보기</option>
          </select>
        </div>
      </div>

      {/* 테이블 */}
      <div style={card}>
        <div style={{ overflowX: 'auto' }}>
          {loading ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>로딩 중...</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8125rem' }}>
              <thead>
                <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid #2D2D2D' }}>
                  <th style={{ width: '40px', padding: '0.75rem 0.5rem', textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      checked={inquiries.length > 0 && selected.size === inquiries.length}
                      onChange={toggleAll}
                      style={{ accentColor: '#FF8C00' }}
                    />
                  </th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'center', whiteSpace: 'nowrap', width: '80px' }}>
                    사진
                  </th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'left', whiteSpace: 'nowrap' }}>
                    마켓<br /><span style={{ fontSize: '0.75rem' }}>(주문번호)</span>
                  </th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'left', whiteSpace: 'nowrap' }}>
                    문의유형<br /><span style={{ fontSize: '0.75rem' }}>(질문자)</span>
                  </th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'left', minWidth: '400px' }}>문의내용</th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'center', whiteSpace: 'nowrap' }}>답변여부</th>
                  <th style={{ padding: '0.75rem 1rem', color: '#888', fontWeight: 500, textAlign: 'right', whiteSpace: 'nowrap' }}>
                    문의일시<br /><span style={{ fontSize: '0.75rem' }}>(문의수집일자)</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {inquiries.map(item => {
                  const st = REPLY_STATUS_MAP[item.reply_status] || REPLY_STATUS_MAP.pending
                  const tp = INQUIRY_TYPE_MAP[item.inquiry_type] || { label: item.inquiry_type, color: '#888' }
                  return (
                    <tr
                      key={item.id}
                      style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}
                      onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                    >
                      {/* 체크박스 */}
                      <td style={{ padding: '0.75rem 0.5rem', textAlign: 'center', verticalAlign: 'top' }}>
                        <input
                          type="checkbox"
                          checked={selected.has(item.id)}
                          onChange={() => toggleOne(item.id)}
                          style={{ accentColor: '#FF8C00' }}
                        />
                      </td>

                      {/* 사진 */}
                      <td style={{ padding: '0.75rem 0.5rem', verticalAlign: 'top', textAlign: 'center' }}>
                        {item.product_image ? (
                          <img
                            src={item.product_image}
                            alt=""
                            onClick={() => item.product_link && window.open(item.product_link, '_blank')}
                            style={{ width: '60px', height: '60px', objectFit: 'cover', borderRadius: '6px', border: '1px solid #2D2D2D', cursor: item.product_link ? 'pointer' : 'default' }}
                          />
                        ) : (
                          <div
                            onClick={() => item.product_link && window.open(item.product_link, '_blank')}
                            style={{ width: '60px', height: '60px', background: '#1A1A1A', borderRadius: '6px', border: '1px solid #2D2D2D', display: 'flex', alignItems: 'center', justifyContent: 'center', color: item.product_link ? '#4C9AFF' : '#444', fontSize: '0.625rem', cursor: item.product_link ? 'pointer' : 'default', textDecoration: item.product_link ? 'underline' : 'none', margin: '0 auto' }}
                          >
                            {item.product_link ? '링크' : 'No IMG'}
                          </div>
                        )}
                      </td>

                      {/* 마켓/주문번호 */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top', whiteSpace: 'nowrap' }}>
                        <div style={{ fontWeight: 600, color: '#E5E5E5', marginBottom: '0.25rem' }}>
                          {item.market}
                        </div>
                        {item.account_name && (
                          <div style={{ fontSize: '0.75rem', color: '#666' }}>{item.account_name}</div>
                        )}
                        {item.market_order_id && (
                          <div style={{ fontSize: '0.75rem', color: '#555' }}>({item.market_order_id})</div>
                        )}
                      </td>

                      {/* 문의유형/질문자 */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top' }}>
                        <span style={{ padding: '0.15rem 0.5rem', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 600, background: `${tp.color}22`, color: tp.color }}>
                          {tp.label}
                        </span>
                        {item.questioner && (
                          <div style={{ fontSize: '0.75rem', color: '#888', marginTop: '0.375rem' }}>({item.questioner})</div>
                        )}
                      </td>

                      {/* 문의내용 */}
                      <td style={{ padding: '0.75rem 1rem', verticalAlign: 'top' }}>
                        {/* 상품명 + 링크 */}
                        {item.product_name && (
                          <div style={{ marginBottom: '0.5rem' }}>
                            <span style={{ fontWeight: 600, color: '#E5E5E5', fontSize: '0.8125rem' }}>
                              {item.product_name}
                            </span>
                            <div style={{ display: 'flex', gap: '0.375rem', marginTop: '0.25rem', flexWrap: 'wrap' }}>
                              {item.product_link && (
                                <a href={item.product_link} target="_blank" rel="noreferrer" style={{ fontSize: '0.6875rem', padding: '0.125rem 0.375rem', border: '1px solid #444', borderRadius: '3px', color: '#888', textDecoration: 'none' }}>
                                  상품링크
                                </a>
                              )}
                              {item.market_link && (
                                <a href={item.market_link} target="_blank" rel="noreferrer" style={{ fontSize: '0.6875rem', padding: '0.125rem 0.375rem', border: '1px solid #444', borderRadius: '3px', color: '#888', textDecoration: 'none' }}>
                                  판매마켓링크
                                </a>
                              )}
                              {item.original_link && (
                                <a href={item.original_link} target="_blank" rel="noreferrer" style={{ fontSize: '0.6875rem', padding: '0.125rem 0.375rem', border: '1px solid #444', borderRadius: '3px', color: '#888', textDecoration: 'none' }}>
                                  원문링크
                                </a>
                              )}
                            </div>
                          </div>
                        )}

                        {/* 문의 내용 */}
                        <div style={{ color: '#ccc', fontSize: '0.8125rem', lineHeight: '1.5', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {item.content}
                        </div>

                        {/* 답변 내용 */}
                        {item.reply && (
                          <div style={{ marginTop: '0.5rem', padding: '0.5rem 0.75rem', background: 'rgba(81,207,102,0.08)', borderRadius: '6px', borderLeft: '3px solid #51CF66' }}>
                            <div style={{ fontSize: '0.75rem', color: '#51CF66', marginBottom: '0.25rem', fontWeight: 600 }}>답변</div>
                            <div style={{ color: '#aaa', fontSize: '0.8125rem', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
                              {item.reply}
                            </div>
                            {item.replied_at && (
                              <div style={{ fontSize: '0.6875rem', color: '#555', marginTop: '0.25rem' }}>
                                [{new Date(item.replied_at).toLocaleString('ko-KR')}]
                              </div>
                            )}
                          </div>
                        )}
                      </td>

                      {/* 답변 여부 */}
                      <td style={{ padding: '0.75rem 1rem', textAlign: 'center', verticalAlign: 'top' }}>
                        <span style={{
                          padding: '0.25rem 0.625rem',
                          borderRadius: '20px',
                          fontSize: '0.75rem',
                          fontWeight: 600,
                          background: st.bg,
                          color: st.text,
                        }}>
                          {st.label}
                        </span>
                      </td>

                      {/* 문의일시 + 액션 */}
                      <td style={{ padding: '0.75rem 1rem', textAlign: 'right', verticalAlign: 'top', whiteSpace: 'pre-line' }}>
                        <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>
                          {fmtDate(item.inquiry_date)}
                        </div>
                        <div style={{ fontSize: '0.6875rem', color: '#555', marginBottom: '0.5rem' }}>
                          {fmtDate(item.collected_at)}
                        </div>
                        <div style={{ display: 'flex', gap: '0.375rem', justifyContent: 'flex-end' }}>
                          {item.reply_status === 'pending' && (
                            <button
                              onClick={() => { setReplyModal(item); setReplyText(''); setSelectedTemplate('') }}
                              style={{ padding: '0.25rem 0.5rem', background: 'rgba(255,140,0,0.15)', border: '1px solid rgba(255,140,0,0.3)', borderRadius: '4px', color: '#FF8C00', fontSize: '0.6875rem', cursor: 'pointer' }}
                            >
                              답변
                            </button>
                          )}
                          <button
                            onClick={() => handleDelete(item.id)}
                            style={{ padding: '0.25rem 0.5rem', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.2)', borderRadius: '4px', color: '#FF6B6B', fontSize: '0.6875rem', cursor: 'pointer' }}
                          >
                            삭제
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
                {inquiries.length === 0 && (
                  <tr>
                    <td colSpan={7} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>
                      문의 내역이 없습니다
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>

        {/* 페이지네이션 */}
        {totalPages > 1 && (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '0.5rem', padding: '1rem', borderTop: '1px solid #2D2D2D' }}>
            <button
              disabled={page === 0}
              onClick={() => setPage(p => p - 1)}
              style={{ padding: '0.375rem 0.75rem', background: page === 0 ? '#1A1A1A' : '#2A2A2A', border: '1px solid #2D2D2D', borderRadius: '4px', color: page === 0 ? '#444' : '#E5E5E5', fontSize: '0.8125rem', cursor: page === 0 ? 'default' : 'pointer' }}
            >
              이전
            </button>
            <span style={{ fontSize: '0.8125rem', color: '#888' }}>
              {page + 1} / {totalPages} ({total}건)
            </span>
            <button
              disabled={page >= totalPages - 1}
              onClick={() => setPage(p => p + 1)}
              style={{ padding: '0.375rem 0.75rem', background: page >= totalPages - 1 ? '#1A1A1A' : '#2A2A2A', border: '1px solid #2D2D2D', borderRadius: '4px', color: page >= totalPages - 1 ? '#444' : '#E5E5E5', fontSize: '0.8125rem', cursor: page >= totalPages - 1 ? 'default' : 'pointer' }}
            >
              다음
            </button>
          </div>
        )}
      </div>

      {/* 답변 모달 */}
      {replyModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '560px', maxWidth: '90vw', maxHeight: '80vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5' }}>답변 작성</h3>
              <button onClick={() => setReplyModal(null)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
            </div>

            {/* 문의 정보 */}
            <div style={{ background: '#111', borderRadius: '8px', padding: '1rem', marginBottom: '1rem' }}>
              <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.5rem', fontSize: '0.8125rem' }}>
                <span style={{ color: '#888' }}>마켓:</span>
                <span style={{ color: '#E5E5E5', fontWeight: 600 }}>{replyModal.market}</span>
                {replyModal.questioner && (
                  <>
                    <span style={{ color: '#888' }}>질문자:</span>
                    <span style={{ color: '#E5E5E5' }}>{replyModal.questioner}</span>
                  </>
                )}
              </div>
              {replyModal.product_name && (
                <div style={{ fontSize: '0.8125rem', color: '#aaa', marginBottom: '0.5rem' }}>
                  {replyModal.product_name}
                </div>
              )}
              <div style={{ fontSize: '0.8125rem', color: '#ccc', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
                {replyModal.content}
              </div>
            </div>

            {/* 템플릿 선택 */}
            <div style={{ marginBottom: '0.75rem' }}>
              <label style={{ fontSize: '0.75rem', color: '#888', display: 'block', marginBottom: '0.375rem' }}>답변 템플릿</label>
              <select
                value={selectedTemplate}
                onChange={e => applyTemplate(e.target.value)}
                style={inputStyle}
              >
                <option value="">직접 입력</option>
                {Object.entries(templates).map(([key, tpl]) => (
                  <option key={key} value={key}>{tpl.name}</option>
                ))}
              </select>
            </div>

            {/* 답변 입력 */}
            <div style={{ marginBottom: '1rem' }}>
              <label style={{ fontSize: '0.75rem', color: '#888', display: 'block', marginBottom: '0.375rem' }}>답변 내용</label>
              <textarea
                value={replyText}
                onChange={e => setReplyText(e.target.value)}
                placeholder="답변 내용을 입력하세요"
                rows={6}
                style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit', lineHeight: '1.5' }}
              />
            </div>

            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              <button onClick={() => setReplyModal(null)} style={{ padding: '0.625rem 1.25rem', background: 'transparent', border: '1px solid #2D2D2D', borderRadius: '8px', color: '#888', fontSize: '0.875rem', cursor: 'pointer' }}>취소</button>
              <button onClick={handleReply} style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}>답변 등록</button>
            </div>
          </div>
        </div>
      )}

      {/* 답변 템플릿 관리 모달 */}
      {showTemplateManager && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '16px', padding: '2rem', width: '600px', maxWidth: '90vw', maxHeight: '80vh', overflowY: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
              <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: '#E5E5E5' }}>답변 템플릿 관리</h3>
              <button onClick={() => setShowTemplateManager(false)} style={{ background: 'none', border: 'none', color: '#888', fontSize: '1.25rem', cursor: 'pointer' }}>✕</button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {Object.entries(templates).map(([key, tpl]) => (
                <div key={key} style={{ background: '#111', borderRadius: '8px', padding: '1rem', border: '1px solid #2A2A2A' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                    <span style={{ fontSize: '0.875rem', fontWeight: 600, color: '#FF8C00' }}>{tpl.name}</span>
                    <span style={{ fontSize: '0.6875rem', color: '#555', fontFamily: 'monospace' }}>{key}</span>
                  </div>
                  <p style={{ fontSize: '0.8125rem', color: '#aaa', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
                    {tpl.content}
                  </p>
                </div>
              ))}
              {Object.keys(templates).length === 0 && (
                <div style={{ padding: '2rem', textAlign: 'center', color: '#555' }}>
                  등록된 템플릿이 없습니다
                </div>
              )}
            </div>

            <p style={{ fontSize: '0.75rem', color: '#555', marginTop: '1rem' }}>
              * 템플릿 추가/수정은 백엔드 서비스에서 관리됩니다
            </p>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button onClick={() => setShowTemplateManager(false)} style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', border: 'none', borderRadius: '8px', color: '#fff', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}>닫기</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
