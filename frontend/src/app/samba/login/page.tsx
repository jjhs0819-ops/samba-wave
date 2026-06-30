'use client'

import { useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { userApi } from '@/lib/samba/api/operations'
import { useTheme } from '@/lib/samba/useTheme'

export default function SambaLoginPage() {
  const c = useTheme()
  const router = useRouter()
  const searchParams = useSearchParams()
  const justRegistered = searchParams.get('registered') === '1'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

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
      style={{ background: `linear-gradient(135deg, ${c.pageBg} 0%, ${c.surface} 100%)` }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '400px',
          padding: '2.5rem',
          background: c.surface,
          backdropFilter: 'blur(20px)',
          border: `1px solid ${c.border}`,
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
          <h1 style={{ fontSize: '1.25rem', fontWeight: 800, color: c.text, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
            SAMBA WAVE
          </h1>
          <p style={{ fontSize: '0.75rem', color: c.textMuted, marginTop: '0.25rem' }}>
            무재고 위탁판매 솔루션
          </p>
        </div>

        {/* 가입 완료 안내 */}
        {justRegistered && (
          <p style={{ fontSize: '0.8125rem', color: c.success, marginBottom: '1rem', textAlign: 'center' }}>
            회원가입이 완료되었습니다. 로그인해주세요.
          </p>
        )}

        {/* 폼 */}
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', fontSize: '0.8125rem', color: c.textSub, marginBottom: '0.375rem' }}>
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
                background: c.inputBg,
                border: `1px solid ${c.border}`,
                borderRadius: '8px',
                color: c.text,
                outline: 'none',
                boxSizing: 'border-box',
              }}
              onFocus={(e) => { e.currentTarget.style.borderColor = c.primary }}
              onBlur={(e) => { e.currentTarget.style.borderColor = c.border }}
            />
          </div>

          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ display: 'block', fontSize: '0.8125rem', color: c.textSub, marginBottom: '0.375rem' }}>
              비밀번호
            </label>
            <div style={{ position: 'relative' }}>
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                style={{
                  width: '100%',
                  padding: '0.625rem 2.5rem 0.625rem 0.75rem',
                  fontSize: '0.875rem',
                  background: c.inputBg,
                  border: `1px solid ${c.border}`,
                  borderRadius: '8px',
                  color: c.text,
                  outline: 'none',
                  boxSizing: 'border-box',
                }}
                onFocus={(e) => { e.currentTarget.style.borderColor = c.primary }}
                onBlur={(e) => { e.currentTarget.style.borderColor = c.border }}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                style={{
                  position: 'absolute',
                  right: '0.625rem',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: c.textMuted,
                  fontSize: '0.75rem',
                  padding: '0.25rem',
                }}
              >
                {showPassword ? '숨김' : '표시'}
              </button>
            </div>
          </div>

          {error && (
            <p style={{ fontSize: '0.8125rem', color: c.danger, marginBottom: '1rem', textAlign: 'center' }}>
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
              color: '#fff',
              background: submitting ? c.textMuted : c.primary,
              border: 'none',
              borderRadius: '8px',
              cursor: submitting ? 'not-allowed' : 'pointer',
              transition: 'background 0.2s',
            }}
            onMouseEnter={(e) => { if (!submitting) e.currentTarget.style.background = c.link }}
            onMouseLeave={(e) => { if (!submitting) e.currentTarget.style.background = c.primary }}
          >
            {submitting ? '로그인 중...' : '로그인'}
          </button>
        </form>

        {/* 회원가입 링크 */}
        <p style={{ textAlign: 'center', marginTop: '1.25rem', fontSize: '0.8125rem', color: c.textMuted }}>
          계정이 없으신가요?{' '}
          <a
            href="/samba/sign-up"
            style={{ color: c.primary, fontWeight: 600, textDecoration: 'none' }}
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
