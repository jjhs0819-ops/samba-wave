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
  ['task1_enabled', 'Task 1 — 미매핑 카테고리 자동 매핑'],
  ['task2_enabled', 'Task 2 — AI 태그 자동 설정'],
  ['task3_enabled', 'Task 3 — 가디 정책 자동 설정'],
  ['task4_enabled', 'Task 4 — 품절 상품 처리'],
  ['task5_enabled', 'Task 5 — 브랜드 재수집 잡 생성'],
]

export function DailyJobSettingsPanel() {
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
    <div style={{ ...card, padding: '1.5rem', flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>데일리 유지보수</div>
      <p style={{ fontSize: '0.8125rem', color: '#666', marginBottom: '1.25rem' }}>
        매일 새벽 1시 KST 자동 실행 (VM 크론탭 관리)
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem', marginBottom: '1.25rem' }}>
        {TASK_LABELS.map(([key, label]) => {
          const enabled = config[key] as boolean
          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <button
                type="button"
                onClick={() => toggle(key)}
                style={{
                  width: '40px',
                  height: '22px',
                  borderRadius: '11px',
                  border: 'none',
                  background: enabled ? '#FF8C00' : '#333',
                  position: 'relative',
                  cursor: 'pointer',
                  flexShrink: 0,
                  transition: 'background 0.2s',
                }}
              >
                <span style={{
                  position: 'absolute',
                  top: '3px',
                  left: enabled ? '21px' : '3px',
                  width: '16px',
                  height: '16px',
                  borderRadius: '50%',
                  background: '#fff',
                  transition: 'left 0.2s',
                }} />
              </button>
              <span style={{ fontSize: '0.8125rem', color: enabled ? '#E5E5E5' : '#666' }}>{label}</span>
            </div>
          )
        })}
      </div>

      {/* Task 5 재수집 주기 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1.25rem', paddingTop: '0.75rem', borderTop: '1px solid #2D2D2D' }}>
        <label style={{ color: '#888', fontSize: '0.8125rem', flexShrink: 0 }}>재수집 주기</label>
        <input
          type="number"
          min={1}
          max={30}
          style={{ ...inputStyle, width: '72px' }}
          value={config.recollect_interval_days}
          onChange={(e) => setConfig(prev => ({ ...prev, recollect_interval_days: Math.max(1, Number(e.target.value)) }))}
        />
        <span style={{ fontSize: '0.8125rem', color: '#666' }}>일 (Task 5 기준)</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button
          type="button"
          onClick={save}
          disabled={saving}
          style={{ padding: '0.5rem 1.25rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontWeight: 600, fontSize: '0.8125rem', cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.6 : 1 }}
        >저장</button>
        {status && <span style={{ fontSize: '0.8125rem', color: '#51CF66' }}>{status}</span>}
      </div>
    </div>
  )
}
