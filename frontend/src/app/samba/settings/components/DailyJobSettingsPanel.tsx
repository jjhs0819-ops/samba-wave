'use client'

import { useEffect, useState, useCallback } from 'react'
import { card, inputStyle } from '@/lib/samba/styles'
import { forbiddenApi } from '@/lib/samba/api/commerce'
import { showAlert } from '@/components/samba/Modal'

interface DailyJobConfig {
  task1_enabled: boolean
  task2_enabled: boolean
  task3_enabled: boolean
  task4_enabled: boolean
  task5_enabled: boolean
  recollect_interval_days: number
}

const DEFAULT_CONFIG: DailyJobConfig = {
  task1_enabled: true,
  task2_enabled: true,
  task3_enabled: true,
  task4_enabled: true,
  task5_enabled: true,
  recollect_interval_days: 5,
}

const TASK_LABELS: [keyof DailyJobConfig, string][] = [
  ['task1_enabled', '미매핑 카테고리'],
  ['task2_enabled', 'AI 태그'],
  ['task3_enabled', '정책 설정'],
  ['task4_enabled', '품절 처리'],
  ['task5_enabled', '브랜드 재수집'],
]

interface Props {
  networkIps: { web: string; local: string }
  networkIpStatus: string
  setNetworkIps: (fn: (prev: { web: string; local: string }) => { web: string; local: string }) => void
  saveNetworkIps: () => void
}

export function DailyJobSettingsPanel({ networkIps, networkIpStatus, setNetworkIps, saveNetworkIps }: Props) {
  const [config, setConfig] = useState<DailyJobConfig>(DEFAULT_CONFIG)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState('')

  const load = useCallback(async () => {
    try {
      const res = await forbiddenApi.getSetting('daily_job_config')
      if (res && typeof res === 'object') {
        setConfig({ ...DEFAULT_CONFIG, ...(res as Partial<DailyJobConfig>) })
      }
    } catch {
      // 설정 없으면 기본값 사용
    }
  }, [])

  useEffect(() => { load() }, [load])

  const save = async () => {
    setSaving(true)
    setStatus('')
    try {
      await forbiddenApi.saveSetting('daily_job_config', config)
      setStatus('저장됨')
      setTimeout(() => setStatus(''), 2000)
    } catch {
      showAlert('저장 실패', 'error')
    } finally {
      setSaving(false)
    }
  }

  const toggle = (key: keyof DailyJobConfig) => {
    setConfig(prev => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div style={{ ...card, padding: '1.25rem 1.5rem', marginBottom: '1.5rem' }}>
      <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.2rem' }}>데일리 유지보수</div>
      <p style={{ fontSize: '0.8125rem', color: '#666', marginBottom: '1rem' }}>
        매일 새벽 1시 KST 자동 실행 (VM 크론탭 관리)
      </p>

      {/* 1행: 토글 × 5 + 재수집 주기 + 저장 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', flexWrap: 'wrap' }}>
        {TASK_LABELS.map(([key, label]) => {
          const enabled = config[key] as boolean
          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <button
                type="button"
                onClick={() => toggle(key)}
                style={{
                  width: '34px', height: '18px', borderRadius: '9px', border: 'none',
                  background: enabled ? '#FF8C00' : '#333',
                  position: 'relative', cursor: 'pointer', flexShrink: 0, transition: 'background 0.2s',
                }}
              >
                <span style={{
                  position: 'absolute', top: '1px',
                  left: enabled ? '17px' : '1px',
                  width: '16px', height: '16px', borderRadius: '50%',
                  background: '#fff', transition: 'left 0.2s',
                }} />
              </button>
              <span style={{ fontSize: '0.8125rem', color: enabled ? '#E5E5E5' : '#555', whiteSpace: 'nowrap' }}>{label}</span>
            </div>
          )
        })}

        <div style={{ width: '1px', height: '20px', background: '#2D2D2D', flexShrink: 0 }} />

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <label style={{ color: '#888', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>재수집 주기</label>
          <input
            type="number" min={1} max={30}
            style={{ ...inputStyle, width: '52px' }}
            value={config.recollect_interval_days}
            onChange={(e) => setConfig(prev => ({ ...prev, recollect_interval_days: Math.max(1, Number(e.target.value)) }))}
          />
          <span style={{ fontSize: '0.8125rem', color: '#666' }}>일</span>
        </div>

        <button
          type="button" onClick={save} disabled={saving}
          style={{ padding: '0.375rem 1rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontWeight: 600, fontSize: '0.8125rem', cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.6 : 1, whiteSpace: 'nowrap' }}
        >저장</button>
        {status && <span style={{ fontSize: '0.8125rem', color: '#51CF66' }}>{status}</span>}
      </div>

      {/* 구분선 */}
      <div style={{ borderTop: '1px solid #2D2D2D', margin: '0.875rem 0' }} />

      {/* 2행: 웹/로컬 IP */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.8125rem', color: '#888', whiteSpace: 'nowrap' }}>웹 / 로컬 IP</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <label style={{ color: '#666', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>웹</label>
          <input
            type="text" style={{ ...inputStyle, width: '140px' }}
            value={networkIps.web}
            onChange={(e) => setNetworkIps(prev => ({ ...prev, web: e.target.value }))}
            placeholder="123.123.123.123"
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <label style={{ color: '#666', fontSize: '0.8125rem', whiteSpace: 'nowrap' }}>로컬</label>
          <input
            type="text" style={{ ...inputStyle, width: '140px' }}
            value={networkIps.local}
            onChange={(e) => setNetworkIps(prev => ({ ...prev, local: e.target.value }))}
            placeholder="192.168.0.10"
          />
        </div>
        <button
          type="button" onClick={saveNetworkIps}
          style={{ padding: '0.375rem 1rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontWeight: 600, fontSize: '0.8125rem', cursor: 'pointer', whiteSpace: 'nowrap' }}
        >저장</button>
        {networkIpStatus && (
          <span style={{ fontSize: '0.8125rem', color: networkIpStatus.includes('실패') ? '#FF6B6B' : '#51CF66' }}>
            {networkIpStatus}
          </span>
        )}
      </div>
    </div>
  )
}
