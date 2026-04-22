'use client'

import { useEffect, useState, useCallback } from 'react'
import { userApi, type SambaUser } from '@/lib/samba/api/operations'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { inputStyle } from '@/lib/samba/styles'
import { fmtDate, fmtDateTime } from '@/lib/samba/utils'
import { fetchWithAuth, SAMBA_PREFIX } from '@/lib/samba/legacy'

interface License {
  id: string
  license_key: string
  buyer_name: string
  buyer_email: string
  is_active: boolean
  expires_at: string | null
  last_verified_at: string | null
  created_at: string
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  active: { label: '활성', color: '#51CF66' },
  draft: { label: '대기', color: '#FFD93D' },
  inactive: { label: '비활성', color: '#888' },
  suspended: { label: '정지', color: '#FF6B6B' },
}

interface LoginHistory {
  id: string
  email: string
  ip_address: string | null
  region: string | null
  created_at: string
}

// IP 마스킹 (222.109.12.34 → 222.109.**)
const maskIp = (ip: string | null) => {
  if (!ip) return '-'
  const parts = ip.split('.')
  if (parts.length === 4) return `${parts[0]}.${parts[1]}.**.**`
  return ip
}

// 년/월/일 select용 헬퍼
const years = () => {
  const cur = new Date().getFullYear()
  return Array.from({ length: 3 }, (_, i) => cur - i)
}
const months = () => Array.from({ length: 12 }, (_, i) => i + 1)
const daysInMonth = (y: number, m: number) => new Date(y, m, 0).getDate()

const pad = (n: number) => String(n).padStart(2, '0')

const selectStyle: React.CSSProperties = {
  padding: '0.35rem 0.5rem', fontSize: '0.8rem', background: '#1A1A1A',
  border: '1px solid #333', color: '#E5E5E5', borderRadius: '4px', cursor: 'pointer',
}
const thStyle: React.CSSProperties = {
  padding: '0.6rem 1rem', textAlign: 'center', fontSize: '0.75rem', color: '#888',
}
const tdStyle: React.CSSProperties = {
  padding: '0.5rem 1rem', textAlign: 'center', fontSize: '0.8rem', color: '#C5C5C5',
}

// 로그인 일시 포맷: 2026-04-07 [08:44:50] — KST 명시적 변환
const fmtLoginDate = (iso: string) => fmtDateTime(iso)

export default function UsersPage() {
  useEffect(() => { document.title = 'SAMBA-사용자' }, [])
  const [users, setUsers] = useState<SambaUser[]>([])
  const [loading, setLoading] = useState(true)

  // 생성/수정 모달
  const [showModal, setShowModal] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState({ name: '', email: '', password: '', is_admin: false })
  const [showPassword, setShowPassword] = useState(false)

  // 라이선스 관리
  const [licenses, setLicenses] = useState<License[]>([])
  const [licForm, setLicForm] = useState({ buyer_name: '', buyer_email: '', expires_at: '', notes: '' })
  const [licCreating, setLicCreating] = useState(false)

  const loadLicenses = useCallback(async () => {
    const res = await fetchWithAuth(`${SAMBA_PREFIX}/admin/licenses`)
    if (res.ok) setLicenses(await res.json())
  }, [])

  useEffect(() => { loadLicenses() }, [loadLicenses])

  const createLicense = async () => {
    setLicCreating(true)
    try {
      const res = await fetchWithAuth(`${SAMBA_PREFIX}/admin/licenses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          buyer_name: licForm.buyer_name,
          buyer_email: licForm.buyer_email,
          expires_at: licForm.expires_at ? new Date(licForm.expires_at).toISOString() : null,
          notes: licForm.notes || null,
        }),
      })
      if (res.ok) {
        setLicForm({ buyer_name: '', buyer_email: '', expires_at: '', notes: '' })
        await loadLicenses()
        showAlert('라이선스가 발급되었습니다', 'success')
      } else {
        const err = await res.json().catch(() => ({}))
        showAlert(`발급 실패 (${res.status}): ${err.detail ?? '알 수 없는 오류'}`, 'error')
      }
    } catch (e) {
      showAlert(`발급 실패: ${e instanceof Error ? e.message : e}`, 'error')
    } finally {
      setLicCreating(false)
    }
  }

  const toggleLicense = async (id: string, isActive: boolean) => {
    await fetchWithAuth(`${SAMBA_PREFIX}/admin/licenses/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: isActive }),
    })
    await loadLicenses()
  }

  const deleteLicense = async (id: string, key: string) => {
    if (!await showConfirm(`${key} 라이선스를 삭제하시겠습니까?`)) return
    await fetchWithAuth(`${SAMBA_PREFIX}/admin/licenses/${id}`, { method: 'DELETE' })
    await loadLicenses()
  }

  // 로그인 기록
  const now = new Date()
  const [startY, setStartY] = useState(now.getFullYear())
  const [startM, setStartM] = useState(now.getMonth() + 1)
  const [startD, setStartD] = useState(now.getDate())
  const [endY, setEndY] = useState(now.getFullYear())
  const [endM, setEndM] = useState(now.getMonth() + 1)
  const [endD, setEndD] = useState(now.getDate())
  const [loginLogs, setLoginLogs] = useState<LoginHistory[]>([])
  const [logLoading, setLogLoading] = useState(false)

  const searchLogs = useCallback(async () => {
    setLogLoading(true)
    try {
      const start = `${startY}-${pad(startM)}-${pad(startD)}`
      const end = `${endY}-${pad(endM)}-${pad(endD)}`
      setLoginLogs(await userApi.loginHistory(start, end))
    } catch { /* ignore */ }
    setLogLoading(false)
  }, [startY, startM, startD, endY, endM, endD])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setUsers(await userApi.list(0, 200))
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { load() }, [load])

  const openCreate = () => {
    setEditingId(null)
    setForm({ name: '', email: '', password: '', is_admin: false })
    setShowPassword(false)
    setShowModal(true)
  }

  const openEdit = (u: SambaUser) => {
    setEditingId(u.id)
    setForm({ name: u.name || '', email: u.email || '', password: '', is_admin: u.is_admin })
    setShowPassword(false)
    setShowModal(true)
  }

  const handleSave = async () => {
    if (!form.name.trim() || !form.email.trim()) {
      showAlert('이름과 이메일을 입력해주세요', 'error')
      return
    }
    try {
      if (editingId) {
        const update: Record<string, unknown> = { name: form.name, email: form.email, is_admin: form.is_admin }
        if (form.password) update.password = form.password
        await userApi.update(editingId, update as Parameters<typeof userApi.update>[1])
        showAlert('계정이 수정되었습니다', 'success')
      } else {
        if (!form.password || form.password.length < 6) {
          showAlert('비밀번호를 6자 이상 입력해주세요', 'error')
          return
        }
        await userApi.create({ name: form.name, email: form.email, password: form.password, is_admin: form.is_admin })
        showAlert('계정이 생성되었습니다', 'success')
      }
      setShowModal(false)
      load()
    } catch (e) {
      showAlert(`저장 실패: ${e instanceof Error ? e.message : e}`, 'error')
    }
  }

  const handleDelete = async (u: SambaUser) => {
    if (!await showConfirm(`${u.name || u.email} 계정을 삭제하시겠습니까?`)) return
    try {
      await userApi.delete(u.id)
      showAlert('계정이 삭제되었습니다', 'success')
      load()
    } catch {
      showAlert('삭제 실패', 'error')
    }
  }

  const handleToggleStatus = async (u: SambaUser) => {
    const newStatus = u.status === 'active' ? 'inactive' : 'active'
    try {
      await userApi.update(u.id, { status: newStatus })
      load()
    } catch {
      showAlert('상태 변경 실패', 'error')
    }
  }

  return (
    <div style={{ color: '#E5E5E5' }}>
      {/* 라이선스 발급 */}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', padding: '1.5rem', marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 700, marginBottom: '1.25rem' }}>라이선스 발급</h2>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '0.75rem' }}>
          <input placeholder="구매자 이름" value={licForm.buyer_name}
            onChange={e => setLicForm(p => ({ ...p, buyer_name: e.target.value }))}
            style={{ ...inputStyle, fontSize: '0.85rem' }} />
          <input placeholder="구매자 연락처" value={licForm.buyer_email}
            onChange={e => setLicForm(p => ({ ...p, buyer_email: e.target.value }))}
            style={{ ...inputStyle, fontSize: '0.85rem' }} />
          <input type="date" value={licForm.expires_at}
            onChange={e => setLicForm(p => ({ ...p, expires_at: e.target.value }))}
            title="만료일 (비워두면 영구)"
            style={{ ...inputStyle, fontSize: '0.85rem' }} />
          <input placeholder="메모 (선택)" value={licForm.notes}
            onChange={e => setLicForm(p => ({ ...p, notes: e.target.value }))}
            style={{ ...inputStyle, fontSize: '0.85rem' }} />
        </div>
        <button onClick={createLicense} disabled={licCreating || !licForm.buyer_name || !licForm.buyer_email}
          style={{ padding: '0.5rem 1.25rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '8px', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer', opacity: licCreating || !licForm.buyer_name || !licForm.buyer_email ? 0.5 : 1 }}>
          {licCreating ? '발급 중...' : '발급'}
        </button>

        {/* 라이선스 목록 */}
        {licenses.length > 0 && (
          <div style={{ marginTop: '1.25rem', overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2A2A2A' }}>
                  {['키', '구매자', '만료일', '마지막 검증', '상태', ''].map(h => (
                    <th key={h} style={{ ...thStyle, textAlign: 'left' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {licenses.map(lic => (
                  <tr key={lic.id} style={{ borderBottom: '1px solid #1A1A1A' }}>
                    <td style={{ ...tdStyle, textAlign: 'left', fontFamily: 'monospace', fontSize: '0.75rem', color: '#AAA' }}>{lic.license_key}</td>
                    <td style={{ ...tdStyle, textAlign: 'left' }}>
                      <div>{lic.buyer_name}</div>
                      <div style={{ color: '#666', fontSize: '0.72rem' }}>{lic.buyer_email}</div>
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'left' }}>{lic.expires_at ? lic.expires_at.slice(0, 10) : '영구'}</td>
                    <td style={{ ...tdStyle, textAlign: 'left', color: '#666', fontSize: '0.75rem' }}>
                      {lic.last_verified_at ? lic.last_verified_at.slice(0, 16).replace('T', ' ') : '-'}
                    </td>
                    <td style={tdStyle}>
                      <span style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '0.72rem', background: lic.is_active ? 'rgba(74,222,128,0.15)' : 'rgba(255,107,107,0.15)', color: lic.is_active ? '#4ADE80' : '#FF6B6B' }}>
                        {lic.is_active ? '활성' : '비활성'}
                      </span>
                    </td>
                    <td style={tdStyle}>
                      <div style={{ display: 'flex', gap: '6px', justifyContent: 'center' }}>
                        <button onClick={() => toggleLicense(lic.id, !lic.is_active)}
                          style={{ padding: '3px 10px', fontSize: '0.72rem', background: '#2A2A2A', color: '#AAA', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
                          {lic.is_active ? '비활성화' : '활성화'}
                        </button>
                        <button onClick={() => deleteLicense(lic.id, lic.license_key)}
                          style={{ padding: '3px 10px', fontSize: '0.72rem', background: 'rgba(255,107,107,0.15)', color: '#FF6B6B', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
                          삭제
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>계정 관리</h2>
          <p style={{ fontSize: '0.875rem', color: '#888' }}>로그인 가능한 사용자 계정을 관리합니다</p>
        </div>
        <button
          onClick={openCreate}
          style={{ padding: '0.625rem 1.25rem', background: '#FF8C00', color: '#fff', border: 'none', borderRadius: '8px', fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer' }}
        >
          + 계정 추가
        </button>
      </div>

      {/* 테이블 */}
      <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #1C2030' }}>
              <th style={{ padding: '0.75rem 1rem', textAlign: 'left', fontSize: '0.75rem', color: '#888', width: '50px' }}>No</th>
              <th style={{ padding: '0.75rem 1rem', textAlign: 'left', fontSize: '0.75rem', color: '#888' }}>이름</th>
              <th style={{ padding: '0.75rem 1rem', textAlign: 'left', fontSize: '0.75rem', color: '#888' }}>이메일</th>
              <th style={{ padding: '0.75rem 1rem', textAlign: 'center', fontSize: '0.75rem', color: '#888', width: '80px' }}>권한</th>
              <th style={{ padding: '0.75rem 1rem', textAlign: 'center', fontSize: '0.75rem', color: '#888', width: '80px' }}>상태</th>
              <th style={{ padding: '0.75rem 1rem', textAlign: 'center', fontSize: '0.75rem', color: '#888', width: '150px' }}>생성일</th>
              <th style={{ padding: '0.75rem 1rem', textAlign: 'center', fontSize: '0.75rem', color: '#888', width: '180px' }}>관리</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>로딩 중...</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={7} style={{ padding: '3rem', textAlign: 'center', color: '#555' }}>등록된 계정이 없습니다</td></tr>
            ) : users.map((u, idx) => {
              const st = STATUS_MAP[u.status] || { label: u.status, color: '#888' }
              return (
                <tr key={u.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <td style={{ padding: '0.625rem 1rem', fontSize: '0.8rem', color: '#666' }}>{idx + 1}</td>
                  <td style={{ padding: '0.625rem 1rem', fontSize: '0.8rem' }}>{u.name || '-'}</td>
                  <td style={{ padding: '0.625rem 1rem', fontSize: '0.8rem', color: '#B0B0B0' }}>{u.email || '-'}</td>
                  <td style={{ padding: '0.625rem 1rem', textAlign: 'center' }}>
                    <span style={{
                      fontSize: '0.72rem', padding: '2px 8px', borderRadius: '4px',
                      background: u.is_admin ? 'rgba(255,140,0,0.15)' : 'rgba(100,100,100,0.15)',
                      color: u.is_admin ? '#FF8C00' : '#888',
                    }}>{u.is_admin ? '관리자' : '일반'}</span>
                  </td>
                  <td style={{ padding: '0.625rem 1rem', textAlign: 'center' }}>
                    <button
                      onClick={() => handleToggleStatus(u)}
                      style={{
                        fontSize: '0.72rem', padding: '2px 8px', borderRadius: '4px', border: 'none', cursor: 'pointer',
                        background: `${st.color}20`, color: st.color,
                      }}
                    >{st.label}</button>
                  </td>
                  <td style={{ padding: '0.625rem 1rem', textAlign: 'center', fontSize: '0.75rem', color: '#666' }}>{fmtDate(u.created_at)}</td>
                  <td style={{ padding: '0.625rem 1rem', textAlign: 'center' }}>
                    <div style={{ display: 'flex', gap: '4px', justifyContent: 'center' }}>
                      <button onClick={() => openEdit(u)}
                        style={{ fontSize: '0.72rem', padding: '3px 10px', background: 'rgba(76,154,255,0.1)', border: '1px solid rgba(76,154,255,0.3)', color: '#4C9AFF', borderRadius: '4px', cursor: 'pointer' }}
                      >수정</button>
                      <button onClick={() => handleDelete(u)}
                        style={{ fontSize: '0.72rem', padding: '3px 10px', background: 'rgba(255,107,107,0.1)', border: '1px solid rgba(255,107,107,0.3)', color: '#FF6B6B', borderRadius: '4px', cursor: 'pointer' }}
                      >삭제</button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 로그인 기록 */}
      <div style={{ marginTop: '2.5rem' }}>
        <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>로그인 기록보기</h3>

        {/* 날짜 필터 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <select value={startY} onChange={e => setStartY(Number(e.target.value))} style={selectStyle}>{years().map(y => <option key={y} value={y}>{y}년</option>)}</select>
          <select value={startM} onChange={e => setStartM(Number(e.target.value))} style={selectStyle}>{months().map(m => <option key={m} value={m}>{m}월</option>)}</select>
          <select value={startD} onChange={e => setStartD(Number(e.target.value))} style={selectStyle}>{Array.from({ length: daysInMonth(startY, startM) }, (_, i) => i + 1).map(d => <option key={d} value={d}>{d}일</option>)}</select>
          <span style={{ color: '#666' }}>~</span>
          <select value={endY} onChange={e => setEndY(Number(e.target.value))} style={selectStyle}>{years().map(y => <option key={y} value={y}>{y}년</option>)}</select>
          <select value={endM} onChange={e => setEndM(Number(e.target.value))} style={selectStyle}>{months().map(m => <option key={m} value={m}>{m}월</option>)}</select>
          <select value={endD} onChange={e => setEndD(Number(e.target.value))} style={selectStyle}>{Array.from({ length: daysInMonth(endY, endM) }, (_, i) => i + 1).map(d => <option key={d} value={d}>{d}일</option>)}</select>
          <button onClick={searchLogs}
            style={{ padding: '0.4rem 1rem', fontSize: '0.8rem', background: '#333', border: '1px solid #444', color: '#E5E5E5', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}>
            검색
          </button>
        </div>

        {/* 로그인 기록 테이블 */}
        <div style={{ background: 'rgba(18,18,18,0.98)', border: '1px solid #232323', borderRadius: '10px', overflow: 'hidden' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #1C2030' }}>
                <th style={thStyle}>접속일시</th>
                <th style={thStyle}>아이디</th>
                <th style={thStyle}>접속 IP</th>
                <th style={thStyle}>접속 지역</th>
              </tr>
            </thead>
            <tbody>
              {logLoading ? (
                <tr><td colSpan={4} style={{ padding: '2rem', textAlign: 'center', color: '#555' }}>조회 중...</td></tr>
              ) : loginLogs.length === 0 ? (
                <tr><td colSpan={4} style={{ padding: '2rem', textAlign: 'center', color: '#555' }}>검색 버튼을 눌러주세요</td></tr>
              ) : loginLogs.map(log => (
                <tr key={log.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                  <td style={tdStyle}>{fmtLoginDate(log.created_at)}</td>
                  <td style={{ ...tdStyle, color: '#4C9AFF' }}>{log.email}</td>
                  <td style={tdStyle}>{maskIp(log.ip_address)}</td>
                  <td style={tdStyle}>{log.region || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 생성/수정 모달 */}
      {showModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => setShowModal(false)}
        >
          <div style={{ background: '#1A1A1A', border: '1px solid #2D2D2D', borderRadius: '12px', padding: '1.5rem', width: '420px', maxWidth: '90vw' }}
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>
              {editingId ? '계정 수정' : '계정 추가'}
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div>
                <label style={{ fontSize: '0.78rem', color: '#888', marginBottom: '4px', display: 'block' }}>이름</label>
                <input style={inputStyle} value={form.name} onChange={e => setForm(prev => ({ ...prev, name: e.target.value }))} placeholder="사용자 이름" />
              </div>
              <div>
                <label style={{ fontSize: '0.78rem', color: '#888', marginBottom: '4px', display: 'block' }}>이메일</label>
                <input style={inputStyle} type="email" value={form.email} onChange={e => setForm(prev => ({ ...prev, email: e.target.value }))} placeholder="login@example.com" />
              </div>
              <div>
                <label style={{ fontSize: '0.78rem', color: '#888', marginBottom: '4px', display: 'block' }}>
                  비밀번호 {editingId && <span style={{ color: '#555' }}>(빈칸이면 변경 안 함)</span>}
                </label>
                <div style={{ position: 'relative' }}>
                  <input style={{ ...inputStyle, paddingRight: '2.5rem' }} type={showPassword ? 'text' : 'password'} value={form.password} onChange={e => setForm(prev => ({ ...prev, password: e.target.value }))} placeholder="6자 이상" />
                  <button type="button" onClick={() => setShowPassword(v => !v)}
                    style={{ position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', color: '#888', cursor: 'pointer', padding: '4px', fontSize: '0.85rem' }}>
                    {showPassword ? '🙈' : '👁'}
                  </button>
                </div>
              </div>
              <div>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8rem', color: '#C5C5C5', cursor: 'pointer' }}>
                  <input type="checkbox" checked={form.is_admin} onChange={e => setForm(prev => ({ ...prev, is_admin: e.target.checked }))}
                    style={{ accentColor: '#FF8C00', width: '16px', height: '16px' }} />
                  관리자 권한
                </label>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', marginTop: '1.25rem' }}>
              <button onClick={() => setShowModal(false)}
                style={{ padding: '0.5rem 1.25rem', fontSize: '0.85rem', background: 'transparent', border: '1px solid #3D3D3D', color: '#C5C5C5', borderRadius: '6px', cursor: 'pointer' }}
              >취소</button>
              <button onClick={handleSave}
                style={{ padding: '0.5rem 1.25rem', fontSize: '0.85rem', background: '#FF8C00', border: 'none', color: '#fff', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}
              >{editingId ? '수정' : '생성'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
