'use client'

export default function CSPage() {
  return (
    <div style={{ color: '#E5E5E5' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, color: '#E5E5E5', marginBottom: '0.25rem' }}>CS</h2>
          <p style={{ fontSize: '0.875rem', color: '#888' }}>고객 문의 및 CS 요청을 관리합니다</p>
        </div>
      </div>

      <div style={{
        background: 'rgba(22,22,22,0.9)',
        border: '1px solid #2A2A2A',
        borderRadius: '10px',
        padding: '3rem',
        textAlign: 'center',
        color: '#555',
        fontSize: '0.9rem',
      }}>
        CS 관리 기능 준비중입니다
      </div>
    </div>
  )
}
