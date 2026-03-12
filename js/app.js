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
            'apply-group': 'apply',
            'apply-category': 'apply',
            'apply-recollect': 'apply',
            'orders': 'orders',
            'cs': 'orders',
            'returns': 'orders',
            'analytics': 'analytics',
            'analytics-product': 'analytics'
        }
        this.validPages = [
            'dashboard',
            'sourcing-collect',
            'products',
            'policy', 'policy-template', 'policy-option-name',
            'apply-group', 'apply-category', 'apply-recollect',
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
            'sourcing': 'sourcing-collect'
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
     */
    showNotification(message, type = 'info') {
        const notification = document.createElement('div')
        notification.className = 'fixed top-4 right-4 px-6 py-3 rounded-lg text-white font-medium shadow-lg z-50'

        const bgColor = {
            'success': '#51CF66',
            'error': '#FF6B6B',
            'warning': '#FFD93D',
            'info': '#4C9AFF'
        }[type] || '#4C9AFF'

        notification.style.background = bgColor
        notification.textContent = message
        document.body.appendChild(notification)

        setTimeout(() => notification.remove(), 3000)
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

// URL 기반 페이지 복원
window.addEventListener('load', async () => {
    app.restorePageFromUrl()
    await initializeDummyData()
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
 * 상품 수집 시작 (프레임 전용 - 실제 수집 미구현)
 */
function startCollection() {
    const url = document.getElementById('collect-url-input')?.value
    if (!url) {
        app.showNotification('URL을 입력해주세요', 'warning')
        return
    }
    app.showNotification('수집 기능은 추후 구현됩니다', 'info')
}

/**
 * 초기 더미 데이터 생성
 */
async function initializeDummyData() {
    const existingProducts = await storage.getAll('products')
    if (existingProducts.length > 0) return

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

    console.log('더미 데이터 초기화 완료')
}
