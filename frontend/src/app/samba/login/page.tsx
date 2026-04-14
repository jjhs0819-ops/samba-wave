'use client'

import { useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { userApi } from '@/lib/samba/api/operations'

export default function SambaLoginPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const justRegistered = searchParams.get('registered') === '1'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!email.trim() || !password.trim()) {
      setError('이메일과 비밀번호를 입력해주세요')
      return
    }
    setSubmitting(true)
    try {
      const user = await userApi.login(email, password)
      // JWT 토큰과 사용자 정보를 localStorage + 쿠키에 저장
      const token = user.access_token || user.token
      if (token) {
        localStorage.setItem('samba_token', token)
        // 미들웨어(서버사이드) 인증을 위해 쿠키에도 토큰 설정
        document.cookie = `samba_user=${token}; path=/; max-age=${60 * 60 * 24 * 30}; SameSite=Lax`
      }
      localStorage.setItem('samba_user', JSON.stringify(user))
      router.replace('/samba')
    } catch (err) {
      setError(err instanceof Error ? err.message : '로그인에 실패했습니다')
    } finally {
      setSubmitting(false)
    }
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
            SAMBA WAVE
          </h1>
          <p style={{ fontSize: '0.75rem', color: '#666', marginTop: '0.25rem' }}>
            무재고 위탁판매 솔루션
          </p>
        </div>

        {/* 가입 완료 안내 */}
        {justRegistered && (
          <p style={{ fontSize: '0.8125rem', color: '#51CF66', marginBottom: '1rem', textAlign: 'center' }}>
            회원가입이 완료되었습니다. 로그인해주세요.
          </p>
        )}

        {/* 폼 */}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', fontSize: '0.8125rem', color: '#888', marginBottom: '0.375rem' }}>
              이메일
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              autoFocus
              style={{
                width: '100%',
                padding: '0.625rem 0.75rem',
                fontSize: '0.875rem',
                background: '#111520',
                border: '1px solid #2A3040',
                borderRadius: '8px',
                color: '#E5E5E5',
                outline: 'none',
                boxSizing: 'border-box',
              }}
              onFocus={(e) => { e.currentTarget.style.borderColor = '#FF8C00' }}
              onBlur={(e) => { e.currentTarget.style.borderColor = '#2A3040' }}
            />
          </div>

          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ display: 'block', fontSize: '0.8125rem', color: '#888', marginBottom: '0.375rem' }}>
              비밀번호
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              style={{
                width: '100%',
                padding: '0.625rem 0.75rem',
                fontSize: '0.875rem',
                background: '#111520',
                border: '1px solid #2A3040',
                borderRadius: '8px',
                color: '#E5E5E5',
                outline: 'none',
                boxSizing: 'border-box',
              }}
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
            {submitting ? '로그인 중...' : '로그인'}
          </button>
        </form>

        {/* 회원가입 링크 */}
        <p style={{ textAlign: 'center', marginTop: '1.25rem', fontSize: '0.8125rem', color: '#666' }}>
          계정이 없으신가요?{' '}
          <a
            href="/samba/sign-up"
            style={{ color: '#FF8C00', fontWeight: 600, textDecoration: 'none' }}
            onMouseEnter={(e) => { e.currentTarget.style.textDecoration = 'underline' }}
            onMouseLeave={(e) => { e.currentTarget.style.textDecoration = 'none' }}
          >
            회원가입
          </a>
        </p>
      </div>
    </div>
  )
}
