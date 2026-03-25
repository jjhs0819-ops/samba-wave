'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { userApi } from '@/lib/samba/api'

export default function SambaSignUpPage() {
  const router = useRouter()
  const [inviteCode, setInviteCode] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!inviteCode.trim() || !name.trim() || !email.trim() || !password.trim()) {
      setError('모든 항목을 입력해주세요')
      return
    }
    if (password !== passwordConfirm) {
      setError('비밀번호가 일치하지 않습니다')
      return
    }
    if (password.length < 6) {
      setError('비밀번호는 6자 이상이어야 합니다')
      return
    }

    setSubmitting(true)
    try {
      await userApi.create({ email, password, name, invite_code: inviteCode })
      router.replace('/samba/login?registered=1')
    } catch (err) {
      setError(err instanceof Error ? err.message : '회원가입에 실패했습니다')
    } finally {
      setSubmitting(false)
    }
  }

  const inputStyle = {
    width: '100%',
    padding: '0.625rem 0.75rem',
    fontSize: '0.875rem',
    background: '#111520',
    border: '1px solid #2A3040',
    borderRadius: '8px',
    color: '#E5E5E5',
    outline: 'none',
    boxSizing: 'border-box' as const,
  }

  return (
    <div
      className="flex items-center justify-center min-h-screen"
      style={{ background: 'linear-gradient(135deg, #0F0F0F 0%, #1A1A1A 100%)' }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '400px',
          padding: '2.5rem',
          background: 'rgba(30,30,30,0.6)',
          backdropFilter: 'blur(20px)',
          border: '1px solid #2D2D2D',
          borderRadius: '16px',
        }}
      >
        {/* 로고 */}
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <img
            src="/logo.png"
            alt="SAMBA WAVE"
            width={56}
            height={56}
            style={{ borderRadius: '12px', margin: '0 auto 0.75rem' }}
          />
          <h1 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#E5E5E5', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            회원가입
          </h1>
          <p style={{ fontSize: '0.75rem', color: '#666', marginTop: '0.25rem' }}>
            SAMBA WAVE 계정 만들기
          </p>
        </div>

        {/* 폼 */}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', fontSize: '0.8125rem', color: '#888', marginBottom: '0.375rem' }}>
              초대 코드
            </label>
            <input
              type="text"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
              autoFocus
              placeholder="팀장에게 받은 초대 코드"
              style={inputStyle}
              onFocus={(e) => { e.currentTarget.style.borderColor = '#FF8C00' }}
              onBlur={(e) => { e.currentTarget.style.borderColor = '#2A3040' }}
            />
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', fontSize: '0.8125rem', color: '#888', marginBottom: '0.375rem' }}>
              이름
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="name"
              placeholder="홍길동"
              style={inputStyle}
              onFocus={(e) => { e.currentTarget.style.borderColor = '#FF8C00' }}
              onBlur={(e) => { e.currentTarget.style.borderColor = '#2A3040' }}
            />
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', fontSize: '0.8125rem', color: '#888', marginBottom: '0.375rem' }}>
              이메일
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              placeholder="example@email.com"
              style={inputStyle}
              onFocus={(e) => { e.currentTarget.style.borderColor = '#FF8C00' }}
              onBlur={(e) => { e.currentTarget.style.borderColor = '#2A3040' }}
            />
          </div>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', fontSize: '0.8125rem', color: '#888', marginBottom: '0.375rem' }}>
              비밀번호
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              placeholder="6자 이상"
              style={inputStyle}
              onFocus={(e) => { e.currentTarget.style.borderColor = '#FF8C00' }}
              onBlur={(e) => { e.currentTarget.style.borderColor = '#2A3040' }}
            />
          </div>

          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ display: 'block', fontSize: '0.8125rem', color: '#888', marginBottom: '0.375rem' }}>
              비밀번호 확인
            </label>
            <input
              type="password"
              value={passwordConfirm}
              onChange={(e) => setPasswordConfirm(e.target.value)}
              autoComplete="new-password"
              placeholder="비밀번호 재입력"
              style={inputStyle}
              onFocus={(e) => { e.currentTarget.style.borderColor = '#FF8C00' }}
              onBlur={(e) => { e.currentTarget.style.borderColor = '#2A3040' }}
            />
          </div>

          {error && (
            <p style={{ fontSize: '0.8125rem', color: '#FF6B6B', marginBottom: '1rem', textAlign: 'center' }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            style={{
              width: '100%',
              padding: '0.75rem',
              fontSize: '0.9375rem',
              fontWeight: 600,
              color: '#0F0F0F',
              background: submitting ? '#997733' : '#FF8C00',
              border: 'none',
              borderRadius: '8px',
              cursor: submitting ? 'not-allowed' : 'pointer',
              transition: 'background 0.2s',
            }}
            onMouseEnter={(e) => { if (!submitting) e.currentTarget.style.background = '#FFB84D' }}
            onMouseLeave={(e) => { if (!submitting) e.currentTarget.style.background = '#FF8C00' }}
          >
            {submitting ? '가입 중...' : '회원가입'}
          </button>
        </form>

        {/* 로그인 링크 */}
        <p style={{ textAlign: 'center', marginTop: '1.25rem', fontSize: '0.8125rem', color: '#666' }}>
          이미 계정이 있으신가요?{' '}
          <a
            href="/samba/login"
            style={{ color: '#FF8C00', fontWeight: 600, textDecoration: 'none' }}
            onMouseEnter={(e) => { e.currentTarget.style.textDecoration = 'underline' }}
            onMouseLeave={(e) => { e.currentTarget.style.textDecoration = 'none' }}
          >
            로그인
          </a>
        </p>
      </div>
    </div>
  )
}
