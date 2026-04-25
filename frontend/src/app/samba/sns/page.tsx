'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchWithAuth } from '@/lib/samba/api/shared'
import { snsApi, wholesaleApi } from '@/lib/samba/api/operations'
import { fmtNum } from '@/lib/samba/styles'
import { showAlert, showConfirm } from '@/components/samba/Modal'
import { fmtDate as _fmtDate } from '@/lib/samba/utils'
import {
  type TabType, type DashboardData, type PostItem, type PostsResponse,
  type WpSite, type KeywordGroup, type SseLog,
  type WholesaleProduct, type WholesaleSearchResult,
  TAB_LIST, ISSUE_CATEGORIES, cardPad, getStatusBadge,
  btnPrimary, btnDanger, btnOutline, thStyle, tdStyle, sectionTitle, inputBox, selectStyle,
} from './constants'

const fmtDate = (iso: string | undefined | null) => _fmtDate(iso, '.')

// ── 메인 컴포넌트 ──

export default function SNSPage() {
  useEffect(() => { document.title = 'SAMBA-SNS' }, [])
  const [tab, setTab] = useState<TabType>('overview')

  // 종합현황
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [recentPosts, setRecentPosts] = useState<PostItem[]>([])

  // 자동 포스팅
  const [wpSites, setWpSites] = useState<WpSite[]>([])
  const [wpForm, setWpForm] = useState({ site_url: '', username: '', app_password: '' })
  const [wpConnecting, setWpConnecting] = useState(false)
  const [keywordGroups, setKeywordGroups] = useState<KeywordGroup[]>([])
  const [kwForm, setKwForm] = useState({ name: '', category: 'politics', keywords: '' })
  const [autoConfig, setAutoConfig] = useState({
    interval_minutes: '300',
    max_daily_posts: '30',
    language: 'ko',
    product_banner_html: '',
  })
  const [autoRunning, setAutoRunning] = useState(false)
  const [activeSiteId, setActiveSiteId] = useState('')
  const [sseLogs, setSseLogs] = useState<SseLog[]>([])
  const sseAbortRef = useRef<AbortController | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  // 게시물 관리
  const [posts, setPosts] = useState<PostItem[]>([])
  const [postsTotal, setPostsTotal] = useState(0)
  const [postsPage, setPostsPage] = useState(1)
  const [postsTotalPages, setPostsTotalPages] = useState(1)
  const [postsFilter, setPostsFilter] = useState<string>('')

  // 상품 연동
  const [wsSource, setWsSource] = useState('도매매')
  const [wsKeyword, setWsKeyword] = useState('')
  const [wsResults, setWsResults] = useState<WholesaleProduct[]>([])
  const [wsSearching, setWsSearching] = useState(false)
  const [bannerHtml, setBannerHtml] = useState('')

  // ── 데이터 로드 ──

  const loadDashboard = useCallback(async () => {
    try {
      const data = await snsApi.getDashboard() as DashboardData
      setDashboard(data)
    } catch {
      // 대시보드 로드 실패 — 초기값 유지
    }
  }, [])

  const loadRecentPosts = useCallback(async () => {
    try {
      const data = await snsApi.listPosts(1) as PostsResponse
      setRecentPosts((data.items || []).slice(0, 5))
    } catch {
      // 최근 포스트 로드 실패
    }
  }, [])

  const loadWpSites = useCallback(async () => {
    try {
      const data = await snsApi.listWpSites() as { items: WpSite[] }
      const items = data?.items || []
      setWpSites(items)
      if (items.length && !activeSiteId) {
        setActiveSiteId(items[0].id)
      }
    } catch {
      // WP 사이트 로드 실패
    }
  }, [activeSiteId])

  const loadKeywordGroups = useCallback(async () => {
    try {
      const data = await snsApi.listKeywordGroups() as { items: KeywordGroup[] }
      setKeywordGroups(data?.items || [])
    } catch {
      // 키워드 그룹 로드 실패
    }
  }, [])

  const loadPosts = useCallback(async (page: number, status?: string) => {
    try {
      const data = await snsApi.listPosts(page, status || undefined) as PostsResponse
      setPosts(data.items || [])
      setPostsTotal(data.total || 0)
      setPostsTotalPages(data.pages || 1)
    } catch {
      // 포스트 목록 로드 실패
    }
  }, [])

  useEffect(() => {
    if (tab === 'overview') {
      loadDashboard()
      loadRecentPosts()
    }
    if (tab === 'auto-posting') {
      loadWpSites()
      loadKeywordGroups()
    }
    if (tab === 'posts') {
      loadPosts(postsPage, postsFilter)
    }
    if (tab === 'settings') {
      loadWpSites()
    }
  }, [tab, postsPage, postsFilter, loadDashboard, loadRecentPosts, loadWpSites, loadKeywordGroups, loadPosts])

  // SSE 로그 자동 스크롤
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [sseLogs])

  // ── 핸들러 ──

  const handleConnectWp = async () => {
    if (!wpForm.site_url || !wpForm.username || !wpForm.app_password) {
      showAlert('모든 필드를 입력하세요.', 'error')
      return
    }
    setWpConnecting(true)
    try {
      await snsApi.connectWp(wpForm)
      showAlert('워드프레스 연결 성공!', 'success')
      setWpForm({ site_url: '', username: '', app_password: '' })
      await loadWpSites()
    } catch (e) {
      showAlert(`연결 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    } finally {
      setWpConnecting(false)
    }
  }

  const handleAddKeywordGroup = async () => {
    if (!kwForm.name || !kwForm.keywords) {
      showAlert('그룹명과 키워드를 입력하세요.', 'error')
      return
    }
    try {
      const keywords = kwForm.keywords.split(',').map(k => k.trim()).filter(Boolean)
      await snsApi.createKeywordGroup({ name: kwForm.name, category: kwForm.category, keywords })
      showAlert('키워드 그룹 추가 완료', 'success')
      setKwForm({ name: '', category: 'politics', keywords: '' })
      await loadKeywordGroups()
    } catch (e) {
      showAlert(`추가 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  const handleDeleteKeywordGroup = async (id: string) => {
    const ok = await showConfirm('키워드 그룹을 삭제하시겠습니까?')
    if (!ok) return
    try {
      await snsApi.deleteKeywordGroup(id)
      await loadKeywordGroups()
    } catch (e) {
      showAlert(`삭제 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  const handleSaveAutoConfig = async () => {
    if (!activeSiteId) {
      showAlert('WP 사이트를 먼저 연결하세요.', 'error')
      return
    }
    try {
      await snsApi.saveAutoConfig({
        wp_site_id: activeSiteId,
        interval_minutes: Number(autoConfig.interval_minutes) || 300,
        max_daily_posts: Number(autoConfig.max_daily_posts) || 30,
        language: autoConfig.language,
        product_banner_html: autoConfig.product_banner_html || undefined,
      })
      showAlert('자동 포스팅 설정 저장 완료', 'success')
    } catch (e) {
      showAlert(`설정 저장 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    }
  }

  const handleStartAutoPosting = async () => {
    if (!activeSiteId) {
      showAlert('WP 사이트를 선택하세요.', 'error')
      return
    }

    // 설정 저장 먼저
    await handleSaveAutoConfig()

    setAutoRunning(true)
    setSseLogs([])

    const abortController = new AbortController()
    sseAbortRef.current = abortController

    try {
      const url = snsApi.getAutoPostingUrl(activeSiteId)
      const res = await fetchWithAuth(url, {
        method: 'POST',
        signal: abortController.signal,
      })

      const reader = res.body?.getReader()
      if (!reader) return

      const decoder = new TextDecoder()
      const readStream = async () => {
        let running = true
        while (running) {
          const { done, value } = await reader.read()
          if (done) {
            running = false
            break
          }
          const text = decoder.decode(value)
          const lines = text.split('\n').filter(l => l.startsWith('data: '))
          lines.forEach(line => {
            try {
              const data = JSON.parse(line.replace('data: ', '')) as SseLog
              setSseLogs(prev => [...prev, data])
              if (data.event === 'done' || data.event === 'error') {
                setAutoRunning(false)
              }
            } catch {
              // JSON 파싱 실패 무시
            }
          })
        }
        setAutoRunning(false)
      }

      readStream()
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        showAlert(`자동 포스팅 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
      }
      setAutoRunning(false)
    }
  }

  const handleStopAutoPosting = async () => {
    sseAbortRef.current?.abort()
    try {
      if (activeSiteId) {
        await snsApi.stopAutoPosting(activeSiteId)
      }
    } catch {
      // 중지 요청 실패 무시
    }
    setAutoRunning(false)
    setSseLogs(prev => [...prev, { event: 'log', message: '자동 포스팅 중지됨' }])
  }

  const handleWholesaleSearch = async () => {
    if (!wsKeyword) {
      showAlert('검색 키워드를 입력하세요.', 'error')
      return
    }
    setWsSearching(true)
    try {
      const data = await wholesaleApi.search({ source: wsSource, keyword: wsKeyword }) as WholesaleSearchResult
      setWsResults(data.items || [])
    } catch (e) {
      showAlert(`검색 실패: ${e instanceof Error ? e.message : '알 수 없는 오류'}`, 'error')
    } finally {
      setWsSearching(false)
    }
  }

  const handleDeleteWpSite = async (siteId: string) => {
    const ok = await showConfirm('이 WP 사이트를 삭제하시겠습니까?')
    if (!ok) return
    try {
      // WP 사이트 삭제는 별도 API가 필요 — 현재 연결 해제로 처리
      showAlert('사이트 삭제 기능은 준비 중입니다.', 'info')
      void siteId
    } catch {
      // 삭제 실패
    }
  }

  // ── 렌더 ──

  return (
    <div style={{ padding: 0 }}>
      {/* 헤더 + 탭 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#E5E5E5', margin: 0 }}>SNS 마케팅</h2>
          <p style={{ fontSize: '0.78rem', color: '#8A95B0', marginTop: '4px' }}>자동 포스팅 · 도매몰 연동 · 수익 대시보드</p>
        </div>
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {TAB_LIST.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)} style={{
              padding: '6px 14px', fontSize: '0.78rem', borderRadius: '6px', cursor: 'pointer', fontWeight: 600,
              background: tab === t.key ? '#FF8C00' : 'rgba(255,255,255,0.05)',
              color: tab === t.key ? '#000' : '#8A95B0',
              border: tab === t.key ? 'none' : '1px solid #2D2D2D',
              whiteSpace: 'nowrap',
            }}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* ─── 탭 1: 종합현황 ─── */}
      {tab === 'overview' && (
        <>
          {/* KPI 카드 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
            <div style={cardPad}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>오늘 포스팅</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#4C9AFF' }}>{fmtNum(dashboard?.today_posts ?? 0)}건</div>
            </div>
            <div style={cardPad}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>전체 포스팅</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#51CF66' }}>{fmtNum(dashboard?.total_posts ?? 0)}건</div>
            </div>
            <div style={cardPad}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>성공률</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 700, color: '#FF8C00' }}>{dashboard?.success_rate ?? 0}%</div>
            </div>
            <div style={cardPad}>
              <div style={{ fontSize: '0.7rem', color: '#8A95B0', marginBottom: '4px' }}>자동화 상태</div>
              <div style={{ marginTop: '4px' }}>
                {getStatusBadge(dashboard?.auto_status === 'running' ? 'running' : 'stopped')}
              </div>
            </div>
          </div>

          {/* 최근 포스팅 */}
          <div style={cardPad}>
            <h3 style={sectionTitle}>최근 포스팅 5건</h3>
            {recentPosts.length === 0 ? (
              <div style={{ padding: '2rem', textAlign: 'center', color: '#555', fontSize: '0.85rem' }}>
                아직 포스팅 이력이 없습니다.
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                    <th style={thStyle}>제목</th>
                    <th style={{ ...thStyle, textAlign: 'center' }}>카테고리</th>
                    <th style={{ ...thStyle, textAlign: 'center' }}>상태</th>
                    <th style={{ ...thStyle, textAlign: 'center' }}>발행일</th>
                  </tr>
                </thead>
                <tbody>
                  {recentPosts.map(p => (
                    <tr key={p.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                      <td style={tdStyle}>{p.title}</td>
                      <td style={{ ...tdStyle, textAlign: 'center' }}>{p.category}</td>
                      <td style={{ ...tdStyle, textAlign: 'center' }}>{getStatusBadge(p.status)}</td>
                      <td style={{ ...tdStyle, textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0' }}>{fmtDate(p.published_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {/* ─── 탭 2: 자동 포스팅 ─── */}
      {tab === 'auto-posting' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* WP 연결 섹션 */}
          <div style={cardPad}>
            <h3 style={sectionTitle}>워드프레스 연결</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: '10px', alignItems: 'end' }}>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>사이트 URL</label>
                <input
                  style={inputBox}
                  placeholder="https://myblog.com"
                  value={wpForm.site_url}
                  onChange={e => setWpForm(p => ({ ...p, site_url: e.target.value }))}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>사용자명</label>
                <input
                  style={inputBox}
                  placeholder="admin"
                  value={wpForm.username}
                  onChange={e => setWpForm(p => ({ ...p, username: e.target.value }))}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>앱 비밀번호</label>
                <input
                  style={inputBox}
                  type="password"
                  placeholder="xxxx xxxx xxxx xxxx"
                  value={wpForm.app_password}
                  onChange={e => setWpForm(p => ({ ...p, app_password: e.target.value }))}
                />
              </div>
              <button
                style={{ ...btnPrimary, padding: '8px 16px', opacity: wpConnecting ? 0.6 : 1 }}
                onClick={handleConnectWp}
                disabled={wpConnecting}
              >
                {wpConnecting ? '연결중...' : '연결 테스트'}
              </button>
            </div>

            {/* 연결된 사이트 목록 */}
            {wpSites.length > 0 && (
              <div style={{ marginTop: '16px' }}>
                <div style={{ fontSize: '0.78rem', color: '#8A95B0', marginBottom: '8px' }}>연결된 WP 사이트</div>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {wpSites.map(s => (
                    <div key={s.id}
                      onClick={() => setActiveSiteId(s.id)}
                      style={{
                        padding: '6px 12px', borderRadius: '8px', fontSize: '0.78rem', cursor: 'pointer', fontWeight: 600,
                        background: activeSiteId === s.id ? 'rgba(255,140,0,0.15)' : 'rgba(255,255,255,0.03)',
                        color: activeSiteId === s.id ? '#FF8C00' : '#8A95B0',
                        border: activeSiteId === s.id ? '1px solid rgba(255,140,0,0.3)' : '1px solid #2D2D2D',
                      }}>
                      {s.site_name || s.site_url}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 키워드 관리 섹션 */}
          <div style={cardPad}>
            <h3 style={sectionTitle}>키워드 그룹 관리</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr auto', gap: '10px', alignItems: 'end' }}>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>그룹명</label>
                <input
                  style={inputBox}
                  placeholder="그룹 이름"
                  value={kwForm.name}
                  onChange={e => setKwForm(p => ({ ...p, name: e.target.value }))}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>카테고리</label>
                <select
                  style={selectStyle}
                  value={kwForm.category}
                  onChange={e => setKwForm(p => ({ ...p, category: e.target.value }))}
                >
                  {ISSUE_CATEGORIES.map(c => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>키워드 (콤마 구분)</label>
                <input
                  style={inputBox}
                  placeholder="키워드1, 키워드2, 키워드3"
                  value={kwForm.keywords}
                  onChange={e => setKwForm(p => ({ ...p, keywords: e.target.value }))}
                />
              </div>
              <button style={{ ...btnPrimary, padding: '8px 16px' }} onClick={handleAddKeywordGroup}>추가</button>
            </div>

            {/* 키워드 그룹 목록 */}
            {keywordGroups.length > 0 && (
              <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {keywordGroups.map(g => (
                  <div key={g.id} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '10px 14px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid #2D2D2D',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#E5E5E5' }}>{g.name}</span>
                      <span style={{ fontSize: '0.68rem', padding: '2px 8px', borderRadius: '8px', background: 'rgba(76,154,255,0.15)', color: '#4C9AFF' }}>
                        {ISSUE_CATEGORIES.find(c => c.value === g.category)?.label || g.category}
                      </span>
                      <span style={{ fontSize: '0.72rem', color: '#8A95B0' }}>{g.keywords.join(', ')}</span>
                    </div>
                    <button style={btnDanger} onClick={() => handleDeleteKeywordGroup(g.id)}>삭제</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 자동 포스팅 제어 */}
          <div style={cardPad}>
            <h3 style={sectionTitle}>자동 포스팅 제어</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '16px' }}>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>포스팅 간격 (초)</label>
                <input
                  style={inputBox}
                  type="number"
                  value={autoConfig.interval_minutes}
                  onChange={e => setAutoConfig(p => ({ ...p, interval_minutes: e.target.value }))}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>일일 최대 포스팅</label>
                <input
                  style={inputBox}
                  type="number"
                  value={autoConfig.max_daily_posts}
                  onChange={e => setAutoConfig(p => ({ ...p, max_daily_posts: e.target.value }))}
                />
              </div>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>언어</label>
                <select
                  style={selectStyle}
                  value={autoConfig.language}
                  onChange={e => setAutoConfig(p => ({ ...p, language: e.target.value }))}
                >
                  <option value="ko">한국어</option>
                  <option value="en">영어</option>
                </select>
              </div>
              <div style={{ display: 'flex', alignItems: 'end', gap: '8px' }}>
                {!autoRunning ? (
                  <button style={{ ...btnPrimary, padding: '8px 20px' }} onClick={handleStartAutoPosting}>시작</button>
                ) : (
                  <button style={{ ...btnDanger, padding: '8px 20px' }} onClick={handleStopAutoPosting}>중지</button>
                )}
                {autoRunning && getStatusBadge('running')}
              </div>
            </div>

            {/* 상품 배너 HTML */}
            <div style={{ marginBottom: '16px' }}>
              <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>상품 배너 HTML (선택)</label>
              <textarea
                style={{ ...inputBox, minHeight: '60px', resize: 'vertical', fontFamily: 'monospace', fontSize: '0.75rem' }}
                placeholder='<a href="https://shop.com/product"><img src="banner.jpg" /></a>'
                value={autoConfig.product_banner_html}
                onChange={e => setAutoConfig(p => ({ ...p, product_banner_html: e.target.value }))}
              />
            </div>

            {/* SSE 실시간 로그 */}
            <div>
              <div style={{ fontSize: '0.78rem', color: '#8A95B0', marginBottom: '6px' }}>실시간 로그</div>
              <div style={{
                background: '#0D0D0D', border: '1px solid #2D2D2D', borderRadius: '8px',
                padding: '12px', maxHeight: '280px', overflowY: 'auto', fontFamily: 'monospace', fontSize: '0.72rem',
              }}>
                {sseLogs.length === 0 ? (
                  <div style={{ color: '#555' }}>자동 포스팅을 시작하면 로그가 표시됩니다.</div>
                ) : (
                  sseLogs.map((log, i) => (
                    <div key={i} style={{
                      padding: '2px 0',
                      color: log.event === 'success' ? '#51CF66'
                        : log.event === 'fail' ? '#FF6B6B'
                        : log.event === 'error' ? '#FF6B6B'
                        : log.event === 'done' ? '#4C9AFF'
                        : '#8A95B0',
                    }}>
                      <span style={{ color: '#555', marginRight: '6px' }}>[{log.event}]</span>
                      {log.message}
                    </div>
                  ))
                )}
                <div ref={logEndRef} />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── 탭 3: 게시물 관리 ─── */}
      {tab === 'posts' && (
        <div style={cardPad}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ ...sectionTitle, marginBottom: 0 }}>
              포스팅 이력 <span style={{ fontSize: '0.72rem', color: '#8A95B0', fontWeight: 400 }}>({fmtNum(postsTotal)}건)</span>
            </h3>
            <div style={{ display: 'flex', gap: '6px' }}>
              {[
                { value: '', label: '전체' },
                { value: 'published', label: '발행됨' },
                { value: 'failed', label: '실패' },
              ].map(f => (
                <button key={f.value} onClick={() => { setPostsFilter(f.value); setPostsPage(1) }} style={{
                  padding: '4px 12px', fontSize: '0.72rem', borderRadius: '6px', cursor: 'pointer', fontWeight: 600,
                  background: postsFilter === f.value ? '#FF8C00' : 'rgba(255,255,255,0.05)',
                  color: postsFilter === f.value ? '#000' : '#8A95B0',
                  border: postsFilter === f.value ? 'none' : '1px solid #2D2D2D',
                }}>
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          {posts.length === 0 ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: '#555', fontSize: '0.85rem' }}>
              포스팅 이력이 없습니다.
            </div>
          ) : (
            <>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                    <th style={thStyle}>제목</th>
                    <th style={{ ...thStyle, textAlign: 'center' }}>카테고리</th>
                    <th style={{ ...thStyle, textAlign: 'center' }}>키워드</th>
                    <th style={{ ...thStyle, textAlign: 'center' }}>상태</th>
                    <th style={{ ...thStyle, textAlign: 'center' }}>발행일</th>
                  </tr>
                </thead>
                <tbody>
                  {posts.map(p => (
                    <tr key={p.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                      <td style={{ ...tdStyle, maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.title}</td>
                      <td style={{ ...tdStyle, textAlign: 'center', fontSize: '0.75rem' }}>{p.category}</td>
                      <td style={{ ...tdStyle, textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0' }}>{p.keyword}</td>
                      <td style={{ ...tdStyle, textAlign: 'center' }}>{getStatusBadge(p.status)}</td>
                      <td style={{ ...tdStyle, textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0' }}>{fmtDate(p.published_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {/* 페이지네이션 */}
              {postsTotalPages > 1 && (
                <div style={{ display: 'flex', justifyContent: 'center', gap: '6px', marginTop: '16px' }}>
                  <button
                    style={{ ...btnOutline, opacity: postsPage <= 1 ? 0.4 : 1 }}
                    disabled={postsPage <= 1}
                    onClick={() => setPostsPage(p => p - 1)}
                  >
                    이전
                  </button>
                  <span style={{ padding: '6px 12px', fontSize: '0.78rem', color: '#8A95B0' }}>
                    {postsPage} / {postsTotalPages}
                  </span>
                  <button
                    style={{ ...btnOutline, opacity: postsPage >= postsTotalPages ? 0.4 : 1 }}
                    disabled={postsPage >= postsTotalPages}
                    onClick={() => setPostsPage(p => p + 1)}
                  >
                    다음
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* ─── 탭 4: 상품 연동 ─── */}
      {tab === 'products' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* 도매몰 검색 */}
          <div style={cardPad}>
            <h3 style={sectionTitle}>도매몰 소싱 검색</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '150px 1fr auto', gap: '10px', alignItems: 'end' }}>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>소스</label>
                <select
                  style={selectStyle}
                  value={wsSource}
                  onChange={e => setWsSource(e.target.value)}
                >
                  <option value="도매매">도매매</option>
                  <option value="오너클랜">오너클랜</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: '0.72rem', color: '#8A95B0', display: 'block', marginBottom: '4px' }}>키워드</label>
                <input
                  style={inputBox}
                  placeholder="검색할 상품 키워드"
                  value={wsKeyword}
                  onChange={e => setWsKeyword(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleWholesaleSearch()}
                />
              </div>
              <button
                style={{ ...btnPrimary, padding: '8px 16px', opacity: wsSearching ? 0.6 : 1 }}
                onClick={handleWholesaleSearch}
                disabled={wsSearching}
              >
                {wsSearching ? '검색중...' : '검색'}
              </button>
            </div>

            {/* 검색 결과 */}
            {wsResults.length > 0 && (
              <div style={{ marginTop: '16px' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                      <th style={{ ...thStyle, width: '60px' }}>이미지</th>
                      <th style={thStyle}>상품명</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>가격</th>
                      <th style={{ ...thStyle, textAlign: 'center' }}>소스</th>
                    </tr>
                  </thead>
                  <tbody>
                    {wsResults.map(p => (
                      <tr key={p.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                        <td style={tdStyle}>
                          {p.image ? (
                            <img src={p.image} alt="" style={{ width: '44px', height: '44px', objectFit: 'cover', borderRadius: '4px' }} />
                          ) : (
                            <div style={{ width: '44px', height: '44px', background: '#2D2D2D', borderRadius: '4px' }} />
                          )}
                        </td>
                        <td style={{ ...tdStyle, fontSize: '0.8rem' }}>{p.name}</td>
                        <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>{fmtNum(p.price)}원</td>
                        <td style={{ ...tdStyle, textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0' }}>{p.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* 배너 HTML 설정 */}
          <div style={cardPad}>
            <h3 style={sectionTitle}>배너 HTML 설정</h3>
            <p style={{ fontSize: '0.75rem', color: '#8A95B0', marginBottom: '10px' }}>
              자동 포스팅 시 본문 하단에 삽입할 상품 배너 HTML을 입력하세요.
            </p>
            <textarea
              style={{ ...inputBox, minHeight: '100px', resize: 'vertical', fontFamily: 'monospace', fontSize: '0.75rem' }}
              placeholder='<div class="product-banner"><a href="..."><img src="..." /></a></div>'
              value={bannerHtml}
              onChange={e => setBannerHtml(e.target.value)}
            />
            <div style={{ marginTop: '10px', display: 'flex', justifyContent: 'flex-end' }}>
              <button style={btnPrimary} onClick={() => {
                setAutoConfig(p => ({ ...p, product_banner_html: bannerHtml }))
                showAlert('배너 HTML이 자동 포스팅 설정에 반영되었습니다.', 'success')
              }}>
                자동포스팅에 적용
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ─── 탭 5: 수익 대시보드 ─── */}
      {tab === 'revenue' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          {/* 에드센스 안내 */}
          <div style={cardPad}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
              <div style={{ width: '36px', height: '36px', borderRadius: '8px', background: 'rgba(76,154,255,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.1rem' }}>
                G
              </div>
              <h3 style={{ ...sectionTitle, marginBottom: 0 }}>구글 에드센스</h3>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '20px', height: '20px', borderRadius: '50%', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', fontWeight: 700 }}>1</span>
                <span style={{ fontSize: '0.8rem', color: '#E5E5E5' }}>구글 에드센스에 가입합니다.</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '20px', height: '20px', borderRadius: '50%', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', fontWeight: 700 }}>2</span>
                <span style={{ fontSize: '0.8rem', color: '#E5E5E5' }}>워드프레스에 에드센스 코드를 삽입합니다.</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '20px', height: '20px', borderRadius: '50%', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', fontWeight: 700 }}>3</span>
                <span style={{ fontSize: '0.8rem', color: '#E5E5E5' }}>자동 포스팅이 트래픽을 모읍니다.</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '20px', height: '20px', borderRadius: '50%', background: 'rgba(81,207,102,0.15)', color: '#51CF66', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', fontWeight: 700 }}>$</span>
                <span style={{ fontSize: '0.8rem', color: '#51CF66', fontWeight: 600 }}>광고 수익이 발생합니다!</span>
              </div>
            </div>
            <a
              href="https://www.google.com/adsense"
              target="_blank"
              rel="noopener noreferrer"
              style={{ ...btnOutline, display: 'inline-block', marginTop: '16px', textDecoration: 'none', textAlign: 'center' }}
            >
              에드센스 가입하기
            </a>
          </div>

          {/* 쿠팡 파트너스 안내 */}
          <div style={cardPad}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
              <div style={{ width: '36px', height: '36px', borderRadius: '8px', background: 'rgba(255,107,107,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.8rem', color: '#FF6B6B', fontWeight: 700 }}>
                CP
              </div>
              <h3 style={{ ...sectionTitle, marginBottom: 0 }}>쿠팡 파트너스</h3>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '20px', height: '20px', borderRadius: '50%', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', fontWeight: 700 }}>1</span>
                <span style={{ fontSize: '0.8rem', color: '#E5E5E5' }}>쿠팡 파트너스에 가입합니다.</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '20px', height: '20px', borderRadius: '50%', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', fontWeight: 700 }}>2</span>
                <span style={{ fontSize: '0.8rem', color: '#E5E5E5' }}>배너 코드를 생성합니다.</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '20px', height: '20px', borderRadius: '50%', background: 'rgba(255,140,0,0.15)', color: '#FF8C00', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', fontWeight: 700 }}>3</span>
                <span style={{ fontSize: '0.8rem', color: '#E5E5E5' }}>상품 연동 탭에서 배너 HTML을 설정합니다.</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ width: '20px', height: '20px', borderRadius: '50%', background: 'rgba(81,207,102,0.15)', color: '#51CF66', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', fontWeight: 700 }}>$</span>
                <span style={{ fontSize: '0.8rem', color: '#51CF66', fontWeight: 600 }}>구매 커미션 수익이 발생합니다!</span>
              </div>
            </div>
            <a
              href="https://partners.coupang.com"
              target="_blank"
              rel="noopener noreferrer"
              style={{ ...btnOutline, display: 'inline-block', marginTop: '16px', textDecoration: 'none', textAlign: 'center' }}
            >
              쿠팡 파트너스 가입하기
            </a>
          </div>

          {/* 수익 안내 */}
          <div style={{ ...cardPad, gridColumn: '1 / -1' }}>
            <h3 style={sectionTitle}>수익 구조 안내</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
              <div style={{ padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid #2D2D2D' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#4C9AFF', marginBottom: '6px' }}>에드센스 광고 수익</div>
                <div style={{ fontSize: '0.75rem', color: '#8A95B0', lineHeight: 1.5 }}>
                  블로그 방문자가 광고를 클릭/조회하면 수익이 발생합니다. 월 1,000건 이상 포스팅 시 안정적 수익이 기대됩니다.
                </div>
              </div>
              <div style={{ padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid #2D2D2D' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#FF8C00', marginBottom: '6px' }}>쿠팡 파트너스 커미션</div>
                <div style={{ fontSize: '0.75rem', color: '#8A95B0', lineHeight: 1.5 }}>
                  블로그 배너를 통해 쿠팡에서 구매가 발생하면 최대 3% 커미션을 받습니다.
                </div>
              </div>
              <div style={{ padding: '16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', border: '1px solid #2D2D2D' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: '#51CF66', marginBottom: '6px' }}>자사몰 유입</div>
                <div style={{ fontSize: '0.75rem', color: '#8A95B0', lineHeight: 1.5 }}>
                  도매몰 상품 배너를 통해 자사 쇼핑몰로 트래픽을 유도하여 직접 판매 수익을 올립니다.
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── 탭 6: 채널 설정 ─── */}
      {tab === 'settings' && (
        <div style={cardPad}>
          <h3 style={sectionTitle}>등록된 WP 사이트</h3>
          {wpSites.length === 0 ? (
            <div style={{ padding: '2rem', textAlign: 'center', color: '#555', fontSize: '0.85rem' }}>
              등록된 워드프레스 사이트가 없습니다. 자동 포스팅 탭에서 사이트를 연결하세요.
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #2D2D2D' }}>
                  <th style={thStyle}>사이트 URL</th>
                  <th style={{ ...thStyle, textAlign: 'center' }}>사이트명</th>
                  <th style={{ ...thStyle, textAlign: 'center' }}>상태</th>
                  <th style={{ ...thStyle, textAlign: 'center' }}>등록일</th>
                  <th style={{ ...thStyle, textAlign: 'center' }}>관리</th>
                </tr>
              </thead>
              <tbody>
                {wpSites.map(s => (
                  <tr key={s.id} style={{ borderBottom: '1px solid rgba(45,45,45,0.5)' }}>
                    <td style={tdStyle}>
                      <a href={s.site_url} target="_blank" rel="noopener noreferrer" style={{ color: '#4C9AFF', textDecoration: 'none', fontSize: '0.8rem' }}>
                        {s.site_url}
                      </a>
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'center' }}>{s.site_name || '-'}</td>
                    <td style={{ ...tdStyle, textAlign: 'center' }}>{getStatusBadge(s.status || 'connected')}</td>
                    <td style={{ ...tdStyle, textAlign: 'center', fontSize: '0.75rem', color: '#8A95B0' }}>{fmtDate(s.created_at)}</td>
                    <td style={{ ...tdStyle, textAlign: 'center' }}>
                      <button style={btnDanger} onClick={() => handleDeleteWpSite(s.id)}>삭제</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}
