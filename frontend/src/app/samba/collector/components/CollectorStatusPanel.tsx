"use client"

import type { Dispatch, RefObject, SetStateAction } from 'react'
import { fetchWithAuth, API_BASE } from '@/lib/samba/api/shared'
import { fmtNum, fmtTextNumbers } from '@/lib/samba/styles'

// 인증/프록시 상태 타입
type StatusState = 'checking' | 'ok' | 'error'

// 수집 큐 상태 타입
type CollectQueueItem = { filter_name: string; source_site: string }
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
  setProxyStatus: Dispatch<SetStateAction<StatusState>>
  setProxyText: Dispatch<SetStateAction<string>>
}

// 로그 섹션 전용 props (section='log')
type LogProps = {
  section: 'log'
  collectLog: string[]
  collecting: boolean
  collectQueueStatus: CollectQueueStatus
  logRef: RefObject<HTMLDivElement | null>
  handleStopCollect: () => void | Promise<void>
  handleCopyLog: () => void
  handleClearLog: () => void
  parseGroupName: (name: string, site: string) => ParsedGroup
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
      setProxyStatus,
      setProxyText,
    } = props
    return (
      // 프록시 + 무신사 인증 상태 (1줄)
      <div style={{
        display: 'flex', alignItems: 'center', gap: '16px', padding: '6px 14px',
        borderRadius: '8px', marginBottom: '12px',
        background: 'rgba(255,140,0,0.07)', border: '1px solid rgba(255,140,0,0.2)',
        fontSize: '0.78rem',
      }}>
        <span style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
          background: proxyStatus === 'ok' ? '#51CF66' : proxyStatus === 'error' ? '#FF6B6B' : '#555',
        }} />
        <span style={{ color: proxyStatus === 'ok' ? '#51CF66' : '#888' }}>{proxyText}</span>
        <span style={{ color: '#2D2D2D' }}>|</span>
        <span style={{ width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
          background: musinsaAuth === 'ok' ? '#51CF66' : musinsaAuth === 'error' ? '#FF6B6B' : '#555',
        }} />
        <span style={{ color: musinsaAuth === 'ok' ? '#51CF66' : '#888' }}>{musinsaAuthText}</span>
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
            marginLeft: 'auto', background: 'transparent', border: '1px solid #3D3D3D',
            color: '#888', padding: '2px 10px', borderRadius: '4px', fontSize: '0.72rem', cursor: 'pointer',
          }}
        >재확인</button>
      </div>
    )
  }

  // 로그현황 섹션
  const {
    collectLog,
    collecting,
    collectQueueStatus,
    logRef,
    handleStopCollect,
    handleCopyLog,
    handleClearLog,
    parseGroupName,
  } = props
  return (
    // 로그현황
    <div style={{
      background: "rgba(30,30,30,0.5)", border: "1px solid #2D2D2D", borderRadius: "8px",
      overflow: "hidden", marginBottom: "1rem",
    }}>
      <div style={{
        padding: "8px 16px", borderBottom: "1px solid #2D2D2D",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "#C5C5C5" }}>로그현황</span>
          {(() => {
            const { running, pending } = collectQueueStatus
            const hasActivity = running.length > 0 || pending.length > 0
            // 브랜드별 그룹핑
            const groupByBrand = (items: Array<{ filter_name: string; source_site: string }>) => {
              const brands = new Map<string, number>()
              for (const item of items) {
                const parsed = parseGroupName(item.filter_name, item.source_site)
                const brand = parsed.brand || item.source_site || '알수없음'
                brands.set(brand, (brands.get(brand) || 0) + 1)
              }
              return brands
            }
            const runBrands = groupByBrand(running)
            const penBrands = groupByBrand(pending)
            const formatBrands = (brands: Map<string, number>) => {
              const entries = [...brands.entries()]
              if (entries.length === 0) return ''
              if (entries.length <= 2) return entries.map(([b, c]) => c > 1 ? `${b} ${fmtNum(c)}건` : b).join('/')
              return `${entries[0][0]} 외 ${fmtNum(entries.length - 1)}개`
            }
            return (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem' }}>
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', flexShrink: 0,
                  background: running.length > 0 ? '#51CF66' : pending.length > 0 ? '#FAB005' : '#444',
                }} />
                {running.length > 0 && (
                  <span style={{ color: '#51CF66' }}>
                    {formatBrands(runBrands)} 진행 {fmtNum(running.length)}건
                  </span>
                )}
                {pending.length > 0 && (
                  <span style={{ color: '#FAB005' }}>
                    {running.length > 0 ? '+ ' : ''}{formatBrands(penBrands)} 대기 {fmtNum(pending.length)}건
                  </span>
                )}
                {!hasActivity && <span style={{ color: '#555' }}>대기 잡 없음</span>}
              </div>
            )
          })()}
        </div>
        <div style={{ display: "flex", gap: "4px" }}>
          {collecting && (
            <button onClick={handleStopCollect} style={{
              fontSize: "0.75rem", color: "#FF6B6B", background: "rgba(255,100,100,0.1)",
              border: "1px solid rgba(255,100,100,0.4)", padding: "2px 10px", borderRadius: "4px", cursor: "pointer",
            }}>수집 중단</button>
          )}
          <button onClick={handleCopyLog} style={{
            fontSize: "0.75rem", color: "#888", background: "transparent",
            border: "1px solid #3D3D3D", padding: "2px 10px", borderRadius: "4px", cursor: "pointer",
          }}>복사</button>
          <button onClick={handleClearLog} style={{
            fontSize: "0.75rem", color: "#888", background: "transparent",
            border: "1px solid #3D3D3D", padding: "2px 10px", borderRadius: "4px", cursor: "pointer",
          }}>초기화</button>
        </div>
      </div>
      <div
        ref={logRef}
        style={{
          height: "160px", overflowY: "auto", padding: "10px 16px",
          fontFamily: "monospace", fontSize: "0.78rem", color: "#8A95B0", zoom: "0.7",
          background: "#080A10", lineHeight: 1.6,
        }}
      >
        {collectLog.map((line, i) => (
          <p key={i} style={{
            color: line.includes("완료") ? "#51CF66"
              : line.includes("실패") || line.includes("오류") ? "#FF6B6B"
              : line.includes("대기") || line.includes("초기화") ? "#555"
              : "#8A95B0",
            margin: 0,
          }}>
            {fmtTextNumbers(line)}
          </p>
        ))}
      </div>
    </div>
  )
}
