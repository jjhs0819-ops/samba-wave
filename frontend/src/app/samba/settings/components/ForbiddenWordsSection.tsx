'use client'

import { Dispatch, SetStateAction, useCallback, useEffect, useState } from 'react'
import { card, fmtNum } from '@/lib/samba/styles'
import { forbiddenApi, type SambaForbiddenWord } from '@/lib/samba/api/commerce'
import { MARKETS } from '@/lib/samba/markets'
import { showAlert } from '@/components/samba/Modal'
import { useTheme } from '@/lib/samba/useTheme'
import { btn } from '@/lib/samba/buttons'

interface Props {
  // 아래 텍스트/세터 props 는 레거시 호환용 — 본 섹션은 마켓별 상태를 자체 관리한다.
  forbiddenText?: string
  deletionText?: string
  optionDeletionText?: string
  wordsSaving?: boolean
  setForbiddenText?: (v: string) => void
  setDeletionText?: (v: string) => void
  setOptionDeletionText?: (v: string) => void
  setWordsSaving?: (v: boolean) => void
  setInitialForbiddenText?: (v: string) => void
  setInitialDeletionText?: (v: string) => void
  setInitialOptionDeletionText?: (v: string) => void
  tagBanned: { rejected: string[]; brands: string[]; source_sites: string[] }
  setTagBanned: Dispatch<SetStateAction<{ rejected: string[]; brands: string[]; source_sites: string[] }>>
}

// 공통 + 전송 대상 마켓(카테고리 전용 제외)
const MARKET_OPTIONS: { value: string; label: string }[] = [
  { value: 'common', label: '공통 (모든 마켓)' },
  ...MARKETS.filter(m => !m.categoryOnly).map(m => ({ value: m.id, label: m.label })),
]

// 미적용 선택용 — 판매처(마켓, 카테고리 전용 제외)
const EXEMPT_MARKET_OPTIONS: { value: string; label: string }[] =
  MARKETS.filter(m => !m.categoryOnly).map(m => ({ value: m.id, label: m.label }))

// 미적용 선택용 — 소싱처(확장앱 source_site 표준값과 동일)
const SOURCE_SITE_OPTIONS: { value: string; label: string }[] = [
  { value: 'MUSINSA', label: '무신사' },
  { value: 'SSG', label: 'SSG' },
  { value: 'LOTTEON', label: '롯데ON' },
  { value: 'GSShop', label: 'GS샵' },
  { value: 'ABCmart', label: 'ABC마트' },
  { value: 'GrandStage', label: '그랜드스테이지' },
  { value: 'KREAM', label: 'KREAM' },
  { value: 'FashionPlus', label: '패션플러스' },
  { value: 'eBay', label: 'eBay' },
]

const EXEMPT_MARKETS_KEY = 'forbidden_exempt_markets'
const EXEMPT_SOURCES_KEY = 'forbidden_exempt_sources'

const toStrArray = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : [])

const wordsToText = (words: SambaForbiddenWord[], type: string) =>
  [...new Set(words.filter(w => w.type === type).map(w => w.word.trim()).filter(Boolean))].join('; ')

export function ForbiddenWordsSection({ tagBanned, setTagBanned }: Props) {
  const c = useTheme()
  const [market, setMarket] = useState('common')
  const [forbiddenText, setForbiddenText] = useState('')
  const [deletionText, setDeletionText] = useState('')
  const [optionDeletionText, setOptionDeletionText] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState('')  // 저장 중인 type ('' = 없음)

  // 금지어/삭제어 미적용 목록 (판매처/소싱처)
  const [exemptMarkets, setExemptMarkets] = useState<string[]>([])
  const [exemptSources, setExemptSources] = useState<string[]>([])
  const [exemptSaving, setExemptSaving] = useState(false)

  useEffect(() => {
    forbiddenApi.getSetting(EXEMPT_MARKETS_KEY)
      .then(v => setExemptMarkets(toStrArray(v)))
      .catch(() => {})
    forbiddenApi.getSetting(EXEMPT_SOURCES_KEY)
      .then(v => setExemptSources(toStrArray(v)))
      .catch(() => {})
  }, [])

  const toggleExempt = (kind: 'market' | 'source', value: string) => {
    const setter = kind === 'market' ? setExemptMarkets : setExemptSources
    setter(prev => (prev.includes(value) ? prev.filter(x => x !== value) : [...prev, value]))
  }

  const saveExempt = async () => {
    setExemptSaving(true)
    try {
      await forbiddenApi.saveSetting(EXEMPT_MARKETS_KEY, exemptMarkets)
      await forbiddenApi.saveSetting(EXEMPT_SOURCES_KEY, exemptSources)
      showAlert(
        `미적용 저장 완료 (판매처 ${fmtNum(exemptMarkets.length)}개 / 소싱처 ${fmtNum(exemptSources.length)}개)`,
        'success',
      )
    } catch {
      showAlert('미적용 저장 실패', 'error')
    }
    setExemptSaving(false)
  }

  // 선택 마켓의 단어 로드
  const loadWords = useCallback((mk: string) => {
    setLoading(true)
    forbiddenApi.listWords(undefined, mk)
      .then((words: SambaForbiddenWord[]) => {
        setForbiddenText(wordsToText(words, 'forbidden'))
        setDeletionText(wordsToText(words, 'deletion'))
        setOptionDeletionText(wordsToText(words, 'option_deletion'))
      })
      .catch(() => { showAlert('금지어 로드 실패', 'error') })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadWords(market) }, [market, loadWords])

  const save = async (type: string, text: string) => {
    setSaving(type)
    try {
      const words = [...new Set(text.split(';').map(w => w.trim()).filter(Boolean))]
      await forbiddenApi.bulkSaveWords(type, words, market)
      const deduped = words.join('; ')
      if (type === 'forbidden') setForbiddenText(deduped)
      else if (type === 'deletion') setDeletionText(deduped)
      else setOptionDeletionText(deduped)
      const label = type === 'forbidden' ? '금지어' : type === 'deletion' ? '삭제어' : '옵션삭제어'
      const mkLabel = MARKET_OPTIONS.find(m => m.value === market)?.label ?? market
      showAlert(`[${mkLabel}] ${label} ${fmtNum(words.length)}개 저장 완료`, 'success')
    } catch {
      showAlert('저장 실패', 'error')
    }
    setSaving('')
  }

  const isCommon = market === 'common'

  // 입력 컬럼 1개 렌더
  const column = (
    type: string, title: string, color: string, bg: string, border: string,
    value: string, setValue: (v: string) => void, placeholder: string, note?: string,
  ) => (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.4rem' }}>
        <div style={{ fontSize: '0.8125rem', color, fontWeight: 600 }}>{title}</div>
        <button
          disabled={saving !== '' || loading}
          onClick={() => save(type, value)}
          style={{
            padding: '0.25rem 0.75rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600,
            background: bg, border: `1px solid ${border}`, color, cursor: 'pointer',
          }}
        >{saving === type ? '...' : '저장'}</button>
      </div>
      <textarea
        value={value}
        onChange={e => setValue(e.target.value)}
        placeholder={placeholder}
        style={{
          width: '100%', height: '100px', background: c.inputBg, border: `1px solid ${c.border}`,
          borderRadius: '6px', padding: '8px', color: c.text, fontSize: '0.8125rem',
          resize: 'vertical', fontFamily: 'monospace',
        }}
      />
      <div style={{ fontSize: '0.75rem', color: c.textMuted, marginTop: '2px' }}>
        {fmtNum(value.split(';').filter(w => w.trim()).length)}개
        {note && <span style={{ marginLeft: '0.5rem', color: c.warn }}>{note}</span>}
      </div>
    </div>
  )

  // 미적용 체크박스 그리드 1개 렌더
  const exemptGroup = (
    kind: 'market' | 'source',
    title: string,
    options: { value: string; label: string }[],
    selected: string[],
  ) => (
    <div>
      <div style={{ fontSize: '0.8125rem', color: c.text, fontWeight: 600, marginBottom: '0.5rem' }}>
        {title} <span style={{ color: c.textMuted, fontWeight: 400 }}>({fmtNum(selected.length)}개 선택)</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
        {options.map(o => {
          const on = selected.includes(o.value)
          return (
            <button
              key={o.value}
              onClick={() => toggleExempt(kind, o.value)}
              style={{
                fontSize: '0.75rem', padding: '4px 10px', borderRadius: '14px', cursor: 'pointer',
                background: on ? 'rgba(96,165,250,0.16)' : c.surfaceAlt,
                border: `1px solid ${on ? 'rgba(96,165,250,0.5)' : c.border}`,
                color: on ? '#60A5FA' : c.textSub, fontWeight: on ? 600 : 400,
              }}
            >{on ? '✓ ' : ''}{o.label}</button>
          )
        })}
      </div>
    </div>
  )

  return (
    <>
      {/* 금지어 / 삭제어 미적용 (판매처 / 소싱처) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: c.text }}>금지어 / 삭제어 미적용</span>
          <span style={{ fontSize: '0.8125rem', color: c.textMuted }}>선택한 판매처·소싱처는 금지어(전송 제외)·삭제어(상품명 제거)를 모두 적용하지 않음</span>
          <button
            disabled={exemptSaving}
            onClick={saveExempt}
            style={{ ...btn('primary'), marginLeft: 'auto', padding: '0.3rem 0.875rem', fontSize: '0.8125rem' }}
          >{exemptSaving ? '...' : '저장'}</button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {exemptGroup('market', '판매처 (마켓)', EXEMPT_MARKET_OPTIONS, exemptMarkets)}
          {exemptGroup('source', '소싱처', SOURCE_SITE_OPTIONS, exemptSources)}
        </div>
      </div>

      {/* 금지어 / 삭제어 (마켓별) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: c.text }}>금지어 / 삭제어</span>
          <select
            value={market}
            onChange={e => setMarket(e.target.value)}
            style={{
              background: c.inputBg, border: `1px solid ${c.border}`, borderRadius: '6px',
              color: c.text, fontSize: '0.8125rem', padding: '0.3rem 0.6rem', cursor: 'pointer',
            }}
          >
            {MARKET_OPTIONS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
          <span style={{ fontSize: '0.8125rem', color: c.textMuted }}>
            {isCommon ? '모든 마켓에 공통 적용' : '공통 + 이 마켓에만 추가 적용'}
          </span>
          {loading && <span style={{ fontSize: '0.75rem', color: c.textMuted }}>불러오는 중…</span>}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
          {column('forbidden', '금지어 (포함 시 해당 마켓 전송 제외) — 세미콜론(;) 구분', c.danger,
            'rgba(255,107,107,0.12)', 'rgba(255,107,107,0.3)',
            forbiddenText, setForbiddenText, '구찌; 루이비통; 샤넬; 프라다')}
          {column('deletion', '삭제어 — 상품명에서 자동 제거', c.warn,
            'rgba(255,184,77,0.12)', 'rgba(255,184,77,0.3)',
            deletionText, setDeletionText, '매장정품; 정품; 해외직구; 무료배송')}
          {column('option_deletion', '옵션삭제어 — 옵션명에서 자동 제거', '#A29BFE',
            'rgba(162,155,254,0.12)', 'rgba(162,155,254,0.3)',
            optionDeletionText, setOptionDeletionText, '01(; 02(; ); [품절]',
            market !== 'common' && market !== 'smartstore' ? '※ 옵션삭제어는 현재 스마트스토어 전송에만 적용됨' : undefined)}
        </div>
      </div>

      {/* 태그 금지어 (스마트스토어 등록불가 단어) */}
      <div style={{ ...card, padding: '1.5rem', marginTop: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.9375rem', fontWeight: 700, color: c.danger }}>태그 금지어</span>
          <span style={{ fontSize: '0.8125rem', color: c.textMuted }}>** 스마트스토어 등록 시 자동 제외되는 단어 (API 거부 + 소싱처 + 브랜드)</span>
          <button onClick={() => forbiddenApi.getTagBannedWords().then(setTagBanned).catch(() => {})}
            style={{ ...btn('secondary'), marginLeft: 'auto', padding: '0.3rem 0.875rem', fontSize: '0.8125rem' }}>새로고침</button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <div style={{ fontSize: '0.8125rem', color: c.danger, fontWeight: 600, marginBottom: '0.4rem' }}>
              API 거부 태그 ({fmtNum(tagBanned.rejected.length)}개)
              <span style={{ fontWeight: 400, color: c.textMuted, marginLeft: '0.5rem' }}>전송 실패 시 자동 누적 + 직접 추가 가능</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', alignItems: 'center' }}>
              {tagBanned.rejected.length === 0 && <span style={{ fontSize: '0.75rem', color: c.textMuted }}>아직 없음</span>}
              {tagBanned.rejected.map((w, i) => (
                <span key={i} style={{
                  fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px',
                  background: 'rgba(196,115,110,0.12)', border: '1px solid rgba(196,115,110,0.3)', color: c.danger,
                  display: 'inline-flex', alignItems: 'center', gap: '4px',
                }}>
                  {w}
                  <span style={{ cursor: 'pointer', color: c.textMuted, fontSize: '0.8rem', lineHeight: 1 }}
                    onClick={async () => {
                      const updated = tagBanned.rejected.filter((_, idx) => idx !== i)
                      await forbiddenApi.saveSetting('smartstore_banned_tags', updated)
                      setTagBanned(prev => ({ ...prev, rejected: updated }))
                    }}>×</span>
                </span>
              ))}
              <input
                type="text"
                placeholder="금지어 입력 후 Enter"
                style={{ fontSize: '0.7rem', padding: '2px 7px', border: `1px solid ${c.border}`, borderRadius: '4px', color: c.text, background: c.inputBg, outline: 'none', width: '140px' }}
                onKeyDown={async (e) => {
                  if (e.key === 'Enter') {
                    const val = e.currentTarget.value.trim().toLowerCase()
                    if (!val || tagBanned.rejected.includes(val)) return
                    const updated = [...tagBanned.rejected, val]
                    await forbiddenApi.saveSetting('smartstore_banned_tags', updated)
                    setTagBanned(prev => ({ ...prev, rejected: updated }))
                    e.currentTarget.value = ''
                  }
                }}
              />
            </div>
          </div>
          <div>
            <div style={{ fontSize: '0.8125rem', color: c.warn, fontWeight: 600, marginBottom: '0.4rem' }}>
              수집 브랜드 ({fmtNum(tagBanned.brands.length)}개)
              <span style={{ fontWeight: 400, color: c.textMuted, marginLeft: '0.5rem' }}>브랜드명 포함 태그 자동 제외</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', maxHeight: '80px', overflow: 'auto' }}>
              {tagBanned.brands.map((w, i) => (
                <span key={i} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px', background: 'rgba(255,184,77,0.08)', border: '1px solid rgba(255,184,77,0.25)', color: c.warn }}>{w}</span>
              ))}
            </div>
          </div>
          <div>
            <div style={{ fontSize: '0.8125rem', color: c.textSub, fontWeight: 600, marginBottom: '0.4rem' }}>
              소싱처 ({fmtNum(tagBanned.source_sites.length)}개)
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
              {tagBanned.source_sites.map((w, i) => (
                <span key={i} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px', background: c.surfaceAlt, border: `1px solid ${c.border}`, color: c.textSub }}>{w}</span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
