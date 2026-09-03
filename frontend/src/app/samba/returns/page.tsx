'use client'

import { useEffect, useState, useCallback, useRef, useMemo, Fragment } from 'react'
import { useSearchParams } from 'next/navigation'
import { accountApi, orderApi, type SambaMarketAccount } from '@/lib/samba/api/commerce'
import { returnApi, type SambaReturn } from '@/lib/samba/api/support'
import { request, SAMBA_PREFIX } from '@/lib/samba/api/shared'
import { jobApi } from '@/lib/samba/api/operations'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { makeCard, makeInputStyle, fmtNum, fmtTextNumbers } from '@/lib/samba/styles'
import { PERIOD_BUTTONS } from '@/lib/samba/constants'
import { fmtTime, getPeriodStart, getPeriodEnd } from '@/lib/samba/utils'
import { useTheme } from '@/lib/samba/useTheme'
import type { Palette } from '@/lib/samba/colors'
import { btn } from '@/lib/samba/buttons'

import {
  STATUS_MAP, TYPE_LABELS, RETURN_REASONS,
  fmtMD, getAccountOptionLabel, tdCenter,
  classifyReturnSection, makeReturnSections, isOrderPlacedWarnMemo,
  type ReturnSectionKey,
} from './constants'
import { ReturnDetailModal } from './components/ReturnDetailModal'

// 완료내역(completion_detail) 옵션 + 색상 (옅은 배경 + 팔레트 글자색)
// value = 백엔드 저장 어휘(진행중/취소/반품/교환/거부), label = 화면 표시(완료형)
// 백엔드 정식값과 일치시켜야 필터/표시가 동작 (issue #334)
const COMPLETION_DEFAULT = '진행중'
const COMPLETION_OPTIONS: { value: string; label: string }[] = [
  { value: '진행중', label: '대기중' },
  { value: '취소', label: '취소완료' },
  { value: '반품', label: '반품완료' },
  { value: '교환', label: '교환완료' },
  { value: '거부', label: '거부' },
]
// 라이트/다크 팔레트를 받아 뱃지 색을 만든다 — 모듈 스코프 다크 고정이던 것을 테마 반응형으로 전환
const makeCompletionColors = (c: Palette): Record<string, { bg: string; fg: string }> => ({
  '진행중': { bg: 'rgba(255,217,61,0.12)', fg: c.warn },   // 노랑(대기중)
  '취소': { bg: 'rgba(255,107,107,0.12)', fg: c.danger },    // 빨강(취소완료)
  '반품': { bg: c.badgePinkBg, fg: c.badgePinkFg },    // 핑크(반품완료)
  '교환': { bg: 'rgba(76,154,255,0.12)', fg: c.link },     // 파랑(교환완료)
  '거부': { bg: 'rgba(150,150,150,0.14)', fg: c.textSub },    // 회색(거부)
})

// ── 고객비용/회사비용 콤마 포맷 (B1) ──
// 숫자로만 이루어진 입력(공백/콤마/앞의 -/소수점 허용)만 1,000 형태로 포맷.
// 글자가 섞이면(예: "택배비 회사부담") 입력 그대로 반환 — 메모 기능 유지.
const AMOUNT_NUMERIC_RE = /^-?\d[\d,]*(\.\d+)?$/
const formatAmountInput = (raw: string): string => {
  const s = raw.trim()
  if (!AMOUNT_NUMERIC_RE.test(s)) return raw
  const n = Number(s.replace(/,/g, ''))
  if (!Number.isFinite(n)) return raw
  return fmtNum(n)
}
// 콤마 포함 저장 문자열 → 숫자 (수익총액 계산용). 숫자 아니면(메모 등) 0.
const parseAmount = (v: string | null | undefined): number => {
  const n = Number(String(v ?? '').replace(/,/g, ''))
  return Number.isFinite(n) ? n : 0
}

// ── 마감(종결) 로컬 확장 타입 (T7) ──
// samba_return 신규 컬럼 closed_at/closed_by 가 lib 타입(SambaReturn)에 아직 없다.
// lib 파일은 수정 금지이므로 이 페이지 안에서만 구조적으로 확장해 쓴다.
type ReturnRow = SambaReturn & { closed_at?: string | null; closed_by?: string | null }

export default function ReturnsPage() {
  const c = useTheme()
  // 완료내역 뱃지 색 — 테마(c) 변경 시에만 재생성
  const COMPLETION_COLORS = useMemo(() => makeCompletionColors(c), [c])
  useEffect(() => { document.title = 'SAMBA-반품관리' }, [])
  const [returns, setReturns] = useState<ReturnRow[]>([])
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [, setStats] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [detailItem, setDetailItem] = useState<SambaReturn | null>(null)
  const [filterStatus] = useState<string>('')
  const [filterType] = useState<string>('')
  const [form, setForm] = useState({ order_id: '', type: 'return', reason: '', customReason: '', quantity: 1, requested_amount: 0 })

  // 로그 + 검색/필터 상태
  const logRef = useRef<HTMLDivElement>(null)
  const [logMessages, _setLogMessagesRaw] = useState<string[]>(['[대기] 반품교환 가져오기 결과가 여기에 표시됩니다...'])
  const setLogMessages: typeof _setLogMessagesRaw = (v) => _setLogMessagesRaw(prev => {
    const next = typeof v === 'function' ? v(prev) : v
    return next.slice(-30)
  })
  const [period, setPeriod] = useState('2month')
  const [syncAccountId, setSyncAccountId] = useState('')
  const [syncBusy, setSyncBusy] = useState(false)
  const [customStart, setCustomStart] = useState((getPeriodStart('2month') ?? new Date()).toLocaleDateString('sv-SE'))
  const [customEnd, setCustomEnd] = useState(getPeriodEnd('2month').toLocaleDateString('sv-SE'))
  const [startLocked, setStartLocked] = useState(false)
  const [dateLocked, setDateLocked] = useState(false)
  const [accounts, setAccounts] = useState<SambaMarketAccount[]>([])

  // 주문관리에서 `/samba/returns?order_number=주문번호` 로 새 탭 진입 시
  // 해당 주문의 반품/교환만 표시 (날짜 범위 무시). 마운트 1회만 시드.
  const searchParams = useSearchParams()
  // 주문탭 [반품/교환] 새 탭 진입(?order_number=...)은 첫 렌더에서 바로 필터를 채운다.
  // 예전처럼 ''로 시작해 useEffect 로 채우면 마운트 직후 '필터 없는' 목록 요청이 먼저
  // 나가고, 그 응답이 늦게 도착하면 주문번호 필터 결과를 덮어써 대상 주문이 화면에서
  // 사라졌다(사장님 지적: 검색을 한 번 더 눌러야 보임).
  const seedOrderNumber = searchParams.get('order_number')?.trim() ?? ''
  const [orderNumberFilter, setOrderNumberFilter] = useState(seedOrderNumber)
  const seededRef = useRef(Boolean(seedOrderNumber))
  useEffect(() => {
    // 폴백 — 첫 렌더에 검색 파라미터가 아직 안 붙는 렌더링 경로 대비.
    if (seededRef.current) return
    const q = searchParams.get('order_number')?.trim()
    if (q) {
      seededRef.current = true
      setOrderNumberFilter(q)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 전체보기 — 주문번호 필터 해제 + URL 에서 ?order_number 제거 (새로고침 시 재적용 방지)
  const clearOrderNumberFilter = () => {
    multiAppliedRef.current = false
    setOrderNumberFilter('')
    window.history.replaceState(null, '', window.location.pathname)
  }

  // ── 다중 주문번호 조회 (요청 #9) ──
  // [다중] 토글 ON 시 검색 input 이 textarea 로 스왑되고, [검색]이 클라이언트 필터가 아니라
  // 서버 조회(orderNumberFilter)로 여러 주문번호를 한 번에 보낸다.
  const [multiMode, setMultiMode] = useState(false)
  const [multiText, setMultiText] = useState('')
  // 현재 orderNumberFilter 가 다중 검색으로 걸린 것인지 추적 — 토글 OFF 시 이것만 해제
  // (URL ?order_number= 시드로 들어온 단건 필터는 토글과 무관하므로 건드리지 않음)
  const multiAppliedRef = useRef(false)

  const toggleMultiMode = () => {
    if (multiMode) {
      // OFF: 다중 검색으로 걸어둔 서버 필터를 해제하고 기존(클라이언트 필터) 동작으로 복귀
      setMultiMode(false)
      if (multiAppliedRef.current) clearOrderNumberFilter()
    } else {
      setMultiMode(true)
    }
  }

  const applyMultiSearch = () => {
    // 개행·쉼표·공백으로 토큰화 + 빈 토큰 제거 + 중복 제거 (백엔드 토큰화 규칙과 동일)
    const tokens = [...new Set(multiText.split(/[\s,]+/).filter(Boolean))]
    if (tokens.length === 0) {
      showAlert('조회할 주문번호를 입력해주세요', 'info')
      return
    }
    let limited = tokens
    if (tokens.length > 200) {
      // 상한 초과는 막지 않고 앞 200건만 조회 (백엔드 상한 200과 동일 · 안내 문구는 주문탭과 통일)
      showAlert(`주문번호 ${fmtNum(tokens.length)}건 입력 — 최대 200건까지만 조회됩니다 (앞 200건)`, 'info')
      limited = tokens.slice(0, 200)
    }
    multiAppliedRef.current = true
    // 쉼표로 합쳐 서버 조회 경로로 전달 — 백엔드 list_filtered 가 다시 토큰화해 IN 조회
    setOrderNumberFilter(limited.join(','))
  }

  useEffect(() => { accountApi.listActiveCached(setAccounts) }, [])
  useEffect(() => { logRef.current && (logRef.current.scrollTop = logRef.current.scrollHeight) }, [logMessages])



  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // 편집칸(고객/회사/반품링크) 포커스 시점의 값 보관 — 저장 실패 시 되돌리기용
  // key = `${field}:${id}`
  const cellEditRef = useRef<Record<string, string>>({})

  // 편집칸 onBlur 저장 공통 처리: 실패 시 console.error + 알림 + 직전 값 복원
  const saveCell = async (
    id: string,
    data: Parameters<typeof returnApi.patch>[1],
    revert: () => void,
    label: string,
  ) => {
    try {
      await returnApi.patch(id, data)
    } catch (e) {
      console.error(`[반품교환] ${label} 저장 실패 (id=${id}):`, e)
      showAlert(`${label} 저장에 실패했습니다. 입력값을 직전 값으로 되돌립니다.`, 'error')
      revert()
    }
  }

  const [siteFilter, setSiteFilter] = useState('')
  const [pageSize, setPageSize] = useState(50)
  const [searchCategory, setSearchCategory] = useState('product')
  const [searchText, setSearchText] = useState('')
  const [marketFilter, setMarketFilter] = useState('')

  // ── 구획 접기/펴기 (T6) — '기타'만 기본 접힘, localStorage 에 접힘 상태 유지 ──
  const SECTION_COLLAPSE_KEY = 'samba_returns_section_collapsed'
  // 기타 구획은 취소완료·거부 등 종결건이 대부분(운영DB 90일 실측 914건)이라 기본 접힘.
  const SECTION_COLLAPSE_DEFAULT: Partial<Record<ReturnSectionKey, boolean>> = { etc: true }
  const [collapsedSections, setCollapsedSections] = useState<Partial<Record<ReturnSectionKey, boolean>>>(SECTION_COLLAPSE_DEFAULT)
  useEffect(() => {
    try {
      const raw = localStorage.getItem(SECTION_COLLAPSE_KEY)
      if (raw) {
        const parsed: unknown = JSON.parse(raw)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          setCollapsedSections(parsed as Partial<Record<ReturnSectionKey, boolean>>)
        }
      }
    } catch { /* 읽기 실패 시 기본(기타만 접힘) 유지 */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const toggleSection = (key: ReturnSectionKey) => {
    setCollapsedSections(prev => {
      const next = { ...prev, [key]: !prev[key] }
      try { localStorage.setItem(SECTION_COLLAPSE_KEY, JSON.stringify(next)) } catch { /* 저장 실패해도 화면 동작엔 영향 없음 */ }
      return next
    })
  }

  // 구획 정의(색 포함) — 테마 팔레트(c) 변경 시에만 재생성
  const RETURN_SECTIONS = useMemo(() => makeReturnSections(c), [c])

  // ── 회수상태 자동조회 (T4 프론트) ──
  // POST /returns/collect-status/refresh — 백엔드가 원주문/회수 송장을 택배사에 조회해
  // 미수거/수거중/수거완료 상태를 자동 갱신한다. 결과는 로그창에만 남긴다
  // (백엔드 미배포로 404/500 이어도 모달 없이 로그 한 줄로 조용히 종료).
  const [collectStatusBusy, setCollectStatusBusy] = useState(false)
  const refreshCollectStatus = async () => {
    if (collectStatusBusy) return // 연타 방지
    setCollectStatusBusy(true)
    setLogMessages(prev => [...prev, `[${fmtTime()}] 회수상태 자동조회 시작...`])
    try {
      const res = await request<{ ok: boolean; checked: number; updated: number; skipped: number; errors: unknown[] }>(
        `${SAMBA_PREFIX}/returns/collect-status/refresh`,
        { method: 'POST', body: JSON.stringify({}) },
      )
      const errCount = Array.isArray(res.errors) ? res.errors.length : 0
      setLogMessages(prev => [...prev,
        `[${fmtTime()}] 회수상태 조회 완료 — 확인 ${fmtNum(res.checked ?? 0)}건 · 갱신 ${fmtNum(res.updated ?? 0)}건 · 건너뜀 ${fmtNum(res.skipped ?? 0)}건${errCount ? ` · 오류 ${fmtNum(errCount)}건` : ''}`,
      ])
      await load()
    } catch (e) {
      setLogMessages(prev => [...prev, `[${fmtTime()}] 회수상태 조회 실패 — ${e instanceof Error ? e.message : String(e)}`])
    } finally {
      setCollectStatusBusy(false)
    }
  }

  // ── 마감(종결) (T7) ──
  // '완료 처리까지 다 끝낸 건'을 목록에서 숨긴다 — 완료내역(어떻게 끝났나)과 직교 축.
  // '마감 포함 보기' 토글(localStorage 유지, 기본 꺼짐)을 켜면 include_closed=true 로 조회해
  // 마감 행을 흐리게 + [마감 해제] 버튼과 함께 보여준다.
  const INCLUDE_CLOSED_KEY = 'samba_returns_include_closed'
  const [includeClosed, setIncludeClosed] = useState(false)
  useEffect(() => {
    try {
      if (localStorage.getItem(INCLUDE_CLOSED_KEY) === '1') setIncludeClosed(true)
    } catch { /* 읽기 실패 시 기본값 false 유지 */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const toggleIncludeClosed = () => {
    setIncludeClosed(prev => {
      const next = !prev
      try { localStorage.setItem(INCLUDE_CLOSED_KEY, next ? '1' : '0') } catch { /* 저장 실패해도 화면 동작엔 영향 없음 */ }
      return next
    })
  }

  // 마감/해제 공통 호출 — 백엔드 미배포로 404/500 이 날 수 있으므로
  // 실패는 모달 없이 로그창 한국어 한 줄로만 남기고 조용히 끝낸다.
  const closeReturns = async (ids: string[]) => {
    if (ids.length === 0) return
    try {
      const res = await request<{ ok: boolean; closed: number }>(
        `${SAMBA_PREFIX}/returns/close`,
        { method: 'POST', body: JSON.stringify({ ids }) },
      )
      // 낙관적 업데이트 — 마감 포함 보기 OFF면 즉시 목록에서 제거, ON이면 마감 표시로 전환
      const now = new Date().toISOString()
      setReturns(prev => includeClosed
        ? prev.map(x => ids.includes(x.id) ? { ...x, closed_at: now, closed_by: 'manual' } : x)
        : prev.filter(x => !ids.includes(x.id)))
      setSelectedIds(new Set())
      setLogMessages(prev => [...prev, `[${fmtTime()}] 마감 완료 — ${fmtNum(res.closed ?? ids.length)}건`])
      await load()
    } catch (e) {
      setLogMessages(prev => [...prev, `[${fmtTime()}] 마감 실패 — ${e instanceof Error ? e.message : String(e)}`])
    }
  }
  const reopenReturns = async (ids: string[]) => {
    if (ids.length === 0) return
    try {
      const res = await request<{ ok: boolean; reopened: number }>(
        `${SAMBA_PREFIX}/returns/reopen`,
        { method: 'POST', body: JSON.stringify({ ids }) },
      )
      setReturns(prev => prev.map(x => ids.includes(x.id) ? { ...x, closed_at: null, closed_by: null } : x))
      setLogMessages(prev => [...prev, `[${fmtTime()}] 마감 해제 — ${fmtNum(res.reopened ?? ids.length)}건`])
      await load()
    } catch (e) {
      setLogMessages(prev => [...prev, `[${fmtTime()}] 마감 해제 실패 — ${e instanceof Error ? e.message : String(e)}`])
    }
  }
  // 행 단위 마감 — 한 번 확인 후 실행
  const closeOne = async (r: ReturnRow) => {
    const label = r.order_number || r.order_id || r.id
    if (!await showConfirm(`주문 ${label} 건을 마감하시겠습니까?\n마감된 건은 목록에서 숨겨집니다 ('마감 포함 보기'로 재확인 가능).`)) return
    await closeReturns([r.id])
  }
  // 체크박스로 고른 행 일괄 마감 — 개수 확인 후 실행
  const closeSelected = async () => {
    if (selectedIds.size === 0) {
      showAlert('마감할 항목을 선택해주세요', 'info')
      return
    }
    if (!await showConfirm(`선택한 ${fmtNum(selectedIds.size)}건을 일괄 마감하시겠습니까?\n마감된 건은 목록에서 숨겨집니다.`)) return
    await closeReturns([...selectedIds])
  }

  // 목록 요청 일련번호 — 필터를 연달아 바꾸거나 새 탭 진입처럼 요청이 겹칠 때,
  // 먼저 보낸 요청이 늦게 도착해 최신 결과를 덮어쓰는 것을 막는다.
  const loadSeqRef = useRef(0)

  // ?order_number= 시드 진입 첫 조회가 0건일 때 1.5초 후 1회만 자동 재조회 (B3).
  // 백엔드가 주문→반품 레코드를 백필로 "생성"하는데, 첫 조회가 생성 전에 도착하면
  // 0건이 나와 검색을 다시 눌러야 보이던 문제 대응. ref 가드로 무한루프 차단.
  const seedRetryDoneRef = useRef(false)
  // 재조회 예약 시점의 낡은 load 클로저 대신 항상 최신 load 를 부르기 위한 ref
  const loadRef = useRef<() => void>(() => {})

  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current
    setLoading(true)
    // 주문번호 필터 진입 시 날짜 범위는 보내지 않음 — 해당 주문 전체 반품/교환을 잡기 위함
    const onf = orderNumberFilter.trim()
    // 다중 주문번호(요청 #9)면 pageSize(기본 50)로는 잘릴 수 있어 라우트 상한(1000)까지 확장
    const onfCount = onf ? onf.split(/[\s,]+/).filter(Boolean).length : 0
    // include_closed(T7)는 returnApi.list 에 없고 lib 은 수정 금지 —
    // returnApi.list 와 동일한 파라미터를 페이지에서 직접 구성해 호출한다.
    const p = new URLSearchParams()
    // 주문번호 필터 진입 시 날짜 범위는 보내지 않음 — 해당 주문 전체 반품/교환을 잡기 위함
    if (onf) p.set('order_number', onf)
    if (filterStatus) p.set('status', filterStatus)
    if (filterType) p.set('type', filterType)
    if (!onf && customStart) p.set('start_date', customStart)
    if (!onf && customEnd) p.set('end_date', customEnd)
    // 주문번호 시드 진입(주문탭 [반품/교환] 새 탭)일 때만 강제 백필 — 방금 취소요청한
    // 주문이 재검색 없이 첫 로드에 바로 뜨도록 (요청 #10). 일반 진입은 기존 스로틀 유지.
    if (onf) p.set('force_backfill', 'true')
    // '마감 포함 보기' ON — 마감(closed_at)된 건까지 포함 조회 (기본은 백엔드가 제외)
    if (includeClosed) p.set('include_closed', 'true')
    p.set('limit', String(onfCount > 1 ? 1000 : pageSize))
    // 실패를 빈 배열로 바꾸지 않는다 — 일시적 오류에 목록이 통째로 비어
    // '데이터 없음'처럼 보이던 문제 방지. null 이면 기존 목록을 그대로 둔다.
    const data = await request<ReturnRow[]>(`${SAMBA_PREFIX}/returns?${p}`).catch(() => null)
    const st = await returnApi.getStats().catch(() => null)
    // 내가 최신 요청이 아니면 반영하지 않는다(늦게 온 옛 응답이 최신을 덮어쓰는 것 차단).
    if (seq !== loadSeqRef.current) return
    if (data !== null) setReturns(data)
    if (st !== null) setStats(st)
    setLoading(false)
    // 시드 진입(주문탭 딥링크) 한정 — 첫 조회 0건이면 1회만 자동 재조회 (B3).
    // 사용자가 [다중]으로 직접 조회한 경우(multiAppliedRef)는 재시도하지 않는다.
    if (
      onf && seededRef.current && !multiAppliedRef.current &&
      !seedRetryDoneRef.current && data !== null && data.length === 0
    ) {
      seedRetryDoneRef.current = true
      setLogMessages(prev => [...prev, '[안내] 반품/교환 데이터 생성 대기 — 1.5초 후 1회 재조회'])
      setTimeout(() => loadRef.current(), 1500)
    }
  }, [filterStatus, filterType, customStart, customEnd, orderNumberFilter, pageSize, includeClosed])

  useEffect(() => { loadRef.current = load }, [load])
  useEffect(() => { load() }, [load])

  // 가져오기 버튼 — 백그라운드 returns_sync 잡 생성 + 진행률 폴링 후 DB 로드.
  // (구: 단일 HTTP 로 31개 계정을 동기 순회 → Caddy 120초 컷 → 재클릭 sweep 중첩
  //  + write 트랜잭션 장기 점유로 풀 고갈. order_sync 와 동일하게 잡으로 분리)
  const loadReturns = async () => {
    if (syncBusy) return  // 연타 방지 — 중복 잡은 백엔드 create_job 가드도 차단
    setSyncBusy(true)
    const ts = fmtTime

    // 대상 계정 해석 (type: 그룹 / 특정 계정 / 전체)
    let accountIds: string[] | undefined
    let label: string
    if (syncAccountId.startsWith('type:')) {
      const marketType = syncAccountId.replace('type:', '')
      const marketAccs = accounts.filter(a => a.market_type === marketType)
      accountIds = marketAccs.map(a => a.id)
      label = `${marketAccs[0]?.market_name || marketType} (${fmtNum(marketAccs.length)}개 계정)`
    } else if (syncAccountId) {
      accountIds = [syncAccountId]
      label = accounts.find(a => a.id === syncAccountId)?.market_name || syncAccountId
    } else {
      accountIds = undefined  // 전체 활성 계정
      label = `전체마켓 (${fmtNum(accounts.length)}개 계정)`
    }

    setLogMessages(prev => [...prev, `[${ts()}] ${label} 반품교환 수집 시작...`])

    try {
      const payload: Record<string, unknown> = { days: 30 }
      if (accountIds && accountIds.length > 0) payload.account_ids = accountIds
      const created = await jobApi.create({ job_type: 'returns_sync', payload })
      const jobId = created.id
      setLogMessages(prev => [...prev, `[${ts()}] 백그라운드 반품수집 ${created.duplicate ? '재연결' : '시작'} (${jobId.slice(0, 12)}...)`])

      let logSince = 0
      let done = false
      while (!done) {
        await new Promise(resolve => setTimeout(resolve, 2000))
        try {
          const logsRes = await jobApi.jobLogs(jobId, logSince)
          if (logsRes.logs.length > 0) {
            setLogMessages(prev => [...prev, ...logsRes.logs])
            logSince += logsRes.logs.length
          }
          const job = await jobApi.get(jobId)
          const status = job.status
          if (status === 'completed' || status === 'failed' || status === 'cancelled') {
            // 잡 종료 직전 백엔드가 추가한 결과 로그 누락 방지
            try {
              const finalLogs = await jobApi.jobLogs(jobId, logSince)
              if (finalLogs.logs.length > 0) {
                setLogMessages(prev => [...prev, ...finalLogs.logs])
                logSince += finalLogs.logs.length
              }
            } catch { /* 최종 로그 폴링 실패 무시 */ }
            setLogMessages(prev => [...prev, `[${ts()}] ${status === 'completed' ? '반품교환 수집 완료' : status === 'failed' ? '반품교환 수집 실패' : '반품교환 수집 취소'}`])
            done = true
          }
        } catch {
          // 폴링 실패는 일시적 네트워크/DB 풀 압박 — 다음 사이클 자동 재시도
        }
      }
    } catch (e) {
      setLogMessages(prev => [...prev, `[오류] 반품교환 수집 실패: ${e instanceof Error ? e.message : String(e)}`])
    } finally {
      await load()
      setSyncBusy(false)
    }
  }

  const handleSubmit = async () => {
    try {
      const reason = form.reason || form.customReason
      if (!reason) {
        showAlert('반품/교환 사유를 입력해주세요', 'error')
        return
      }
      await returnApi.create({
        order_id: form.order_id,
        type: form.type,
        reason,
        quantity: form.quantity,
        requested_amount: form.requested_amount || undefined,
      })
      setShowForm(false)
      setForm({ order_id: '', type: 'return', reason: '', customReason: '', quantity: 1, requested_amount: 0 })
      load()
    } catch (e) {
      showAlert(e instanceof Error ? e.message : '저장 실패', 'error')
    }
  }

  const [rejectModal, setRejectModal] = useState<{ id: string; reason: string } | null>(null)
  const [locationModal, setLocationModal] = useState<{ id: string; value: string; address: string } | null>(null)
  const [addressModal, setAddressModal] = useState<{ region: string; address: string; phone: string; customer: string } | null>(null)

  const submitReject = async () => {
    if (!rejectModal || !rejectModal.reason.trim()) {
      showAlert('거절 사유를 입력해주세요', 'error')
      return
    }
    try {
      await returnApi.reject(rejectModal.id, rejectModal.reason)
      setRejectModal(null)
      load()
    } catch (e) { showAlert(e instanceof Error ? e.message : '거절 처리 실패', 'error') }
  }
  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) {
      showAlert('삭제할 항목을 선택해주세요', 'info')
      return
    }
    if (!await showConfirm(`${fmtNum(selectedIds.size)}건을 삭제하시겠습니까?`)) return
    let deleted = 0
    for (const id of selectedIds) {
      try {
        await returnApi.cancel(id)
        deleted++
      } catch (_e) { /* 무시 */ }
    }
    setSelectedIds(new Set())
    load()
    showAlert(`${fmtNum(deleted)}건 삭제 완료`, 'success')
  }

  // 교환/취소 액션
  const [exchangeActionItem, setExchangeActionItem] = useState<SambaReturn | null>(null)
  const [reshipStep, setReshipStep] = useState(false) // 교환재배송 송장 입력 단계
  const [reshipForm, setReshipForm] = useState({ tracking_number: '', shipping_company: '롯데택배' })

  const handleExchangeAction = async (r: SambaReturn, action: string, extra?: { tracking_number?: string; shipping_company?: string }) => {
    const orderNum = r.order_number || r.order_id
    if (!orderNum) { showAlert('주문번호가 없습니다', 'error'); return }
    const labels: Record<string, string> = { reship: '교환재배송', reject: '교환거부', convert_return: '반품변경' }
    if (!await showConfirm(`${orderNum} 주문을 ${labels[action]} 처리하시겠습니까?`)) return
    try {
      const order = await orderApi.findByOrderNumber(orderNum)
      if (!order) { showAlert('해당 주문을 찾을 수 없습니다', 'error'); return }
      const res = await orderApi.exchangeAction(order.id, action, undefined, extra)
      showAlert(res.message || `${labels[action]} 완료`, 'success')
      setExchangeActionItem(null)
      setReshipStep(false)
      setReshipForm({ tracking_number: '', shipping_company: '롯데택배' })
      load()
    } catch (e) { showAlert(e instanceof Error ? e.message : `${labels[action]} 실패`, 'error') }
  }


  // 주문번호 기준 중복 제거 — 같은 order_number 행은 하나만 남긴다.
  // 우선순위: ① 완료 상태(취소/반품/교환) 행을 우선 보존 — 완료 처리한 행이 사라지지 않도록.
  //          ② 사용자가 손댄 흔적(메모·비용·체크일·물품위치)이 많은 행 우선 —
  //             수정 내용이 새로고침 후에도 대표로 남아 보이도록.
  //          ③ 그래도 같으면 최신 접수건(return_request_date, 없으면 created_at).
  //          ④ 전부 동점이면 id 사전순 — 어떤 경우에도 항상 같은 행이 뽑히게(비결정성 제거).
  // 주문번호가 다르면 별개 건이므로 유지하고, 주문번호가 비어있는 행은 식별 불가하므로
  // 묶지 않고 각각 그대로 둔다.
  const dedupedReturns = useMemo(() => {
    const isDone = (r: SambaReturn) => ['취소', '반품', '교환'].includes(r.completion_detail || '')
    const tsOf = (r: SambaReturn) => {
      const t = new Date(r.return_request_date || r.created_at || 0).getTime()
      return Number.isNaN(t) ? 0 : t
    }
    // 사용자가 손댄 흔적 점수 — memo·고객비용·회사비용·체크일·물품위치 중 값이 있는 필드 수.
    // 단 memo 가 자동 기입값('취소요청')뿐이면 손댄 것으로 치지 않는다 —
    // 백엔드가 취소요청 INSERT 시 자동으로 넣는 값이라, 이걸 점수로 치면 사용자가
    // 메모를 지우거나 고쳐 저장한 행이 자동 기입 행에 다시 밀리는 문제가 재발한다.
    const editScore = (r: SambaReturn) => {
      const has = (v: string | undefined | null) => !!(v && String(v).trim())
      // '⚠️발주완료\n취소승인 금지' 도 백엔드 자동 기입 메모 — 손댄 것으로 치지 않는다
      const memoTouched = has(r.memo) && r.memo!.trim() !== '취소요청' && !isOrderPlacedWarnMemo(r.memo)
      return (memoTouched ? 1 : 0)
        + (has(r.customer_amount) ? 1 : 0)
        + (has(r.company_amount) ? 1 : 0)
        + (has(r.check_date) ? 1 : 0)
        + (has(r.product_location) ? 1 : 0)
    }
    // 새 행(cand)이 기존 행(cur)을 대체해야 하는지 — 4단계 모두 결정적 비교라
    // 서버 정렬 순서가 흔들려도 대표 행이 새로고침마다 바뀌지 않는다.
    const shouldReplace = (cand: SambaReturn, cur: SambaReturn) => {
      // ① 완료 상태인 쪽 우선 — 완료 처리한 이력이 대기 행에 가려지지 않게
      const candDone = isDone(cand), curDone = isDone(cur)
      if (candDone !== curDone) return candDone
      // ② 손댄 흔적 많은 쪽 우선 — 사용자가 수정한 행이 미수정(자동 기입) 행에 밀리지 않게
      const candScore = editScore(cand), curScore = editScore(cur)
      if (candScore !== curScore) return candScore > curScore
      // ③ 최신 접수건 우선 — 같은 주문의 재접수는 최신 건이 실상태
      const candTs = tsOf(cand), curTs = tsOf(cur)
      if (candTs !== curTs) return candTs > curTs
      // ④ 최종 tie-break: id 사전순(작은 쪽) — 완전 동점이어도 항상 같은 행 선택
      return cand.id < cur.id
    }
    const seen = new Map<string, number>() // order_number -> result 내 인덱스
    const result: ReturnRow[] = []
    for (const r of returns) {
      const key = (r.order_number || '').trim()
      if (!key) { result.push(r); continue } // 주문번호 없음 → 별개 유지
      const idx = seen.get(key)
      if (idx === undefined) {
        seen.set(key, result.length)
        result.push(r)
      } else if (shouldReplace(r, result[idx])) {
        result[idx] = r // 원래 위치 유지하며 교체
      }
    }
    return result
  }, [returns])

  // 화면 필터(완료내역/마켓/검색어) 적용 목록 — 렌더와 수익총액 계산에 공용
  const filteredReturns = dedupedReturns.filter(r => {
    // 주문번호 검색 중(다중 조회 또는 주문탭 딥링크 시드)엔 화면 필터 전부 무시 —
    // 입력한 주문번호에 해당하는 반품/교환은 무조건 전부 보여준다 (B2)
    if (orderNumberFilter.trim()) return true
    if (siteFilter && (r.completion_detail || COMPLETION_DEFAULT) !== siteFilter) return false
    if (marketFilter) {
      if (marketFilter.startsWith('type:')) {
        const mType = marketFilter.replace('type:', '')
        const mName = accounts.find(a => a.market_type === mType)?.market_name || ''
        if (mName && !r.market?.includes(mName)) return false
      } else if (marketFilter.startsWith('acc:')) {
        const accId = marketFilter.replace('acc:', '')
        const acc = accounts.find(a => a.id === accId)
        if (acc && !r.market?.includes(acc.market_name || '')) return false
      }
    }
    // 검색어 필터 (카테고리별 필드 기준, 대소문자 무시)
    // 다중 모드(요청 #9)에서는 건너뜀 — 검색 input 이 textarea 로 스왑돼 searchText 가
    // 화면에서 보이지 않는데 필터만 살아 있으면 서버가 내려준 다건 결과를 조용히 걸러냄.
    // state 는 지우지 않아 토글 OFF 시 원래 검색어 필터가 되살아난다.
    const q = multiMode ? '' : searchText.trim().toLowerCase()
    if (q) {
      const field =
        searchCategory === 'customer' ? r.customer_name :
        searchCategory === 'product' ? r.product_name :
        searchCategory === 'order_number' ? (r.order_number || r.order_id) :
        ''
      if (!(field || '').toLowerCase().includes(q)) return false
    }
    return true
  })

  // 체크된 주문번호 복사 — 왼쪽 체크박스로 고른 행의 주문번호만 줄바꿈으로 이어 복사.
  // [2026-09-04] 기존 '표시된 주문번호 전부 복사' + 세로 드래그 복사를 대체.
  // 드래그 방식은 표 구조(레코드당 2줄)와 브라우저 선택 동작이 맞지 않아 실사용에서
  // 동작하지 않았고, 표 전체 텍스트 선택까지 막는 부작용이 있어 걷어냈다.
  // 순서는 selectedIds(Set) 가 아니라 화면에 보이는 순서(filteredReturns)를 따른다.
  const copyCheckedOrderNumbers = async () => {
    if (selectedIds.size === 0) {
      showAlert('먼저 왼쪽 체크박스로 주문을 선택해주세요', 'info')
      return
    }
    const nums = filteredReturns
      .filter(r => selectedIds.has(r.id))
      .map(r => (r.order_number || '').trim())
      .filter(Boolean)
    if (nums.length === 0) {
      showAlert('선택한 건에 주문번호가 없습니다', 'info')
      return
    }
    try {
      await navigator.clipboard.writeText(nums.join('\n'))
      showAlert(`${fmtNum(nums.length)}건 복사됨`, 'success')
    } catch {
      showAlert('클립보드 복사에 실패했습니다', 'error')
    }
  }

  // ── 구획 분리 (T6·T9) — filteredReturns 를 급한 순서 6구획으로 분할 ──
  // classifyReturnSection 은 early-return 으로 어떤 행이든 정확히 한 구획 키를 반환하므로
  // 구획별 건수 합계 = filteredReturns.length 가 항상 성립(빠지거나 중복되는 행 없음).
  // 구획 내부 순서는 filteredReturns 순서(기존 정렬·최신순) 그대로 유지된다.
  // startIdx = 화면 행 번호(연속 번호) 시작값 — 접힘 여부와 무관하게 번호 고정.
  const sectionRows = (() => {
    const buckets: Record<ReturnSectionKey, ReturnRow[]> = {
      cancel_request: [], not_collected: [], collecting: [], return_done: [], exchange: [], etc: [],
    }
    for (const r of filteredReturns) buckets[classifyReturnSection(r)].push(r)
    let start = 0
    return RETURN_SECTIONS.map(def => {
      const rows = buckets[def.key]
      const item = { def, rows, startIdx: start }
      start += rows.length
      return item
    })
  })()

  // 수익총액 계산 (고객비용 - 회사비용) — 화면 필터 적용 목록 기준,
  // 완료내역 상태(대기/반품완료/교환완료) 무관하게 전체 합산.
  // 값은 콤마 포함 문자열("1,000")로 저장되므로 콤마 제거 후 숫자 변환 (B1).
  const totalProfit = filteredReturns
    .reduce((sum, r) => sum + (parseAmount(r.customer_amount) - parseAmount(r.company_amount)), 0)

  // completion_detail 기준 통계 — 중복 제거된 목록 기준
  const completionCounts = {
    total: dedupedReturns.length,
    requested: dedupedReturns.filter(r => (r.completion_detail || COMPLETION_DEFAULT) === '진행중').length,
    completed: dedupedReturns.filter(r => ['취소', '반품', '교환'].includes(r.completion_detail || '')).length,
    rejected: dedupedReturns.filter(r => (r.completion_detail || '') === '거부').length,
  }

  return (
    <div style={{ color: c.text }}>
      {/* 숫자 input 스피너 제거 */}
      <style>{`
        input[type=number]::-webkit-outer-spin-button,
        input[type=number]::-webkit-inner-spin-button {
          -webkit-appearance: none;
          margin: 0;
        }
        input[type=number] {
          -moz-appearance: textfield;
          appearance: textfield;
        }
      `}</style>
      {/* 관련 페이지 연결 */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginBottom: '0.25rem' }}>
        <a href="/samba/orders" style={{ fontSize: '0.75rem', color: c.textMuted, textDecoration: 'none' }}>← 주문</a>
        <a href="/samba/cs" style={{ fontSize: '0.75rem', color: c.link, textDecoration: 'none' }}>CS →</a>
      </div>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: c.text, marginBottom: '0.25rem' }}>반품교환</h2>
          <p style={{ fontSize: '0.875rem', color: c.textMuted }}>반품교환 요청을 관리</p>
        </div>
      </div>

      {/* 주문번호 필터 배너 — /returns?order_number=XXXX 진입 시 노출 */}
      {orderNumberFilter && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', background: 'rgba(255,140,0,0.08)', border: '1px solid rgba(255,140,0,0.3)', borderRadius: '8px', padding: '0.6rem 1rem', marginBottom: '1rem' }}>
          <span style={{ fontSize: '0.85rem', color: c.text }}>
            {(() => {
              // 다중 조회(요청 #9)면 번호 나열 대신 건수로 표시
              const n = orderNumberFilter.split(/[\s,]+/).filter(Boolean).length
              return n > 1
                ? <>주문 <strong style={{ color: c.text }}>{fmtNum(n)}건</strong> 관련 반품/교환만 표시 · 화면 필터 무시</>
                : <>주문 <strong style={{ color: c.text }}>{orderNumberFilter}</strong> 관련 반품/교환만 표시 · 화면 필터 무시</>
            })()}
          </span>
          <button
            onClick={clearOrderNumberFilter}
            style={{ ...btn('secondary', c), padding: '0.3rem 0.8rem', fontSize: '0.78rem' }}
          >전체보기</button>
        </div>
      )}

      {/* 통계 카드 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
        {[
          { key: 'total', label: '전체', color: c.text },
          { key: 'requested', label: '진행내역', color: c.warn },
          { key: 'completed', label: '완료됨', color: c.success },
          { key: 'rejected', label: '거절됨', color: c.danger },
        ].map(({ key, label, color }) => (
          <div key={key} style={{ ...makeCard(c), padding: '1rem 1.25rem' }}>
            <p style={{ fontSize: '0.75rem', color: c.textSub, marginBottom: '0.375rem' }}>{label}</p>
            <p style={{ fontSize: '1.5rem', fontWeight: 700, color }}>{fmtNum(completionCounts[key as keyof typeof completionCounts] ?? 0)}{key === 'requested' ? '건' : ''}</p>
          </div>
        ))}
        {/* 수익총액 통계 */}
        <div style={{ ...makeCard(c), padding: '1rem 1.25rem', border: `1px solid ${totalProfit >= 0 ? 'rgba(81,207,102,0.2)' : 'rgba(255,107,107,0.2)'}` }}>
          <p style={{ fontSize: '0.75rem', color: c.textSub, marginBottom: '0.375rem' }}>수익총액</p>
          <p style={{ fontSize: '1.25rem', fontWeight: 700, color: totalProfit >= 0 ? c.success : c.danger }}>₩{fmtNum(totalProfit)}</p>
        </div>
      </div>

      {/* 로그 영역 */}
      <div style={{ border: `1px solid ${c.borderStrong}`, borderRadius: '8px', overflow: 'hidden', marginBottom: '0.75rem' }}>
        <div style={{ padding: '6px 14px', background: c.headerBg, borderBottom: `1px solid ${c.borderStrong}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: c.headerText }}>반품교환 로그</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button onClick={() => navigator.clipboard.writeText(logMessages.join('\n'))} style={{ ...btn('ghost', c), fontSize: '0.72rem', padding: '1px 8px' }}>복사</button>
            <button onClick={() => setLogMessages(['[대기] 반품교환 가져오기 결과가 여기에 표시됩니다...'])} style={{ ...btn('ghost', c), fontSize: '0.72rem', padding: '1px 8px' }}>초기화</button>
          </div>
        </div>
        <div ref={logRef} style={{ height: '144px', overflowY: 'auto', padding: '8px 14px', fontFamily: "'Courier New', monospace", fontSize: '0.788rem', color: c.textMuted, background: c.surfaceAlt, lineHeight: 1.8 }}>
          {logMessages.map((msg, i) => <p key={i} style={{ color: c.textMuted, fontSize: 'inherit', margin: 0 }}>{fmtTextNumbers(msg)}</p>)}
        </div>
      </div>

      {/* 기간 필터 바 */}
      <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '10px', padding: '0.625rem 0.875rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.5rem' }}>
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
              style={{ padding: '0.22rem 0.55rem', borderRadius: '5px', fontSize: '0.75rem', background: period === pb.key ? c.btnSolidBg : c.btnBg, border: period === pb.key ? `1px solid ${c.border}` : `1px solid ${c.border}`, color: period === pb.key ? '#fff' : c.text, cursor: dateLocked ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap', opacity: dateLocked && period !== pb.key ? 0.5 : 1 }}
            >{pb.label}</button>
          ))}
          <span style={{ width: '1px', background: c.border, height: '18px', margin: '0 4px' }} />
          <input type="date" value={customStart} onChange={e => setCustomStart(e.target.value)} style={{ ...makeInputStyle(c), padding: '0.22rem 0.4rem', fontSize: '0.75rem', ...(startLocked ? { borderColor: c.danger, color: c.text } : {}) }} />
          <button onClick={() => setStartLocked(p => !p)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', background: startLocked ? c.danger : c.btnBg, border: startLocked ? `1px solid ${c.danger}` : `1px solid ${c.border}`, color: startLocked ? '#fff' : c.text }}>고정</button>
          <span style={{ color: c.textMuted, fontSize: '0.75rem' }}>~</span>
          <input type="date" value={customEnd} onChange={e => setCustomEnd(e.target.value)} style={{ ...makeInputStyle(c), padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} />
          <button onClick={() => setDateLocked(p => !p)} style={{ padding: '0.22rem 0.5rem', fontSize: '0.72rem', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap', background: dateLocked ? c.danger : c.btnBg, border: dateLocked ? `1px solid ${c.danger}` : `1px solid ${c.border}`, color: dateLocked ? '#fff' : c.text }}>고정</button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
          <select value={syncAccountId} onChange={e => setSyncAccountId(e.target.value)} style={{ ...makeInputStyle(c), padding: '0.22rem 0.4rem', fontSize: '0.72rem', minWidth: '200px' }}>
            <option value="">전체마켓보기</option>
            {(() => {
              const marketTypes = [...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()]
              return marketTypes.flatMap(([type, name]) => [
                <option key={`type:${type}`} value={`type:${type}`}>{name}</option>,
                ...accounts
                  .filter(a => a.market_type === type)
                  .map(a => <option key={a.id} value={a.id}>- {getAccountOptionLabel(a)}</option>),
              ])
            })()}
          </select>
          <button onClick={loadReturns} disabled={syncBusy} style={{ ...btn('primary', c), padding: '0.22rem 0.65rem', fontSize: '0.75rem', ...(syncBusy ? { opacity: 0.6, cursor: 'not-allowed' } : null) }}>{syncBusy ? '수집 중...' : '가져오기'}</button>
          {/* 회수상태 자동조회 (T4) — 반품/교환 건의 회수 송장을 택배사에 조회해 미수거/수거중/수거완료 자동 갱신 */}
          <button onClick={refreshCollectStatus} disabled={collectStatusBusy} title="회수 송장을 택배사에 조회해 미수거·수거중·수거완료 상태를 자동 갱신" style={{ ...btn('secondary', c), padding: '0.22rem 0.65rem', fontSize: '0.75rem', whiteSpace: 'nowrap', ...(collectStatusBusy ? { opacity: 0.6, cursor: 'not-allowed' } : null) }}>{collectStatusBusy ? '조회 중...' : '회수상태 자동조회'}</button>
        </div>
      </div>

      {/* 필터 바 */}
      <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '10px', padding: '0.75rem 1rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'nowrap' }}>
        {/* 다중 모드에서는 카테고리를 '주문번호'로 고정 + 비활성화 (주문탭과 동일 UX) */}
        <select style={{ ...makeInputStyle(c), width: '80px', padding: '0.22rem 0.4rem', fontSize: '0.75rem', opacity: multiMode ? 0.6 : 1 }} value={multiMode ? 'order_number' : searchCategory} onChange={e => setSearchCategory(e.target.value)} disabled={multiMode}>
          <option value="product">상품</option>
          <option value="customer">고객</option>
          <option value="order_number">주문번호</option>
        </select>
        {multiMode ? (
          // 다중 모드: 같은 자리에서 input → textarea 스왑, Enter=줄바꿈 · Ctrl/Cmd+Enter=조회
          <textarea
            rows={4}
            value={multiText}
            onChange={e => setMultiText(e.target.value)}
            onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') applyMultiSearch() }}
            placeholder={'주문번호 여러 건 붙여넣기\n(줄바꿈·쉼표로 구분, 최대 200건)'}
            title={'Enter=줄바꿈 · Ctrl/Cmd+Enter=조회'}
            style={{ ...makeInputStyle(c), width: '240px', padding: '0.22rem 0.4rem', fontSize: '0.75rem', lineHeight: 1.35, resize: 'vertical', verticalAlign: 'middle' }}
          />
        ) : (
          <input style={{ ...makeInputStyle(c), width: '140px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={searchText} onChange={e => setSearchText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }} placeholder="검색어 입력" />
        )}
        <button
          onClick={toggleMultiMode}
          title="여러 주문번호를 한 번에 조회 (줄바꿈·쉼표·공백 구분)"
          style={{ ...(multiMode ? btn('primary', c) : btn('ghost', c)), padding: '0.22rem 0.6rem', fontSize: '0.75rem' }}
        >다중</button>
        <button onClick={() => { if (multiMode) applyMultiSearch() /* 일반 모드 검색은 입력 즉시 목록에 반영됨 */ }} style={{ ...btn('secondary', c), padding: '0.22rem 0.75rem', fontSize: '0.75rem' }}>검색</button>
        <button
          onClick={handleBatchDelete}
          style={{ ...btn('danger', c), padding: '0.22rem 0.6rem', fontSize: '0.75rem' }}
        >
          선택삭제
        </button>
        {/* 선택 일괄 마감 (T7) — 체크박스로 고른 행들을 한 번에 마감 */}
        <button
          onClick={closeSelected}
          title="체크한 건들을 일괄 마감 — 마감된 건은 목록에서 숨겨집니다"
          style={{ ...btn('secondary', c), padding: '0.22rem 0.6rem', fontSize: '0.75rem', whiteSpace: 'nowrap' }}
        >선택 일괄 마감</button>
        {/* 마감 포함 보기 토글 (T7) — ON이면 include_closed=true 로 조회해 마감건도 흐리게 표시 */}
        <button
          onClick={toggleIncludeClosed}
          title="ON: 마감된 건도 흐리게 표시 (마감 해제 가능) · OFF: 마감건 숨김(기본)"
          style={{ ...(includeClosed ? btn('primary', c) : btn('ghost', c)), padding: '0.22rem 0.6rem', fontSize: '0.75rem', whiteSpace: 'nowrap' }}
        >마감 포함 보기</button>
        {/* 체크된 주문번호 복사 — 왼쪽 체크박스로 고른 행만 */}
        <button
          onClick={copyCheckedOrderNumbers}
          title="왼쪽 체크박스로 선택한 주문의 주문번호를 줄바꿈으로 이어 복사"
          style={{ ...btn('secondary', c), padding: '0.22rem 0.6rem', fontSize: '0.75rem', whiteSpace: 'nowrap' }}
        >체크된 주문번호 복사</button>
        <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', flexShrink: 0, alignItems: 'center' }}>
          <select style={{ ...makeInputStyle(c), width: '130px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={marketFilter} onChange={e => setMarketFilter(e.target.value)}>
            <option value="">전체마켓보기</option>
            {(() => {
              const marketTypes = [...new Map(accounts.map(a => [a.market_type, a.market_name])).entries()]
              return marketTypes.flatMap(([type, name]) => [
                <option key={`type:${type}`} value={`type:${type}`}>{name}</option>,
                ...accounts
                  .filter(a => a.market_type === type)
                  .map(a => <option key={`acc:${a.id}`} value={`acc:${a.id}`}>- {getAccountOptionLabel(a)}</option>),
              ])
            })()}
          </select>
          <select style={{ ...makeInputStyle(c), width: '110px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={siteFilter} onChange={e => setSiteFilter(e.target.value)}><option value="">전체내역</option>{COMPLETION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select>
          <select style={{ ...makeInputStyle(c), width: '92px', padding: '0.22rem 0.4rem', fontSize: '0.75rem' }} value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
            <option value={50}>50개 보기</option><option value={100}>100개 보기</option><option value={200}>200개 보기</option><option value={500}>500개 보기</option>
          </select>
        </div>
      </div>

      {/* 등록 폼 */}
      {showForm && (
        <div style={{ ...makeCard(c), padding: '1.5rem', marginBottom: '1rem' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>반품/교환 등록</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1rem' }}>
            <div>
              <label style={{ fontSize: '0.75rem', color: c.textSub, marginBottom: '0.375rem', display: 'block' }}>주문 ID</label>
              <input style={makeInputStyle(c)} value={form.order_id} onChange={(e) => setForm({ ...form, order_id: e.target.value })} />
            </div>
            <div>
              <label style={{ fontSize: '0.75rem', color: c.textSub, marginBottom: '0.375rem', display: 'block' }}>유형</label>
              <select style={makeInputStyle(c)} value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                <option value='return'>반품</option>
                <option value='exchange'>교환</option>
                <option value='cancel'>취소</option>
              </select>
            </div>
            {/* 반품사유 드롭다운 */}
            <div>
              <label style={{ fontSize: '0.75rem', color: c.textSub, marginBottom: '0.375rem', display: 'block' }}>사유 선택</label>
              <select
                style={makeInputStyle(c)}
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
              >
                {RETURN_REASONS.map(r => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
            </div>
            {/* 직접입력 시 텍스트 필드 */}
            <div>
              <label style={{ fontSize: '0.75rem', color: c.textSub, marginBottom: '0.375rem', display: 'block' }}>
                {form.reason ? '추가 상세 사유' : '사유 직접입력'}
              </label>
              <input
                style={makeInputStyle(c)}
                value={form.customReason}
                onChange={(e) => setForm({ ...form, customReason: e.target.value })}
                placeholder={form.reason ? '추가 설명 (선택)' : '반품/교환 사유를 입력하세요'}
              />
            </div>
            <div>
              <label style={{ fontSize: '0.75rem', color: c.textSub, marginBottom: '0.375rem', display: 'block' }}>수량</label>
              <input type='number' style={makeInputStyle(c)} value={form.quantity} onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })} />
            </div>
            <div>
              <label style={{ fontSize: '0.75rem', color: c.textSub, marginBottom: '0.375rem', display: 'block' }}>요청 금액</label>
              <input type='number' style={makeInputStyle(c)} value={form.requested_amount} onChange={(e) => setForm({ ...form, requested_amount: Number(e.target.value) })} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
            <button onClick={() => setShowForm(false)} style={{ ...btn('ghost', c), padding: '0.625rem 1.25rem', fontSize: '0.875rem' }}>취소</button>
            <button onClick={handleSubmit} style={{ ...btn('primary', c), padding: '0.625rem 1.25rem', fontSize: '0.875rem' }}>저장</button>
          </div>
        </div>
      )}

      {/* 테이블 */}
      <div style={makeCard(c)}>
        <div style={{ overflowX: 'auto' }}>
          {loading ? (
            <div style={{ padding: '3rem', textAlign: 'center', color: c.textMuted }}>로딩 중...</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ background: c.surfaceAlt, borderBottom: `1px solid ${c.border}` }}>
                  <th rowSpan={2} style={{ width: '36px', textAlign: 'center', padding: '0.3rem 0.5rem', verticalAlign: 'middle' }}>
                    <input
                      type="checkbox"
                      checked={dedupedReturns.length > 0 && selectedIds.size === dedupedReturns.length}
                      onChange={(e) => {
                        if (e.target.checked) setSelectedIds(new Set(dedupedReturns.map(r => r.id)))
                        else setSelectedIds(new Set())
                      }}
                      style={{ width: '13px', height: '13px', cursor: 'pointer', accentColor: c.primary }}
                    />
                  </th>
                  <th rowSpan={2} style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: c.textSub, fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap', verticalAlign: 'middle' }}>사진</th>
                  {/* 마켓 → 마켓/사업자 — 주문번호 열에서 뺀 사업자를 마켓 칸에 함께 표시 (T6) */}
                  {['고객', '마켓/사업자', '소싱주문번호'].map((h, i) => (
                    <th key={i} style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: c.textSub, fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                  {/* 주문번호 — 사업자(1줄)+주문번호(2줄) 자리를 합쳐 2줄 통합 열로 승격 (T5) */}
                  <th rowSpan={2} style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: c.textSub, fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap', verticalAlign: 'middle' }}>주문번호</th>
                  {['주문/CS접수일', '고객비용', '회사비용', '완료내역', '메모'].map((h, i) => (
                    <th key={i} style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: c.textSub, fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                  <th colSpan={2} style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: c.textSub, fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap' }}>고객주문</th>
                </tr>
                <tr style={{ background: c.surfaceAlt, borderBottom: `1px solid ${c.border}` }}>
                  {/* 체크날짜(T8)만 의미 설명 툴팁 — 마우스 올리면 이 칸의 용도가 보인다 */}
                  {['지역', '상품명', '고객전화번호', '상품위치', '반품신청한곳', '상태', '체크날짜'].map((h, i) => (
                    <th
                      key={i}
                      title={h === '체크날짜' ? '자동조회가 상태를 바꾸면 오늘 날짜가 찍힙니다. 오늘 날짜면 확인 안 하셔도 됩니다.' : undefined}
                      style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: c.textSub, fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap' }}
                    >{h}</th>
                  ))}
                  <th style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: c.textSub, fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap' }}>반품링크</th>
                  <th colSpan={2} style={{ textAlign: 'center', padding: '0.5rem 0.625rem', color: c.textSub, fontWeight: 500, fontSize: '0.75rem', whiteSpace: 'nowrap' }}>원주문</th>
                </tr>
              </thead>
              {/* 한 반품건 = tr 2줄 세트. Fragment 대신 건별 <tbody>로 묶고 tbody에 hover 클래스를
                  붙여 마우스가 어느 줄에 있든 두 줄이 함께 강조되게 한다.
                  (table의 다중 tbody는 HTML상 유효, 렌더 결과·레이아웃 동일) */}
              {/* 구획 루프 (T6) — 각 구획: 중제목 행(별도 tbody, 표 2줄 구조 불침범) + 반품건들.
                  건수 0 구획은 중제목 행도 렌더하지 않는다. 접힌 구획은 중제목만 남긴다. */}
              {sectionRows.map(({ def, rows, startIdx }) => rows.length === 0 ? null : (
                <Fragment key={def.key}>
                  <tbody>
                    <tr
                      onClick={() => toggleSection(def.key)}
                      title={collapsedSections[def.key] ? '클릭하여 펼치기' : '클릭하여 접기'}
                      style={{ cursor: 'pointer', background: def.bg, borderTop: `1px solid ${c.border}`, borderBottom: `1px solid ${c.border}` }}
                    >
                      <td colSpan={13} style={{ padding: '0.4rem 0.75rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                          {/* 왼쪽 4px 색 막대 */}
                          <span style={{ width: '4px', height: '16px', background: def.fg, borderRadius: '2px', flexShrink: 0 }} />
                          <span style={{ fontSize: '0.8rem', fontWeight: 700, color: def.fg, whiteSpace: 'nowrap' }}>{def.label}</span>
                          {/* 건수 뱃지 */}
                          <span style={{ fontSize: '0.72rem', fontWeight: 600, color: def.fg, background: c.surface, border: `1px solid ${c.border}`, borderRadius: '999px', padding: '0 0.45rem', whiteSpace: 'nowrap' }}>{fmtNum(rows.length)}건</span>
                          {/* 오른쪽 흐린 안내문구 + 접힘 표시 */}
                          <span style={{ fontSize: '0.7rem', color: c.textMuted, marginLeft: 'auto', whiteSpace: 'nowrap' }}>{def.hint}</span>
                          <span style={{ fontSize: '0.7rem', color: c.textMuted, whiteSpace: 'nowrap' }}>{collapsedSections[def.key] ? '▸ 펼치기' : '▾'}</span>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                  {!collapsedSections[def.key] && rows.map((r, i) => {
                  const idx = startIdx + i
                  return (
                    // 마감된 행(T7)은 흐리게 — '마감 포함 보기' ON일 때만 목록에 존재
                    <tbody key={r.id} className="samba-row-hover" style={r.closed_at ? { opacity: 0.55 } : undefined}>
                      <tr>
                        <td rowSpan={2} style={{ width: '36px', textAlign: 'center', padding: '0.5rem', verticalAlign: 'middle' }}>
                          <div style={{ fontSize: '0.675rem', color: c.textMuted, marginBottom: '2px' }}>{idx + 1}</div>
                          <input
                            type="checkbox"
                            checked={selectedIds.has(r.id)}
                            onChange={(e) => {
                              const next = new Set(selectedIds)
                              if (e.target.checked) next.add(r.id)
                              else next.delete(r.id)
                              setSelectedIds(next)
                            }}
                            style={{ width: '13px', height: '13px', cursor: 'pointer', accentColor: c.primary }}
                          />
                        </td>
                        <td rowSpan={2} style={{ padding: '0.625rem 0.5rem', textAlign: 'center', verticalAlign: 'middle' }}>
                        {(() => {
                          const ordNo = r.order_number || r.order_id
                          const goOrder = () => { if (ordNo) window.open(`/samba/orders?search=${encodeURIComponent(ordNo)}&search_type=order_number`, '_blank') }
                          return r.product_image ? (
                            <img
                              src={r.product_image}
                              alt=""
                              onClick={goOrder}
                              title="주문관리에서 이 주문 보기 (새 탭)"
                              style={{ width: '60px', height: '60px', objectFit: 'cover', borderRadius: '6px', border: `1px solid ${c.border}`, cursor: ordNo ? 'pointer' : 'default', display: 'block', margin: '0 auto' }}
                            />
                          ) : (
                            <div
                              onClick={goOrder}
                              title="주문관리에서 이 주문 보기 (새 탭)"
                              style={{ width: '60px', height: '60px', background: c.surfaceAlt, borderRadius: '6px', border: `1px solid ${c.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: ordNo ? c.textSub : c.textMuted, fontSize: '0.625rem', cursor: ordNo ? 'pointer' : 'default', margin: '0 auto' }}
                            >
                              No IMG
                            </div>
                          )
                        })()}
                      </td>
                      <td style={{ ...tdCenter, maxWidth: '64px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.customer_name || ''}>{r.customer_name || '-'}</td>
                      {/* 마켓/사업자 — 마켓명 아래 사업자를 흐린 작은 글씨로 (T6) */}
                      <td style={{ ...tdCenter, maxWidth: '70px', overflow: 'hidden' }} title={`${r.market || '-'}${r.business_name ? ` / ${r.business_name}` : ''}`}>
                        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.market || '-'}</div>
                        {r.business_name ? (
                          <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.68rem', color: c.textMuted }}>{r.business_name}</div>
                        ) : null}
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.25rem' }}>
                          <input
                            type="text"
                            value={r.sourcing_order_no ?? ''}
                            placeholder="소싱주문번호"
                            onFocus={(e) => { cellEditRef.current[`sourcing_order_no:${r.id}`] = e.target.value }}
                            onChange={(e) => {
                              const val = e.target.value
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, sourcing_order_no: val } : x))
                            }}
                            onBlur={(e) => {
                              const val = e.target.value
                              const prevVal = cellEditRef.current[`sourcing_order_no:${r.id}`] ?? ''
                              if (val === prevVal) return
                              saveCell(r.id, { sourcing_order_no: val }, () => {
                                setReturns(prev => prev.map(x => x.id === r.id ? { ...x, sourcing_order_no: prevVal } : x))
                              }, '소싱주문번호')
                            }}
                            style={{ width: '110px', padding: '0.3rem 0.5rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, fontSize: '0.8rem', textAlign: 'center' }}
                          />
                        </div>
                      </td>
                      {/* 주문번호 — 사업자(1줄)+주문번호(2줄) 자리를 합친 2줄 통합 셀 (T5) */}
                      <td
                        rowSpan={2}
                        style={{ ...tdCenter, maxWidth: '90px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={r.order_number || ''}
                      >{r.order_number || '-'}</td>
                      <td style={{ ...tdCenter, color: c.textMuted }}>
                        <div style={{ fontSize: '0.7rem', whiteSpace: 'nowrap' }}>
                          주문 {fmtMD(r.order_date)} · 접수 {fmtMD(r.return_request_date || r.created_at)}
                        </div>
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <input
                          type="text"
                          value={formatAmountInput(r.customer_amount || '')}
                          placeholder=""
                          onFocus={(e) => { cellEditRef.current[`customer_amount:${r.id}`] = e.target.value }}
                          onChange={(e) => {
                            // 숫자만 입력 시 세자리 콤마 자동 포맷, 글자 섞이면 그대로(메모) (B1)
                            const val = formatAmountInput(e.target.value)
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, customer_amount: val } : x))
                          }}
                          onBlur={(e) => {
                            const val = e.target.value
                            const prevVal = cellEditRef.current[`customer_amount:${r.id}`] ?? ''
                            if (val === prevVal) return
                            saveCell(r.id, { customer_amount: val }, () => {
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, customer_amount: prevVal } : x))
                            }, '고객')
                          }}
                          style={{ width: '80px', padding: '0.3rem 0.5rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, fontSize: '0.8rem', textAlign: 'right' }}
                        />
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <input
                          type="text"
                          value={formatAmountInput(r.company_amount || '')}
                          placeholder=""
                          onFocus={(e) => { cellEditRef.current[`company_amount:${r.id}`] = e.target.value }}
                          onChange={(e) => {
                            // 숫자만 입력 시 세자리 콤마 자동 포맷, 글자 섞이면 그대로(메모) (B1)
                            const val = formatAmountInput(e.target.value)
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, company_amount: val } : x))
                          }}
                          onBlur={(e) => {
                            const val = e.target.value
                            const prevVal = cellEditRef.current[`company_amount:${r.id}`] ?? ''
                            if (val === prevVal) return
                            saveCell(r.id, { company_amount: val }, () => {
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, company_amount: prevVal } : x))
                            }, '회사')
                          }}
                          style={{ width: '80px', padding: '0.3rem 0.5rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, fontSize: '0.8rem', textAlign: 'right' }}
                        />
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        {(() => {
                          const cd = r.completion_detail || COMPLETION_DEFAULT
                          const cc = COMPLETION_COLORS[cd]
                          return (
                        <select
                          value={cd}
                          onChange={async (e) => {
                            const val = e.target.value
                            if (val === '반품') {
                              // 요청 #2: '반품완료' 선택 시 고객주문·원주문도 자동 '완료' (취소완료·교환완료는 미적용)
                              // 역방향(완료→진행중 등)은 자동으로 되돌리지 않음 — 사장님이 수동 조정한 값 보호
                              const prevVals = {
                                completion_detail: r.completion_detail,
                                customer_order_no: r.customer_order_no,
                                original_order_no: r.original_order_no,
                              }
                              setReturns(prev => prev.map(x => x.id === r.id
                                ? { ...x, completion_detail: val, customer_order_no: 'return_complete', original_order_no: 'return_complete' }
                                : x))
                              // 3필드를 PATCH 1회로 전송 — 실패 시 로컬 state가 서버와 어긋나므로 알림 + 직전 값 복원 (saveCell 패턴)
                              saveCell(r.id, { completion_detail: val, customer_order_no: 'return_complete', original_order_no: 'return_complete' }, () => {
                                setReturns(prev => prev.map(x => x.id === r.id ? { ...x, ...prevVals } : x))
                              }, '완료내역')
                              return
                            }
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, completion_detail: val } : x))
                            try {
                              await returnApi.patch(r.id, { completion_detail: val })
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ padding: '0.2rem 0.3rem', background: cc?.bg || c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: cc?.fg || c.text, fontSize: '0.75rem', fontWeight: 600, cursor: 'pointer', outline: 'none' }}
                        >
                          {COMPLETION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                          )
                        })()}
                        {/* 마감 (T7) — 열을 새로 만들지 않고 완료내역 셀 안에 작은 버튼으로.
                            마감된 행(마감 포함 보기 ON)은 [마감] 뱃지 + [마감 해제] 버튼으로 전환 */}
                        {r.closed_at ? (
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.25rem', marginTop: '0.25rem' }}>
                            <span style={{ fontSize: '0.65rem', fontWeight: 700, color: c.textSub, border: `1px solid ${c.border}`, borderRadius: '4px', padding: '0 0.3rem', whiteSpace: 'nowrap' }}>마감</span>
                            <button
                              onClick={() => reopenReturns([r.id])}
                              title="마감을 해제해 목록에 다시 표시"
                              style={{ ...btn('ghost', c), fontSize: '0.65rem', padding: '0 0.35rem', whiteSpace: 'nowrap' }}
                            >마감 해제</button>
                          </div>
                        ) : (
                          <button
                            onClick={() => closeOne(r)}
                            title="이 건을 마감(종결) — 목록에서 숨깁니다 ('마감 포함 보기'로 재확인 가능)"
                            style={{ ...btn('ghost', c), fontSize: '0.65rem', padding: '0 0.35rem', whiteSpace: 'nowrap', display: 'block', margin: '0.25rem auto 0' }}
                          >마감</button>
                        )}
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        {(() => {
                          // 메모 두 줄 표시 (T6) — 백엔드가 "⚠️발주완료\n취소승인 금지" 처럼
                          // 줄바꿈 포함 메모를 저장하므로 input → textarea 로 교체(편집 동작은 동일).
                          // 경고 메모면 셀 배경을 옅은 빨강으로 강조.
                          const warn = isOrderPlacedWarnMemo(r.memo)
                          const lineCount = (r.memo || '').split('\n').length
                          return (
                            <textarea
                              value={r.memo || ''}
                              placeholder=""
                              rows={Math.min(Math.max(lineCount, 1), 3)}
                              onChange={(e) => {
                                const val = e.target.value
                                setReturns(prev => prev.map(x => x.id === r.id ? { ...x, memo: val } : x))
                              }}
                              onBlur={async (e) => {
                                try {
                                  await returnApi.patch(r.id, { memo: e.target.value })
                                } catch (_e) { /* 무시 */ }
                              }}
                              style={{ width: '100px', padding: '0.3rem 0.5rem', background: warn ? 'rgba(255,107,107,0.15)' : c.inputBg, border: `1px solid ${warn ? c.danger : c.border}`, borderRadius: '4px', color: warn ? c.danger : c.text, fontSize: '0.8rem', fontWeight: warn ? 600 : 400, textAlign: 'center', resize: 'none', overflow: 'hidden', lineHeight: 1.3, verticalAlign: 'middle', fontFamily: 'inherit', display: 'block', margin: '0 auto' }}
                            />
                          )
                        })()}
                      </td>
                      <td colSpan={2} style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select
                          value={r.customer_order_no || 'return_incomplete'}
                          onChange={async (e) => {
                            const val = e.target.value
                            try {
                              await returnApi.patch(r.id, { customer_order_no: val })
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, customer_order_no: val } : x))
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ display: 'block', margin: '0 auto', width: '90px', padding: '0.2rem 0.3rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, fontSize: '0.75rem', textAlign: 'center', textAlignLast: 'center', cursor: 'pointer', outline: 'none' }}
                        >
                          <option value="return_incomplete">미완료</option>
                          <option value="return_complete">완료</option>
                        </select>
                      </td>
                      </tr>
                      <tr style={{ borderBottom: `1px solid ${c.border}` }}>
                      <td style={{ ...tdCenter, maxWidth: '64px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {r.region ? (
                          <span
                            onClick={() => setAddressModal({ region: r.region || '', address: r.customer_address || '', phone: r.customer_phone || '', customer: r.customer_name || '' })}
                            style={{ color: c.text, cursor: 'pointer', textDecoration: 'underline', textDecorationColor: c.border, textUnderlineOffset: '3px' }}
                            title={r.customer_address || '주소 정보 없음'}
                          >{r.region}</span>
                        ) : '-'}
                      </td>
                      <td style={{ ...tdCenter, maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.product_name || '-'}</td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <input
                          type="text"
                          value={r.customer_phone_manual ?? r.customer_phone ?? ''}
                          placeholder=""
                          onFocus={(e) => { cellEditRef.current[`customer_phone_manual:${r.id}`] = e.target.value }}
                          onChange={(e) => {
                            const val = e.target.value
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, customer_phone_manual: val } : x))
                          }}
                          onBlur={(e) => {
                            const val = e.target.value
                            const prevVal = cellEditRef.current[`customer_phone_manual:${r.id}`] ?? ''
                            if (val === prevVal) return
                            saveCell(r.id, { customer_phone_manual: val }, () => {
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, customer_phone_manual: prevVal } : x))
                            }, '고객전화번호')
                          }}
                          style={{ width: '110px', padding: '0.3rem 0.5rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, fontSize: '0.8rem', textAlign: 'center' }}
                        />
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select
                          value={r.product_location || '고객'}
                          onChange={async (e) => {
                            const val = e.target.value
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, product_location: val } : x))
                            try {
                              await returnApi.patch(r.id, { product_location: val })
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ padding: '0.2rem 0.3rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, fontSize: '0.75rem', cursor: 'pointer', outline: 'none' }}
                        >
                          <option value="고객">고객</option>
                          <option value="사무실">사무실</option>
                          <option value="원주문">원주문</option>
                          <option value="배송미완료">배송미완료</option>
                        </select>
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select value={r.return_source || '원주문'} onChange={async (e) => {
                          try {
                            await returnApi.patch(r.id, { return_source: e.target.value })
                            load()  // 목록만 재로드 — 구코드는 loadReturns()로 전체 마켓 sweep을 유발했음
                          } catch {}
                        }} style={{ fontSize: '0.72rem', padding: '2px 4px', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, cursor: 'pointer' }}>
                          <option value="원주문">원주문</option>
                          <option value="홈픽">홈픽</option>
                          <option value="자동회수">자동회수</option>
                        </select>
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select
                          value={r.status}
                          onChange={async (e) => {
                            const val = e.target.value
                            try {
                              await returnApi.patch(r.id, { status: val })
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, status: val } : x))
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ padding: '0.2rem 0.3rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, fontSize: '0.75rem', cursor: 'pointer', outline: 'none' }}
                        >
                          <option value="not_collected">미수거</option>
                          <option value="collecting">수거중</option>
                          <option value="collected">수거완료</option>
                        </select>
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        {/* 체크날짜 (T8) — "안 봐도 되는 건" 표시기.
                            자동조회가 상태를 바꾸면 오늘 날짜가 찍힌다 → 오늘 날짜(초록) = 확인 불필요,
                            과거 날짜(흐림 + N일 전) = 다시 봐야 하는 건.
                            셀 클릭 = 즉시 오늘 날짜 저장(피커 없음), 다른 날짜는 옆 📅 아이콘으로 기존 피커. */}
                        {(() => {
                          // 오늘/저장값 모두 로컬(KST) 기준 YYYY-MM-DD 로 비교 ('sv-SE' 로케일 트릭)
                          const todayStr = new Date().toLocaleDateString('sv-SE')
                          const ckStr = (() => {
                            if (!r.check_date) return ''
                            const d = new Date(r.check_date)
                            return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('sv-SE')
                          })()
                          const isToday = ckStr !== '' && ckStr === todayStr
                          // 과거면 며칠 지났는지 — 로컬 자정 기준 일수 차이
                          const daysAgo = ckStr ? Math.max(0, Math.round((new Date(todayStr).getTime() - new Date(ckStr).getTime()) / 86400000)) : 0
                          const saveToday = () => {
                            // 셀 클릭 = 즉시 오늘로 체크 — 기존 저장 경로(returnApi.patch check_date) 그대로
                            const prevVal = r.check_date
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, check_date: todayStr } : x))
                            saveCell(r.id, { check_date: todayStr }, () => {
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, check_date: prevVal } : x))
                            }, '체크날짜')
                          }
                          return (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.2rem' }}>
                              <div
                                onClick={saveToday}
                                title="클릭 = 오늘 날짜로 체크 (확인 완료 표시)"
                                style={{ cursor: 'pointer', fontSize: '0.8rem', minWidth: '40px', color: isToday ? c.success : (ckStr ? c.textMuted : c.textMuted), fontWeight: isToday ? 700 : 400, opacity: ckStr && !isToday ? 0.75 : 1, whiteSpace: 'nowrap' }}
                              >
                                {fmtMD(r.check_date)}
                                {ckStr && !isToday && (
                                  <span style={{ fontSize: '0.62rem', color: c.textMuted, marginLeft: '2px' }}>{fmtNum(daysAgo)}일 전</span>
                                )}
                              </div>
                              {/* 다른 날짜가 필요할 때 — 기존 date picker 열기 */}
                              <span
                                onClick={() => {
                                  const inp = document.getElementById(`ck-${r.id}`) as HTMLInputElement
                                  if (!inp) return
                                  // 피커가 항상 "오늘" 기준으로 열리도록 showPicker 직전에 DOM 값을 비운다 (요청 #1).
                                  // - React value tracker는 직전 prop 값을 기억 → 날짜 선택 시 ''→'YYYY-MM-DD' 변화로 onChange 정상 발화
                                  // - ESC 취소 시 DOM 값만 ''로 남지만, 화면 표시는 옆 div의 fmtMD(state 기반)라 깨지지 않음
                                  inp.value = ''
                                  inp.showPicker?.()
                                }}
                                title="다른 날짜 선택"
                                style={{ cursor: 'pointer', fontSize: '0.72rem', lineHeight: 1 }}
                              >📅</span>
                            </div>
                          )
                        })()}
                        <input
                          id={`ck-${r.id}`}
                          type="date"
                          // check_date 는 UTC 저장(KST 자정 = 전날 15:00Z) — 문자열 slice(0,10)는
                          // 하루 이른 날짜가 되므로 로컬(KST) 기준 YYYY-MM-DD 로 변환해 넣는다.
                          // 잘못된 날짜 문자열이면 빈 값. ('sv-SE' 로케일 = 로컬 기준 YYYY-MM-DD 포맷)
                          value={(() => {
                            if (!r.check_date) return ''
                            const d = new Date(r.check_date)
                            return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('sv-SE')
                          })()}
                          onChange={async (e) => {
                            const val = e.target.value
                            setReturns(prev => prev.map(x => x.id === r.id ? { ...x, check_date: val } : x))
                            try {
                              await returnApi.patch(r.id, { check_date: val || '' })
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ width: 0, height: 0, opacity: 0, position: 'absolute', pointerEvents: 'none' }}
                        />
                      </td>
                      <td style={{ ...tdCenter, padding: '0.375rem' }}>
                        {(r.return_link_manual || r.return_link) ? (
                          <span
                            onClick={() => window.open((r.return_link_manual || r.return_link) as string, '_blank')}
                            title={r.return_link_manual || r.return_link || ''}
                            style={{ color: c.link, cursor: 'pointer', textDecoration: 'underline', fontSize: '0.8rem' }}
                          >링크</span>
                        ) : '-'}
                      </td>
                      <td colSpan={2} style={{ ...tdCenter, padding: '0.375rem' }}>
                        <select
                          value={r.original_order_no || 'return_incomplete'}
                          onChange={async (e) => {
                            const val = e.target.value
                            try {
                              await returnApi.patch(r.id, { original_order_no: val })
                              setReturns(prev => prev.map(x => x.id === r.id ? { ...x, original_order_no: val } : x))
                            } catch (_e) { /* 무시 */ }
                          }}
                          style={{ display: 'block', margin: '0 auto', width: '90px', padding: '0.2rem 0.3rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, fontSize: '0.75rem', textAlign: 'center', textAlignLast: 'center', cursor: 'pointer', outline: 'none' }}
                        >
                          <option value="return_incomplete">미완료</option>
                          <option value="return_complete">완료</option>
                        </select>
                      </td>
                      </tr>
                    </tbody>
                  )
                  })}
                </Fragment>
              ))}
              {dedupedReturns.length === 0 && (
                // 전체 열 수 = 13 (체크박스+사진+주문번호 rowSpan 3 + 윗줄 8 + 고객주문 colSpan 2)
                // — 사업자 열 제거·주문번호 통합(T5)은 같은 열 자리를 합친 것이라 열 수 불변
                <tbody><tr><td colSpan={13} style={{ padding: '3rem', textAlign: 'center', color: c.textMuted }}>반품/교환 내역이 없습니다</td></tr></tbody>
              )}
            </table>
          )}
        </div>
      </div>

      {/* 거절 사유 입력 모달 */}
      {rejectModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '16px', padding: '2rem', width: '400px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: c.text, marginBottom: '1rem' }}>거절 사유 입력</h3>
            <input
              style={makeInputStyle(c)}
              placeholder="거절 사유를 입력하세요"
              value={rejectModal.reason}
              onChange={e => setRejectModal({ ...rejectModal, reason: e.target.value })}
              onKeyDown={e => e.key === 'Enter' && submitReject()}
              autoFocus
            />
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button onClick={() => setRejectModal(null)} style={{ ...btn('ghost', c), padding: '0.625rem 1.25rem', fontSize: '0.875rem' }}>취소</button>
              <button onClick={submitReject} style={{ ...btn('dangerSolid', c), padding: '0.625rem 1.25rem', fontSize: '0.875rem' }}>거절</button>
            </div>
          </div>
        </div>
      )}

{/* 고객 주소 보기 모달 */}
      {addressModal && (
        <div onClick={() => setAddressModal(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div onClick={e => e.stopPropagation()} style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '16px', padding: '1.75rem', width: '460px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: c.text, marginBottom: '1rem' }}>고객 주소</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', marginBottom: '1.25rem' }}>
              {addressModal.customer && (
                <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <span style={{ color: c.textSub, minWidth: '64px' }}>고객명</span>
                  <span style={{ color: c.text }}>{addressModal.customer}</span>
                </div>
              )}
              {addressModal.phone && (
                <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.85rem' }}>
                  <span style={{ color: c.textSub, minWidth: '64px' }}>전화</span>
                  <span style={{ color: c.text }}>{addressModal.phone}</span>
                </div>
              )}
              <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.85rem' }}>
                <span style={{ color: c.textSub, minWidth: '64px' }}>지역</span>
                <span style={{ color: c.text }}>{addressModal.region || '-'}</span>
              </div>
              <div style={{ padding: '0.75rem', background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: '8px', fontSize: '0.85rem', color: c.text, lineHeight: 1.5 }}>
                <div style={{ color: c.textSub, fontSize: '0.72rem', marginBottom: '0.25rem' }}>전체 주소</div>
                {addressModal.address || '주소 정보 없음'}
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
              {addressModal.address && (
                <button onClick={() => { navigator.clipboard.writeText(addressModal.address); showAlert('주소가 복사되었습니다', 'success') }} style={{ ...btn('secondary', c), padding: '0.55rem 1.1rem', fontSize: '0.85rem' }}>복사</button>
              )}
              <button onClick={() => setAddressModal(null)} style={{ ...btn('ghost', c), padding: '0.55rem 1.1rem', fontSize: '0.85rem' }}>닫기</button>
            </div>
          </div>
        </div>
      )}

      {/* 상품위치 수정 모달 */}      {locationModal && (        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '16px', padding: '2rem', width: '420px', maxWidth: '90vw' }}>            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: c.text, marginBottom: '1rem' }}>상품위치 수정</h3>            {locationModal.address && (              <div style={{ padding: '0.75rem', background: c.surfaceAlt, border: `1px solid ${c.border}`, borderRadius: '8px', marginBottom: '1rem', fontSize: '0.85rem', color: c.text, lineHeight: 1.5 }}>                <span style={{ color: c.textMuted, fontSize: '0.75rem' }}>전체 주소</span><br/>                {locationModal.address}              </div>            )}            <input style={makeInputStyle(c)} placeholder="시/군/구 입력" value={locationModal.value} onChange={e => setLocationModal({ ...locationModal, value: e.target.value })} onKeyDown={async e => { if (e.key === 'Enter') { const val = locationModal.value.trim(); setReturns(prev => prev.map(x => x.id === locationModal.id ? { ...x, product_location: val } : x)); try { await returnApi.patch(locationModal.id, { product_location: val }) } catch (_e) { /* */ } setLocationModal(null) } }} autoFocus />            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '1rem' }}>              <button onClick={() => setLocationModal(null)} style={{ ...btn('ghost', c), padding: '0.625rem 1.25rem', fontSize: '0.875rem' }}>취소</button>              <button onClick={async () => { const val = locationModal.value.trim(); setReturns(prev => prev.map(x => x.id === locationModal.id ? { ...x, product_location: val } : x)); try { await returnApi.patch(locationModal.id, { product_location: val }) } catch (_e) { /* */ } setLocationModal(null) }} style={{ ...btn('primary', c), padding: '0.625rem 1.25rem', fontSize: '0.875rem' }}>저장</button>            </div>          </div>        </div>      )}
      {/* 교환 액션 선택 모달 */}
      {exchangeActionItem && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '16px', padding: '2rem', width: '380px', maxWidth: '90vw' }}>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 700, color: c.text, marginBottom: '0.5rem' }}>교환요청 처리</h3>
            <p style={{ fontSize: '0.8125rem', color: c.textMuted, marginBottom: '1.5rem' }}>주문번호: {exchangeActionItem.order_number || exchangeActionItem.order_id || '-'}</p>
            {!reshipStep ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <button onClick={() => setReshipStep(true)} style={{ ...btn('primary', c), padding: '0.75rem', fontSize: '0.875rem' }}>교환재배송</button>
                <button onClick={() => handleExchangeAction(exchangeActionItem, 'convert_return')} style={{ ...btn('secondary', c), padding: '0.75rem', fontSize: '0.875rem' }}>반품변경</button>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <p style={{ fontSize: '0.8125rem', color: c.textSub, margin: 0 }}>재배송 송장 정보를 입력하세요 (롯데ON 필수)</p>
                <select
                  value={reshipForm.shipping_company}
                  onChange={e => setReshipForm(f => ({ ...f, shipping_company: e.target.value }))}
                  style={{ padding: '0.5rem 0.75rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '8px', color: c.text, fontSize: '0.875rem' }}
                >
                  {['CJ대한통운','한진택배','롯데택배','로젠택배','우체국택배','경동택배','대신택배','일양로지스','딜리박스'].map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <input
                  placeholder="송장번호 입력"
                  value={reshipForm.tracking_number}
                  onChange={e => setReshipForm(f => ({ ...f, tracking_number: e.target.value }))}
                  style={{ padding: '0.5rem 0.75rem', background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '8px', color: c.text, fontSize: '0.875rem' }}
                />
                <button
                  onClick={() => handleExchangeAction(exchangeActionItem, 'reship', { tracking_number: reshipForm.tracking_number, shipping_company: reshipForm.shipping_company })}
                  style={{ ...btn('primary', c), padding: '0.75rem', fontSize: '0.875rem' }}
                >재배송 처리</button>
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button
                onClick={() => { setExchangeActionItem(null); setReshipStep(false); setReshipForm({ tracking_number: '', shipping_company: '롯데택배' }) }}
                style={{ ...btn('ghost', c), padding: '0.625rem 1.25rem', fontSize: '0.875rem' }}
              >닫기</button>
            </div>
          </div>
        </div>
      )}

      <ReturnDetailModal detailItem={detailItem} onClose={() => setDetailItem(null)} />
    </div>
  )
}
