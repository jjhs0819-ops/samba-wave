'use client'

import { card, inputStyle } from '@/lib/samba/styles'

interface Props {
  networkIps: { web: string; local: string }
  networkIpStatus: string
  setNetworkIps: (fn: (prev: { web: string; local: string }) => { web: string; local: string }) => void
  saveNetworkIps: () => void
}

export function NetworkIpPanel({ networkIps, networkIpStatus, setNetworkIps, saveNetworkIps }: Props) {
  return (
    <div style={{ ...card, padding: '1.5rem', flex: 1, minWidth: 0 }}>
      <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>웹 / 로컬 IP</div>
      <p style={{ fontSize: '0.8125rem', color: '#666', marginBottom: '1.25rem' }}>
        소싱처 수집 시 사용하는 IP를 등록합니다
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <label style={{ color: '#888', fontSize: '0.875rem', minWidth: '80px', flexShrink: 0 }}>웹 IP</label>
          <input
            type="text"
            style={{ ...inputStyle, flex: 1 }}
            value={networkIps.web}
            onChange={(e) => setNetworkIps(prev => ({ ...prev, web: e.target.value }))}
            placeholder="예: 123.123.123.123"
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <label style={{ color: '#888', fontSize: '0.875rem', minWidth: '80px', flexShrink: 0 }}>로컬 IP</label>
          <input
            type="text"
            style={{ ...inputStyle, flex: 1 }}
            value={networkIps.local}
            onChange={(e) => setNetworkIps(prev => ({ ...prev, local: e.target.value }))}
            placeholder="예: 192.168.0.10"
          />
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button
          type="button"
          onClick={saveNetworkIps}
          style={{ padding: '0.5rem 1.25rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontWeight: 600, fontSize: '0.8125rem', cursor: 'pointer' }}
        >IP 저장</button>
        {networkIpStatus && (
          <span style={{ fontSize: '0.8125rem', color: networkIpStatus.includes('실패') ? '#FF6B6B' : '#51CF66' }}>
            {networkIpStatus}
          </span>
        )}
      </div>
    </div>
  )
}
