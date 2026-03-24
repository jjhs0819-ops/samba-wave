'use client'

import React, { useState } from 'react'

const card = {
  background: 'rgba(30,30,30,0.5)',
  backdropFilter: 'blur(20px)',
  border: '1px solid #2D2D2D',
  borderRadius: '12px',
  padding: '20px',
}

const CHANNELS = [
  { id: 'instagram', name: '인스타그램', color: '#E4405F', icon: '📸' },
  { id: 'blog', name: '네이버블로그', color: '#03C75A', icon: '📝' },
  { id: 'youtube', name: '유튜브', color: '#FF0000', icon: '🎬' },
  { id: 'tiktok', name: '틱톡', color: '#010101', icon: '🎵' },
  { id: 'twitter', name: 'X (트위터)', color: '#1DA1F2', icon: '🐦' },
  { id: 'facebook', name: '페이스북', color: '#1877F2', icon: '👤' },
]

function fmt(n: number) { return n.toLocaleString() }

function getStatusBadge(status: string) {
  const map: Record<string, { bg: string; color: string; label: string }> = {
    published: { bg: 'rgba(81,207,102,0.15)', color: '#51CF66', label: '발행됨' },
    scheduled: { bg: 'rgba(76,154,255,0.15)', color: '#4C9AFF', label: '예약됨' },
    draft: { bg: 'rgba(138,149,176,0.15)', color: '#8A95B0', label: '임시저장' },
    failed: { bg: 'rgba(255,107,107,0.15)', color: '#FF6B6B', label: '실패' },
  }
  const s = map[status] || map.draft
  return (
    <span style={{ fontSize: '0.68rem', padding: '2px 8px', borderRadius: '8px', background: s.bg, color: s.color, fontWeight: 600 }}>
      {s.label}
    </span>
  )
}

export default function SNSPage() {
  const [tab, setTab] = useState<'overview' | 'posts' | 'templates' | 'settings'>('overview')

  return (
    <div style={{ padding: '0' }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#E5E5E5', margin: 0 }}>SNS 마케팅</h2>
          <p style={{ fontSize: '0.78rem', color: '#8A95B0', marginTop: '4px' }}>상품 홍보 · 자동 포스팅 · 채널 관리</p>
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          {(['overview', 'posts', 'templates', 'settings'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px', cursor: 'pointer', fontWeight: 600,
              background: tab === t ? '#FF8C00' : 'rgba(255,255,255,0.05)',
              color: tab === t ? '#000' : '#8A95B0',
              border: tab === t ? 'none' : '1px solid #2D2D2D',
            }}>
              {{ overview: '종합현황', posts: '게시물 관리', templates: '템플릿', settings: '채널 설정' }[t]}
            </button>
          ))}
        </div>
      </div>

      {/* KPI 카드 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
        <div style={card}>
          <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>연결 채널</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#4C9AFF' }}>0개</div>
          <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginTop: '2px' }}>총 {CHANNELS.length}개 지원</div>
        </div>
        <div style={card}>
          <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>이번달 게시물</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#51CF66' }}>0건</div>
        </div>
        <div style={card}>
          <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>예약 게시물</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#FF8C00' }}>0건</div>
        </div>
        <div style={card}>
          <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>템플릿</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#E5E5E5' }}>0개</div>
        </div>
      </div>

      {/* 종합현황 탭 */}
      {tab === 'overview' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          {/* 채널 현황 */}
          <div style={card}>
            <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '16px' }}>채널 현황</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {CHANNELS.map(ch => (
                <div key={ch.id} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '10px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid #2D2D2D' }}>
                  <span style={{ fontSize: '1.2rem' }}>{ch.icon}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#E5E5E5' }}>{ch.name}</div>
                    <div style={{ fontSize: '0.72rem', color: '#8A95B0' }}>미연결</div>
                  </div>
                  <button style={{
                    fontSize: '0.72rem', padding: '4px 12px', background: 'rgba(255,140,0,0.15)',
                    color: '#FF8C00', border: '1px solid rgba(255,140,0,0.3)', borderRadius: '6px', cursor: 'pointer', fontWeight: 600,
                  }}>연결하기</button>
                </div>
              ))}
            </div>
          </div>

          {/* 최근 게시물 */}
          <div style={card}>
            <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '16px' }}>최근 게시물</h3>
            <div style={{ padding: '2rem', textAlign: 'center', color: '#555', fontSize: '0.85rem' }}>
              아직 게시물이 없습니다.<br />
              <span style={{ fontSize: '0.78rem', color: '#8A95B0' }}>채널을 연결하고 첫 게시물을 작성해보세요.</span>
            </div>
          </div>
        </div>
      )}

      {/* 게시물 관리 탭 */}
      {tab === 'posts' && (
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', margin: 0 }}>게시물 목록</h3>
            <button style={{
              padding: '6px 14px', fontSize: '0.78rem', background: '#FF8C00', color: '#000',
              border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600,
            }}>+ 새 게시물</button>
          </div>
          <div style={{ padding: '2rem', textAlign: 'center', color: '#555', fontSize: '0.85rem' }}>
            게시물이 없습니다. 상품을 선택하여 SNS 홍보 게시물을 만들어보세요.
          </div>
        </div>
      )}

      {/* 템플릿 탭 */}
      {tab === 'templates' && (
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', margin: 0 }}>게시물 템플릿</h3>
            <button style={{
              padding: '6px 14px', fontSize: '0.78rem', background: '#FF8C00', color: '#000',
              border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600,
            }}>+ 템플릿 추가</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
            {/* 기본 템플릿 3개 */}
            {[
              { name: '신상품 소개', desc: '상품 이미지 + 가격 + 구매링크', tags: '#신상 #추천 #{브랜드명}' },
              { name: '할인 이벤트', desc: '할인율 강조 + 한정수량 + 구매링크', tags: '#세일 #할인 #{브랜드명}' },
              { name: '스타일링 추천', desc: '착용샷 + 코디 추천 + 구매링크', tags: '#코디 #데일리룩 #{브랜드명}' },
            ].map((tpl, i) => (
              <div key={i} style={{ padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px dashed #3D3D3D' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '6px' }}>{tpl.name}</div>
                <div style={{ fontSize: '0.75rem', color: '#8A95B0', marginBottom: '8px', lineHeight: 1.4 }}>{tpl.desc}</div>
                <div style={{ fontSize: '0.7rem', color: '#FF8C00' }}>{tpl.tags}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 채널 설정 탭 */}
      {tab === 'settings' && (
        <div style={card}>
          <h3 style={{ fontSize: '0.9rem', fontWeight: 600, color: '#E5E5E5', marginBottom: '16px' }}>채널 연동 설정</h3>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                <th style={{ padding: '10px', textAlign: 'left', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>채널</th>
                <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>상태</th>
                <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>계정</th>
                <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>자동 포스팅</th>
                <th style={{ padding: '10px', textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0', fontWeight: 500 }}>관리</th>
              </tr>
            </thead>
            <tbody>
              {CHANNELS.map(ch => (
                <tr key={ch.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                  <td style={{ padding: '10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '1.1rem' }}>{ch.icon}</span>
                      <span style={{ fontSize: '0.82rem', color: '#E5E5E5', fontWeight: 600 }}>{ch.name}</span>
                    </div>
                  </td>
                  <td style={{ padding: '10px', textAlign: 'center' }}>
                    <span style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: '8px', background: 'rgba(138,149,176,0.15)', color: '#8A95B0', fontWeight: 600 }}>미연결</span>
                  </td>
                  <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.78rem', color: '#555' }}>-</td>
                  <td style={{ padding: '10px', textAlign: 'center', fontSize: '0.78rem', color: '#555' }}>-</td>
                  <td style={{ padding: '10px', textAlign: 'center' }}>
                    <button style={{
                      fontSize: '0.72rem', padding: '4px 12px', background: 'rgba(255,140,0,0.15)',
                      color: '#FF8C00', border: '1px solid rgba(255,140,0,0.3)', borderRadius: '4px', cursor: 'pointer',
                    }}>연결</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
