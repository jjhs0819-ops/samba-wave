"use client"

import type { Dispatch, RefObject, SetStateAction } from 'react'
import { fetchWithAuth, API_BASE } from '@/lib/samba/api/shared'
import { fmtNum, fmtTextNumbers } from '@/lib/samba/styles'
import { light as c } from '@/lib/samba/colors'
import { btn, btnDisabled } from '@/lib/samba/buttons'
import type { MusinsaAccount, PoolInfo } from '../hooks/useProxyAuth'

// 인증/프록시 상태 타입
type StatusState = 'checking' | 'ok' | 'error'

// 수집 큐 상태 타입
type CollectQueueItem = { id: string; filter_name: string; source_site: string; started_at: string | null; current: number; total: number }
type CollectQueueStatus = {
  running: CollectQueueItem[]
  pending: CollectQueueItem[]
}

// 그룹명 파싱 결과 타입
type ParsedGroup = { brand: string; category: string }

// 상태 섹션 전용 props (section='status')
type StatusProps = {
  section: 'status'
  proxyStatus: StatusState
  proxyText: string
  musinsaAuth: StatusState
  musinsaAuthText: string
  musinsaCookieUpdatedAt?: string | null
  musinsaAccount?: MusinsaAccount
  poolInfo?: PoolInfo
  setProxyStatus: Dispatch<SetStateAction<StatusState>>
  setProxyText: Dispatch<SetStateAction<string>>
}

// 쿠키 갱신 시각 → 상대시간 문자열 + 색상
// 5분 미만: 회색 '방금 갱신', 24시간 미만: 회색 'N분/시간 전 갱신', 24시간 이상: 주황 'N일 전 갱신'
function formatCookieFreshness(iso: string | null | undefined): { text: string; color: string } | null {
  if (!iso) return null
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) return null
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (diffSec < 300) return { text: '방금 갱신', color: c.textMuted }
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return { text: `${diffMin}분 전 갱신`, color: c.textMuted }
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return { text: `${diffHour}시간 전 갱신`, color: c.textMuted }
  const diffDay = Math.floor(diffHour / 24)
  return { text: `${diffDay}일 전 갱신`, color: c.warn }
}

// 로그 섹션 전용 props (section='log')
type LogProps = {
  section: 'log'
  collectLog: string[]
  collecting: boolean
  collectQueueStatus: CollectQueueStatus
  cancellingJobIds: string[]
  logRef: RefObject<HTMLDivElement | null>
  handleStopCollect: () => void | Promise<void>
  handleCancelCollectJob: (jobId: string) => void
  handleCopyLog: () => void
  handleClearLog: () => void
  parseGroupName?: (name: string, site: string) => ParsedGroup
}

type Props = StatusProps | LogProps

export default function CollectorStatusPanel(props: Props) {
  // 프록시 + 무신사 인증 상태 섹션
  if (props.section === 'status') {
    const {
      proxyStatus,
      proxyText,
      musinsaAuth,
      musinsaAuthText,
      musinsaCookieUpdatedAt,
      musinsaAccount,
      poolInfo,
      setProxyStatus,
      setProxyText,
    } = props
    const cookieFresh = musinsaAuth === 'ok' ? formatCookieFreshness(musinsaCookieUpdatedAt) : null

    // 쿠키 주인 식별 정보 — slot vs cookie hashId 매칭 결과
    let accountText: string | null = null
    let accountColor: string = c.success
    if (musinsaAccount) {
      const slot = musinsaAccount.slot_label
        ? `${musinsaAccount.slot_label}${musinsaAccount.slot_username ? `(${musinsaAccount.slot_username})` : ''}`
        : '자리미설정'
      const lvl = musinsaAccount.level != null ? `LV.${musinsaAccount.level}` : ''
      const gender = musinsaAccount.gender
        ? (musinsaAccount.gender === 'M' ? '남' : musinsaAccount.gender === 'F' ? '여' : '')
        : ''
      const cookieDesc = [lvl, gender, musinsaAccount.birth_year].filter(Boolean).join(' ')
      if (musinsaAccount.match === false) {
        // 오염 — slot 과 쿠키 주인 다름
        const shortCookieHash = (musinsaAccount.cookie_hash_id || '').slice(0, 8)
        accountText = `⚠ 자리:${slot} / 쿠키:외부 ${cookieDesc} (${shortCookieHash}..)`
        accountColor = c.danger
      } else if (musinsaAccount.match === true) {
        accountText = `${slot} · ${cookieDesc} ✓`
        accountColor = c.success
      } else if (musinsaAccount.slot_hash_id == null && musinsaAccount.cookie_hash_id) {
        // bootstrap 미완료 — hashId 캡처 대기
        accountText = `${slot} · ${cookieDesc} · (식별자 미설정)`
        accountColor = c.warn
      } else {
        accountText = `${slot} · ${cookieDesc}`
        accountColor = c.textMuted
      }
    }

    // write/read pool_max 분리 — 같은 값으로 표시하면 read(실제 30) 오인 유발
    const wPoolMax = poolInfo?.write_pool_max ?? poolInfo?.write?.pool_max ?? poolInfo?.pool_max ?? 60
    const rPoolMax = poolInfo?.read_pool_max ?? poolInfo?.read?.pool_max ?? 30
    // pg_stat_activity는 DB 서버 전역 통계 — write/read로 나뉘지 않는다.
    // 백엔드가 단일 스냅샷(poolInfo.db)을 주므로 전역 1개 값으로 표시(과거엔 두 번 따로 세서 어긋났음).
    const dbPg = poolInfo?.db ?? poolInfo?.write?.pg ?? poolInfo?.read?.pg
    const gActive = dbPg?.active ?? 0
    const gIit = dbPg?.idle_in_transaction ?? 0
    const gIdle = dbPg?.idle ?? 0
    const gTotal = dbPg?.total ?? 0
    // 백엔드 SQLAlchemy 풀 실제 점유 (이게 진짜 풀 사용량 — DB 전체 세션과 비교 금지)
    const wCheckedOut = poolInfo?.write?.checkedout ?? 0
    const rCheckedOut = poolInfo?.read?.checkedout ?? 0
    // IIT 임계 — 단순 카운트는 BEGIN 직후 정상 트랜잭션도 잡혀 false positive.
    // age >= 30s 좀비(iit_zombie) 기반으로 빨강/노랑 판단. 전역 단일값.
    const gZombie = dbPg?.iit_zombie ?? 0
    const maxZombie = gZombie
    // 빨강 기준: 실제 백엔드 풀 점유율 또는 좀비 (DB 전체 세션 totals 는 다른 컨테이너/cron 포함이라 무관)
    const wPoolRatio = wPoolMax > 0 ? wCheckedOut / wPoolMax : 0
    const rPoolRatio = rPoolMax > 0 ? rCheckedOut / rPoolMax : 0
    const poolStatusColor = (wPoolRatio >= 1 || rPoolRatio >= 1 || maxZombie >= 5)
      ? c.danger
      : (wPoolRatio >= 0.85 || rPoolRatio >= 0.85 || maxZombie >= 2)
        ? c.warn
        : c.success
    const poolCellColor = (ratio: number) =>
      ratio >= 1 ? c.danger : ratio >= 0.85 ? c.warn : c.text
    const iitCellColor = (zombie: number) =>
      zombie >= 5 ? c.danger : zombie >= 2 ? c.warn : c.text

    return (
      <div style={{ marginBottom: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {/* 프록시 + 무신사 인증 상태 */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: '16px', padding: '6px 14px',
          borderRadius: '8px', background: c.accentBg, border: `1px solid ${c.border}`,
          fontSize: '0.78rem',
        }}>
          <span style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
            background: proxyStatus === 'ok' ? c.success : proxyStatus === 'error' ? c.danger : c.textMuted,
          }} />
          <span style={{ color: proxyStatus === 'ok' ? c.success : c.textMuted }}>{proxyText}</span>
          <span style={{ color: c.border }}>|</span>
          <span style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
            background: musinsaAuth === 'ok' ? c.success : musinsaAuth === 'error' ? c.danger : c.textMuted,
          }} />
          <span style={{ color: musinsaAuth === 'ok' ? c.success : c.textMuted }}>{musinsaAuthText}</span>
          {accountText && (
            <span style={{ color: accountColor, fontSize: '0.72rem', fontWeight: musinsaAccount?.match === false ? 700 : 400 }}>
              · {accountText}
            </span>
          )}
          {cookieFresh && (
            <span style={{ color: cookieFresh.color, fontSize: '0.72rem' }}>· {cookieFresh.text}</span>
          )}
          <button
            onClick={() => {
              setProxyStatus('checking')
              setProxyText('프록시 서버 확인 중...')
              fetchWithAuth(`${API_BASE}/api/v1/samba/collector/proxy-status`)
                .then(r => r.json())
                .then(data => {
                  if (data.status === 'ok') { setProxyStatus('ok'); setProxyText(data.message || '프록시 서버 정상 작동 중') }
                  else { setProxyStatus('error'); setProxyText(data.message || '프록시 서버 연결 실패') }
                })
                .catch(() => { setProxyStatus('error'); setProxyText('백엔드 서버 연결 실패') })
            }}
            style={{
              ...btn('secondary'), marginLeft: 'auto',
              padding: '2px 10px', borderRadius: '4px', fontSize: '0.72rem',
            }}
          >재확인</button>
        </div>

        {/* DB 커넥션 풀 테이블 */}
        {poolInfo && dbPg && (
          <div style={{
            borderRadius: '8px', overflow: 'hidden',
            border: `1px solid ${poolStatusColor === c.danger ? c.danger : poolStatusColor === c.warn ? c.warn : c.success}`,
            background: c.surface, fontSize: '0.78rem',
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ background: c.surfaceAlt }}>
                  <th style={{ padding: '6px 14px', textAlign: 'left', color: c.textSub, fontWeight: 600, borderBottom: `1px solid ${c.border}` }}>상태</th>
                  <th style={{ padding: '6px 14px', textAlign: 'center', color: c.textSub, fontWeight: 600, borderBottom: `1px solid ${c.border}` }}>Write DB</th>
                  <th style={{ padding: '6px 14px', textAlign: 'center', color: c.textSub, fontWeight: 600, borderBottom: `1px solid ${c.border}` }}>Read DB</th>
                </tr>
              </thead>
              <tbody>
                {/* 백엔드 SQLAlchemy 풀 실제 점유 — 이게 진짜 "풀 꽉참" 지표 */}
                <tr style={{ background: c.surfaceAlt, borderBottom: `1px solid ${c.border}` }}>
                  <td style={{ padding: '6px 14px', color: c.text, fontWeight: 700 }}>
                    백엔드 풀 점유
                    <span style={{ marginLeft: 8, fontSize: '0.7rem', color: c.textMuted, fontWeight: 400 }}>
                      (이 값이 풀 최대 넘으면 진짜 꽉참)
                    </span>
                  </td>
                  <td style={{ padding: '6px 14px', textAlign: 'center', color: poolCellColor(wPoolRatio), fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                    {fmtNum(wCheckedOut)} / {fmtNum(wPoolMax)} ({Math.round(wPoolRatio * 100)}%)
                  </td>
                  <td style={{ padding: '6px 14px', textAlign: 'center', color: poolCellColor(rPoolRatio), fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                    {fmtNum(rCheckedOut)} / {fmtNum(rPoolMax)} ({Math.round(rPoolRatio * 100)}%)
                  </td>
                </tr>
                {/* 아래 4줄은 DB 서버 전역 통계 — write/read로 나뉘지 않으므로 단일 값(2칸 병합) 표시 */}
                <tr>
                  <td colSpan={3} style={{ padding: '4px 14px', color: c.textMuted, fontSize: '0.68rem', background: c.surfaceAlt }}>
                    ─ DB 서버 전역 (write/read 공통 · 풀과 무관)
                  </td>
                </tr>
                {([
                  { label: 'active', val: gActive, type: 'normal' as const },
                  { label: 'idle in transaction', val: gIit, type: 'iit' as const },
                  { label: 'idle', val: gIdle, type: 'normal' as const },
                ]).map((row) => (
                  <tr key={row.label} style={{ borderBottom: `1px solid ${c.border}` }}>
                    <td style={{ padding: '5px 14px', color: c.textMuted }}>
                      {row.label}
                      {row.type === 'iit' && (
                        <span style={{ marginLeft: 8, fontSize: '0.7rem', color: c.textMuted }}>
                          (좀비 ≥30s: {fmtNum(gZombie)})
                        </span>
                      )}
                    </td>
                    <td colSpan={2} style={{ padding: '5px 14px', textAlign: 'center', color: row.type === 'iit' ? iitCellColor(gZombie) : c.text, fontVariantNumeric: 'tabular-nums' }}>{fmtNum(row.val)}개</td>
                  </tr>
                ))}
                <tr style={{ borderTop: `1px solid ${c.border}`, background: c.surfaceAlt }}>
                  <td style={{ padding: '6px 14px', color: c.textMuted }}>
                    DB 전체 세션
                    <span style={{ marginLeft: 8, fontSize: '0.7rem', color: c.textMuted }}>
                      (백엔드 + cron + admin + 다른 컨테이너 합산 — 풀 최대와 비교 X)
                    </span>
                  </td>
                  <td colSpan={2} style={{ padding: '6px 14px', textAlign: 'center', color: c.textMuted, fontVariantNumeric: 'tabular-nums' }}>{fmtNum(gTotal)}개</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>
    )
  }

  // 로그현황 섹션
  const {
    collectLog,
    collecting,
    collectQueueStatus,
    cancellingJobIds,
    logRef,
    handleStopCollect,
    handleCancelCollectJob,
    handleCopyLog,
    handleClearLog,
  } = props
  const { running, pending } = collectQueueStatus
  const hasJobs = running.length > 0 || pending.length > 0
  return (
    <>
      {/* 수집 잡 진행상황 섹션 */}
      {hasJobs && (
        <div style={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: '8px', marginBottom: '8px', overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px', background: c.surfaceAlt, borderBottom: `1px solid ${c.border}` }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%',
              background: running.length > 0 ? c.success : c.warn }} />
            <span style={{ fontSize: '0.82rem', fontWeight: 600, color: c.textSub }}>
              수집 잡 진행상황
              {running.length > 0 && ` — 수집 중 ${fmtNum(running.length)}건`}
              {pending.length > 0 && `${running.length > 0 ? ' · ' : ' — '}대기 ${fmtNum(pending.length)}건`}
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', padding: '8px 14px' }}>
            {running.map((j, idx) => {
              const started = j.started_at ? new Date(j.started_at) : null
              const startedStr = started
                ? `${String(started.getHours()).padStart(2,'0')}:${String(started.getMinutes()).padStart(2,'0')}:${String(started.getSeconds()).padStart(2,'0')}`
                : '-'
              const pct = j.total > 0 ? Math.floor((j.current / j.total) * 100) : 0
              const busy = cancellingJobIds.includes(j.id)
              return (
                <div key={`rc-${j.id || idx}`} style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.75rem', color: c.text }}>
                  <span style={{ color: c.success, fontWeight: 600, minWidth: '40px' }}>수집중</span>
                  <span style={{ color: c.textMuted, minWidth: '72px' }}>시작 {startedStr}</span>
                  <span style={{ color: c.textSub, minWidth: '64px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{j.source_site}</span>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{j.filter_name || '—'}</span>
                  <span style={{ color: c.textSub, minWidth: '110px', textAlign: 'right' }}>
                    {j.total > 0 ? `${fmtNum(j.current)} / ${fmtNum(j.total)} (${pct}%)` : '—'}
                  </span>
                  <button
                    onClick={() => handleCancelCollectJob(j.id)}
                    disabled={busy}
                    style={{ ...btn('danger'), ...(busy ? btnDisabled : null), padding: '2px 8px', fontSize: '0.7rem', borderRadius: '3px', minWidth: '44px' }}
                  >{busy ? '취소중' : '취소'}</button>
                </div>
              )
            })}
            {pending.map((j, idx) => {
              const busy = cancellingJobIds.includes(j.id)
              return (
                <div key={`pc-${j.id || idx}`} style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.75rem', color: c.textMuted }}>
                  <span style={{ color: c.warn, fontWeight: 600, minWidth: '40px' }}>대기</span>
                  <span style={{ minWidth: '72px' }}>—</span>
                  <span style={{ color: c.textSub, minWidth: '64px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{j.source_site}</span>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{j.filter_name || '—'}</span>
                  <span style={{ minWidth: '110px', textAlign: 'right' }}>—</span>
                  <button
                    onClick={() => handleCancelCollectJob(j.id)}
                    disabled={busy}
                    style={{ ...btn('danger'), ...(busy ? btnDisabled : null), padding: '2px 8px', fontSize: '0.7rem', borderRadius: '3px', minWidth: '44px' }}
                  >{busy ? '취소중' : '취소'}</button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* 로그현황 */}
      <div style={{
        background: c.surface, border: `1px solid ${c.border}`, borderRadius: "8px",
        overflow: "hidden", marginBottom: "1rem",
      }}>
        <div style={{
          padding: "8px 16px", borderBottom: `1px solid ${c.border}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <span style={{ fontSize: "0.85rem", fontWeight: 600, color: c.text }}>로그현황</span>
          <div style={{ display: "flex", gap: "4px" }}>
            {collecting && (
              <button onClick={handleStopCollect} style={{
                ...btn('danger'), fontSize: "0.75rem", padding: "2px 10px", borderRadius: "4px",
              }}>수집 중단</button>
            )}
            <button onClick={handleCopyLog} style={{
              ...btn('ghost'), fontSize: "0.75rem", padding: "2px 10px", borderRadius: "4px",
            }}>복사</button>
            <button onClick={handleClearLog} style={{
              ...btn('ghost'), fontSize: "0.75rem", padding: "2px 10px", borderRadius: "4px",
            }}>초기화</button>
          </div>
        </div>
        <div
          ref={logRef}
          style={{
            height: "160px", overflowY: "auto", padding: "10px 16px",
            fontFamily: "monospace", fontSize: "0.78rem", color: c.textMuted, zoom: "0.7",
            background: c.surfaceAlt, lineHeight: 1.6,
          }}
        >
          {collectLog.map((line, i) => (
            <p key={i} style={{
              color: line.includes("완료") ? c.success
                : line.includes("실패") || line.includes("오류") ? c.danger
                : line.includes("대기") || line.includes("초기화") ? c.textMuted
                : c.textMuted,
              margin: 0,
            }}>
              {fmtTextNumbers(line)}
            </p>
          ))}
        </div>
      </div>
    </>
  )
}
