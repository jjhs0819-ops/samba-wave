'use client'

import { card, inputStyle } from '@/lib/samba/styles'
import {
  type ProxyConfigItem,
  type ProxyPurpose,
} from '@/lib/samba/api/commerce'
import type { ProxySettingsState, ProxySettingsActions } from '../hooks/useProxySettings'

type Props = ProxySettingsState & Pick<ProxySettingsActions,
  'testProxy' | 'openProxyAdd' | 'openProxyEdit' | 'handleProxySave' |
  'handleProxyDelete' | 'handleProxyToggle' | 'toggleProxyPurpose' |
  'setProxyModalOpen' | 'setProxyForm' | 'setProxyFields'
>

const PURPOSE_STYLES: Record<ProxyPurpose, { bg: string; color: string; label: string }> = {
  transmit: { bg: 'rgba(0,200,150,0.1)', color: '#00C896', label: '전송' },
  collect: { bg: 'rgba(255,184,77,0.1)', color: '#FFB84D', label: '수집' },
  autotune: { bg: 'rgba(76,154,255,0.1)', color: '#4C9AFF', label: '오토튠' },
}

export function ProxySettingsPanel(props: Props) {
  const {
    proxies,
    proxyModalOpen,
    proxyEditIdx,
    proxyForm,
    proxyFields,
    proxyTesting,
    proxySaving,
    testProxy,
    openProxyAdd,
    openProxyEdit,
    handleProxySave,
    handleProxyDelete,
    handleProxyToggle,
    toggleProxyPurpose,
    setProxyModalOpen,
    setProxyForm,
    setProxyFields,
  } = props

  return (
    <>
      {/* 프록시 설정 */}
      <div style={{ ...card, padding: '1.5rem', marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
          <div>
            <div style={{ fontSize: '1rem', fontWeight: 700, color: '#E5E5E5' }}>프록시 / IP 설정</div>
            <p style={{ fontSize: '0.8125rem', color: '#666', margin: '0.25rem 0 0' }}>전송·수집·오토튠에 사용할 IP/프록시를 관리합니다</p>
          </div>
          <button
            onClick={openProxyAdd}
            style={{ padding: '0.4rem 1rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontSize: '0.8125rem', fontWeight: 600, cursor: 'pointer' }}
          >+ 추가</button>
        </div>

        {proxies.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '2rem', color: '#555', fontSize: '0.8125rem' }}>
            등록된 프록시가 없습니다
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: '1rem', fontSize: '0.8125rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #2D2D2D', color: '#888' }}>
                <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 500 }}>이름</th>
                <th style={{ textAlign: 'left', padding: '0.5rem 0.75rem', fontWeight: 500 }}>IP / URL</th>
                <th style={{ textAlign: 'center', padding: '0.5rem 0.75rem', fontWeight: 500 }}>용도</th>
                <th style={{ textAlign: 'center', padding: '0.5rem 0.75rem', fontWeight: 500 }}>상태</th>
                <th style={{ textAlign: 'center', padding: '0.5rem 0.75rem', fontWeight: 500 }}>관리</th>
              </tr>
            </thead>
            <tbody>
              {proxies.map((p, i) => {
                const isMainIp = !p.url
                const masked = isMainIp ? '34.47.122.131 (직접 연결)' : p.url.includes('@') ? `***@${p.url.split('@').pop()}` : p.url.replace(/^https?:\/\//, '')
                return (
                  <tr key={i} style={{ borderBottom: '1px solid #1A1A1A' }}>
                    <td style={{ padding: '0.6rem 0.75rem', color: '#E5E5E5' }}>
                      {isMainIp && <span style={{ color: '#00C896', marginRight: '4px', fontSize: '0.7rem' }}>●</span>}
                      {p.name}
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', color: isMainIp ? '#00C896' : '#999', fontFamily: 'monospace', fontSize: '0.75rem' }}>{masked}</td>
                    <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center' }}>
                      <div style={{ display: 'flex', gap: '4px', justifyContent: 'center', flexWrap: 'wrap' }}>
                        {(p.purposes || []).map(pp => {
                          const s = PURPOSE_STYLES[pp]
                          return s ? <span key={pp} style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '10px', background: s.bg, color: s.color }}>{s.label}</span> : null
                        })}
                      </div>
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center' }}>
                      <span
                        onClick={() => handleProxyToggle(i)}
                        style={{
                          display: 'inline-block', width: '36px', height: '20px', borderRadius: '10px', cursor: 'pointer', position: 'relative',
                          background: p.enabled ? '#FF8C00' : '#333',
                          transition: 'background 0.2s',
                        }}
                      >
                        <span style={{
                          position: 'absolute', top: '2px', left: p.enabled ? '18px' : '2px',
                          width: '16px', height: '16px', borderRadius: '50%', background: '#fff',
                          transition: 'left 0.2s',
                        }} />
                      </span>
                    </td>
                    <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center', whiteSpace: 'nowrap' }}>
                      <button
                        onClick={() => testProxy(i)}
                        disabled={proxyTesting === i}
                        style={{ background: 'none', border: '1px solid #2D2D2D', color: proxyTesting === i ? '#555' : '#4C9AFF', borderRadius: '4px', padding: '2px 8px', fontSize: '0.75rem', cursor: 'pointer', marginRight: '4px' }}
                      >{proxyTesting === i ? '테스트중' : '테스트'}</button>
                      <button
                        onClick={() => openProxyEdit(i)}
                        style={{ background: 'none', border: '1px solid #2D2D2D', color: '#999', borderRadius: '4px', padding: '2px 8px', fontSize: '0.75rem', cursor: 'pointer', marginRight: '4px' }}
                      >수정</button>
                      <button
                        onClick={() => handleProxyDelete(i)}
                        style={{ background: 'none', border: '1px solid #2D2D2D', color: '#C4736E', borderRadius: '4px', padding: '2px 8px', fontSize: '0.75rem', cursor: 'pointer' }}
                      >삭제</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* 프록시 추가/수정 모달 */}
      {proxyModalOpen && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => setProxyModalOpen(false)}>
          <div onClick={e => e.stopPropagation()} style={{ ...card, padding: '1.5rem', width: '420px', maxWidth: '90vw' }}>
            <div style={{ fontSize: '0.9375rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '1rem' }}>
              {proxyEditIdx !== null ? '프록시 수정' : '프록시 추가'}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div>
                <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '4px', display: 'block' }}>이름</label>
                <input value={proxyForm.name} onChange={e => setProxyForm((p: ProxyConfigItem) => ({ ...p, name: e.target.value }))}
                  placeholder="프록시칩 1" style={{ ...inputStyle }} />
              </div>
              <div style={{ background: '#141414', border: '1px solid #2D2D2D', borderRadius: '8px', padding: '0.75rem' }}>
                <div style={{ fontSize: '0.75rem', color: '#888', marginBottom: '0.5rem' }}>프록시 인증 정보 <span style={{ color: '#555' }}>(비워두면 메인 IP)</span></div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
                  <div>
                    <label style={{ fontSize: '0.7rem', color: '#666', marginBottom: '2px', display: 'block' }}>Username</label>
                    <input value={proxyFields.username} onChange={e => setProxyFields(f => ({ ...f, username: e.target.value }))}
                      placeholder="username" style={{ ...inputStyle, fontSize: '0.8125rem', fontFamily: 'monospace' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '0.7rem', color: '#666', marginBottom: '2px', display: 'block' }}>Password</label>
                    <input value={proxyFields.password} onChange={e => setProxyFields(f => ({ ...f, password: e.target.value }))}
                      placeholder="password" style={{ ...inputStyle, fontSize: '0.8125rem', fontFamily: 'monospace' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '0.7rem', color: '#666', marginBottom: '2px', display: 'block' }}>IP Address</label>
                    <input value={proxyFields.ip} onChange={e => setProxyFields(f => ({ ...f, ip: e.target.value }))}
                      placeholder="0.0.0.0" style={{ ...inputStyle, fontSize: '0.8125rem', fontFamily: 'monospace' }} />
                  </div>
                  <div>
                    <label style={{ fontSize: '0.7rem', color: '#666', marginBottom: '2px', display: 'block' }}>Port</label>
                    <input value={proxyFields.port} onChange={e => setProxyFields(f => ({ ...f, port: e.target.value }))}
                      placeholder="0000" style={{ ...inputStyle, fontSize: '0.8125rem', fontFamily: 'monospace' }} />
                  </div>
                </div>
              </div>
              <div>
                <label style={{ fontSize: '0.75rem', color: '#888', marginBottom: '6px', display: 'block' }}>용도 (복수 선택 가능)</label>
                <div style={{ display: 'flex', gap: '0.75rem' }}>
                  {([
                    { key: 'transmit' as ProxyPurpose, label: '전송', color: '#00C896' },
                    { key: 'collect' as ProxyPurpose, label: '수집', color: '#FFB84D' },
                    { key: 'autotune' as ProxyPurpose, label: '오토튠', color: '#4C9AFF' },
                  ]).map(({ key, label, color }) => {
                    const active = proxyForm.purposes.includes(key)
                    return (
                      <button key={key} onClick={() => toggleProxyPurpose(key)}
                        style={{
                          padding: '0.35rem 0.75rem', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer',
                          background: active ? `${color}20` : '#1A1A1A',
                          border: `1px solid ${active ? color : '#2D2D2D'}`,
                          color: active ? color : '#666',
                          fontWeight: active ? 600 : 400,
                        }}>{label}</button>
                    )
                  })}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input type="checkbox" checked={proxyForm.enabled} onChange={e => setProxyForm((p: ProxyConfigItem) => ({ ...p, enabled: e.target.checked }))} />
                <label style={{ fontSize: '0.8125rem', color: '#E5E5E5' }}>활성화</label>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1.25rem' }}>
              <button onClick={() => setProxyModalOpen(false)}
                style={{ padding: '0.4rem 1rem', background: '#333', color: '#999', border: 'none', borderRadius: '6px', fontSize: '0.8125rem', cursor: 'pointer' }}>취소</button>
              <button onClick={handleProxySave} disabled={proxySaving}
                style={{ padding: '0.4rem 1rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '6px', fontSize: '0.8125rem', fontWeight: 600, cursor: 'pointer', opacity: proxySaving ? 0.6 : 1 }}>
                {proxySaving ? '저장중...' : '저장'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
