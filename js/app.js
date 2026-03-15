/**
 * 메인 애플리케이션 로직
 * The.Mango 스타일 네비게이션 (드롭다운 + 단독 메뉴)
 */

class SambaWaveApp {
    constructor() {
        this.currentPage = 'products'
        // 페이지 → 소속 그룹 매핑
        this.pageGroups = {
            'policy': 'policy',
            'policy-template': 'policy',
            'policy-option-name': 'policy',
            'analytics': 'analytics',
            'analytics-product': 'analytics'
        }
        this.validPages = [
            'dashboard',
            'sourcing-collect',
            'products',
            'policy', 'policy-template', 'policy-option-name',
            'apply-category', 'apply-recollect',
            'shipment',
            'orders', 'cs', 'returns',
            'analytics', 'analytics-product',
            'settings'
        ]
        this.init()
    }

    /**
     * 앱 초기화
     */
    init() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setupEventListeners())
        } else {
            this.setupEventListeners()
        }
    }

    /**
     * 이벤트 리스너 설정
     */
    setupEventListeners() {
        // 단독 nav-item 클릭
        document.querySelectorAll('.nav-item').forEach(button => {
            button.addEventListener('click', () => {
                const pageName = button.getAttribute('data-page')
                if (pageName) this.navigateTo(pageName)
            })
        })

        // 드롭다운 서브메뉴 클릭
        document.querySelectorAll('.nav-dropdown-item').forEach(item => {
            item.addEventListener('click', () => {
                const pageName = item.getAttribute('data-page')
                if (pageName) this.navigateTo(pageName)
            })
        })

        // 상품 뷰 탭 클릭
        document.querySelectorAll('.product-view-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.product-view-tab').forEach(t => t.classList.remove('active'))
                tab.classList.add('active')
            })
        })

        console.log('SambaWaveApp 초기화 완료')
    }

    /**
     * 페이지 전환
     */
    navigateTo(pageName) {
        // 레거시 해시 리다이렉트
        const redirects = {
            'channels': 'products',
            'contacts': 'cs',
            'sourcing': 'sourcing-collect',
            'apply-group': 'sourcing-collect'
        }
        if (redirects[pageName]) pageName = redirects[pageName]

        // 유효하지 않은 페이지 → products로
        if (!this.validPages.includes(pageName)) pageName = 'products'

        // 모든 페이지 숨기기
        document.querySelectorAll('.page-content').forEach(page => {
            page.classList.add('hidden')
        })

        // 새 페이지 표시
        const pageElement = document.getElementById(`page-${pageName}`)
        if (pageElement) {
            pageElement.classList.remove('hidden')
        }

        // 단독 nav-item 활성화 초기화
        document.querySelectorAll('.nav-item').forEach(button => {
            button.classList.remove('sidebar-active')
        })

        // 드롭다운 그룹 활성화 초기화
        document.querySelectorAll('.nav-dropdown').forEach(dropdown => {
            dropdown.classList.remove('active')
        })

        // 드롭다운 아이템 활성화 초기화
        document.querySelectorAll('.nav-dropdown-item').forEach(item => {
            item.classList.remove('active')
        })

        const group = this.pageGroups[pageName]
        if (group) {
            // 드롭다운 그룹 활성화
            const groupEl = document.getElementById(`nav-group-${group}`)
            if (groupEl) groupEl.classList.add('active')

            // 해당 서브메뉴 아이템 활성화
            const activeItem = document.querySelector(`.nav-dropdown-item[data-page="${pageName}"]`)
            if (activeItem) activeItem.classList.add('active')
        } else {
            // 단독 nav-item 활성화
            const activeButton = document.querySelector(`.nav-item[data-page="${pageName}"]`)
            if (activeButton) activeButton.classList.add('sidebar-active')
        }

        this.currentPage = pageName
        window.history.pushState({ page: pageName }, '', `#${pageName}`)

        // product-count 동기화
        const c1 = document.getElementById('product-count')
        const c2 = document.getElementById('product-count2')
        if (c1 && c2) c2.textContent = c1.textContent

        // 페이지별 초기화
        if (pageName === 'analytics') setTimeout(initAcTables, 60)
        if (pageName === 'apply-category') setTimeout(() => {
            if (typeof ui !== 'undefined') ui.renderCategoryBrowser()
        }, 60)
        if (pageName === 'products') setTimeout(() => {
            updateDashboardCards()
            if (typeof ui !== 'undefined') ui.renderProducts()
        }, 100)
        if (pageName === 'dashboard') setTimeout(initDashboardCharts, 80)
        if (pageName === 'sourcing-collect') setTimeout(() => {
            if (typeof ui !== 'undefined') ui.renderSearchFilterTable()
        }, 60)
        if (pageName === 'settings') setTimeout(() => {
            // 금지어/삭제어 목록 렌더
            if (typeof ui !== 'undefined') ui.renderForbiddenWords()
            // Claude API 저장된 설정 불러오기
            storage.getAll('settings').then(rows => {
                const cfg = rows.find(r => r.key === 'claude')
                if (!cfg) return
                const keyEl = document.getElementById('claude-api-key')
                const modelEl = document.getElementById('claude-model')
                if (keyEl) keyEl.value = cfg.apiKey || ''
                if (modelEl) modelEl.value = cfg.model || 'claude-sonnet-4-6'
            })
        }, 60)
    }

    /**
     * URL에 따라 페이지 복원 (새로고침 시)
     */
    restorePageFromUrl() {
        const hash = window.location.hash.slice(1)
        if (hash) {
            this.navigateTo(hash)
        } else {
            this.navigateTo('dashboard')
        }
    }

    /**
     * 알림 표시
     * @param {string} message - 메시지
     * @param {string} type - 'info' | 'success' | 'warning' | 'error'
     * @param {boolean} persistent - true이면 확인 버튼 클릭 전까지 유지 + 소리 알람
     */
    showNotification(message, type = 'info', persistent = false) {
        const colorMap = {
            'success': { bg: '#2A7A45', text: '#fff' },
            'error':   { bg: '#C0392B', text: '#fff' },
            'warning': { bg: '#E67E00', text: '#fff' },
            'info':    { bg: '#1A65C0', text: '#fff' },
        }
        const { bg } = colorMap[type] || colorMap['info']

        const notification = document.createElement('div')
        notification.style.cssText = `
            position: fixed; top: 1rem; right: 1rem; z-index: 9999;
            background: ${bg}; color: #fff; font-weight: 600;
            border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.5);
            max-width: 360px; min-width: 220px; overflow: hidden;
        `

        if (persistent) {
            // 확인 버튼 포함 레이아웃
            notification.innerHTML = `
                <div style="padding: 14px 16px 10px; font-size: 0.875rem; line-height: 1.5;">${message}</div>
                <div style="padding: 0 12px 12px; text-align: right;">
                    <button style="
                        background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.4);
                        color: #fff; font-size: 0.8rem; font-weight: 700;
                        padding: 4px 14px; border-radius: 6px; cursor: pointer;
                    ">확인</button>
                </div>
            `
            notification.querySelector('button').addEventListener('click', () => notification.remove())
            // 소리 알람 (Web Audio API - 외부 파일 불필요)
            this._playAlertSound(type)
        } else {
            notification.style.padding = '12px 20px'
            notification.style.fontSize = '0.875rem'
            notification.textContent = message
            setTimeout(() => notification.remove(), 3000)
        }

        document.body.appendChild(notification)
    }

    /**
     * Web Audio API로 알람음 생성 (외부 파일 없음)
     * @param {string} type - 알람 타입별 다른 음
     */
    _playAlertSound(type) {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)()
            const sequences = {
                'warning': [{ f: 880, t: 0.0, d: 0.15 }, { f: 660, t: 0.18, d: 0.2 }],
                'error':   [{ f: 440, t: 0.0, d: 0.12 }, { f: 330, t: 0.15, d: 0.12 }, { f: 220, t: 0.3, d: 0.2 }],
                'info':    [{ f: 660, t: 0.0, d: 0.1 }, { f: 880, t: 0.12, d: 0.15 }],
                'success': [{ f: 660, t: 0.0, d: 0.1 }, { f: 880, t: 0.12, d: 0.1 }, { f: 1100, t: 0.25, d: 0.15 }],
            }
            const notes = sequences[type] || sequences['info']
            notes.forEach(({ f, t, d }) => {
                const osc = ctx.createOscillator()
                const gain = ctx.createGain()
                osc.connect(gain)
                gain.connect(ctx.destination)
                osc.frequency.value = f
                osc.type = 'sine'
                gain.gain.setValueAtTime(0.3, ctx.currentTime + t)
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + t + d)
                osc.start(ctx.currentTime + t)
                osc.stop(ctx.currentTime + t + d + 0.05)
            })
        } catch (e) {
            // 소리 재생 실패 시 무시
        }
    }

    /**
     * 로딩 표시
     */
    showLoading(show = true) {
        let loader = document.getElementById('global-loader')
        if (!loader) {
            loader = document.createElement('div')
            loader.id = 'global-loader'
            loader.innerHTML = `
                <div class="fixed inset-0 flex items-center justify-center z-40" style="background:rgba(0,0,0,0.5);">
                    <div style="background:#1A1A1A; border:1px solid #2D2D2D; border-radius:12px; padding:2rem; display:flex; flex-direction:column; align-items:center; gap:1rem;">
                        <div style="width:2rem; height:2rem; border:3px solid #2D2D2D; border-top-color:#FF8C00; border-radius:50%; animation:spin 0.8s linear infinite;"></div>
                        <p style="color:#E5E5E5; font-size:0.9rem;">로딩 중...</p>
                    </div>
                </div>
            `
            document.body.appendChild(loader)
        }
        loader.style.display = show ? 'block' : 'none'
    }
}

// 앱 인스턴스 생성
const app = new SambaWaveApp()

// 공유 마켓 목록 (설정/매출통계/상품전송 공통)
// 판매마켓 ID와 표시명: SSG→신세계몰, 롯데온→롯데ON, GS샵→GS샵 으로 통일
const MARKET_LIST = ['쿠팡','신세계몰','스마트스토어','11번가','지마켓','옥션','GS샵','롯데ON','롯데홈쇼핑','홈앤쇼핑','HMALL','KREAM']

// 공유 소싱사이트 목록 (상품관리/정책적용/주문목록 공통) - 10개
// 소싱처 식별명 (판매마켓 ID와 별도): SSG=소싱처명, LOTTEON=소싱처명, GSShop=소싱처명
const SITE_LIST = ['ABCmart','FOLDERStyle','GrandStage','GSShop','KREAM','LOTTEON','MUSINSA','Nike','OliveYoung','SSG']

// collectorManager.supportedSites에서 사이트 이름 배열을 가져오는 유틸
function getSiteList() {
    if (typeof collectorManager !== 'undefined' && collectorManager.supportedSites) {
        return collectorManager.supportedSites.map(s => s.name)
    }
    return SITE_LIST
}

// 페이지 로드 시 모든 소싱사이트 UI를 동적으로 채우기
function populateSiteFilters() {
    const sites = getSiteList()

    // select 드롭다운: data-site-select 속성 가진 모든 select 채우기
    document.querySelectorAll('select[data-site-select]').forEach(sel => {
        const placeholder = sel.dataset.sitePlaceholder || '전체'
        sel.innerHTML = `<option value="">${placeholder}</option>`
            + sites.map(s => `<option value="${s}">${s}</option>`).join('')
    })

    // 체크박스 그룹: data-site-checkboxes 속성 가진 div 채우기
    document.querySelectorAll('[data-site-checkboxes]').forEach(container => {
        const cls = container.dataset.siteClass || 'site-cb'
        const allId = container.dataset.siteAllId || `${cls}-all`
        const allOnchange = container.dataset.siteAllOnchange || ''
        const labelStyle = container.dataset.siteLabelStyle || ''
        const itemStyle = container.dataset.siteItemStyle || ''
        const inputStyle = container.dataset.siteInputStyle || ''
        const allLabel = container.dataset.siteAllLabel || '전체'
        const divider = container.dataset.siteDivider

        let html = `<label ${labelStyle ? `style="${labelStyle}"` : `class="af-cb"`}>`
            + `<input type="checkbox" id="${allId}" ${inputStyle ? `style="${inputStyle}"` : ''}`
            + ` ${allOnchange ? `onchange="${allOnchange}"` : ''}> <span>${allLabel}</span></label>`

        if (divider !== undefined) {
            html += '<div class="af-cb-divider"></div>'
        }

        html += sites.map(s =>
            `<label ${labelStyle ? `style="${itemStyle || labelStyle}"` : `class="af-cb"`}>`
            + `<input type="checkbox" class="${cls}" value="${s}" checked`
            + ` ${inputStyle ? `style="${inputStyle}"` : ''}>`
            + `<span>${s}</span></label>`
        ).join('')

        container.innerHTML = html
    })

    // 테이블 헤더: data-site-thead 속성 가진 tr 채우기
    document.querySelectorAll('tr[data-site-thead]').forEach(tr => {
        tr.innerHTML = '<th></th>'
            + sites.map(s => `<th>${s}</th>`).join('')
            + '<th style="color:#FF8C00;">합계</th>'
    })
}

// URL 기반 페이지 복원
window.addEventListener('load', async () => {
    app.restorePageFromUrl()
    populateSiteFilters()
    await initializeDummyData()
    // 더미데이터 추가 후 상품 목록 새로고침
    if (typeof ui !== 'undefined') {
        await productManager.loadProducts()
        ui.renderProducts()
        ui.updateCounts()
    }
})

// 뒤로가기/앞으로가기 지원
window.addEventListener('popstate', (event) => {
    if (event.state && event.state.page) {
        app.navigateTo(event.state.page)
    }
})

/**
 * 가격범위 행 추가 (정책관리 페이지)
 */
function addPriceRange() {
    const container = document.getElementById('price-ranges')
    if (!container) return
    const row = document.createElement('div')
    row.className = 'price-range-row'
    row.innerHTML = `
        <input type="number" placeholder="최소가격" style="width:80px; padding:0.25rem 0.5rem; font-size:0.8125rem;"> <span style="color:#555;">~</span>
        <input type="number" placeholder="최대가격" style="width:80px; padding:0.25rem 0.5rem; font-size:0.8125rem;"> <span style="color:#888; font-size:0.8125rem;">원</span>
        <input type="number" value="15" style="width:60px; padding:0.25rem 0.5rem; font-size:0.8125rem;"> <span style="color:#888; font-size:0.75rem;">%</span>
        <span style="color:#555;">/</span>
        <input type="number" style="width:80px; padding:0.25rem 0.5rem; font-size:0.8125rem;" placeholder="선택"> <span style="color:#888; font-size:0.75rem;">원</span>
        <button onclick="this.parentElement.remove()" style="color:#FF6B6B; background:transparent; font-size:0.75rem; margin-left:0.5rem;">삭제</button>
    `
    container.appendChild(row)
}

/**
 * 초기 더미 데이터 생성
 */
async function initializeDummyData() {
    // DB 초기화 완료 대기 (IndexedDB 준비 전 호출 방지)
    await storageReady
    // 이미 초기화 완료 플래그가 있으면 재삽입하지 않음
    // settings 스토어의 keyPath는 'key'이므로 key 속성으로 조회/저장
    const settings = await storage.getAll('settings')
    const initialized = settings.find(s => s.key === 'dummyDataInitialized')
    if (initialized) return

    const existingProducts = await storage.getAll('products')
    if (existingProducts.length > 0) {
        // 상품이 있으면 플래그만 기록하고 종료
        await storage.save('settings', { key: 'dummyDataInitialized', value: true })
        return
    }

    // 판매처 추가
    const channels = [
        { name: '쿠팡', type: 'open-market', platform: 'coupang', feeRate: 8.5 },
        { name: '무신사', type: 'resale', platform: 'musinsa', feeRate: 10 },
        { name: 'SSG', type: 'mall', platform: 'ssg', feeRate: 4.5 },
        { name: '11번가', type: 'open-market', platform: '11st', feeRate: 8.5 }
    ]

    const savedChannels = {}
    for (const ch of channels) {
        const channel = await channelManager.addChannel(ch)
        if (channel) savedChannels[ch.platform] = channel.id
    }

    // 상품 추가
    const products = [
        {
            name: '에어 포스 1 07 블랙 CW2288-001',
            category: '신발',
            sourceUrl: 'https://example.com/product1',
            sourcePrice: 118730,
            cost: 118730,
            marginRate: 15,
            description: '나이키 에어 포스 1 클래식 블랙'
        },
        {
            name: 'T셔츠 (화이트)',
            category: '의류',
            sourceUrl: 'https://example.com/product2',
            sourcePrice: 12000,
            cost: 8000,
            marginRate: 40,
            description: '순면 100% 기본 티셔츠'
        },
        {
            name: '백팩 (블랙)',
            category: '가방',
            sourceUrl: 'https://example.com/product3',
            sourcePrice: 65000,
            cost: 48000,
            marginRate: 30,
            description: '내구성 좋은 일상용 백팩'
        }
    ]

    for (const prod of products) {
        await productManager.addProduct(prod)
    }

    // 샘플 주문 추가
    const sampleOrders = [
        {
            channelId: Object.values(savedChannels)[0],
            productId: productManager.products[0]?.id,
            customerName: '김철수',
            customerPhone: '010-1234-5678',
            salePrice: 136300,
            cost: 118730,
            feeRate: 8.5
        },
        {
            channelId: Object.values(savedChannels)[1],
            productId: productManager.products[1]?.id,
            customerName: '이영희',
            customerPhone: '010-9876-5432',
            salePrice: 18000,
            cost: 8000,
            feeRate: 10
        }
    ]

    for (const order of sampleOrders) {
        if (order.channelId && order.productId) {
            await orderManager.addOrder(order)
        }
    }

    // 초기화 완료 플래그 저장 (이후 재삽입 방지)
    await storage.save('settings', { key: 'dummyDataInitialized', value: true })
    console.log('더미 데이터 초기화 완료')
}

// KREAM 브라우저 로그인
async function kreamBrowserLogin() {
  const email = document.getElementById('kr-email')?.value || ''
  const password = document.getElementById('kr-password')?.value || ''
  const statusEl = document.getElementById('kr-browser-status')
  if (!email || !password) {
    if (statusEl) statusEl.innerHTML = '<span style="color:#FF6B6B;">이메일과 비밀번호를 입력해주세요.</span>'
    return
  }
  if (statusEl) statusEl.innerHTML = '<span style="color:#FFB84D;">브라우저 로그인 시도 중...</span>'
  try {
    const res = await fetch('http://localhost:3001/api/kream/browser-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    })
    const data = await res.json()
    if (data.success) {
      if (statusEl) statusEl.innerHTML = '<span style="color:#51CF66;">브라우저 로그인 성공</span>'
      app.showNotification('KREAM 브라우저 로그인 성공', 'success')
    } else {
      if (statusEl) statusEl.innerHTML = `<span style="color:#FF6B6B;">${data.message}</span>`
    }
  } catch (e) {
    if (statusEl) statusEl.innerHTML = '<span style="color:#FF6B6B;">프록시 서버 연결 실패. 서버가 실행 중인지 확인하세요.</span>'
  }
}

// KREAM 브라우저 상태 확인
async function kreamCheckBrowserStatus() {
  const statusEl = document.getElementById('kr-browser-status')
  if (statusEl) statusEl.innerHTML = '<span style="color:#FFB84D;">확인 중...</span>'
  try {
    const res = await fetch('http://localhost:3001/api/kream/browser-status')
    const data = await res.json()
    if (data.isLoggedIn) {
      if (statusEl) statusEl.innerHTML = '<span style="color:#51CF66;">로그인 상태 (세션 유지 중)</span>'
    } else {
      if (statusEl) statusEl.innerHTML = '<span style="color:#FF6B6B;">로그인 안됨. "브라우저 로그인" 버튼을 클릭하거나, 열린 Chrome 창에서 직접 로그인하세요.</span>'
    }
  } catch {
    if (statusEl) statusEl.innerHTML = '<span style="color:#FF6B6B;">프록시 서버 연결 실패</span>'
  }
}

