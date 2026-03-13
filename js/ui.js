/**
 * UI 관리 모듈
 * 모달, 테이블, 폼 렌더링 및 이벤트 처리
 */

class UIManager {
    constructor() {
        this.currentProductEditId = null
        this.currentChannelEditId = null
        this.currentOrderFilter = 'all'
        this.smsSentOrders = new Set()   // 발송 완료된 주문 ID 집합
        this.orderDateStartLocked = false // 시작일 고정 여부
        this.productViewMode = 'card'    // 'card' | 'image'
        this.catState = { site: null, cat1: null, cat2: null, cat3: null, cat4: null } // 카테고리 브라우저 선택 상태
        this._catData = null             // 수집 상품 기반 카테고리 데이터
        this.focusedProductId = null     // 이미지뷰 클릭 시 단일 상품 포커스
        this.init()
    }

    /**
     * 초기화
     */
    async init() {
        // DOM 로드 대기
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setupEventListeners().catch(err => console.error('UI 초기화 오류:', err)))
        } else {
            this.setupEventListeners().catch(err => console.error('UI 초기화 오류:', err))
        }
    }

    // ==================== 모달 다이얼로그 시스템 ====================

    /**
     * confirm() 대체 — 확인/취소 모달
     * @param {string} message - 메시지 (줄바꿈은 \n)
     * @param {Object} opts - { title, confirmText, cancelText, danger }
     * @returns {Promise<boolean>}
     */
    showConfirm(message, opts = {}) {
        const { title = '확인', confirmText = '확인', cancelText = '취소', danger = false } = opts
        return new Promise(resolve => {
            const overlay = document.createElement('div')
            overlay.className = 'sw-modal-overlay'
            overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.65);'
            const btnColor = danger
                ? 'background:linear-gradient(135deg,#FF4444,#FF6B6B);'
                : 'background:linear-gradient(135deg,#FF8C00,#FFB84D);'
            overlay.innerHTML = `
                <div style="background:#1A1A1A;border:1px solid #2D2D2D;border-radius:12px;padding:24px;min-width:320px;max-width:480px;box-shadow:0 20px 60px rgba(0,0,0,0.5);">
                    <div style="font-size:0.95rem;font-weight:600;color:#E5E5E5;margin-bottom:16px;">${title}</div>
                    <div style="font-size:0.85rem;color:#B0B0B0;line-height:1.6;margin-bottom:24px;white-space:pre-line;">${message}</div>
                    <div style="display:flex;justify-content:flex-end;gap:8px;">
                        <button class="sw-modal-cancel" style="padding:8px 20px;font-size:0.82rem;border:1px solid #3D3D3D;border-radius:6px;color:#999;background:transparent;cursor:pointer;">${cancelText}</button>
                        <button class="sw-modal-ok" style="padding:8px 20px;font-size:0.82rem;border:none;border-radius:6px;color:#fff;${btnColor}cursor:pointer;font-weight:600;">${confirmText}</button>
                    </div>
                </div>`
            const cleanup = (val) => { overlay.remove(); resolve(val) }
            overlay.querySelector('.sw-modal-ok').onclick = () => cleanup(true)
            overlay.querySelector('.sw-modal-cancel').onclick = () => cleanup(false)
            overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(false) })
            // ESC 키로 취소
            const esc = e => { if (e.key === 'Escape') { cleanup(false); document.removeEventListener('keydown', esc) } }
            document.addEventListener('keydown', esc)
            document.body.appendChild(overlay)
            overlay.querySelector('.sw-modal-ok').focus()
        })
    }

    /**
     * prompt() 대체 — 입력 모달
     * @param {string} message - 안내 메시지
     * @param {Object} opts - { title, placeholder, defaultValue }
     * @returns {Promise<string|null>}
     */
    showPrompt(message, opts = {}) {
        const { title = '입력', placeholder = '', defaultValue = '' } = opts
        return new Promise(resolve => {
            const overlay = document.createElement('div')
            overlay.className = 'sw-modal-overlay'
            overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.65);'
            overlay.innerHTML = `
                <div style="background:#1A1A1A;border:1px solid #2D2D2D;border-radius:12px;padding:24px;min-width:360px;max-width:480px;box-shadow:0 20px 60px rgba(0,0,0,0.5);">
                    <div style="font-size:0.95rem;font-weight:600;color:#E5E5E5;margin-bottom:12px;">${title}</div>
                    <div style="font-size:0.85rem;color:#B0B0B0;margin-bottom:14px;">${message}</div>
                    <input class="sw-modal-input" type="text" value="${(defaultValue || '').replace(/"/g, '&quot;')}" placeholder="${placeholder}"
                        style="width:100%;padding:10px 12px;font-size:0.85rem;background:#0F0F0F;border:1px solid #3D3D3D;color:#E5E5E5;border-radius:6px;outline:none;box-sizing:border-box;">
                    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:18px;">
                        <button class="sw-modal-cancel" style="padding:8px 20px;font-size:0.82rem;border:1px solid #3D3D3D;border-radius:6px;color:#999;background:transparent;cursor:pointer;">취소</button>
                        <button class="sw-modal-ok" style="padding:8px 20px;font-size:0.82rem;border:none;border-radius:6px;color:#fff;background:linear-gradient(135deg,#FF8C00,#FFB84D);cursor:pointer;font-weight:600;">확인</button>
                    </div>
                </div>`
            const input = overlay.querySelector('.sw-modal-input')
            const cleanup = (val) => { overlay.remove(); resolve(val) }
            overlay.querySelector('.sw-modal-ok').onclick = () => cleanup(input.value)
            overlay.querySelector('.sw-modal-cancel').onclick = () => cleanup(null)
            overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(null) })
            input.addEventListener('keydown', e => { if (e.key === 'Enter') cleanup(input.value) })
            const esc = e => { if (e.key === 'Escape') { cleanup(null); document.removeEventListener('keydown', esc) } }
            document.addEventListener('keydown', esc)
            document.body.appendChild(overlay)
            input.focus()
            input.select()
        })
    }

    /**
     * 이벤트 리스너 설정
     */
    async setupEventListeners() {
        // 모달 폼 제출
        document.getElementById('product-form')?.addEventListener('submit', (e) => this.handleProductSubmit(e))
        document.getElementById('channel-form')?.addEventListener('submit', (e) => this.handleChannelSubmit(e))
        document.getElementById('order-form')?.addEventListener('submit', (e) => this.handleOrderSubmit(e))
        document.getElementById('sourcing-form')?.addEventListener('submit', (e) => this.handleSourcingSubmit(e))
        document.getElementById('contact-form')?.addEventListener('submit', (e) => this.handleContactSubmit(e))
        document.getElementById('return-form')?.addEventListener('submit', (e) => this.handleReturnSubmit(e))

        // 상품 검색 및 필터
        document.getElementById('product-search')?.addEventListener('input', () => this.renderProducts())
        document.getElementById('product-status')?.addEventListener('change', () => this.renderProducts())

        // 주문 상태 탭
        document.querySelectorAll('.order-tab').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.currentOrderFilter = e.target.getAttribute('data-status')
                document.querySelectorAll('.order-tab').forEach(b => {
                    b.style.background = 'rgba(50,50,50,0.8)'
                    b.style.color = '#C5C5C5'
                    b.style.border = '1px solid #3D3D3D'
                })
                e.target.style.background = 'linear-gradient(135deg,#FF8C00,#FFB84D)'
                e.target.style.color = '#fff'
                e.target.style.border = 'none'
                this.renderOrders()
            })
        })

        // 통계 탭
        document.querySelectorAll('.analytics-tab').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const tab = e.target.getAttribute('data-tab')
                document.querySelectorAll('.analytics-tab').forEach(b => {
                    b.style.background = 'rgba(50,50,50,0.8)'
                    b.style.color = '#C5C5C5'
                    b.style.border = '1px solid #3D3D3D'
                })
                document.querySelectorAll('.analytics-content').forEach(c => c.classList.add('hidden'))
                e.target.style.background = 'linear-gradient(135deg,#FF8C00,#FFB84D)'
                e.target.style.color = '#fff'
                e.target.style.border = 'none'
                document.getElementById(`analytics-${tab}`)?.classList.remove('hidden')
            })
        })

        // 모달 닫기 (ESC 키)
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeAllModals()
            }
        })

        // 초기 데이터 로드 및 렌더링
        await this.loadAndRenderAll()

        // 수집 탭 전환
        // 수집하기 버튼 클릭 이벤트
        document.getElementById('btn-collect-bulk')?.addEventListener('click', () => this.handleCollect())


        // 기간 버튼 - 기본값: 올해 1월 1일 ~ 오늘
        this.initOrderDateRange()
        document.querySelectorAll('.order-period-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.order-period-btn').forEach(b => {
                    b.style.background = 'rgba(50,50,50,0.8)'
                    b.style.border = '1px solid #3D3D3D'
                    b.style.color = '#C5C5C5'
                })
                btn.style.background = 'linear-gradient(135deg,#FF8C00,#FFB84D)'
                btn.style.border = 'none'
                btn.style.color = '#fff'
                this.setOrderDateRange(btn.getAttribute('data-period'))
            })
        })

        console.log('UIManager 초기화 완료')
    }

    /**
     * 모든 데이터 로드 및 렌더링
     */
    async loadAndRenderAll() {
        // storage 초기화 완료 대기 (IndexedDB 준비될 때까지)
        await storageReady

        await productManager.loadProducts()
        await channelManager.loadChannels()
        await orderManager.loadOrders()
        await sourcingManager.loadSourcingSites()
        await analyticsManager.loadAnalytics()
        await contactManager.loadContactLogs()
        await returnManager.loadReturns()

        // 새 모듈 초기화
        if (typeof collectorManager !== 'undefined') await collectorManager.init()
        if (typeof policyManager !== 'undefined') await policyManager.init()
        if (typeof accountManager !== 'undefined') await accountManager.init()
        if (typeof categoryManager !== 'undefined') await categoryManager.init()
        if (typeof shipmentManager !== 'undefined') await shipmentManager.init()
        if (typeof forbiddenManager !== 'undefined') await forbiddenManager.init()

        this.renderDashboard()
        this.renderProducts()
        this.renderChannels()
        this.renderOrders()
        this.renderSourcing()
        this.renderAnalytics()
        this.renderCharts()
        this.renderContacts()
        this.renderReturns()
        this.updateCounts()

        // 새 모듈 렌더링
        this.renderSiteTags()
        await this.updateSavedCount()
        // 프록시 서버 상태 초기 반영 (비동기)
        setTimeout(() => this.refreshProxyStatusUI(), 2500)
        this.renderPolicyList()
        this.renderAccountCheckboxes()
        this.renderAnalyticsMarkets()
        this.renderAccountDashboard()
        await this.renderSearchFilterTable()
        await this.renderShipmentPage()
        this.renderForbiddenWords()
        this.renderAccountList()
        this.renderCategoryMappings()
        await this.renderCS()
    }

    /**
     * === 대시보드 ===
     */

    renderDashboard() {
        const today = new Date()
        const dbDate = document.getElementById('db-date')
        if (dbDate) dbDate.textContent = today.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' })

        // 수집상품 수 (searchFilters savedCount 합산)
        const collectedEl = document.getElementById('db-collected')
        if (collectedEl) {
            const total = (typeof collectorManager !== 'undefined')
                ? collectorManager.filters.reduce((sum, f) => sum + (f.savedCount || 0), 0)
                : 0
            collectedEl.textContent = total.toLocaleString() + '개'
        }

        // 주문 데이터 기반 KPI
        const orders = orderManager.orders || []
        const curY = today.getFullYear()
        const curM = today.getMonth()

        const monthOrders = orders.filter(o => {
            const d = new Date(o.createdAt)
            return d.getFullYear() === curY && d.getMonth() === curM
        })

        const monthOrderEl = document.getElementById('db-month-orders')
        if (monthOrderEl) monthOrderEl.textContent = monthOrders.length + '건'

        const totalSales = orders.reduce((sum, o) => sum + (o.salePrice || 0), 0)
        const totalSalesEl = document.getElementById('db-total-sales')
        if (totalSalesEl) totalSalesEl.textContent = '₩' + totalSales.toLocaleString()

        // 주문이행율 (취소 제외 비율)
        const fulfilled = orders.filter(o => o.status !== 'cancelled')
        const fulfillRate = orders.length > 0 ? Math.round(fulfilled.length / orders.length * 100) : 100
        const fulfillEl = document.getElementById('db-fulfill-rate')
        if (fulfillEl) fulfillEl.textContent = fulfillRate + '%'

        // 최근 일주일 매출 테이블
        const weekTbody = document.getElementById('db-week-tbody')
        if (weekTbody) {
            const rows = []
            for (let i = 6; i >= 0; i--) {
                const d = new Date(today)
                d.setDate(d.getDate() - i)
                const dayStr = d.toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' })
                const dayOrders = orders.filter(o => new Date(o.createdAt).toDateString() === d.toDateString())
                const sales = dayOrders.reduce((sum, o) => sum + (o.salePrice || 0), 0)
                const fulfilledSales = dayOrders.filter(o => o.status !== 'cancelled').reduce((sum, o) => sum + (o.salePrice || 0), 0)
                const rate = sales > 0 ? Math.round(fulfilledSales / sales * 100) : 0
                rows.push(`<tr>
                    <td>${dayStr}</td>
                    <td>₩${sales.toLocaleString()}</td>
                    <td>₩${fulfilledSales.toLocaleString()}</td>
                    <td>${rate}%</td>
                </tr>`)
            }
            weekTbody.innerHTML = rows.join('')
        }

        // 금월/전월 비교 테이블
        const monthTbody = document.getElementById('db-month-tbody')
        if (monthTbody) {
            const calcMonth = (year, month) => {
                const mo = orders.filter(o => {
                    const d = new Date(o.createdAt)
                    return d.getFullYear() === year && d.getMonth() === month
                })
                const total = mo.reduce((sum, o) => sum + (o.salePrice || 0), 0)
                const fil = mo.filter(o => o.status !== 'cancelled').reduce((sum, o) => sum + (o.salePrice || 0), 0)
                const rate = total > 0 ? Math.round(fil / total * 100) : 0
                return { total, fil, rate }
            }
            const cur = calcMonth(curY, curM)
            const prevDate = new Date(curY, curM - 1, 1)
            const prev = calcMonth(prevDate.getFullYear(), prevDate.getMonth())
            monthTbody.innerHTML = `
                <tr><td>금월</td><td>₩${cur.total.toLocaleString()}</td><td>₩${cur.fil.toLocaleString()}</td><td>${cur.rate}%</td></tr>
                <tr><td>전월</td><td>₩${prev.total.toLocaleString()}</td><td>₩${prev.fil.toLocaleString()}</td><td>${prev.rate}%</td></tr>
            `
        }
    }

    /**
     * === 상품 관리 ===
     */

    showProductModal(productId = null) {
        const modal = document.getElementById('product-modal')
        const form = document.getElementById('product-form')
        const title = document.getElementById('modal-title')

        form.reset()
        this.currentProductEditId = null

        // 이미지 미리보기 초기화
        document.getElementById('product-image-preview').innerHTML = '<i class="fas fa-image text-gray-400 text-2xl"></i>'
        document.getElementById('product-image-analysis').classList.add('hidden')
        document.getElementById('product-estimated-price').textContent = '₩0'

        if (productId) {
            const product = productManager.products.find(p => p.id === productId)
            if (product) {
                title.textContent = '상품 수정'
                form.name.value = product.name
                form.category.value = product.category
                form.sourceUrl.value = product.sourceUrl
                form.sourcePrice.value = product.sourcePrice
                form.cost.value = product.cost
                form.marginRate.value = product.marginRate
                form.description.value = product.description
                // 영문/일어명 필드 채우기
                const nameEnInput = document.getElementById('product-name-en')
                const nameJaInput = document.getElementById('product-name-ja')
                if (nameEnInput) nameEnInput.value = product.nameEn || ''
                if (nameJaInput) nameJaInput.value = product.nameJa || ''
                this.currentProductEditId = productId
            }
        } else {
            title.textContent = '상품 추가'
        }

        modal.classList.remove('hidden')
    }

    /**
     * AI 상품명 개선
     */
    async improveProductName() {
        const nameInput = document.getElementById('product-name-input')
        const category = document.getElementById('product-category').value

        if (!nameInput.value) {
            app.showNotification('상품명을 입력해주세요', 'warning')
            return
        }

        app.showLoading(true)
        const improved = await aiProcessor.improveProductName(nameInput.value, category)
        nameInput.value = improved
        app.showLoading(false)

        app.showNotification('상품명이 개선되었습니다', 'success')
    }

    /**
     * 상품 이미지 분석
     */
    async analyzeProductImage() {
        const imageInput = document.getElementById('product-image-input')
        const file = imageInput.files[0]

        if (!file) return

        app.showLoading(true)

        try {
            // 미리보기 생성
            const preview = await aiProcessor.generatePreview(file)
            document.getElementById('product-image-preview').innerHTML = `<img src="${preview}" class="w-full h-full object-cover rounded-lg">`

            // 이미지 분석
            const analysis = await aiProcessor.analyzeImage(file)

            // 분석 결과 표시
            const analysisDiv = document.getElementById('product-image-analysis')
            const tipsList = document.getElementById('product-image-tips')

            if (analysis.recommendations) {
                tipsList.innerHTML = analysis.recommendations
                    .map(rec => `<li>${rec}</li>`)
                    .join('')
                analysisDiv.classList.remove('hidden')
            }

            app.showNotification('이미지 분석 완료', 'success')
        } catch (error) {
            app.showNotification('이미지 분석 실패', 'error')
        }

        app.showLoading(false)
    }

    /**
     * 판매가 계산
     */
    calculateSalePrice() {
        const sourcePrice = parseFloat(document.getElementById('product-source-price').value) || 0
        const cost = parseFloat(document.getElementById('product-cost').value) || 0
        const marginRate = parseFloat(document.getElementById('product-margin-rate').value) || 30

        // 판매가 = 원가 / (1 - 마진율/100)
        const salePrice = Math.ceil(cost / (1 - marginRate / 100))

        document.getElementById('product-estimated-price').textContent = '₩' + this.formatNumber(salePrice)
    }

    /**
     * AI 마진율 제안
     */
    suggestMarginRate() {
        const category = document.getElementById('product-category').value
        const suggested = aiProcessor.calculateRecommendedMargin(0, category)

        document.getElementById('product-margin-rate').value = suggested
        this.calculateSalePrice()

        app.showNotification(`${category}의 추천 마진율: ${suggested}%`, 'info')
    }

    /**
     * 카테고리 변경 시 마진율 제안
     */
    updateMarginSuggestion() {
        // 자동으로 마진율 업데이트하지 않음 (사용자가 명시적으로 버튼을 눌러야 함)
    }

    closeProductModal() {
        document.getElementById('product-modal').classList.add('hidden')
        this.currentProductEditId = null
    }

    async handleProductSubmit(e) {
        e.preventDefault()
        const form = e.target
        const data = new FormData(form)

        const productData = {
            name: data.get('name'),
            category: data.get('category'),
            sourceUrl: data.get('sourceUrl'),
            sourcePrice: data.get('sourcePrice'),
            cost: data.get('cost'),
            marginRate: data.get('marginRate'),
            description: data.get('description'),
            nameEn: data.get('nameEn') || '', // 영문 상품명 (역직구용)
            nameJa: data.get('nameJa') || ''  // 일어 상품명 (역직구용)
        }

        if (this.currentProductEditId) {
            await productManager.updateProduct(this.currentProductEditId, productData)
        } else {
            await productManager.addProduct(productData)
        }

        this.closeProductModal()
        this.renderProducts()
        this.updateCounts()
    }

    /**
     * 이미지 그리드 뷰 렌더링
     */
    renderProductImageGrid(products) {
        const cells = products.map((p, idx) => {
            const imgSrc = (p.images && p.images[0]) || p.image || p.imageUrl || ''
            const regDate = p.createdAt ? p.createdAt.slice(0, 10) : '-'
            const no = String(idx + 1).padStart(6, '0')
            const imgInner = imgSrc
                ? `<img src="${imgSrc}" style="position:absolute; inset:0; width:100%; height:100%; object-fit:contain; padding:8px;">`
                : `<div style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; flex-direction:column; gap:6px;">
                    <i class="fas fa-image" style="font-size:2rem; color:#3A3A3A;"></i>
                    <span style="font-size:0.7rem; color:#444;">이미지없음</span>
                  </div>`

            return `
                <div style="background:#1E1E1E; border:1px solid #2A2A2A; border-radius:6px; overflow:hidden; cursor:pointer; position:relative;"
                     onclick="ui.focusProduct('${p.id}')">
                    <!-- 체크박스 -->
                    <input type="checkbox" class="product-select-cb" data-product-id="${p.id}"
                        style="position:absolute; top:6px; left:6px; z-index:2; accent-color:#FF8C00; width:14px; height:14px; cursor:pointer;"
                        onclick="event.stopPropagation()">
                    <!-- 이미지 영역 (1:1 비율) -->
                    <div style="position:relative; padding-top:100%; background:#161616;">
                        ${imgInner}
                    </div>
                    <!-- 하단 정보 -->
                    <div style="padding:4px 6px; border-top:1px solid #2A2A2A; text-align:center; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                        <span style="font-size:0.65rem; color:#777;">상품번호:${no} | ${regDate}</span>
                    </div>
                </div>`
        }).join('')

        return `<div style="display:grid; grid-template-columns:repeat(8,1fr); gap:4px;">${cells}</div>`
    }

    /**
     * 상품 뷰 모드 전환 (card / image)
     */
    setProductViewMode(mode) {
        this.productViewMode = mode
        // 버튼 활성화 스타일 토글
        const btnCard = document.getElementById('btn-view-card')
        const btnImage = document.getElementById('btn-view-image')
        if (btnCard) {
            btnCard.style.background = mode === 'card' ? 'rgba(255,140,0,0.15)' : 'transparent'
            btnCard.style.borderColor = mode === 'card' ? '#FF8C00' : '#3D3D3D'
            btnCard.style.color = mode === 'card' ? '#FF8C00' : '#C5C5C5'
        }
        if (btnImage) {
            btnImage.style.background = mode === 'image' ? 'rgba(255,140,0,0.15)' : 'transparent'
            btnImage.style.borderColor = mode === 'image' ? '#FF8C00' : '#3D3D3D'
            btnImage.style.color = mode === 'image' ? '#FF8C00' : '#C5C5C5'
        }
        this.renderProducts()
    }

    async renderProducts() {
        const list = document.getElementById('products-list')
        if (!list) return
        let products = productManager.products

        // 검색 필터
        const searchType = document.getElementById('product-search-type')?.value || 'name'
        const searchQuery = document.getElementById('product-search')?.value || ''

        if (searchQuery) {
            if (searchType === 'filter' && typeof collectorManager !== 'undefined') {
                // 검색그룹명으로 collectedProducts 조회
                const matchFilter = collectorManager.filters.find(f => f.name === searchQuery)
                if (matchFilter) {
                    const collected = await storage.getByIndex('collectedProducts', 'searchFilterId', matchFilter.id)
                    products = collected.map(p => ({
                        ...p,
                        cost: p.bestBenefitPrice || p.couponPrice || p.salePrice || p.originalPrice || 0,
                        sourcePrice: p.originalPrice || p.salePrice || 0,
                        marginRate: p.marginRate || 15,
                        salePrice: p.salePrice || 0,
                        status: p.status === 'saved' ? 'active' : (p.status || 'active'),
                        createdAt: p.collectedAt || p.createdAt || '',
                        _isCollected: true
                    }))
                } else {
                    products = []
                }
            } else {
                products = productManager.searchProducts(searchQuery)
            }
        }

        // 소싱사이트 필터
        const sourceSiteFilter = document.getElementById('product-source-site')?.value || ''
        if (sourceSiteFilter) products = products.filter(p => p.sourceSite === sourceSiteFilter)

        // 상태 필터
        const statusFilter = document.getElementById('product-status')?.value || ''
        if (statusFilter) products = products.filter(p => p.status === statusFilter)

        // 정렬
        const sortVal = document.getElementById('product-sort')?.value || 'collect-desc'
        const isCollect = sortVal.startsWith('collect')
        const isDesc = sortVal.endsWith('desc')
        products.sort((a, b) => {
            const aDate = isCollect
                ? (a.collectedAt || a.createdAt || '')
                : (a.updatedAt || a.createdAt || '')
            const bDate = isCollect
                ? (b.collectedAt || b.createdAt || '')
                : (b.updatedAt || b.createdAt || '')
            return isDesc ? bDate.localeCompare(aDate) : aDate.localeCompare(bDate)
        })

        // 검색결과 카운트 업데이트
        const countEl2 = document.getElementById('product-count2')
        if (countEl2) countEl2.textContent = products.length

        // 페이지 크기 적용
        const pageSize = parseInt(document.getElementById('product-page-size')?.value || '20')
        if (pageSize > 0) products = products.slice(0, pageSize)

        // 포커스 모드: 특정 상품 하나만 표시 (products.length 체크 전에 처리)
        if (this.focusedProductId) {
            let focused = products.find(p => p.id === this.focusedProductId)
            // products 스토어에 없으면 collectedProducts에서 검색 (카테고리 브라우저 클릭 시)
            if (!focused) {
                const collected = await storage.get('collectedProducts', this.focusedProductId)
                if (collected) {
                    focused = {
                        ...collected,
                        cost: collected.bestBenefitPrice || collected.couponPrice || collected.salePrice || collected.originalPrice || 0,
                        sourcePrice: collected.originalPrice || collected.salePrice || 0,
                        marginRate: collected.marginRate || 15,
                        salePrice: collected.salePrice || 0,
                        status: collected.status === 'saved' ? 'active' : (collected.status || 'active'),
                        createdAt: collected.collectedAt || collected.createdAt || '',
                        _isCollected: true
                    }
                }
            }
            if (focused) {
                products = [focused]
                if (!document.getElementById('product-focus-back')) {
                    list.insertAdjacentHTML('beforebegin',
                        `<div id="product-focus-back" style="margin-bottom:8px;">
                            <button onclick="ui.clearProductFocus()"
                                style="padding:5px 14px; font-size:0.8rem; border:1px solid #3D3D3D; border-radius:6px; color:#C5C5C5; background:rgba(40,40,40,0.9); cursor:pointer;">
                                ← 목록으로
                            </button>
                        </div>`)
                }
            }
        }

        if (products.length === 0) {
            list.innerHTML = `<div style="padding:3rem; text-align:center; color:#555; font-size:0.9rem;">등록된 상품이 없습니다</div>`
            return
        }

        // 이미지만 보기 모드
        if (this.productViewMode === 'image') {
            list.innerHTML = this.renderProductImageGrid(products)
            return
        }

        // collectedProductId → searchFilterId 조회용 맵 (기존 저장 상품 대응)
        const collectedMap = {}
        try {
            const allCollected = await storage.getAll('collectedProducts')
            allCollected.forEach(c => { collectedMap[c.id] = c })
        } catch(e) {}

        // 정책 목록 (드롭다운용)
        const policies = (typeof policyManager !== 'undefined') ? policyManager.policies : []

        list.innerHTML = products.map((product, idx) => {
            const cost = product.cost || product.sourcePrice || 0
            const marginRate = product.marginRate || 15
            const salePrice = cost > 0 ? Math.ceil(cost / (1 - marginRate / 100)) : 0
            const profit = salePrice - cost
            const isActive = product.status !== 'inactive'
            const statusColor = isActive ? '#51CF66' : '#888'
            const statusBg = isActive ? 'rgba(81,207,102,0.12)' : 'rgba(100,100,100,0.15)'
            const statusText = isActive ? '활성' : '비활성'
            const regDate = product.createdAt ? product.createdAt.slice(0, 10) : '-'
            const modDate = product.updatedAt ? product.updatedAt.slice(0, 10) : regDate
            const no = String(idx + 1).padStart(3, '0')
            const rawImgSrc = (product.images && product.images[0]) || product.image || product.imageUrl || ''
            // via.placeholder.com 등 외부 서비스 URL → SVG 대체
            let imgSrc = (rawImgSrc && !rawImgSrc.includes('via.placeholder.com')) ? rawImgSrc : ''
            if (!imgSrc) {
                const _ch = (product.brand || product.name || '?')[0]
                const _svg = `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="#1A1A1A"/><text x="100" y="140" text-anchor="middle" font-size="100" font-family="sans-serif" fill="#FF8C00">${_ch}</text></svg>`
                imgSrc = 'data:image/svg+xml,' + encodeURIComponent(_svg)
            }
            const imgHtml = `<img src="${imgSrc}" style="width:110px; height:110px; object-fit:cover; border-radius:8px; border:1px solid #2D2D2D;" onerror="this.outerHTML='<div style=\\'width:110px;height:110px;border-radius:8px;border:1px dashed #3D3D3D;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:6px;text-align:center;\\'><i class=\\'fas fa-image\\' style=\\'font-size:1.8rem;color:#3A3A3A;\\'></i><span style=\\'font-size:0.72rem;color:#444;line-height:1.3;\\'>이미지<br>없음</span></div>'">`

            // 마켓가격 섹션 (적용 정책 기준)
            const appliedPolicy = policies.find(p => p.id === product.appliedPolicyId)
            const policyName = appliedPolicy ? appliedPolicy.name : '기본'
            const pr = appliedPolicy?.pricing || {}
            const displayMarginRate = pr.marginRate || marginRate
            const displayShipping = pr.shippingCost || 0
            const displayExtra = pr.extraCharge || 0
            // 마켓 수수료: 상품에 연결된 첫 번째 채널의 feeRate
            const firstChannelId = product.channelId || Object.keys(product.channels || {})[0]
            const firstChannel = typeof channelManager !== 'undefined'
                ? channelManager.channels.find(c => c.id === firstChannelId)
                : null
            const displayFeeRate = firstChannel?.feeRate || 0
            const policyBasis = [
                `마진 ${displayMarginRate}%`,
                displayFeeRate ? `수수료 ${displayFeeRate}%` : '',
                displayShipping ? `배송비 ₩${this.formatNumber(displayShipping)}` : '',
                displayExtra ? `추가 ₩${this.formatNumber(displayExtra)}` : ''
            ].filter(Boolean).join(' · ')
            // 계산식: 원가 [+배송] ÷(1-마진%) [÷(1-수수료%)] = 마켓가
            const formulaParts = [`₩${this.formatNumber(cost)}`]
            if (displayShipping > 0) formulaParts.push(`+₩${this.formatNumber(displayShipping)}`)
            formulaParts.push(`÷(1-${displayMarginRate}%)`)
            if (displayFeeRate > 0) formulaParts.push(`÷(1-${displayFeeRate}%)`)
            formulaParts.push(`= ₩${this.formatNumber(salePrice)}`)
            const formulaStr = formulaParts.join(' ')
            const marketPriceDisplay = `<div style="display:flex; align-items:center; gap:6px; width:100%;"><div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap; white-space:nowrap;"><span style="color:#FFB84D; font-weight:600;">₩${this.formatNumber(salePrice)}</span><span style="color:#888; font-size:0.75rem;">+₩${this.formatNumber(profit)}</span>${policyBasis ? `<span style="color:#555; font-size:0.71rem; border-left:1px solid #2D2D2D; padding-left:6px;">${policyBasis}</span>` : ''}</div><span style="margin-left:auto; font-size:0.7rem; color:#3A3A3A; font-family:monospace; white-space:nowrap; padding-left:12px;">${formulaStr}</span></div>`

            // 카테고리
            const catSrc = product.sourceCategory || product.category || '-'
            const catMarket = product.marketCategory || product.category || '-'

            // 검색필터 태그 / 검색그룹 연동 표시
            const filterTags = product.filterTags || []
            // collectedProductId로 역참조 (기존 저장 상품의 검색그룹 복원)
            const linkedCollected = product.collectedProductId ? collectedMap[product.collectedProductId] : null
            const filterId = product.searchFilterId || linkedCollected?.searchFilterId || (filterTags.length > 0 ? filterTags[0] : null)
            let filterHtml = ''
            if (filterId && typeof collectorManager !== 'undefined') {
                const filter = collectorManager.filters.find(f => f.id === filterId || f.name === filterId)
                if (filter) {
                    filterHtml = `<button onclick="app.navigateTo('apply-group')"
                        style="background:rgba(255,140,0,0.08); border:1px solid rgba(255,140,0,0.25); color:rgba(255,180,100,0.85); font-size:0.72rem; padding:1px 8px; border-radius:10px; cursor:pointer; transition:all 0.15s;"
                        onmouseover="this.style.background='rgba(255,140,0,0.15)'"
                        onmouseout="this.style.background='rgba(255,140,0,0.08)'"
                    >${filter.name}</button>`
                } else {
                    filterHtml = filterTags.map(t => `<span style="background:rgba(255,140,0,0.12); color:#FF8C00; font-size:0.7rem; padding:2px 8px; border-radius:4px; border:1px solid rgba(255,140,0,0.2);">#${t}</span>`).join(' ')
                }
            } else if (filterTags.length > 0) {
                filterHtml = filterTags.map(t => `<span style="background:rgba(255,140,0,0.12); color:#FF8C00; font-size:0.7rem; padding:2px 8px; border-radius:4px; border:1px solid rgba(255,140,0,0.2);">#${t}</span>`).join(' ')
            }

            // 마켓 ON/OFF 스위치 (MARKET_LIST 기준 - 통계/전송과 동일한 소스)
            const MARKET_ID_MAP = {
                '쿠팡': 'coupang', '신세계몰': 'ssg', '스마트스토어': 'smartstore',
                '11번가': '11st', '지마켓': 'gmarket', '옥션': 'auction',
                'GS샵': 'gsshop', '롯데ON': 'lotteon', '롯데홈쇼핑': 'lottehome',
                '홈앤쇼핑': 'homeand', 'HMALL': 'hmall'
            }
            const markets = (typeof MARKET_LIST !== 'undefined' && MARKET_LIST.length > 0)
                ? MARKET_LIST.map(m => ({ id: MARKET_ID_MAP[m] || m.toLowerCase(), name: m }))
                : [
                    { id: 'coupang', name: '쿠팡' },
                    { id: 'smartstore', name: '스마트스토어' },
                    { id: '11st', name: '11번가' },
                    { id: 'gmarket', name: 'G마켓' }
                ]
            const switchHtml = markets.map(m => {
                const on = product.marketEnabled?.[m.id] !== false
                return `<span style="display:inline-flex; align-items:center; gap:4px; margin-right:10px;">
                    <button onclick="ui.toggleMarket('${product.id}','${m.id}')" style="width:32px; height:18px; border-radius:9px; border:none; cursor:pointer; position:relative; background:${on ? '#FF8C00' : '#333'}; transition:background 0.2s;">
                        <span style="position:absolute; top:2px; left:${on ? '14px' : '2px'}; width:14px; height:14px; border-radius:50%; background:#fff; transition:left 0.2s;"></span>
                    </button>
                    <span style="font-size:0.7rem; color:${on ? '#C5C5C5' : '#555'};">${m.name}</span>
                </span>`
            }).join('')

            // 삭제어 처리
            const hasForbidden = typeof forbiddenManager !== 'undefined'
            const cleanedName = hasForbidden ? forbiddenManager.cleanProductName(product.name) : product.name
            const isConverted = hasForbidden && cleanedName !== product.name
            // 등록 상품명: 원본 유지 + 삭제어 부분만 취소선 표시
            const registeredNameHtml = hasForbidden && isConverted
                ? forbiddenManager.getDeletionMarkedHtml(product.name)
                : product.name

            // 원 상품명 표시: 항상 원본 그대로 표시
            const productNameHtml = `<span style="color:#D1D9EE; font-weight:500;">${product.name}</span>`

            // 인라인 수정 모드 여부
            const isEditing = this._editingProductIds?.has(product.id) || false

            // 태그 표시 (삭제 버튼 포함)
            const tags = product.tags || []
            const tagsHtml = tags.map(t => `<span style="background:rgba(100,100,255,0.12); color:#8B8FD4; font-size:0.7rem; padding:2px 6px; border-radius:4px; border:1px solid rgba(100,100,255,0.2); display:inline-flex; align-items:center; gap:3px;">#${t.replace(/'/g,"\\'")} <button onclick="ui.deleteProductTag('${product.id}','${t.replace(/'/g,"\\'")}');event.stopPropagation()" style="font-size:0.65rem; color:#6B6FA8; background:none; border:none; cursor:pointer; padding:0; line-height:1; margin-left:1px;">✕</button></span>`).join(' ')

            // 헤더 버튼 (수정모드 / 일반모드)
            const headerBtnsHtml = isEditing
                ? `<button onclick="ui.saveProductInlineEdit('${product.id}')" style="font-size:0.7rem; padding:3px 10px; border:1px solid rgba(81,207,102,0.3); border-radius:5px; color:#51CF66; background:rgba(81,207,102,0.08); cursor:pointer;">저장</button>
                   <button onclick="ui.cancelProductInlineEdit('${product.id}')" style="font-size:0.7rem; padding:3px 10px; border:1px solid #333; border-radius:5px; color:#888; background:transparent; cursor:pointer;">취소</button>
                   <button onclick="ui.deleteProduct('${product.id}')" style="font-size:0.7rem; padding:3px 10px; border:1px solid rgba(255,107,107,0.3); border-radius:5px; color:#FF6B6B; background:rgba(255,107,107,0.08); cursor:pointer;">삭제</button>`
                : `<label style="display:flex; align-items:center; gap:4px; cursor:pointer;">
                       <input type="checkbox" ${product.stockLocked ? 'checked' : ''} onchange="ui.toggleStockLock('${product.id}',this.checked)" style="accent-color:#51CF66; width:12px; height:12px; cursor:pointer;">
                       <span style="font-size:0.7rem; color:#888;">재고잠금</span>
                   </label>
                   <label style="display:flex; align-items:center; gap:4px; cursor:pointer;">
                       <input type="checkbox" ${product.deleteLocked ? 'checked' : ''} onchange="ui.toggleDeleteLock('${product.id}',this.checked)" style="accent-color:#FF8C00; width:12px; height:12px; cursor:pointer;">
                       <span style="font-size:0.7rem; color:#888;">삭제잠금</span>
                   </label>
                   <button onclick="ui.toggleProductEdit('${product.id}')" style="font-size:0.7rem; padding:3px 10px; border:1px solid rgba(255,140,0,0.3); border-radius:5px; color:#FF8C00; background:rgba(255,140,0,0.08); cursor:pointer;">수정</button>
                   <button onclick="${product.deleteLocked ? 'app.showNotification(\'삭제잠금 상태입니다\',\'warning\')' : `ui.deleteProduct('${product.id}')`}" style="font-size:0.7rem; padding:3px 10px; border:1px solid rgba(255,107,107,0.3); border-radius:5px; color:${product.deleteLocked ? '#555' : '#FF6B6B'}; background:rgba(255,107,107,0.08); cursor:pointer;">삭제</button>`

            // 인라인 편집 셀
            const nameCell = isEditing
                ? `<input type="text" data-field="name" value="${(product.name || '').replace(/"/g, '&quot;')}" style="width:100%; padding:3px 7px; font-size:0.8rem; background:#1A1A1A; border:1px solid #FF8C00; color:#C5C5C5; border-radius:4px; outline:none;">`
                : productNameHtml

            // 정상가(normalPrice) / 원가(최대혜택가)
            const normalPrice = product.sourcePrice || product.originalPrice || 0
            const costCell = `<span style="color:#C5C5C5; font-weight:600;">${normalPrice > 0 ? `₩${this.formatNumber(normalPrice)}` : '-'}</span>${product.discountRate ? `<span style="color:#FF6B6B; font-size:0.72rem; margin-left:6px;">${product.discountRate}% 할인 → ₩${this.formatNumber(product.salePrice || 0)}</span>` : ''}`
            // bestBenefitPrice 우선 (쿠폰/혜택 포함 최저가) — 옵션은 salePrice 기준이라 혜택가보다 높을 수 있음
            const validOptPrices = (product.options || []).filter(o => !o.isSoldOut && (o.price || 0) > 0).map(o => o.price)
            const optMinPrice = validOptPrices.length > 0 ? Math.min(...validOptPrices) : 0
            const costPrice = product.bestBenefitPrice || optMinPrice || product.couponPrice || product.salePrice || cost
            const isLoggedInPrice = product.isLoggedIn
            const benefitLabel = isLoggedInPrice ? '로그인 최대혜택가' : '최대혜택가'
            const costPriceCell = isEditing
                ? `<input type="number" data-field="cost" value="${cost}" style="width:120px; padding:3px 7px; font-size:0.8rem; background:#1A1A1A; border:1px solid #FF8C00; color:#C5C5C5; border-radius:4px; outline:none;"> <span style="color:#444; font-size:0.72rem; margin-left:6px;">원가</span>`
                : `<span style="color:#FFB84D; font-weight:600;">₩${this.formatNumber(costPrice)}</span><span style="color:#444; font-size:0.72rem; margin-left:6px;">${benefitLabel}</span>`

            const marketPriceCell = isEditing
                ? `<input type="number" data-field="marginRate" value="${marginRate}" style="width:80px; padding:3px 7px; font-size:0.8rem; background:#1A1A1A; border:1px solid #FF8C00; color:#C5C5C5; border-radius:4px; outline:none;"> <span style="color:#444; font-size:0.72rem; margin-left:4px;">% 마진율</span>`
                : marketPriceDisplay

            return `
            <div data-product-id="${product.id}" style="background:rgba(22,22,22,0.9); border:1px solid #2A2A2A; border-radius:10px; overflow:hidden;">
                <!-- 카드 헤더 -->
                <div style="display:flex; align-items:center; justify-content:space-between; padding:7px 14px; background:rgba(15,15,15,0.8); border-bottom:1px solid #222;">
                    <div style="display:flex; align-items:center; gap:12px; font-size:0.75rem; color:#666;">
                        <input type="checkbox" class="product-select-cb" data-product-id="${product.id}" style="accent-color:#FF8C00; width:13px; height:13px; cursor:pointer;">
                        <span style="color:#444;">No.${no}</span>
                        <span>수집 <span style="color:#888;">${regDate}</span></span>
                        <span>업데이트 <span style="color:#888;">${modDate}</span></span>
                    </div>
                    <div style="display:flex; gap:6px; align-items:center;">
                        ${headerBtnsHtml}
                    </div>
                </div>
                <!-- 카드 바디 -->
                <div style="display:flex; gap:0; padding:14px;">
                    <!-- 좌: 이미지 -->
                    <div style="width:130px; flex-shrink:0; display:flex; flex-direction:column; align-items:center; gap:8px; padding-right:14px; border-right:1px solid #222;">
                        ${imgHtml}
                        <button onclick="ui.openImageEditor('${product.id}')" style="font-size:0.68rem; color:#666; background:transparent; border:1px solid #2D2D2D; border-radius:4px; padding:3px 10px; cursor:pointer; width:100%;">이미지 변경</button>
                        ${product.sourceSite ? `<span style="font-size:0.7rem; color:#FF8C00; background:rgba(255,140,0,0.1); border:1px solid rgba(255,140,0,0.25); border-radius:4px; padding:2px 8px; width:100%; text-align:center; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${product.sourceSite}</span>` : ''}
                    </div>
                    <!-- 우: 상세 정보 테이블 -->
                    <div style="flex:1; padding-left:16px;">
                        <!-- 액션 버튼 바 -->
                        <div style="display:flex; flex-wrap:wrap; gap:3px; margin-bottom:8px;">
                            <button onclick="ui.showPriceHistory('${product.id}')" style="font-size:0.72rem; padding:3px 9px; background:#1E1E1E; color:#999; border:1px solid #2D2D2D; border-radius:3px; cursor:pointer; white-space:nowrap;">가격변경이력</button>
                            <button onclick="${product.sourceUrl ? `window.open('${product.sourceUrl}','_blank')` : `app.showNotification('원문링크 없음','warning')`}" style="font-size:0.72rem; padding:3px 9px; background:#1E1E1E; color:#999; border:1px solid #2D2D2D; border-radius:3px; cursor:pointer; white-space:nowrap;">원문링크</button>
                            <button onclick="ui.enrichSingleProduct('${product.id}')" style="font-size:0.72rem; padding:3px 9px; background:#1E1E1E; color:#999; border:1px solid #2D2D2D; border-radius:3px; cursor:pointer; white-space:nowrap;">업데이트</button>
                            <button onclick="ui.goToShipmentWithProduct('${product.id}')" style="font-size:0.72rem; padding:3px 9px; background:#1E1E1E; color:#FF6B6B; border:1px solid rgba(255,107,107,0.2); border-radius:3px; cursor:pointer; white-space:nowrap;">마켓삭제</button>
                        </div>
                        <table style="width:100%; border-collapse:collapse; font-size:0.8125rem;">
                            <colgroup><col style="width:80px;"><col></colgroup>
                            <tbody>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; white-space:nowrap; vertical-align:middle;">원 상품명</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">${nameCell}</td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; white-space:nowrap; vertical-align:middle;">등록 상품명</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">
                                        <span style="color:#D1D9EE; font-size:0.8rem;">${registeredNameHtml}</span>
                                    </td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; white-space:nowrap; vertical-align:middle;">영문 상품명</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">
                                        <input type="text" data-field="nameEn" placeholder="영문 상품명 (English)" value="${(product.nameEn || '').replace(/"/g, '&quot;')}"
                                            style="width:100%; padding:3px 7px; font-size:0.8rem; background:#1A1A1A; border:1px solid #2D2D2D; color:#C5C5C5; border-radius:4px; outline:none;">
                                    </td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; white-space:nowrap; vertical-align:middle;">일문 상품명</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">
                                        <input type="text" data-field="nameJa" placeholder="일문 상품명 (日本語)" value="${(product.nameJa || '').replace(/"/g, '&quot;')}"
                                            style="width:100%; padding:3px 7px; font-size:0.8rem; background:#1A1A1A; border:1px solid #2D2D2D; color:#C5C5C5; border-radius:4px; outline:none;">
                                    </td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; vertical-align:middle;">정상가</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">${costCell}</td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; vertical-align:middle;">원가</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">${costPriceCell}</td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; vertical-align:middle;">마켓가격</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">${marketPriceCell}</td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; vertical-align:middle;">카테고리</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">
                                        <span style="font-size:0.8rem;">${this.formatCategoryHierarchy(catSrc)}</span>
                                    </td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; vertical-align:top; padding-top:10px;">상품정보</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">
                                        <div style="display:flex; flex-wrap:wrap; gap:4px 16px; font-size:0.78rem;">
                                            ${product.origin ? `<span style="color:#888;">제조국 <span style="color:#C5C5C5;">${product.origin}</span></span>` : ''}
                                            ${product.manufacturer ? `<span style="color:#888;">제조사 <span style="color:#C5C5C5;">${product.manufacturer}</span></span>` : ''}
                                            ${product.styleCode ? `<span style="color:#888;">품번 <span style="color:#C5C5C5;">${product.styleCode}</span></span>` : ''}
                                            ${product.season ? `<span style="color:#888;">시즌 <span style="color:#C5C5C5;">${product.season}</span></span>` : ''}
                                            ${product.kcCert ? `<span style="color:#888;">KC <span style="color:#C5C5C5;">${product.kcCert}</span></span>` : ''}
                                            ${!product.origin && !product.manufacturer && !product.styleCode ? '<span style="color:#444;">정보 없음</span>' : ''}
                                        </div>
                                        ${product.material ? `<div style="margin-top:3px; font-size:0.75rem; color:#888;">소재 <span style="color:#B0B0B0;">${product.material}</span></div>` : ''}
                                        ${product.color ? `<div style="margin-top:2px; font-size:0.75rem; color:#888;">색상 <span style="color:#B0B0B0;">${product.color}</span></div>` : ''}
                                        ${product.sizeInfo ? `<div style="margin-top:2px; font-size:0.75rem; color:#888;">치수 <span style="color:#B0B0B0;">${product.sizeInfo}</span></div>` : ''}
                                        ${product.careInstructions ? `<div style="margin-top:2px; font-size:0.75rem; color:#888;">취급주의 <span style="color:#B0B0B0;">${product.careInstructions}</span></div>` : ''}
                                        ${product.qualityGuarantee ? `<div style="margin-top:2px; font-size:0.75rem; color:#888;">품질보증 <span style="color:#B0B0B0;">${product.qualityGuarantee}</span></div>` : ''}
                                    </td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; vertical-align:middle;">검색그룹</td>
                                    <td style="padding:6px 8px; vertical-align:middle; display:flex; flex-wrap:wrap; gap:4px; align-items:center;">${filterHtml}</td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; vertical-align:middle;">적용정책</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">
                                        <select onchange="ui.changeProductPolicy('${product.id}', this.value, ${!!product._isCollected})"
                                            style="background:rgba(22,22,22,0.9); border:1px solid #2D2D2D; color:#C5C5C5; border-radius:4px; padding:2px 6px; font-size:0.75rem; outline:none;">
                                            <option value="" ${!product.appliedPolicyId ? 'selected' : ''}>기본 (그룹 정책)</option>
                                            ${policies.map(p => `<option value="${p.id}" ${p.id === product.appliedPolicyId ? 'selected' : ''}>${p.name}</option>`).join('')}
                                        </select>
                                    </td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; vertical-align:middle;">태그</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">
                                        <div style="display:flex; flex-wrap:wrap; gap:4px; align-items:center;">
                                            ${tagsHtml}
                                            <input type="text" id="tag-input-${product.id}" placeholder="태그는 ','로 구분입력"
                                                onkeydown="if(event.key==='Enter'){ui.addProductTagInline('${product.id}');event.preventDefault()}"
                                                style="font-size:0.7rem; padding:2px 7px; border:1px solid #2D2D2D; border-radius:4px; color:#C5C5C5; background:#1A1A1A; outline:none; width:160px;">
                                            <button onclick="ui.addProductTagInline('${product.id}')" style="font-size:0.68rem; padding:2px 7px; border:1px solid rgba(100,100,255,0.3); border-radius:4px; color:#8B8FD4; background:rgba(100,100,255,0.08); cursor:pointer; white-space:nowrap;">추가</button>
                                        </div>
                                    </td>
                                </tr>
                                <tr style="border-bottom:1px solid #1E1E1E;">
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; vertical-align:middle;">옵션</td>
                                    <td style="padding:6px 8px;">
                                        ${product.options && product.options.length
                                            ? `<div style="display:flex; align-items:center; gap:8px;">
                                                <span style="color:#888; font-size:0.78rem;">${product.options.length}개 옵션</span>
                                                <button onclick="const t=this.closest('td').querySelector('.opt-panel');t.style.display=t.style.display==='none'?'block':'none';this.textContent=t.style.display==='none'?'펼치기':'접기'"
                                                    style="font-size:0.7rem; padding:2px 8px; border:1px solid #2D2D2D; border-radius:4px; color:#888; background:transparent; cursor:pointer;">펼치기</button>
                                               </div>
                                               <div class="opt-panel" style="display:none; margin-top:8px;">${this.renderOptionTable(product)}</div>`
                                            : `<span style="color:#444; font-size:0.75rem;">※ 옵션 미설정 — 단일상품</span>`}
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding:6px 8px; color:#555; font-size:0.75rem; vertical-align:middle;">ON-OFF</td>
                                    <td style="padding:6px 8px; vertical-align:middle;">${switchHtml}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>`
        }).join('')
    }

    // ==================== 옵션 테이블 렌더링 ====================

    /**
     * 상품 옵션 테이블 렌더링 (이미지 기준 신규 UI)
     * @param {Object} product - 상품 객체
     * @returns {string} HTML 문자열
     */
    renderOptionTable(product) {
        const options = product.options || []
        const basePrice = product.originalPrice || product.cost || 0

        // 상단 버튼 + 안내문구
        const headerBtns = `
            <div style="display:flex; gap:0.5rem; margin-bottom:0.5rem;">
                <button onclick="ui.saveSelectedOptions('${product.id}')"
                    style="padding:0.3rem 0.75rem; font-size:0.8rem; background:linear-gradient(135deg,#FF8C00,#FFB84D); color:#fff; border:none; border-radius:4px; cursor:pointer;">선택옵션수정</button>
                <button onclick="ui.addOption('${product.id}')"
                    style="padding:0.3rem 0.75rem; font-size:0.8rem; background:rgba(50,50,50,0.8); color:#C5C5C5; border:1px solid #3D3D3D; border-radius:4px; cursor:pointer;">옵션담기</button>
            </div>
            <p style="font-size:0.72rem; color:#888; margin-bottom:0.75rem; line-height:1.5;">
                ※ 옵션별로 가격 및 재고 수정이 가능합니다. 가격/재고를 수정하시면 해외 가격/재고는 무시되고, 수정하신 가격/재고로 반영됩니다.<br>
                ※ 체크박스에 체크되어 있는 상품만 마켓으로 전송됩니다. 전송을 원하지 않는 옵션은 체크를 해제하신 후 옵션저장 버튼을 클릭해주세요.
            </p>`

        // 테이블 헤더
        const thead = `
            <thead>
                <tr style="border-bottom:1px solid #2D2D2D;">
                    <th style="width:36px; padding:0.5rem; text-align:center;">
                        <input type="checkbox" id="opt-all-${product.id}" onchange="ui.toggleAllOptions('${product.id}',this.checked)" style="cursor:pointer;">
                    </th>
                    <th style="padding:0.5rem; text-align:left; font-size:0.8rem; color:#999; font-weight:500;">
                        옵션명
                        <button onclick="ui.renameOptionModal('${product.id}')" style="margin-left:0.4rem; font-size:0.7rem; padding:1px 6px; background:rgba(255,140,0,0.15); color:#FF8C00; border:1px solid rgba(255,140,0,0.3); border-radius:3px; cursor:pointer;">옵션명변경</button>
                        <button onclick="ui.addOption('${product.id}')" style="margin-left:0.3rem; font-size:0.7rem; padding:1px 6px; background:rgba(255,255,255,0.05); color:#C5C5C5; border:1px solid #3D3D3D; border-radius:3px; cursor:pointer;">옵션추가</button>
                    </th>
                    <th style="padding:0.5rem; text-align:right; font-size:0.8rem; color:#999; font-weight:500;">원가</th>
                    <th style="padding:0.5rem; text-align:right; font-size:0.8rem; color:#999; font-weight:500;">
                        상품가
                        <button onclick="ui.bulkPriceEdit('${product.id}')" style="margin-left:0.3rem; font-size:0.7rem; padding:1px 6px; background:rgba(255,255,255,0.05); color:#C5C5C5; border:1px solid #3D3D3D; border-radius:3px; cursor:pointer;">가격수정</button>
                    </th>
                    <th style="padding:0.5rem; text-align:right; font-size:0.8rem; color:#999; font-weight:500;">
                        옵션재고
                        <button onclick="ui.bulkStockEdit('${product.id}')" style="margin-left:0.3rem; font-size:0.7rem; padding:1px 6px; background:rgba(255,255,255,0.05); color:#C5C5C5; border:1px solid #3D3D3D; border-radius:3px; cursor:pointer;">재고수정</button>
                    </th>
                    <th style="padding:0.5rem; text-align:right; font-size:0.8rem; color:#999; font-weight:500;">마켓전송가격<br><span style="font-size:0.7rem; color:#666;">(마켓수수료 포함가격)</span></th>
                </tr>
            </thead>`

        // 행 생성
        const rows = options.map((o, idx) => {
            const optionCost = o.price || basePrice
            const optionSalePrice = product.salePrice || Math.ceil(optionCost * (1 + (product.marginRate || 15) / 100))
            const origStock = o.originalStock ?? o.stock
            const currentStock = o.stock ?? origStock
            const stockUnknown = currentStock === null || currentStock === undefined || currentStock === -1

            // 품절 판정: isSoldOut 또는 stockStatus 또는 stock === 0
            const isBrandDelivery = o.isBrandDelivery === true
            const isSoldOut = !isBrandDelivery && (o.isSoldOut || o.stockStatus === '품절' || currentStock === 0)
            let stockDisplay
            if (isBrandDelivery) {
                stockDisplay = '<span style="color:#6B8AFF; font-weight:600; font-size:0.78rem;">브랜드배송</span>'
            } else if (isSoldOut) {
                stockDisplay = '<span style="color:#FF6B6B; font-weight:600;">품절</span>'
            } else if (stockUnknown) {
                stockDisplay = `<input type="number" value="" placeholder="직접입력" data-field="stock" data-idx="${idx}" data-pid="${product.id}"
                    style="width:70px; background:rgba(255,255,255,0.05); border:1px solid #3D3D3D; color:#E5E5E5; border-radius:4px; padding:2px 6px; text-align:right; font-size:0.875rem;">
                    <span style="font-size:0.72rem; color:#51CF66;">재고있음</span>`
            } else if (currentStock >= 999) {
                stockDisplay = `<input type="number" value="" placeholder="직접입력" data-field="stock" data-idx="${idx}" data-pid="${product.id}"
                    style="width:70px; background:rgba(255,255,255,0.05); border:1px solid #3D3D3D; color:#E5E5E5; border-radius:4px; padding:2px 6px; text-align:right; font-size:0.875rem;">
                    <span style="font-size:0.72rem; color:#51CF66;">충분</span>`
            } else {
                stockDisplay = `<input type="number" value="${currentStock}" data-field="stock" data-idx="${idx}" data-pid="${product.id}"
                    style="width:60px; background:rgba(255,255,255,0.05); border:1px solid #3D3D3D; color:#E5E5E5; border-radius:4px; padding:2px 6px; text-align:right; font-size:0.875rem;">개`
            }
            const origStockLabel = !stockUnknown && origStock !== null && origStock !== undefined && origStock !== -1 && origStock !== currentStock
                ? `<br><span style="font-size:0.7rem; color:#666;">(원재고: ${origStock}개)</span>`
                : ''

            // 마켓전송가격: marketPrices에서 계정별 가격 표시
            const marketPriceLines = Object.entries(product.marketPrices || {}).map(([accId, price]) => {
                const accLabel = typeof accountManager !== 'undefined'
                    ? accountManager.getAccountLabel(accId)
                    : accId
                return `<div style="font-size:0.78rem; color:#C5C5C5;">${accLabel} : <span style="color:#FFB84D; font-weight:600;">${price?.toLocaleString()}원</span></div>`
            }).join('') || '<span style="color:#555; font-size:0.75rem;">미계산</span>'

            const isChecked = o.enabled !== false && !isSoldOut

            return `
                <tr id="opt-row-${product.id}-${idx}" style="border-bottom:1px solid rgba(45,45,45,0.5);${isSoldOut ? ' opacity:0.5;' : ''}">
                    <td style="padding:0.5rem; text-align:center;">
                        <input type="checkbox" class="opt-cb-${product.id}" data-idx="${idx}" ${isChecked ? 'checked' : ''} style="cursor:pointer; accent-color:#FF8C00;">
                    </td>
                    <td style="padding:0.5rem; font-size:0.875rem; color:#E5E5E5;">${o.name}</td>
                    <td style="padding:0.5rem; text-align:right; font-size:0.875rem; color:#C5C5C5;">₩${optionCost.toLocaleString()}</td>
                    <td style="padding:0.5rem; text-align:right; font-size:0.875rem; color:#E5E5E5;">
                        <input type="number" value="${optionSalePrice}" data-field="price" data-idx="${idx}" data-pid="${product.id}"
                            style="width:100px; background:rgba(255,255,255,0.05); border:1px solid #3D3D3D; color:#E5E5E5; border-radius:4px; padding:2px 6px; text-align:right; font-size:0.875rem;">원
                    </td>
                    <td style="padding:0.5rem; text-align:right; font-size:0.875rem; color:#E5E5E5;">
                        ${stockDisplay}${origStockLabel}
                    </td>
                    <td style="padding:0.5rem; text-align:right;">${marketPriceLines}</td>
                </tr>`
        }).join('')

        return `${headerBtns}<table style="width:100%; border-collapse:collapse;">${thead}<tbody>${rows}</tbody></table>`
    }

    /**
     * 선택된 옵션들의 price, stock 값을 저장
     * @param {string} productId - 상품 ID
     */
    async saveSelectedOptions(productId) {
        // products 또는 collectedProducts에서 상품 조회
        let product = await storage.get('products', productId)
        const storeKey = product ? 'products' : 'collectedProducts'
        if (!product) product = await storage.get('collectedProducts', productId)
        if (!product || !product.options) return

        // 체크된 옵션 인덱스 수집
        const checkboxes = document.querySelectorAll(`.opt-cb-${productId}`)
        const checkedIndices = new Set()
        checkboxes.forEach(cb => {
            if (cb.checked) checkedIndices.add(parseInt(cb.dataset.idx))
        })

        // price, stock 입력값 반영
        const priceInputs = document.querySelectorAll(`input[data-pid="${productId}"]`)
        priceInputs.forEach(input => {
            const idx = parseInt(input.dataset.idx)
            const field = input.dataset.field
            if (product.options[idx] && field) {
                product.options[idx][field] = parseFloat(input.value) || 0
            }
        })

        // 체크 상태 저장 (checked 필드)
        product.options.forEach((o, idx) => {
            o.enabled = checkedIndices.has(idx)
        })

        product.updatedAt = new Date().toISOString()
        await storage.save(storeKey, product)
        app.showNotification('옵션이 저장되었습니다', 'success')
    }

    /**
     * 옵션 추가 (프롬프트로 옵션명 입력)
     * @param {string} productId - 상품 ID
     */
    async addOption(productId) {
        const name = await this.showPrompt('추가할 옵션명을 입력하세요', { title: '옵션 추가' })
        if (!name || !name.trim()) return

        let product = await storage.get('products', productId)
        const storeKey = product ? 'products' : 'collectedProducts'
        if (!product) product = await storage.get('collectedProducts', productId)
        if (!product) return

        if (!product.options) product.options = []
        product.options.push({ name: name.trim(), price: 0, stock: 0, enabled: true })
        product.updatedAt = new Date().toISOString()
        await storage.save(storeKey, product)

        // productManager 캐시 동기화
        if (storeKey === 'products' && typeof productManager !== 'undefined') {
            const idx = productManager.products.findIndex(p => p.id === productId)
            if (idx !== -1) productManager.products[idx] = product
        }

        app.showNotification(`옵션 '${name.trim()}'이 추가되었습니다`, 'success')
        this.renderProducts()
    }

    /**
     * 전체 옵션 체크박스 토글
     * @param {string} productId - 상품 ID
     * @param {boolean} checked - 체크 여부
     */
    toggleAllOptions(productId, checked) {
        document.querySelectorAll(`.opt-cb-${productId}`).forEach(cb => {
            cb.checked = checked
        })
    }

    /**
     * 일괄 가격 수정 (준비 중)
     * @param {string} productId - 상품 ID
     */
    bulkPriceEdit(productId) {
        app.showNotification('준비 중입니다', 'info')
    }

    /**
     * 일괄 재고 수정 (준비 중)
     * @param {string} productId - 상품 ID
     */
    bulkStockEdit(productId) {
        app.showNotification('준비 중입니다', 'info')
    }

    /**
     * 옵션명 변경 모달 (준비 중)
     * @param {string} productId - 상품 ID
     */
    renameOptionModal(productId) {
        app.showNotification('준비 중입니다', 'info')
    }

    // ==================== 마켓 ON/OFF ====================

    async toggleMarket(productId, marketName) {
        const product = productManager.products.find(p => p.id === productId)
        if (!product) return
        if (!product.marketEnabled) product.marketEnabled = {}
        // 현재 값이 false이면 true로, 그 외(true/undefined)이면 false로 토글
        product.marketEnabled[marketName] = product.marketEnabled[marketName] === false ? true : false
        await storage.save('products', product)

        // collectedProductId 역참조로 collectedProducts도 동기화
        if (product.collectedProductId) {
            const cp = await storage.get('collectedProducts', product.collectedProductId)
            if (cp) {
                await storage.save('collectedProducts', {
                    ...cp,
                    marketTransmitEnabled: Object.values(product.marketEnabled).some(v => v),
                    updatedAt: new Date().toISOString()
                })
            }
        }

        this.renderProducts()
    }

    /**
     * 상품 1개 완전 삭제 (products + collectedProducts + savedCount 동기화)
     * @param {string} productId - products 스토어 or collectedProducts 스토어 ID
     * @returns {string|null} 감소한 searchFilterId (없으면 null)
     */
    async _deleteProductWithCascade(productId) {
        let searchFilterId = null

        if (productId.startsWith('col_')) {
            // collectedProducts 스토어 항목
            const cp = await storage.get('collectedProducts', productId)
            searchFilterId = cp?.searchFilterId || null
            await storage.delete('collectedProducts', productId)
            productManager.products = productManager.products.filter(p => p.id !== productId)
        } else {
            // products 스토어 항목 (bridge)
            const prod = await storage.get('products', productId)
            // collectedProductId 연결된 항목도 삭제
            if (prod?.collectedProductId) {
                const cp = await storage.get('collectedProducts', prod.collectedProductId)
                searchFilterId = cp?.searchFilterId || prod.searchFilterId || null
                await storage.delete('collectedProducts', prod.collectedProductId)
            } else {
                searchFilterId = prod?.searchFilterId || null
            }
            await storage.delete('products', productId)
            productManager.products = productManager.products.filter(p => p.id !== productId)
        }

        // searchFilters savedCount 감소
        if (searchFilterId && typeof collectorManager !== 'undefined') {
            const filter = collectorManager.filters.find(f => f.id === searchFilterId)
            if (filter && filter.savedCount > 0) {
                await collectorManager.updateFilter(filter.id, { savedCount: filter.savedCount - 1 })
            }
        }

        return searchFilterId
    }

    async deleteProduct(productId) {
        // 삭제 잠금 체크 (products 스토어 또는 collectedProducts 스토어)
        let targetProduct = productManager.products.find(p => p.id === productId)
        if (!targetProduct && productId.startsWith('col_')) {
            try { targetProduct = await storage.get('collectedProducts', productId) } catch {}
        }
        if (targetProduct?.deleteLocked) {
            app.showNotification('삭제잠금 상태입니다', 'warning')
            return
        }
        if (await this.showConfirm('정말 삭제하시겠습니까?', { title: '상품 삭제', danger: true })) {
            await this._deleteProductWithCascade(productId)
            app.showNotification('상품이 삭제되었습니다', 'success')
            this.renderProducts()
            this.updateCounts()
            await this.renderSearchFilterTable()
        }
    }

    // 인라인 수정 모드 토글
    toggleProductEdit(productId) {
        if (!this._editingProductIds) this._editingProductIds = new Set()
        if (this._editingProductIds.has(productId)) {
            this._editingProductIds.delete(productId)
        } else {
            this._editingProductIds.add(productId)
        }
        this.renderProducts()
    }

    /**
     * 이미지 그리드 클릭 → 건별보기로 전환 + 해당 상품만 표시
     */
    focusProduct(productId) {
        document.getElementById('product-focus-back')?.remove()
        this.focusedProductId = productId
        this.setProductViewMode('card')
        this.renderProducts()
    }

    clearProductFocus() {
        document.getElementById('product-focus-back')?.remove()
        this.focusedProductId = null
        this.setProductViewMode('image')
        this.renderProducts()
    }

    /**
     * 이미지 그리드에서 클릭 → 건별보기로 전환 후 해당 상품으로 스크롤
     */
    jumpToProduct(productId) {
        this.setProductViewMode('card')
        requestAnimationFrame(() => {
            const card = document.querySelector(`[data-product-id="${productId}"]`)
            if (!card) return
            card.scrollIntoView({ behavior: 'smooth', block: 'center' })
        })
    }

    // ==================== 선택처리 일괄 액션 ====================

    toggleSelectActionMenu() {
        const menu = document.getElementById('select-action-menu')
        if (!menu) return
        const isVisible = menu.style.display !== 'none'
        menu.style.display = isVisible ? 'none' : 'block'
        if (!isVisible) {
            const close = (e) => {
                if (!menu.contains(e.target) && e.target.id !== 'btn-select-action') {
                    menu.style.display = 'none'
                    document.removeEventListener('click', close)
                }
            }
            setTimeout(() => document.addEventListener('click', close), 0)
        }
    }

    async bulkAiImageChange() {
        const checked = [...document.querySelectorAll('.product-select-cb:checked')]
        if (checked.length === 0) { app.showNotification('상품을 선택해주세요', 'warning'); return }
        app.showNotification(`${checked.length}개 상품 AI이미지 변경 처리 중...`, 'info')
        // TODO: aiProcessor 연동
    }

    async bulkAiNameChange() {
        const checked = [...document.querySelectorAll('.product-select-cb:checked')]
        if (checked.length === 0) { app.showNotification('상품을 선택해주세요', 'warning'); return }
        app.showNotification(`${checked.length}개 상품 AI상품명 변경 처리 중...`, 'info')
        // TODO: aiProcessor 연동
    }

    async bulkAiTagChange() {
        const checked = [...document.querySelectorAll('.product-select-cb:checked')]
        if (checked.length === 0) { app.showNotification('상품을 선택해주세요', 'warning'); return }
        app.showNotification(`${checked.length}개 상품 AI태그 생성 처리 중...`, 'info')
        // TODO: aiProcessor 연동
    }

    bulkShipment() {
        const checked = [...document.querySelectorAll('.product-select-cb:checked')]
        if (checked.length === 0) { app.showNotification('전송할 상품을 선택해주세요', 'warning'); return }
        app.navigateTo('shipment')
    }

    /**
     * 카테고리 브라우저에서 상품 클릭 → 상품관리 페이지로 이동 후 해당 상품만 표시
     */
    navigateToProduct(productId) {
        document.getElementById('product-focus-back')?.remove()
        this.focusedProductId = productId
        app.navigateTo('products')
        // renderProducts는 app.navigateTo 내부에서 100ms 후 호출됨
        // focusedProductId가 세팅되어 있으므로 해당 상품만 렌더링됨
    }

    // 인라인 수정 저장
    async saveProductInlineEdit(productId) {
        const card = document.querySelector(`[data-product-id="${productId}"]`)
        if (!card) return
        const get = (field) => card.querySelector(`[data-field="${field}"]`)?.value
        const updates = {}
        const name = get('name')
        if (name !== undefined) updates.name = name
        const cost = get('cost')
        if (cost !== undefined) updates.cost = parseFloat(cost) || 0
        const marginRate = get('marginRate')
        if (marginRate !== undefined) updates.marginRate = parseFloat(marginRate) || 0
        const nameEn = get('nameEn')
        if (nameEn !== undefined) updates.nameEn = nameEn
        const nameJa = get('nameJa')
        if (nameJa !== undefined) updates.nameJa = nameJa
        await productManager.updateProduct(productId, updates)
        this._editingProductIds?.delete(productId)
        this.renderProducts()
    }

    // 인라인 수정 취소
    cancelProductInlineEdit(productId) {
        this._editingProductIds?.delete(productId)
        this.renderProducts()
    }

    // 삭제 잠금 토글
    async toggleDeleteLock(productId, locked) {
        if (productId.startsWith('col_')) {
            // collectedProducts 스토어 직접 업데이트
            try {
                const p = await storage.get('collectedProducts', productId)
                if (p) {
                    p.deleteLocked = locked
                    await storage.save('collectedProducts', p)
                    // productManager.products에도 반영
                    const idx = productManager.products.findIndex(x => x.id === productId)
                    if (idx !== -1) productManager.products[idx].deleteLocked = locked
                }
            } catch (e) { console.error('삭제잠금 저장 실패:', e) }
        } else {
            await productManager.updateProduct(productId, { deleteLocked: locked })
        }
    }

    // 재고 잠금 토글
    toggleStockLock(productId, locked) {
        productManager.updateProduct(productId, { stockLocked: locked })
    }

    // 상품 태그 인라인 추가 (","로 구분 다중입력 지원)
    async addProductTagInline(productId) {
        const input = document.getElementById(`tag-input-${productId}`)
        if (!input) return
        const raw = input.value.trim()
        if (!raw) return
        const newTags = raw.split(',').map(t => t.trim()).filter(Boolean)
        input.value = ''

        let product = productManager.products.find(p => p.id === productId)
        let isCollected = false
        if (!product && productId.startsWith('col_')) {
            try { product = await storage.get('collectedProducts', productId); isCollected = !!product } catch {}
        }
        if (!product) return

        const tags = [...(product.tags || [])]
        for (const t of newTags) { if (!tags.includes(t)) tags.push(t) }

        if (isCollected) {
            product.tags = tags
            await storage.save('collectedProducts', product)
            const idx = productManager.products.findIndex(x => x.id === productId)
            if (idx !== -1) productManager.products[idx].tags = tags
        } else {
            await productManager.updateProduct(productId, { tags })
        }
        this.renderProducts()
    }

    // 상품 태그 삭제
    async deleteProductTag(productId, tagToRemove) {
        let product = productManager.products.find(p => p.id === productId)
        let isCollected = false
        if (!product && productId.startsWith('col_')) {
            try { product = await storage.get('collectedProducts', productId); isCollected = !!product } catch {}
        }
        if (!product) return

        const tags = (product.tags || []).filter(t => t !== tagToRemove)
        if (isCollected) {
            product.tags = tags
            await storage.save('collectedProducts', product)
            const idx = productManager.products.findIndex(x => x.id === productId)
            if (idx !== -1) productManager.products[idx].tags = tags
        } else {
            await productManager.updateProduct(productId, { tags })
        }
        this.renderProducts()
    }

    // 상품 전체선택 체크박스
    toggleAllProductsCheckbox(checked) {
        document.querySelectorAll('.product-select-cb').forEach(cb => { cb.checked = checked })
    }

    /**
     * 선택된 상품 일괄 삭제
     */
    async deleteSelectedProducts() {
        const checked = [...document.querySelectorAll('.product-select-cb:checked')]
        if (checked.length === 0) {
            app.showNotification('삭제할 상품을 선택해주세요', 'warning')
            return
        }
        if (!await this.showConfirm(`선택된 ${checked.length}개 상품을 삭제하시겠습니까?`, { title: '상품 일괄 삭제', danger: true })) return

        const ids = checked.map(cb => cb.dataset.productId).filter(Boolean)
        if (ids.length === 0) {
            app.showNotification('상품 ID를 찾을 수 없습니다', 'error')
            return
        }

        let deletedCount = 0
        for (const id of ids) {
            try {
                await this._deleteProductWithCascade(id)
                deletedCount++
            } catch (e) {
                console.error('상품 삭제 오류:', id, e)
            }
        }

        if (deletedCount > 0) {
            app.showNotification(`${deletedCount}개 상품이 삭제되었습니다`, 'success')
        }
        // DB에서 최신 상태 재로드 후 렌더링
        await productManager.loadProducts()
        this.renderProducts()
        this.updateCounts()
        // 검색그룹 목록 카운트 갱신
        await this.renderSearchFilterTable()
    }

    /**
     * 가격/재고 이력 모달 표시
     */
    async showPriceHistory(productId) {
        const product = productManager.products.find(p => p.id === productId)
        if (!product) return

        // 기존 모달 제거
        document.getElementById('price-history-modal')?.remove()

        const siteName = product.sourceSite || 'MUSINSA'
        const currentPrice = product.cost || product.sourcePrice || 0
        const histories = product.priceHistory || []

        // 이력이 없으면 안내 메시지
        if (histories.length === 0) {
            const modal = document.createElement('div')
            modal.id = 'price-history-modal'
            modal.style.cssText = 'position:fixed; inset:0; z-index:1000; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,0.7);'
            modal.innerHTML = `
                <div style="background:#141414; border:1px solid #2D2D2D; border-radius:10px; width:400px; padding:32px; text-align:center;">
                    <div style="font-size:0.95rem; font-weight:700; color:#E5E5E5; margin-bottom:12px;">가격 / 재고 이력</div>
                    <div style="color:#888; font-size:0.85rem; margin-bottom:20px;">수집된 이력 데이터가 없습니다.</div>
                    <button onclick="document.getElementById('price-history-modal').remove()" style="padding:6px 20px; background:#FF8C00; border:none; color:#fff; border-radius:6px; cursor:pointer; font-size:0.8rem;">닫기</button>
                </div>`
            modal.addEventListener('click', e => { if (e.target === modal) modal.remove() })
            document.body.appendChild(modal)
            return
        }

        // 날짜 포맷 헬퍼 (24시간제)
        const fmtDate = (isoStr) => {
            const d = new Date(isoStr)
            return `${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,'0')}.${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`
        }

        // 재고 표시 헬퍼: 숫자면 수량, null이면 O/X
        const fmtStock = (stock, isSoldOut, opt = {}) => {
            if (opt.isBrandDelivery) return '<span style="color:#6B8AFF; font-weight:700;">브랜드</span>'
            if (stock === null || stock === undefined || stock === -1) {
                if (isSoldOut) return '<span style="color:#FF6B6B; font-weight:700;">품절</span>'
                return '<span style="color:#51CF66; font-weight:700;">O</span>'
            }
            if (typeof stock === 'number') {
                if (stock <= 0) return '<span style="color:#FF6B6B; font-weight:700;">품절</span>'
                if (stock >= 999) return '<span style="color:#51CF66; font-weight:700;">충분</span>'
                return `<span style="color:#51CF66; font-weight:700;">${stock}개</span>`
            }
            // 수량 알 수 없음 → O/X 표기
            if (isSoldOut) return '<span style="color:#FF6B6B; font-weight:700;">X</span>'
            return '<span style="color:#51CF66; font-weight:700;">O</span>'
        }

        // 가격 통계
        const allPrices = histories.map(h => h.price).filter(p => p > 0)
        const minPrice = allPrices.length > 0 ? Math.min(...allPrices) : currentPrice
        const maxPrice = allPrices.length > 0 ? Math.max(...allPrices) : currentPrice
        const minEntry = histories.find(h => h.price === minPrice)
        const maxEntry = histories.find(h => h.price === maxPrice)
        const minDate = minEntry ? fmtDate(minEntry.date) : '-'
        const maxDate = maxEntry ? fmtDate(maxEntry.date) : '-'

        // 이력 테이블 행 생성 (최신순 정렬)
        const sorted = [...histories].sort((a, b) => new Date(b.date) - new Date(a.date))
        const rowsHtml = sorted.map(h => {
            const dateStr = fmtDate(h.date)
            const opts = h.options || []
            const optRows = opts.map(opt => `
                <tr style="border-bottom:1px solid #1E1E1E;">
                    <td style="padding:4px 12px; color:#666; font-size:0.75rem;">└ ${opt.name}</td>
                    <td style="padding:4px 12px; text-align:right; color:#C5C5C5; font-size:0.75rem;">₩ ${this.formatNumber(opt.price || h.price)}</td>
                    <td style="padding:4px 12px; text-align:center; font-size:0.75rem;">${fmtStock(opt.stock, opt.isSoldOut, opt)}</td>
                </tr>`).join('')

            // 옵션 없는 경우 상품 전체 행만 표시
            if (opts.length === 0) {
                return `
                <tr style="border-bottom:1px solid #2A2A2A; background:#1A1A1A;">
                    <td style="padding:6px 12px; color:#C5C5C5; font-size:0.8rem; font-weight:600;">${dateStr}</td>
                    <td style="padding:6px 12px; text-align:right; color:#E5E5E5; font-size:0.8rem;">₩ ${this.formatNumber(h.price)}</td>
                    <td style="padding:6px 12px; text-align:center; font-size:0.8rem; color:#51CF66; font-weight:700;">O</td>
                </tr>`
            }

            return `
                <tr style="border-bottom:1px solid #2A2A2A; background:#1A1A1A;">
                    <td style="padding:6px 12px; color:#C5C5C5; font-size:0.8rem; font-weight:600;">${dateStr}</td>
                    <td style="padding:6px 12px; text-align:right; color:#E5E5E5; font-size:0.8rem;">₩ ${this.formatNumber(h.price)}</td>
                    <td style="padding:6px 12px; text-align:center; color:#666; font-size:0.8rem;">${opts.length}개 옵션</td>
                </tr>
                ${optRows}`
        }).join('')

        // 재고 열 헤더: 수량 파악 가능 여부에 따라 표시 변경
        const hasNumericStock = histories.some(h => (h.options || []).some(o => typeof o.stock === 'number' && o.stock >= 0))
        const stockHeader = hasNumericStock ? '재고(수량/O/X)' : '재고(O/X)'

        const modal = document.createElement('div')
        modal.id = 'price-history-modal'
        modal.style.cssText = 'position:fixed; inset:0; z-index:1000; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,0.7);'
        modal.innerHTML = `
            <div style="background:#141414; border:1px solid #2D2D2D; border-radius:10px; width:520px; max-height:80vh; display:flex; flex-direction:column; overflow:hidden;">
                <div style="display:flex; align-items:center; justify-content:space-between; padding:14px 18px; border-bottom:1px solid #2D2D2D;">
                    <span style="font-size:0.95rem; font-weight:700; color:#E5E5E5;">가격 / 재고 이력</span>
                    <div style="display:flex; gap:6px;">
                        <span style="font-size:0.72rem; padding:3px 10px; background:#1E1E1E; border:1px solid #3D3D3D; color:#888; border-radius:4px;">${histories.length}건 기록</span>
                        <button onclick="document.getElementById('price-history-modal').remove()" style="background:transparent; border:none; color:#666; font-size:1.2rem; cursor:pointer; line-height:1;">✕</button>
                    </div>
                </div>
                <div style="overflow-y:auto; flex:1;">
                    <div style="padding:14px 18px; border-bottom:1px solid #222;">
                        <div style="font-size:0.72rem; color:#666; margin-bottom:4px;">[${siteName}]</div>
                        <div style="font-size:0.88rem; font-weight:700; color:#E5E5E5;">${product.name}</div>
                    </div>
                    <div style="padding:12px 18px; border-bottom:1px solid #222; display:flex; flex-direction:column; gap:6px;">
                        <div style="display:flex; gap:16px; font-size:0.8rem;">
                            <span style="color:#888; min-width:60px;">현재가</span>
                            <span style="color:#E5E5E5; font-weight:600;">₩ ${this.formatNumber(currentPrice)}</span>
                        </div>
                        <div style="display:flex; gap:16px; font-size:0.8rem;">
                            <span style="color:#888; min-width:60px;">최저가</span>
                            <span style="color:#5B8EE8; font-weight:600;">₩ ${this.formatNumber(minPrice)} <span style="font-size:0.72rem; color:#5B8EE8;">(${minDate})</span></span>
                        </div>
                        <div style="display:flex; gap:16px; font-size:0.8rem;">
                            <span style="color:#888; min-width:60px;">최고가</span>
                            <span style="color:#E06B6B; font-weight:600;">₩ ${this.formatNumber(maxPrice)} <span style="font-size:0.72rem; color:#E06B6B;">(${maxDate})</span></span>
                        </div>
                    </div>
                    <table style="width:100%; border-collapse:collapse;">
                        <thead>
                            <tr style="background:#1A1A1A; border-bottom:1px solid #2D2D2D;">
                                <th style="padding:6px 12px; text-align:left; font-size:0.75rem; color:#666; font-weight:500;">날짜</th>
                                <th style="padding:6px 12px; text-align:right; font-size:0.75rem; color:#666; font-weight:500;">가격(₩)</th>
                                <th style="padding:6px 12px; text-align:center; font-size:0.75rem; color:#666; font-weight:500;">${stockHeader}</th>
                            </tr>
                        </thead>
                        <tbody>${rowsHtml}</tbody>
                    </table>
                </div>
            </div>`
        modal.addEventListener('click', e => { if (e.target === modal) modal.remove() })
        document.body.appendChild(modal)
    }

    /**
     * 상품전송 탭으로 이동 (마켓삭제 버튼)
     */
    goToShipmentWithProduct(productId) {
        app.navigateTo('shipment')
        // 잠시 후 해당 상품 행 하이라이트
        setTimeout(() => {
            const cb = document.querySelector(`.shipment-product-cb[value="${productId}"]`)
            if (cb) {
                cb.checked = true
                cb.closest('tr')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                cb.closest('tr').style.background = 'rgba(255,107,107,0.08)'
            }
        }, 200)
    }

    /**
     * === 판매처 관리 ===
     */

    showChannelModal(channelId = null) {
        const modal = document.getElementById('channel-modal')
        const form = document.getElementById('channel-form')

        form.reset()
        this.currentChannelEditId = null

        if (channelId) {
            const channel = channelManager.channels.find(c => c.id === channelId)
            if (channel) {
                form.name.value = channel.name
                form.type.value = channel.type
                form.platform.value = channel.platform
                form.feeRate.value = channel.feeRate
                this.currentChannelEditId = channelId
            }
        }

        modal.classList.remove('hidden')
    }

    closeChannelModal() {
        document.getElementById('channel-modal').classList.add('hidden')
        this.currentChannelEditId = null
    }

    async handleChannelSubmit(e) {
        e.preventDefault()
        const form = e.target
        const data = new FormData(form)

        const channelData = {
            name: data.get('name'),
            type: data.get('type'),
            platform: data.get('platform'),
            feeRate: data.get('feeRate')
        }

        if (this.currentChannelEditId) {
            await channelManager.updateChannel(this.currentChannelEditId, channelData)
        } else {
            await channelManager.addChannel(channelData)
        }

        this.closeChannelModal()
        this.renderChannels()
        this.updateCounts()
        this.updateChannelSelects()
    }

    async renderChannels() {
        const grid = document.getElementById('channels-grid')

        if (channelManager.channels.length === 0) {
            grid.innerHTML = '<div class="col-span-3 bg-white rounded-lg shadow p-6 text-center text-gray-500">판매처를 추가해주세요</div>'
            return
        }

        grid.innerHTML = channelManager.channels.map(channel => {
            const typeLabel = channelManager.getChannelTypeLabel(channel.type)
            return `
                <div class="bg-white rounded-lg shadow p-6 border-l-4 border-blue-500">
                    <div class="flex justify-between items-start mb-4">
                        <div>
                            <h4 class="font-bold text-gray-900">${channel.name}</h4>
                            <p class="text-xs text-gray-500">${typeLabel}</p>
                        </div>
                        <div class="flex gap-2">
                            <button onclick="ui.showChannelModal('${channel.id}')" class="text-blue-600 hover:text-blue-800">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button onclick="ui.deleteChannel('${channel.id}')" class="text-red-600 hover:text-red-800">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                    <div class="space-y-2 text-sm">
                        <p><span class="text-gray-600">수수료:</span> <span class="font-bold">${channel.feeRate}%</span></p>
                        <p><span class="text-gray-600">등록상품:</span> <span class="font-bold">${channel.products.length}개</span></p>
                        <p><span class="text-gray-600">상태:</span> <span class="font-bold text-green-600">${channel.status === 'active' ? '활성' : '비활성'}</span></p>
                    </div>
                </div>
            `
        }).join('')
    }

    async deleteChannel(channelId) {
        if (await this.showConfirm('정말 삭제하시겠습니까?', { title: '판매처 삭제', danger: true })) {
            await channelManager.deleteChannel(channelId)
            this.renderChannels()
            this.updateCounts()
            this.updateChannelSelects()
        }
    }

    /**
     * === 주문/CS 관리 ===
     */

    showOrderModal(orderId = null) {
        const modal = document.getElementById('order-modal')
        const form = document.getElementById('order-form')

        form.reset()
        this.updateChannelSelects()
        this.updateProductSelects()

        if (orderId) {
            const order = orderManager.orders.find(o => o.id === orderId)
            if (order) {
                form.channelId.value = order.channelId
                form.productId.value = order.productId
                form.customerName.value = order.customerName
                form.customerPhone.value = order.customerPhone
                form.customerAddress.value = order.customerAddress
                form.quantity.value = order.quantity
                form.salePrice.value = order.salePrice
                form.cost.value = order.cost
                form.feeRate.value = order.feeRate
                form.shippingCompany.value = order.shippingCompany
                form.notes.value = order.notes
            }
        }

        modal.classList.remove('hidden')
    }

    closeOrderModal() {
        document.getElementById('order-modal').classList.add('hidden')
    }

    updateChannelSelects() {
        const select = document.getElementById('order-channel-select')
        if (!select) return

        select.innerHTML = '<option value="">선택하세요</option>' +
            channelManager.channels.map(c => `<option value="${c.id}">${c.name}</option>`).join('')
    }

    updateProductSelects() {
        const select = document.getElementById('order-product-select')
        if (!select) return

        select.innerHTML = '<option value="">선택하세요</option>' +
            productManager.products.map(p => `<option value="${p.id}">${p.name}</option>`).join('')
    }

    async handleOrderSubmit(e) {
        e.preventDefault()
        const form = e.target
        const data = new FormData(form)

        const orderData = {
            channelId: data.get('channelId'),
            productId: data.get('productId'),
            customerName: data.get('customerName'),
            customerPhone: data.get('customerPhone'),
            customerAddress: data.get('customerAddress'),
            quantity: data.get('quantity'),
            salePrice: data.get('salePrice'),
            cost: data.get('cost'),
            feeRate: data.get('feeRate'),
            shippingCompany: data.get('shippingCompany'),
            notes: data.get('notes')
        }

        await orderManager.addOrder(orderData)
        this.closeOrderModal()
        this.renderOrders()
        this.updateCounts()
    }

    /**
     * 날짜 인풋을 yyyy-mm-dd 형식으로 세팅
     */
    _fmtDate(d) {
        // toISOString()은 UTC 기준이라 한국(+9)에서 날짜가 밀릴 수 있음 → 로컬 날짜 사용
        const y = d.getFullYear()
        const m = String(d.getMonth() + 1).padStart(2, '0')
        const day = String(d.getDate()).padStart(2, '0')
        return `${y}-${m}-${day}`
    }

    initOrderDateRange() {
        const today = new Date()
        const jan1  = new Date(today.getFullYear(), 0, 1)
        const s = document.getElementById('order-date-start')
        const e = document.getElementById('order-date-end')
        if (s) s.value = this._fmtDate(jan1)
        if (e) e.value = this._fmtDate(today)
        // 올해 버튼 활성화 표시
        const thisYearBtn = document.querySelector('.order-period-btn[data-period="thisyear"]')
        if (thisYearBtn) {
            thisYearBtn.style.background = 'linear-gradient(135deg,#FF8C00,#FFB84D)'
            thisYearBtn.style.border = 'none'
            thisYearBtn.style.color = '#fff'
        }
    }

    setOrderDateRange(period) {
        const today = new Date()
        const s = document.getElementById('order-date-start')
        const e = document.getElementById('order-date-end')
        if (!s || !e) return
        e.value = this._fmtDate(today)

        // 시작일 고정 중이면 시작일은 변경하지 않음
        if (this.orderDateStartLocked) return

        const ago = (days) => { const d = new Date(today); d.setDate(d.getDate() - days); return d }
        const map = {
            'today':    () => { s.value = this._fmtDate(today) },
            '1week':    () => { s.value = this._fmtDate(ago(7)) },
            '15days':   () => { s.value = this._fmtDate(ago(15)) },
            '1month':   () => { s.value = this._fmtDate(ago(30)) },
            '3months':  () => { s.value = this._fmtDate(ago(90)) },
            '6months':  () => { s.value = this._fmtDate(ago(180)) },
            'thisyear': () => { s.value = this._fmtDate(new Date(today.getFullYear(), 0, 1)) },
            'all':      () => { s.value = '2020-01-01' },
        }
        map[period]?.()
    }

    toggleOrderDateLock() {
        this.orderDateStartLocked = !this.orderDateStartLocked
        const btn = document.getElementById('order-date-lock')
        if (!btn) return
        if (this.orderDateStartLocked) {
            btn.style.background = 'linear-gradient(135deg,#FF8C00,#FFB84D)'
            btn.style.border = 'none'
            btn.style.color = '#fff'
            btn.innerHTML = '&#128204; 시작일 고정'
        } else {
            btn.style.background = 'rgba(50,50,50,0.8)'
            btn.style.border = '1px solid #3D3D3D'
            btn.style.color = '#C5C5C5'
            btn.innerHTML = '시작일 고정'
        }
    }

    async renderOrders() {
        const tbody = document.getElementById('orders-tbody')
        let orders = orderManager.orders

        // 상태 필터
        if (this.currentOrderFilter !== 'all') {
            orders = orders.filter(o => o.status === this.currentOrderFilter)
        }

        if (orders.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="padding:2rem; text-align:center; color:#666;">주문이 없습니다</td></tr>'
            return
        }

        // 주문상태 드롭다운 색상 매핑
        const statusColor = {
            'confirmed':    '#7950F2',
            'waiting':      '#E67700',
            'arrived':      '#1971C2',
            'shipping':     '#0C8599',
            'cancel_req':   '#C92A2A',
            'exchange_req': '#862E9C',
            'return_req':   '#D6336C',
            'done':         '#495057',
            'delivered':    '#2F9E44'
        }

        // 주문상태 옵션 목록
        const statusOptions = [
            { value: 'confirmed',    label: '주문확인' },
            { value: 'waiting',      label: '배송대기' },
            { value: 'arrived',      label: '사무실도착' },
            { value: 'shipping',     label: '국내배송' },
            { value: 'cancel_req',   label: '취소요청' },
            { value: 'exchange_req', label: '교환요청' },
            { value: 'return_req',   label: '반품요청' },
            { value: 'done',         label: '취소/반품/교환/완료' },
            { value: 'delivered',    label: '배송완료' }
        ]

        // 공통 스타일 상수 (가시성 개선 - 밝은 텍스트, 차분한 컬러)
        const S = {
            row:      'border-bottom:1px solid #252B3B; vertical-align:top;',
            cell:     'padding:0.65rem 0.75rem; border-right:1px solid #252B3B;',
            cellLast: 'padding:0.65rem 0.75rem;',
            input:    'width:100%; padding:3px 6px; font-size:0.72rem; background:#161B27; border:1px solid #2D3550; color:#D8DEE9; border-radius:4px; outline:none;',
            select:   'width:100%; padding:3px 6px; font-size:0.72rem; background:#161B27; border:1px solid #2D3550; color:#D8DEE9; border-radius:4px; outline:none; cursor:pointer;',
            tag:      'padding:1px 6px; font-size:0.69rem; border-radius:3px; white-space:nowrap; cursor:pointer;',
        }

        tbody.innerHTML = orders.map((order) => {
            const channel = channelManager.channels.find(c => c.id === order.channelId)
            const channelName = channel ? channel.name : '마켓'
            const orderDate = order.createdAt ? new Date(order.createdAt) : null
            const dateStr   = orderDate ? orderDate.toLocaleDateString('ko-KR') : '-'
            const timeStr   = orderDate ? orderDate.toLocaleTimeString('ko-KR', { hour:'2-digit', minute:'2-digit', hour12: false }) : ''
            const salePrice       = order.salePrice || 0
            const feeRate         = channel ? (channel.feeRate || 0) : 0
            const settlementPrice = Math.round(salePrice * (1 - feeRate / 100))
            const costPrice       = order.costPrice || order.cost || 0       // 등록 당시 원가
            const actualCost      = order.actualCost || 0                    // 실제 구매 금액
            const realProfit      = settlementPrice - costPrice              // 실수익 (등록 원가 기준)
            const realProfitRate  = salePrice > 0 ? Math.round(realProfit / salePrice * 100) : 0
            const origProfit      = actualCost > 0 ? settlementPrice - actualCost : null  // 원수익 (실구매가 기준)
            const origProfitRate  = (origProfit !== null && salePrice > 0) ? Math.round(origProfit / salePrice * 100) : null
            const profitColor     = realProfit >= 0 ? '#6EE7A0' : '#FC8181'
            const origColor       = origProfit === null ? '#555' : (origProfit >= 0 ? '#6EE7A0' : '#FC8181')
            const bgColor         = statusColor[order.status] || '#374151'
            const productName     = order.productName || '-'
            const imgSrc          = order.imageUrl || ''

            const statusOptsHtml = statusOptions.map(s =>
                `<option value="${s.value}" ${order.status === s.value ? 'selected' : ''}>${s.label}</option>`
            ).join('')

            const mgmtBtns = ['상품정보','가격변경이력','원문링크','판매마켓링크','미등록 입력','배송조회','업데이트','마켓상품삭제','원주문취소']

            // 상품 썸네일 (이미지 없으면 회색 placeholder)
            const thumbHtml = imgSrc
                ? `<img src="${imgSrc}" style="width:146px; height:166px; object-fit:cover; border-radius:4px; border:1px solid #252B3B; flex-shrink:0;">`
                : `<div style="width:146px; height:166px; background:#1A1F2E; border:1px solid #252B3B; border-radius:4px; flex-shrink:0; display:flex; align-items:center; justify-content:center;">
                     <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#3D4A6A" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>
                   </div>`

            return `
            <tr style="${S.row}">
                <!-- 체크박스 -->
                <td style="padding:0.65rem 0.5rem; text-align:center; border-right:1px solid #252B3B;">
                    <input type="checkbox" style="accent-color:#FF8C00; width:13px; height:13px;">
                </td>

                <!-- 주문번호 컬럼 (썸네일 + 정보) -->
                <td style="${S.cell}">
                    <div style="display:flex; gap:10px; align-items:flex-start;">
                        <!-- 썸네일 + 주문일시 + 삭제 -->
                        <div style="display:flex; flex-direction:column; align-items:center; gap:5px; flex-shrink:0;">
                            ${thumbHtml}
                            <div style="font-size:0.68rem; color:#7B8DB0; text-align:center; line-height:1.5; white-space:nowrap;">
                                <div>${dateStr}</div>
                                <div>${timeStr}</div>
                            </div>
                            <button onclick="ui.deleteOrder('${order.id}')" style="width:100%; padding:4px 0; font-size:0.7rem; font-weight:600; background:#1A1015; border:1px solid #6B2A20; color:#FF6B6B; border-radius:4px; cursor:pointer;">주문삭제</button>
                        </div>
                        <!-- 주문 정보 -->
                        <div style="flex:1; min-width:0;">
                            <!-- 채널 + 주문번호 + 수량 배지 -->
                            <div style="display:flex; align-items:center; gap:5px; flex-wrap:wrap; margin-bottom:4px;">
                                <span style="padding:1px 6px; font-size:0.68rem; background:#1C2035; color:#7BA7D4; border:1px solid #2D3A55; border-radius:3px;">${channelName}</span>
                                <span style="font-size:0.8rem; color:#EEF2FF; font-weight:600;">${order.orderNumber || '-'}</span>
                                <button style="${S.tag} background:transparent; border:1px solid #2D3550; color:#7B8DB0;">주문번호복사</button>
                                ${(() => {
                                    const sent = this.smsSentOrders.has(order.id)
                                    return `<button id="sms-btn-${order.id}" onclick="ui.showSmsModal('${order.id}')" style="${S.tag} cursor:pointer; ${sent
                                        ? 'background:#0D1E14; border:1px solid #1B5C38; color:#4CAF8A;'
                                        : 'background:#221E0E; border:1px solid #78450A; color:#D4A017;'}">${sent ? '메시지 발송후' : '메시지 발송전'}</button>`
                                })()}
                                ${(() => { const qty = order.quantity || 1; return qty >= 2
                                    ? `<span style="margin-left:auto; background:linear-gradient(135deg,#FF8C00,#FFB84D); color:#fff; font-size:0.75rem; font-weight:700; padding:2px 10px; border-radius:10px; box-shadow:0 0 8px rgba(255,140,0,0.5);">×${qty}</span>`
                                    : `<span style="margin-left:auto; background:#1C2035; color:#7B8DB0; font-size:0.72rem; padding:1px 8px; border-radius:10px; border:1px solid #2D3550;">×${qty}</span>`
                                })()}
                            </div>
                            <!-- 상품명 -->
                            <div style="font-size:0.795rem; color:#D1D9EE; margin-bottom:3px; line-height:1.45; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:500px;">
                                ${productName}
                            </div>
                            <!-- 옵션 + 타사주문링크 -->
                            <div style="display:flex; align-items:center; gap:5px; margin-bottom:7px;">
                                <span style="font-size:0.71rem; color:#8A95B0;">주문옵션(${order.options || 'NONE:NONE'})</span>
                                <button style="${S.tag} background:#152035; border:1px solid #1E3A60; color:#7BAAD4;">옵션매칭</button>
                                <input type="text" placeholder="타사주문링크" style="flex:1; padding:2px 6px; font-size:0.71rem; background:#161B27; border:1px solid #2D3550; color:#D8DEE9; border-radius:4px; outline:none;">
                            </div>
                            <!-- 버튼 그룹 -->
                            <div style="display:flex; align-items:center; gap:4px; flex-wrap:wrap;">
                                <a href="https://search.danawa.com/dsearch.php?query=${encodeURIComponent(productName)}" target="_blank"
                                    style="padding:1.8px 7.5px; font-size:0.77rem; border-radius:3px; white-space:nowrap; cursor:pointer; background:#12233D; border:1px solid #1E3A60; color:#7BAAD4; text-decoration:none;">다나와</a>
                                <a href="https://search.shopping.naver.com/search/all?query=${encodeURIComponent(productName)}&vertical=search" target="_blank"
                                    style="padding:1.8px 7.5px; font-size:0.77rem; border-radius:3px; white-space:nowrap; cursor:pointer; background:#122B1A; border:1px solid #1A4A28; color:#6DBF8A; text-decoration:none;">네이버</a>
                                <span style="width:1px; height:14px; background:#2D3550; margin:0 2px;"></span>
                                ${mgmtBtns.map(b => `<button style="padding:1.8px 7.5px; font-size:0.77rem; border-radius:3px; white-space:nowrap; cursor:pointer; background:transparent; border:1px solid #252B3B; color:#8B9FC8;">${b}</button>`).join('')}
                            </div>
                            <!-- 주문자/수령자/배송정보 (마켓 수신 데이터) -->
                            <div style="margin-top:4px; display:flex; flex-direction:column; gap:3px;">
                                <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:3px;">
                                    <input type="text" placeholder="주문자" value="${order.ordererName || order.customerName || ''}" readonly style="${S.input} background:#0F1320; color:#9AA5C0; cursor:default;">
                                    <input type="text" placeholder="수령자" value="${order.recipientName || order.customerName || ''}" readonly style="${S.input} background:#0F1320; color:#9AA5C0; cursor:default;">
                                    <input type="text" placeholder="전화번호" value="${order.recipientPhone || order.customerPhone || ''}" readonly style="${S.input} background:#0F1320; color:#9AA5C0; cursor:default;">
                                </div>
                                <div style="display:grid; grid-template-columns:2fr 2fr 1fr; gap:3px;">
                                    <input type="text" placeholder="주소" value="${order.address || order.customerAddress || ''}" readonly style="${S.input} background:#0F1320; color:#9AA5C0; cursor:default;">
                                    <input type="text" placeholder="상세주소" value="${order.addressDetail || ''}" readonly style="${S.input} background:#0F1320; color:#9AA5C0; cursor:default;">
                                    <input type="text" placeholder="우편번호" value="${order.zipCode || ''}" readonly style="${S.input} background:#0F1320; color:#9AA5C0; cursor:default;">
                                </div>
                                <input type="text" placeholder="배송메모" value="${order.deliveryMemo || ''}" readonly style="${S.input} background:#0F1320; color:#9AA5C0; cursor:default;">
                            </div>
                        </div>
                    </div>
                </td>

                <!-- 결제금액 -->
                <td style="${S.cell} text-align:right;">
                    <div style="display:flex; flex-direction:column; gap:3px; font-size:0.72rem; line-height:1.55;">
                        <div style="display:flex; justify-content:space-between; gap:8px;">
                            <span style="color:#7B8DB0;">결제</span>
                            <span style="color:#EEF2FF; font-weight:700;">${this.formatNumber(salePrice)}</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; gap:8px;">
                            <span style="color:#7B8DB0;">정산</span>
                            <span style="color:#B0BAD0;">${this.formatNumber(settlementPrice)}</span>
                        </div>
                        <div style="height:1px; background:#252B3B; margin:2px 0;"></div>
                        <div style="display:flex; justify-content:space-between; gap:8px;">
                            <span style="color:#7B8DB0;" title="등록 당시 상품 원가 기준">실수익</span>
                            <span style="color:${profitColor}; font-weight:600;">${realProfit >= 0 ? '+' : ''}${this.formatNumber(realProfit)}</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; gap:8px;">
                            <span style="color:#7B8DB0;" title="등록 당시 상품 원가 기준">실수익률</span>
                            <span style="color:${profitColor}; font-weight:600;">${realProfitRate}%</span>
                        </div>
                        <div style="height:1px; background:#252B3B; margin:2px 0;"></div>
                        <div style="display:flex; justify-content:space-between; gap:8px;">
                            <span style="color:#555;" title="실제 구매한 금액 기준">원수익</span>
                            <span style="color:${origColor}; font-weight:600;">${origProfit === null ? '-' : (origProfit >= 0 ? '+' : '') + this.formatNumber(origProfit)}</span>
                        </div>
                        <div style="display:flex; justify-content:space-between; gap:8px;">
                            <span style="color:#555;" title="실제 구매한 금액 기준">원수익률</span>
                            <span style="color:${origColor}; font-weight:600;">${origProfitRate === null ? '-' : origProfitRate + '%'}</span>
                        </div>
                    </div>
                </td>

                <!-- 상품주문정보 -->
                <td style="${S.cellLast}">
                    <div style="display:flex; gap:8px;">
                        <!-- 왼쪽 -->
                        <div style="display:flex; flex-direction:column; gap:4px; flex:1; min-width:0;">
                            <select style="${S.select}">
                                <option value="">주문계정 선택</option>
                                <option>쿠팡-A사업자</option><option>쿠팡-B사업자</option>
                                <option>스마트스토어-A</option><option>스마트스토어-B</option>
                                <option>11번가-A</option><option>G마켓-A</option>
                            </select>
                            <input type="text" placeholder="마켓주문번호" value="${order.orderNumber || ''}" style="${S.input}">
                            <input type="text" placeholder="원가(실제구매가)" value="${order.actualCost || ''}"
                                onchange="orderManager.updateOrder('${order.id}',{actualCost:parseFloat(this.value)||0}).then(()=>ui.renderOrders())"
                                style="${S.input}">
                            <select style="${S.select}">
                                <option>택배사 선택</option>
                                <option>CJ대한통운</option><option>우체국</option><option>한진택배</option><option>로젠택배</option><option>롯데택배</option>
                            </select>
                            <input type="text" placeholder="국내송장번호" style="${S.input}">
                            <input type="text" placeholder="배송비" style="${S.input}">
                            <!-- 직배/까대기/선물 -->
                            <div style="display:flex; gap:4px;">
                                <button style="flex:1; padding:3px 0; font-size:0.71rem; background:#12233D; border:1px solid #1E3A60; color:#7BAAD4; border-radius:4px; cursor:pointer;">직배</button>
                                <button style="flex:1; padding:3px 0; font-size:0.71rem; background:#2A1E0A; border:1px solid #78450A; color:#D4A017; border-radius:4px; cursor:pointer;">까대기</button>
                                <button style="flex:1; padding:3px 0; font-size:0.71rem; background:#122B1A; border:1px solid #1A4A28; color:#6DBF8A; border-radius:4px; cursor:pointer;">선물</button>
                            </div>
                        </div>
                        <!-- 오른쪽 -->
                        <div style="display:flex; flex-direction:column; gap:4px; flex:1; min-width:0;">
                            <select onchange="ui.updateOrderStatus('${order.id}', this.value)"
                                style="width:100%; padding:4px 6px; font-size:0.75rem; background:${bgColor}; border:none; color:#fff; border-radius:4px; cursor:pointer; font-weight:600; outline:none;">
                                ${statusOptsHtml}
                            </select>
                            <input type="text" placeholder="마켓상태" style="${S.input}">
                            <!-- 취소승인 버튼 (마켓상태 바로 아래) -->
                            <button onclick="ui.showReturnModal('${order.id}')" style="width:100%; padding:5px 0; font-size:0.75rem; font-weight:600; background:#2A1310; border:1px solid #6B2A20; color:#FF8C00; border-radius:4px; cursor:pointer;">취소승인</button>
                            <textarea placeholder="간단메모" rows="5"
                                style="width:100%; padding:5px 7px; font-size:0.71rem; background:#161B27; border:1px solid #2D3550; color:#D1D9EE; border-radius:4px; resize:none; outline:none;"></textarea>
                        </div>
                    </div>
                </td>
            </tr>
            `
        }).join('')
    }

    async updateOrderStatus(orderId, newStatus) {
        await orderManager.updateOrderStatus(orderId, newStatus)
        this.renderOrders()
        this.updateCounts()
    }

    async deleteOrder(orderId) {
        if (await this.showConfirm('정말 삭제하시겠습니까?', { title: '주문 삭제', danger: true })) {
            await orderManager.deleteOrder(orderId)
            this.renderOrders()
            this.updateCounts()
        }
    }

    /**
     * === 소싱 추적 ===
     */

    showSourcingModal() {
        const modal = document.getElementById('sourcing-modal')
        const form = document.getElementById('sourcing-form')
        form.reset()
        modal.classList.remove('hidden')
    }

    closeSourcingModal() {
        document.getElementById('sourcing-modal').classList.add('hidden')
    }

    async handleSourcingSubmit(e) {
        e.preventDefault()
        const form = e.target
        const data = new FormData(form)

        const siteData = {
            name: data.get('name'),
            url: data.get('url'),
            type: data.get('type')
        }

        await sourcingManager.addSourcingSite(siteData)
        this.closeSourcingModal()
        this.renderSourcing()
    }

    async renderSourcing() {
        const tbody = document.getElementById('sourcing-tbody')
        if (!tbody) return  // HTML에 해당 요소 없으면 스킵

        if (sourcingManager.sourcingSites.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="px-6 py-8 text-center text-gray-500">추적 중인 사이트가 없습니다</td></tr>'
        } else {
            tbody.innerHTML = sourcingManager.sourcingSites.map(site => `
                <tr class="hover:bg-gray-50">
                    <td class="px-6 py-4 font-medium text-gray-900">${site.name}</td>
                    <td class="px-6 py-4 text-sm">${sourcingManager.getSiteTypeLabel(site.type)}</td>
                    <td class="px-6 py-4">
                        <span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">활성</span>
                    </td>
                    <td class="px-6 py-4 text-sm text-gray-500">${site.lastChecked ? new Date(site.lastChecked).toLocaleDateString('ko-KR') : '아직 없음'}</td>
                    <td class="px-6 py-4 text-center">
                        <button onclick="ui.deleteSourcingSite('${site.id}')" class="text-red-600 hover:text-red-800 text-sm">삭제</button>
                    </td>
                </tr>
            `).join('')
        }

        // 모니터링 요약 업데이트
        const summary = sourcingManager.getPriceMonitoringSummary()
        document.getElementById('sourcing-tracked').textContent = summary.totalTracked
        document.getElementById('sourcing-today').textContent = summary.todayUpdates
        document.getElementById('sourcing-alerts').textContent = summary.priceAlerts
        document.getElementById('sourcing-low-stock').textContent = summary.lowStockCount
    }

    async deleteSourcingSite(siteId) {
        if (await this.showConfirm('정말 삭제하시겠습니까?', { title: '소싱사이트 삭제', danger: true })) {
            await sourcingManager.deleteSourcingSite(siteId)
            this.renderSourcing()
        }
    }

    /**
     * === 통계/분석 ===
     */

    async renderAnalytics() {
        // 월간 통계 (기존 analytics 페이지 요소용)
        const monthStart = new Date()
        monthStart.setDate(1)
        const monthStats = analyticsManager.getStatsByDateRange(monthStart, new Date())

        // HTML에 없는 요소는 optional chaining으로 안전하게 접근
        const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val }
        setEl('analytics-month-sales', '₩' + this.formatNumber(monthStats.totalSales))
        setEl('analytics-month-profit', '₩' + this.formatNumber(monthStats.totalProfit))
        setEl('analytics-month-orders', monthStats.totalOrders)
        setEl('analytics-profit-rate', monthStats.profitRate + '%')
        setEl('analytics-avg-order', '₩' + this.formatNumber(monthStats.avgOrderValue))
        setEl('analytics-total-orders', orderManager.orders.length)
        setEl('analytics-delivered', orderManager.orders.filter(o => o.status === 'delivered').length)

        // 판매처별 분석
        this.renderAnalyticsChannel()
        // 상품별 분석
        this.renderAnalyticsProduct()
        // 주문 상태 분석
        this.renderAnalyticsStatus()

        // 매출통계 페이지 KPI 카드 + 테이블 초기 갱신 (acSearch 함수 호출)
        if (typeof acSearch === 'function') acSearch()
    }

    renderAnalyticsChannel() {
        const tbody = document.getElementById('analytics-channel-tbody')
        if (!tbody) return
        const channels = analyticsManager.getSalesByChannel()

        if (channels.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="px-6 py-8 text-center text-gray-500">데이터가 없습니다</td></tr>'
            return
        }

        tbody.innerHTML = channels.map(ch => `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-4 font-medium text-gray-900">${ch.channelName}</td>
                <td class="px-6 py-4 text-right font-bold text-gray-900">₩${this.formatNumber(ch.sales)}</td>
                <td class="px-6 py-4 text-right font-bold text-green-600">₩${this.formatNumber(ch.profit)}</td>
                <td class="px-6 py-4 text-right text-gray-700">${ch.orders}개</td>
                <td class="px-6 py-4 text-right text-gray-700">₩${this.formatNumber(ch.avgPrice)}</td>
            </tr>
        `).join('')
    }

    renderAnalyticsProduct() {
        const tbody = document.getElementById('analytics-product-tbody')
        if (!tbody) return
        const products = analyticsManager.getSalesByProduct()

        if (products.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="px-6 py-8 text-center text-gray-500">데이터가 없습니다</td></tr>'
            return
        }

        tbody.innerHTML = products.map(p => `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-4 font-medium text-gray-900">${p.productName}</td>
                <td class="px-6 py-4 text-right font-bold text-gray-900">₩${this.formatNumber(p.sales)}</td>
                <td class="px-6 py-4 text-right text-gray-700">${p.units}개</td>
                <td class="px-6 py-4 text-right font-bold text-green-600">₩${this.formatNumber(p.profit)}</td>
                <td class="px-6 py-4 text-right text-gray-700">₩${this.formatNumber(p.avgPrice)}</td>
            </tr>
        `).join('')
    }

    renderAnalyticsStatus() {
        const status = analyticsManager.getOrderStatusStats()
        const profit = analyticsManager.getProfitAnalysis()
        const total = Object.values(status).reduce((a, b) => a + b, 0)
        const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val }

        // 상태 진행률 업데이트 (요소 존재 시에만)
        if (total > 0) {
            const pendingEl = document.querySelector('#status-pending')
            const shippedEl = document.querySelector('#status-shipped')
            const deliveredEl = document.querySelector('#status-delivered')
            if (pendingEl) pendingEl.parentElement.querySelector('div').style.width = (status.pending / total * 100) + '%'
            if (shippedEl) shippedEl.parentElement.querySelector('div').style.width = (status.shipped / total * 100) + '%'
            if (deliveredEl) deliveredEl.parentElement.querySelector('div').style.width = (status.delivered / total * 100) + '%'
        }

        setEl('status-pending', status.pending)
        setEl('status-shipped', status.shipped)
        setEl('status-delivered', status.delivered)

        if (profit) {
            setEl('profit-total', '₩' + this.formatNumber(profit.totalRevenue))
            setEl('profit-cost', '₩' + this.formatNumber(profit.totalCost))
            setEl('profit-net', '₩' + this.formatNumber(profit.totalProfit))
        }
    }

    /**
     * === 차트 시각화 ===
     */

    renderCharts() {
        if (!document.getElementById('daily-sales-chart')) return

        // 일별 매출 추이
        this.renderDailySalesChart()
        // 판매처별 매출 비율
        this.renderChannelSalesChart()
        // 상품별 판매량 TOP 5
        this.renderProductSalesChart()
        // 주문 상태 분포
        this.renderOrderStatusChart()

        // 차트 섹션 표시
        document.getElementById('analytics-charts').classList.remove('hidden')
    }

    renderDailySalesChart() {
        const ctx = document.getElementById('daily-sales-chart').getContext('2d')
        const trend = analyticsManager.getDailyTrend(30)

        const labels = trend.map(d => {
            const date = new Date(d.date)
            return date.toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' })
        })

        const data = {
            labels,
            datasets: [
                {
                    label: '매출',
                    data: trend.map(d => d.sales),
                    borderColor: '#FF8C00',
                    backgroundColor: 'rgba(255, 140, 0, 0.1)',
                    tension: 0.4,
                    fill: true
                },
                {
                    label: '순이익',
                    data: trend.map(d => d.profit),
                    borderColor: '#FFB84D',
                    backgroundColor: 'rgba(255, 184, 77, 0.1)',
                    tension: 0.4,
                    fill: true
                }
            ]
        }

        new Chart(ctx, {
            type: 'line',
            data,
            options: {
                responsive: true,
                plugins: { legend: { position: 'top' } },
                scales: { y: { beginAtZero: true, ticks: { callback: v => '₩' + (v / 1000000).toFixed(0) + 'M' } } }
            }
        })
    }

    renderChannelSalesChart() {
        const ctx = document.getElementById('channel-sales-chart').getContext('2d')
        const channels = analyticsManager.getSalesByChannel()

        const data = {
            labels: channels.map(c => c.channelName),
            datasets: [{
                data: channels.map(c => c.sales),
                backgroundColor: [
                    '#FF8C00', '#FFB84D', '#FFA500', '#FF6B00',
                    '#FF7700', '#FF9500', '#FF8500', '#FFAA55'
                ]
            }]
        }

        new Chart(ctx, {
            type: 'doughnut',
            data,
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'right' },
                    tooltip: { callbacks: { label: ctx => '₩' + this.formatNumber(ctx.parsed) } }
                }
            }
        })
    }

    renderProductSalesChart() {
        const ctx = document.getElementById('product-sales-chart').getContext('2d')
        const products = analyticsManager.getSalesByProduct().slice(0, 5)

        const data = {
            labels: products.map(p => p.productName),
            datasets: [{
                label: '판매량',
                data: products.map(p => p.units),
                backgroundColor: '#FF8C00'
            }]
        }

        new Chart(ctx, {
            type: 'bar',
            data,
            options: {
                indexAxis: 'y',
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { x: { beginAtZero: true } }
            }
        })
    }

    renderOrderStatusChart() {
        const ctx = document.getElementById('order-status-chart').getContext('2d')
        const status = analyticsManager.getOrderStatusStats()

        const data = {
            labels: ['대기중', '배송중', '배송완료', '취소됨'],
            datasets: [{
                data: [status.pending, status.shipped, status.delivered, status.cancelled],
                backgroundColor: ['#FFC107', '#2196F3', '#4CAF50', '#F44336']
            }]
        }

        new Chart(ctx, {
            type: 'pie',
            data,
            options: {
                responsive: true,
                plugins: { legend: { position: 'bottom' } }
            }
        })
    }

    /**
     * === 반품/교환/취소 ===
     */

    showCsTemplateModal() {
        const modal = document.getElementById('cs-template-modal')
        if (modal) modal.style.display = 'flex'
    }

    closeCsTemplateModal() {
        const modal = document.getElementById('cs-template-modal')
        if (modal) modal.style.display = 'none'
    }

    // 변수 클릭 시 textarea에 커서 위치에 삽입
    insertCsVar(variable) {
        const ta = document.getElementById('cs-template-content')
        if (!ta) return
        const start = ta.selectionStart
        const end = ta.selectionEnd
        ta.value = ta.value.substring(0, start) + variable + ta.value.substring(end)
        const pos = start + variable.length
        ta.setSelectionRange(pos, pos)
        ta.focus()
    }

    saveCsTemplate() {
        const name = document.getElementById('cs-template-name')?.value?.trim()
        const content = document.getElementById('cs-template-content')?.value?.trim()
        if (!name || !content) { app.showNotification('이름과 내용을 모두 입력해주세요', 'warning'); return }

        const list = document.getElementById('cs-template-list')
        const id = Date.now()
        const item = document.createElement('div')
        item.id = `cs-tpl-${id}`
        item.style.cssText = 'background:#1A1A1A; border:1px solid #2D2D2D; border-radius:8px; padding:0.75rem 1rem; display:flex; align-items:flex-start; justify-content:space-between; gap:8px;'
        item.innerHTML = `
            <div style="flex:1; min-width:0;">
                <div style="font-size:0.8rem; font-weight:600; color:#E5E5E5; margin-bottom:4px;">${name}</div>
                <div style="font-size:0.75rem; color:#888; white-space:pre-wrap; line-height:1.5;">${content}</div>
            </div>
            <div style="display:flex; gap:4px; flex-shrink:0;">
                <button style="font-size:0.72rem; padding:2px 8px; border:1px solid #3D3D3D; border-radius:4px; color:#C5C5C5; background:transparent; cursor:pointer;">수정</button>
                <button onclick="document.getElementById('cs-tpl-${id}').remove()" style="font-size:0.72rem; padding:2px 8px; border:1px solid rgba(255,107,107,0.3); border-radius:4px; color:#FF6B6B; background:transparent; cursor:pointer;">삭제</button>
            </div>`
        list.appendChild(item)

        document.getElementById('cs-template-name').value = ''
        document.getElementById('cs-template-content').value = ''
        app.showNotification('답변 양식이 저장되었습니다', 'success')
    }

    addCsTemplate() {
        document.getElementById('cs-template-name')?.focus()
    }

    showReturnModal(orderId) {
        const order = orderManager.orders.find(o => o.id === orderId)
        if (!order) return

        const modal = document.getElementById('return-modal')
        const form = document.getElementById('return-form')

        form.reset()
        document.getElementById('return-order-id').value = orderId
        document.getElementById('return-order-info').value = `${order.orderNumber} - ${order.customerName}`
        document.getElementById('return-reason-select').innerHTML = '<option value="">사유를 선택하세요</option>'

        modal.classList.remove('hidden')
    }

    closeReturnModal() {
        document.getElementById('return-modal').classList.add('hidden')
    }

    updateReturnReasons() {
        const type = document.querySelector('select[name="type"]').value
        const reasons = returnManager.getReturnReasons()[type] || []
        const select = document.getElementById('return-reason-select')

        select.innerHTML = '<option value="">사유를 선택하세요</option>' +
            reasons.map(r => `<option value="${r.value}">${r.label}</option>`).join('')
    }

    async handleReturnSubmit(e) {
        e.preventDefault()
        const form = e.target
        const data = new FormData(form)

        const returnData = {
            orderId: data.get('orderId'),
            type: data.get('type'),
            reason: data.get('reason'),
            description: data.get('description'),
            quantity: parseInt(data.get('quantity')),
            requestedAmount: parseFloat(data.get('requestedAmount'))
        }

        await returnManager.createReturn(returnData)
        this.closeReturnModal()
        this.renderReturns()
        this.updateCounts()
    }

    async renderReturns() {
        const tbody = document.getElementById('returns-tbody')
        const returns = returnManager.returns.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))

        if (returns.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="px-6 py-8 text-center text-gray-500">반품/교환/취소 요청이 없습니다</td></tr>'
        } else {
            tbody.innerHTML = returns.map(ret => {
                const order = orderManager.orders.find(o => o.id === ret.orderId)
                const statusColor = {
                    'requested': 'bg-yellow-100 text-yellow-800',
                    'approved': 'bg-blue-100 text-blue-800',
                    'completed': 'bg-green-100 text-green-800',
                    'rejected': 'bg-red-100 text-red-800',
                    'cancelled': 'bg-gray-100 text-gray-800'
                }[ret.status] || 'bg-gray-100 text-gray-800'

                return `
                    <tr class="hover:bg-gray-50">
                        <td class="px-6 py-4 font-mono text-sm font-medium text-gray-900">${order?.orderNumber || '-'}</td>
                        <td class="px-6 py-4">
                            <p class="font-medium text-gray-900">${order?.customerName || '-'}</p>
                        </td>
                        <td class="px-6 py-4 text-sm">
                            <span class="px-2 py-1 rounded-full text-xs font-medium ${ret.type === 'return' ? 'bg-orange-100 text-orange-800' : ret.type === 'exchange' ? 'bg-blue-100 text-blue-800' : 'bg-red-100 text-red-800'}">
                                ${returnManager.getTypeLabel(ret.type)}
                            </span>
                        </td>
                        <td class="px-6 py-4 text-sm text-gray-600">${ret.reason}</td>
                        <td class="px-6 py-4 text-right font-bold text-gray-900">₩${this.formatNumber(ret.requestedAmount)}</td>
                        <td class="px-6 py-4 text-center">
                            <span class="inline-block px-3 py-1 rounded-full text-xs font-medium ${statusColor}">
                                ${returnManager.getStatusLabel(ret.status)}
                            </span>
                        </td>
                        <td class="px-6 py-4 text-sm text-gray-500">${new Date(ret.createdAt).toLocaleDateString('ko-KR')}</td>
                        <td class="px-6 py-4 text-center space-x-2">
                            ${ret.status === 'requested' ? `
                                <button onclick="ui.approveReturn('${ret.id}')" class="text-green-600 hover:text-green-800 text-sm">승인</button>
                                <button onclick="ui.rejectReturn('${ret.id}')" class="text-red-600 hover:text-red-800 text-sm">거부</button>
                            ` : ret.status === 'approved' ? `
                                <button onclick="ui.completeReturn('${ret.id}')" class="text-blue-600 hover:text-blue-800 text-sm">완료</button>
                            ` : '-'}
                        </td>
                    </tr>
                `
            }).join('')
        }

        // 통계 업데이트
        const stats = returnManager.getReturnStats()
        document.getElementById('return-total').textContent = stats.total
        document.getElementById('return-requested').textContent = stats.requested
        document.getElementById('return-approved').textContent = stats.approved
        document.getElementById('return-completed').textContent = stats.completed
        const badge = document.getElementById('returns-badge')
        if (badge) badge.textContent = stats.requested
    }

    // ==================== CS 관리 ====================

    /**
     * CS 등록 모달 표시
     */
    showCSModal(orderId) {
        const order = orderManager.orders.find(o => o.id === orderId)

        // 기존 모달이 있으면 제거
        const existingModal = document.getElementById('cs-register-modal')
        if (existingModal) existingModal.remove()

        const typeOptions = [
            { value: 'inquiry', label: '문의' },
            { value: 'complaint', label: '불만' },
            { value: 'exchange', label: '교환' },
            { value: 'refund', label: '환불' }
        ]

        const modal = document.createElement('div')
        modal.id = 'cs-register-modal'
        modal.style.cssText = 'position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:9999; display:flex; align-items:center; justify-content:center;'
        modal.innerHTML = `
            <div style="background:#1A1A1A; border:1px solid #2D2D2D; border-radius:8px; padding:1.5rem; width:480px; max-width:95vw;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:1.25rem;">
                    <h3 style="color:#E5E5E5; font-size:1rem; font-weight:600;">CS 등록</h3>
                    <button onclick="document.getElementById('cs-register-modal').remove()" style="background:transparent; border:none; color:#888; font-size:1.2rem; cursor:pointer;">✕</button>
                </div>
                ${order ? `<div style="background:rgba(255,140,0,0.08); border:1px solid rgba(255,140,0,0.2); border-radius:5px; padding:0.75rem; margin-bottom:1rem; font-size:0.8rem; color:#FFB84D;">주문 ${order.orderNumber || ''} - ${order.customerName || ''}</div>` : ''}
                <div style="display:flex; flex-direction:column; gap:0.75rem;">
                    <div>
                        <label style="font-size:0.8rem; color:#888; display:block; margin-bottom:0.3rem;">문의 유형</label>
                        <select id="cs-modal-type" style="width:100%; padding:0.5rem; background:rgba(22,22,22,0.95); border:1px solid #353535; color:#C5C5C5; border-radius:5px; font-size:0.8125rem;">
                            ${typeOptions.map(t => `<option value="${t.value}">${t.label}</option>`).join('')}
                        </select>
                    </div>
                    <div>
                        <label style="font-size:0.8rem; color:#888; display:block; margin-bottom:0.3rem;">문의 내용</label>
                        <textarea id="cs-modal-content" rows="4" placeholder="고객 문의 내용을 입력하세요"
                            style="width:100%; padding:0.5rem; background:rgba(22,22,22,0.95); border:1px solid #353535; color:#C5C5C5; border-radius:5px; font-size:0.8125rem; resize:vertical; outline:none; box-sizing:border-box;"></textarea>
                    </div>
                </div>
                <div style="display:flex; justify-content:flex-end; gap:0.5rem; margin-top:1.25rem;">
                    <button onclick="document.getElementById('cs-register-modal').remove()" style="padding:0.5rem 1rem; background:transparent; border:1px solid #353535; color:#888; border-radius:5px; cursor:pointer; font-size:0.8125rem;">취소</button>
                    <button onclick="ui.submitCSModal('${orderId || ''}')" style="padding:0.5rem 1rem; background:#FF8C00; border:none; color:#fff; border-radius:5px; cursor:pointer; font-size:0.8125rem; font-weight:600;">등록</button>
                </div>
            </div>
        `
        document.body.appendChild(modal)
    }

    /**
     * CS 모달 제출 처리
     */
    async submitCSModal(orderId) {
        const type = document.getElementById('cs-modal-type')?.value || 'inquiry'
        const content = document.getElementById('cs-modal-content')?.value?.trim()

        if (!content) {
            app.showNotification('문의 내용을 입력해주세요', 'warning')
            return
        }

        const order = orderId ? orderManager.orders.find(o => o.id === orderId) : null
        const csData = {
            id: 'cs_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
            orderId: orderId || '',
            orderNumber: order?.orderNumber || '',
            customerName: order?.customerName || '',
            type,
            content,
            status: 'received',
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString()
        }

        try {
            await storage.save('csRequests', csData)
            document.getElementById('cs-register-modal')?.remove()
            app.showNotification('CS가 등록되었습니다', 'success')
            await this.renderCS()
        } catch (e) {
            app.showNotification('CS 등록에 실패했습니다', 'error')
        }
    }

    /**
     * CS 페이지 렌더링
     */
    async renderCS() {
        const tbody = document.getElementById('cs-tbody')
        if (!tbody) return

        let csItems = []
        try {
            csItems = await storage.getAll('csRequests')
            csItems.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))
        } catch (e) {}

        if (csItems.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" style="padding:2rem; text-align:center; color:#666;">CS 요청이 없습니다</td></tr>`
            return
        }

        const typeLabel = { inquiry: '문의', complaint: '불만', exchange: '교환', refund: '환불' }
        const statusLabel = { received: '접수', processing: '처리중', completed: '완료' }
        const statusColor = { received: '#FF8C00', processing: '#1971C2', completed: '#2F9E44' }

        tbody.innerHTML = csItems.map(cs => {
            const typeTxt = typeLabel[cs.type] || cs.type
            const statusTxt = statusLabel[cs.status] || cs.status
            const sColor = statusColor[cs.status] || '#666'
            const dateStr = cs.createdAt ? new Date(cs.createdAt).toLocaleDateString('ko-KR') : '-'

            return `
                <tr style="border-bottom:1px solid #1A1A1A; vertical-align:top;">
                    <td style="padding:0.65rem 0.75rem; font-size:0.8rem; color:#888; font-family:monospace;">${cs.id.slice(-8)}</td>
                    <td style="padding:0.65rem 0.75rem; font-size:0.8rem; color:#C5C5C5;">${cs.orderNumber || '-'}</td>
                    <td style="padding:0.65rem 0.75rem; font-size:0.8rem; color:#C5C5C5;">${cs.customerName || '-'}</td>
                    <td style="padding:0.65rem 0.75rem;">
                        <span style="padding:2px 8px; border-radius:4px; font-size:0.75rem; background:rgba(255,140,0,0.15); color:#FFB84D; border:1px solid rgba(255,140,0,0.3);">${typeTxt}</span>
                    </td>
                    <td style="padding:0.65rem 0.75rem; font-size:0.8rem; color:#C5C5C5; max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${cs.content}</td>
                    <td style="padding:0.65rem 0.75rem; text-align:center;">
                        <span style="padding:2px 8px; border-radius:4px; font-size:0.75rem; background:rgba(0,0,0,0.3); color:${sColor}; border:1px solid ${sColor}40;">${statusTxt}</span>
                    </td>
                    <td style="padding:0.65rem 0.75rem; font-size:0.75rem; color:#666;">${dateStr}</td>
                </tr>
            `
        }).join('')
    }

    async approveReturn(returnId) {
        await returnManager.approveReturn(returnId)
        this.renderReturns()
    }

    async rejectReturn(returnId) {
        const reason = await this.showPrompt('거부 사유를 입력해주세요:', { title: '반품 거부' })
        if (reason !== null) {
            await returnManager.rejectReturn(returnId, reason)
            this.renderReturns()
        }
    }

    async completeReturn(returnId) {
        await returnManager.completeReturn(returnId)
        this.renderReturns()
    }

    /**
     * === 고객 연락 ===
     */

    showContactModal() {
        const modal = document.getElementById('contact-modal')
        const form = document.getElementById('contact-form')
        form.reset()

        // 주문 목록 업데이트
        this.updateContactOrders()
        // 템플릿 업데이트
        this.updateContactTemplates()

        modal.classList.remove('hidden')
    }

    closeContactModal() {
        document.getElementById('contact-modal').classList.add('hidden')
    }

    updateContactOrders() {
        const select = document.getElementById('contact-order-select')
        if (!select) return

        select.innerHTML = '<option value="">선택하세요</option>' +
            orderManager.orders.map(o => {
                const channel = channelManager.channels.find(c => c.id === o.channelId)
                const product = productManager.products.find(p => p.id === o.productId)
                return `<option value="${o.id}">${o.orderNumber} - ${product?.name || '상품'} (${o.customerName})</option>`
            }).join('')

        // 주문 선택 시 고객 정보 자동 입력
        select.addEventListener('change', () => this.updateContactRecipient())
    }

    updateContactRecipient() {
        const orderId = document.querySelector('select[name="orderId"]').value
        const order = orderManager.orders.find(o => o.id === orderId)

        if (order) {
            document.getElementById('contact-recipient').value = `${order.customerName} (${order.customerPhone})`
        }
    }

    updateContactTemplates() {
        const type = document.querySelector('select[name="type"]').value
        const templates = contactManager.templates[type] || {}
        const select = document.getElementById('contact-template-select')

        select.innerHTML = '<option value="">템플릿을 선택하세요</option>' +
            Object.entries(templates).map(([key, template]) => {
                return `<option value="${key}">${template.name}</option>`
            }).join('')

        // 템플릿 선택 시 메시지 자동 입력
        select.addEventListener('change', () => {
            const selectedKey = select.value
            if (selectedKey && templates[selectedKey]) {
                document.querySelector('textarea[name="message"]').value = templates[selectedKey].message
            }
        })
    }

    async handleContactSubmit(e) {
        e.preventDefault()
        const form = e.target
        const data = new FormData(form)

        const orderId = data.get('orderId')
        const order = orderManager.orders.find(o => o.id === orderId)

        if (!order) {
            app.showNotification('주문을 선택해주세요', 'error')
            return
        }

        // 변수 대체
        let message = data.get('message')
        const product = productManager.products.find(p => p.id === order.productId)

        message = message
            .replace('{orderNumber}', order.orderNumber)
            .replace('{productName}', product?.name || '상품')
            .replace('{amount}', this.formatNumber(order.salePrice))
            .replace('{shippingCompany}', order.shippingCompany || '미정')
            .replace('{trackingNumber}', order.trackingNumber || '미정')

        const contactData = {
            orderId,
            type: data.get('type'),
            template: data.get('template'),
            message,
            recipient: order.customerPhone,
            customMessage: data.get('message')
        }

        await contactManager.sendContact(contactData)
        this.closeContactModal()
        this.renderContacts()
        this.updateCounts()
    }

    async renderContacts() {
        const tbody = document.getElementById('contacts-tbody')
        const logs = contactManager.contactLogs.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt))

        if (logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="px-6 py-8 text-center text-gray-500">발송된 연락이 없습니다</td></tr>'
        } else {
            tbody.innerHTML = logs.map(log => {
                const order = orderManager.orders.find(o => o.id === log.orderId)
                const statusColor = {
                    'sent': 'bg-green-100 text-green-800',
                    'pending': 'bg-yellow-100 text-yellow-800',
                    'failed': 'bg-red-100 text-red-800'
                }[log.status] || 'bg-gray-100 text-gray-800'

                return `
                    <tr class="hover:bg-gray-50">
                        <td class="px-6 py-4 font-mono text-sm font-medium text-gray-900">${order?.orderNumber || '-'}</td>
                        <td class="px-6 py-4">
                            <div>
                                <p class="font-medium text-gray-900">${order?.customerName || '-'}</p>
                                <p class="text-xs text-gray-500">${log.recipient}</p>
                            </div>
                        </td>
                        <td class="px-6 py-4 text-sm">${contactManager.getContactTypeLabel(log.type)}</td>
                        <td class="px-6 py-4 text-sm text-gray-600 max-w-sm truncate">${log.message}</td>
                        <td class="px-6 py-4 text-center">
                            <span class="inline-block px-3 py-1 rounded-full text-xs font-medium ${statusColor}">
                                ${contactManager.getStatusLabel(log.status)}
                            </span>
                        </td>
                        <td class="px-6 py-4 text-sm text-gray-500">${log.sentAt ? new Date(log.sentAt).toLocaleString('ko-KR', { hour12: false }) : '-'}</td>
                        <td class="px-6 py-4 text-center">
                            <button onclick="ui.deleteContact('${log.id}')" class="text-red-600 hover:text-red-800 text-sm">삭제</button>
                        </td>
                    </tr>
                `
            }).join('')
        }

        // 통계 업데이트
        const stats = contactManager.getContactStats()
        document.getElementById('contact-total').textContent = stats.total
        document.getElementById('contact-sent').textContent = stats.sent
        document.getElementById('contact-pending').textContent = stats.pending
        document.getElementById('contact-failed').textContent = stats.failed
        document.getElementById('contact-today').textContent = contactManager.getTodayContactCount()
    }

    async deleteContact(contactId) {
        if (await this.showConfirm('정말 삭제하시겠습니까?', { title: '연락 삭제', danger: true })) {
            await contactManager.deleteContact(contactId)
            this.renderContacts()
        }
    }

    /**
     * === 공통 ===
     */

    async updateCounts() {
        const pCount = productManager.products.length
        document.getElementById('product-count').textContent = pCount
        const pc2 = document.getElementById('product-count2')
        if (pc2) pc2.textContent = pCount
        const ccEl = document.getElementById('channel-count')
        if (ccEl) ccEl.textContent = channelManager.channels.length
        document.getElementById('total-orders').textContent = orderManager.orders.length
        document.getElementById('pending-count').textContent = orderManager.getPendingOrders().length
    }

    // ==================== 상품수집 ====================

    /**
     * 프록시 서버 상태 UI 업데이트
     */
    refreshProxyStatusUI() {
        if (typeof collectorManager === 'undefined') return
        const dot = document.getElementById('proxy-status-dot')
        const text = document.getElementById('proxy-status-text')
        if (!dot || !text) return

        if (collectorManager.proxyAvailable) {
            dot.style.background = '#51CF66'
            text.style.color = '#51CF66'
            text.textContent = '실제수집 모드 활성화 — 무신사 실제 상품 데이터 수집 가능'
        } else {
            dot.style.background = '#888'
            text.style.color = '#888'
            text.textContent = '시뮬레이션 모드 — 실제수집을 위해 수집 서버를 실행해주세요'
        }
        // 인증 상태 확인
        this._refreshAuthStatusUI()
    }

    async _refreshAuthStatusUI() {
        const authDot = document.getElementById('musinsa-auth-dot')
        const authText = document.getElementById('musinsa-auth-text')
        if (!authDot || !authText) return
        try {
            const r = await fetch('http://localhost:3001/api/musinsa/auth/status')
            const d = await r.json()
            if (d.isLoggedIn) {
                authDot.style.background = '#51CF66'
                authText.style.color = '#51CF66'
                authText.textContent = '로그인 상태 — 최대혜택가 반영 활성'
            } else {
                authDot.style.background = '#888'
                authText.style.color = '#888'
                authText.textContent = '비로그인 — 로그인 시 최대혜택가 반영'
            }
        } catch {
            authDot.style.background = '#555'
            authText.style.color = '#555'
            authText.textContent = '프록시 서버 미연결'
        }
    }

    async setMusinsaAuth() {
        const input = document.getElementById('musinsa-cookie-input')
        const cookie = input?.value?.trim()
        if (!cookie) {
            app.showNotification('쿠키를 입력해주세요', 'warning')
            return
        }
        try {
            const r = await fetch('http://localhost:3001/api/musinsa/auth', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cookie })
            })
            const d = await r.json()
            if (d.success && d.isLoggedIn) {
                app.showNotification(d.message, 'success')
                input.value = ''
            } else {
                app.showNotification(d.message || '인증 실패', 'error')
            }
            this._refreshAuthStatusUI()
        } catch (e) {
            app.showNotification('프록시 서버 연결 실패', 'error')
        }
    }

    async clearMusinsaAuth() {
        try {
            await fetch('http://localhost:3001/api/musinsa/auth', { method: 'DELETE' })
            app.showNotification('연동 해제 완료', 'success')
            this._refreshAuthStatusUI()
        } catch (e) {
            app.showNotification('프록시 서버 연결 실패', 'error')
        }
    }

    async musinsaLogin() {
        // 1) Chrome 쿠키 자동 읽기 시도
        const authText = document.getElementById('musinsa-auth-text')
        const authDot = document.getElementById('musinsa-auth-dot')
        if (authText) { authText.style.color = '#888'; authText.textContent = '로그인 중...' }

        try {
            const r = await fetch('http://localhost:3001/api/musinsa/chrome-login')
            const d = await r.json()
            if (d.success && d.isLoggedIn) {
                app.showNotification(d.message, 'success')
                this._refreshAuthStatusUI()
                return
            }
            // Chrome 자동 로그인 실패 → 모달로 폴백
            app.showNotification(d.message || 'Chrome 자동 로그인 실패', 'warning')
        } catch {
            // 서버 미연결이면 바로 모달 표시
        }
        this._refreshAuthStatusUI()
        this.showMusinsaLoginModal()
    }

    showMusinsaLoginModal() {
        const existing = document.getElementById('musinsa-auth-modal')
        if (existing) existing.remove()

        const modal = document.createElement('div')
        modal.id = 'musinsa-auth-modal'
        modal.style.cssText = 'position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.7);'
        modal.innerHTML = `
            <div style="background:#1A1A1A;border:1px solid #2D2D2D;border-radius:12px;padding:28px;width:520px;max-width:90vw;box-shadow:0 20px 60px rgba(0,0,0,0.5);">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
                    <span style="font-size:1rem;font-weight:700;color:#E5E5E5;">무신사 로그인</span>
                    <button onclick="document.getElementById('musinsa-auth-modal').remove()" style="background:none;border:none;color:#666;font-size:1.2rem;cursor:pointer;">&times;</button>
                </div>
                <div style="display:flex;gap:2px;background:#0F0F0F;border:1px solid #2D2D2D;border-radius:8px;padding:4px;margin-bottom:16px;">
                    <button id="musinsa-tab-login" onclick="ui._switchMusinsaTab('login')" style="flex:1;padding:8px;border:none;background:linear-gradient(135deg,#FF8C00,#FFB84D);color:#fff;border-radius:6px;font-size:0.82rem;font-weight:700;cursor:pointer;">간편 로그인</button>
                    <button id="musinsa-tab-cookie" onclick="ui._switchMusinsaTab('cookie')" style="flex:1;padding:8px;border:none;background:transparent;color:#888;border-radius:6px;font-size:0.82rem;cursor:pointer;">쿠키 직접 입력</button>
                </div>
                <div id="musinsa-panel-login">
                    <div style="font-size:0.78rem;color:#888;margin-bottom:12px;padding:8px 12px;background:#0F0F0F;border:1px solid #2D2D2D;border-radius:6px;">입력한 정보는 로그인용으로만 사용되며 서버에 저장되지 않습니다</div>
                    <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:16px;">
                        <input id="musinsa-login-id" type="text" placeholder="무신사 아이디" style="padding:10px 14px;font-size:0.85rem;background:#0F0F0F;border:1px solid #3D3D3D;color:#E5E5E5;border-radius:6px;outline:none;">
                        <input id="musinsa-login-pw" type="password" placeholder="비밀번호" style="padding:10px 14px;font-size:0.85rem;background:#0F0F0F;border:1px solid #3D3D3D;color:#E5E5E5;border-radius:6px;outline:none;">
                    </div>
                    <button id="musinsa-login-btn" onclick="ui._submitMusinsaLogin()" style="width:100%;padding:12px;background:linear-gradient(135deg,#FF8C00,#FFB84D);border:none;color:#fff;border-radius:6px;font-size:0.9rem;font-weight:700;cursor:pointer;">로그인</button>
                </div>
                <div id="musinsa-panel-cookie" style="display:none;">
                    <div style="background:#0F0F0F;border:1px solid #2D2D2D;border-radius:8px;padding:16px;margin-bottom:16px;">
                        <div style="font-size:0.82rem;color:#FFB84D;font-weight:600;margin-bottom:12px;">3단계로 간편 연동</div>
                        <div style="display:flex;flex-direction:column;gap:10px;font-size:0.8rem;color:#B0B0B0;line-height:1.6;">
                            <div><span style="color:#FF8C00;font-weight:700;">1.</span> <a href="https://www.musinsa.com" target="_blank" style="color:#6B8AFF;text-decoration:underline;">무신사</a>에 로그인 후 F12 키를 누르세요</div>
                            <div><span style="color:#FF8C00;font-weight:700;">2.</span> Console 탭 클릭 후 아래 명령어를 붙여넣고 Enter</div>
                            <div style="display:flex;align-items:center;gap:8px;background:#161616;border:1px solid #333;border-radius:6px;padding:8px 12px;margin:4px 0;">
                                <code style="color:#51CF66;font-size:0.82rem;flex:1;font-family:monospace;">copy(document.cookie)</code>
                                <button onclick="navigator.clipboard.writeText('copy(document.cookie)');app.showNotification('명령어 복사됨','success')" style="background:rgba(255,140,0,0.15);border:1px solid rgba(255,140,0,0.3);color:#FF8C00;padding:3px 10px;border-radius:4px;font-size:0.72rem;cursor:pointer;white-space:nowrap;">복사</button>
                            </div>
                            <div><span style="color:#FF8C00;font-weight:700;">3.</span> 아래 입력창에 Ctrl+V 붙여넣고 연동 버튼 클릭</div>
                        </div>
                    </div>
                    <div style="display:flex;gap:8px;margin-bottom:16px;">
                        <input id="musinsa-cookie-paste" type="text" placeholder="여기에 Ctrl+V 붙여넣기" style="flex:1;padding:10px 14px;font-size:0.85rem;background:#0F0F0F;border:1px solid #3D3D3D;color:#E5E5E5;border-radius:6px;outline:none;">
                        <button id="musinsa-auth-submit-btn" onclick="ui._submitMusinsaAuth()" style="background:linear-gradient(135deg,#FF8C00,#FFB84D);border:none;color:#fff;padding:10px 24px;border-radius:6px;font-size:0.85rem;cursor:pointer;font-weight:700;white-space:nowrap;">연동</button>
                    </div>
                </div>
                <div id="musinsa-auth-result" style="font-size:0.78rem;color:#888;text-align:center;min-height:20px;"></div>
            </div>`
        modal.addEventListener('click', e => { if (e.target === modal) modal.remove() })
        document.body.appendChild(modal)
        document.getElementById('musinsa-login-id')?.focus()
        document.getElementById('musinsa-login-pw')?.addEventListener('keydown', e => {
            if (e.key === 'Enter') ui._submitMusinsaLogin()
        })
    }

    // 레거시 호환 (기존 코드 참조 대비)
    showMusinsaAuthGuide() { this.showMusinsaLoginModal() }

    _switchMusinsaTab(tab) {
        const loginPanel = document.getElementById('musinsa-panel-login')
        const cookiePanel = document.getElementById('musinsa-panel-cookie')
        const loginBtn = document.getElementById('musinsa-tab-login')
        const cookieBtn = document.getElementById('musinsa-tab-cookie')
        const activeStyle = 'flex:1;padding:8px;border:none;background:linear-gradient(135deg,#FF8C00,#FFB84D);color:#fff;border-radius:6px;font-size:0.82rem;font-weight:700;cursor:pointer;'
        const inactiveStyle = 'flex:1;padding:8px;border:none;background:transparent;color:#888;border-radius:6px;font-size:0.82rem;cursor:pointer;'
        if (tab === 'login') {
            loginPanel.style.display = ''
            cookiePanel.style.display = 'none'
            loginBtn.style.cssText = activeStyle
            cookieBtn.style.cssText = inactiveStyle
        } else {
            loginPanel.style.display = 'none'
            cookiePanel.style.display = ''
            cookieBtn.style.cssText = activeStyle
            loginBtn.style.cssText = inactiveStyle
            document.getElementById('musinsa-cookie-paste')?.focus()
        }
    }

    async _submitMusinsaLogin() {
        const idInput = document.getElementById('musinsa-login-id')
        const pwInput = document.getElementById('musinsa-login-pw')
        const result = document.getElementById('musinsa-auth-result')
        const btn = document.getElementById('musinsa-login-btn')

        const id = idInput?.value?.trim()
        const password = pwInput?.value
        if (!id) { result.innerHTML = '<span style="color:#FF6B6B;">아이디를 입력해주세요</span>'; return }
        if (!password) { result.innerHTML = '<span style="color:#FF6B6B;">비밀번호를 입력해주세요</span>'; return }

        btn.disabled = true
        btn.textContent = '로그인 중...'
        result.innerHTML = '<span style="color:#888;">인증 확인 중...</span>'

        try {
            const r = await fetch('http://localhost:3001/api/musinsa/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id, password })
            })
            const d = await r.json()
            if (d.success && d.isLoggedIn) {
                result.innerHTML = `<span style="color:#51CF66;font-weight:600;">${d.message}</span>`
                app.showNotification(d.message, 'success')
                setTimeout(() => {
                    document.getElementById('musinsa-auth-modal')?.remove()
                    this._refreshAuthStatusUI()
                }, 1500)
            } else if (d.code === 'REQUIRES_VERIFICATION') {
                result.innerHTML = `<span style="color:#FFB84D;">${d.message}</span>`
                app.showNotification('쿠키 직접 입력으로 전환합니다', 'warning')
                this._switchMusinsaTab('cookie')
            } else {
                result.innerHTML = `<span style="color:#FF6B6B;">${d.message || '로그인 실패'}</span>`
            }
        } catch (e) {
            result.innerHTML = '<span style="color:#FF6B6B;">수집 서버 연결 실패</span>'
        }
        btn.disabled = false
        btn.textContent = '로그인'
    }

    async _submitMusinsaAuth() {
        const input = document.getElementById('musinsa-cookie-paste')
        const result = document.getElementById('musinsa-auth-result')
        const btn = document.getElementById('musinsa-auth-submit-btn')
        const cookie = input?.value?.trim()
        if (!cookie) { result.innerHTML = '<span style="color:#FF6B6B;">쿠키를 붙여넣어주세요</span>'; return }

        btn.disabled = true
        btn.textContent = '확인 중...'
        result.innerHTML = '<span style="color:#888;">인증 확인 중...</span>'

        try {
            const r = await fetch('http://localhost:3001/api/musinsa/auth', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cookie })
            })
            const d = await r.json()
            if (d.success && d.isLoggedIn) {
                result.innerHTML = `<span style="color:#51CF66;font-weight:600;">${d.message}</span>`
                app.showNotification(d.message, 'success')
                setTimeout(() => {
                    document.getElementById('musinsa-auth-modal')?.remove()
                }, 1500)
            } else {
                result.innerHTML = `<span style="color:#FF6B6B;">${d.message || '인증 실패'}</span>`
            }
            this._refreshAuthStatusUI()
        } catch (e) {
            result.innerHTML = '<span style="color:#FF6B6B;">프록시 서버 연결 실패</span>'
        }
        btn.disabled = false
        btn.textContent = '연동'
    }

    /**
     * 프록시 재확인 + UI 갱신
     */
    async checkAndRefreshProxyStatus() {
        if (typeof collectorManager === 'undefined') return
        const dot = document.getElementById('proxy-status-dot')
        const text = document.getElementById('proxy-status-text')
        if (text) text.textContent = '확인 중...'
        await collectorManager.checkProxyServer()
        this.refreshProxyStatusUI()
    }

    /**
     * 소싱사이트 태그 동적 렌더링
     */
    renderSiteTags() {
        const container = document.getElementById('sourcing-site-tags')
        if (!container || typeof collectorManager === 'undefined') return

        container.innerHTML = collectorManager.supportedSites.map((site, i) => `
            <button class="site-tag ${i === 0 ? 'active' : ''}" data-site="${site.id}" onclick="ui.selectSiteTag(this, '${site.id}')">
                ${site.label}
            </button>
        `).join('')
    }

    selectSiteTag(btn, siteId) {
        document.querySelectorAll('.site-tag').forEach(b => b.classList.remove('active'))
        btn.classList.add('active')
        this._selectedSiteId = siteId
    }

    /**
     * 저장된 상품 수 업데이트
     */
    async updateSavedCount() {
        if (typeof collectorManager === 'undefined') return
        const count = await collectorManager.getTotalSavedCount()
        const el = document.getElementById('sourcing-saved-count')
        if (el) el.textContent = count.toLocaleString()
    }

    /**
     * 수집 로그 메시지 출력
     */
    /**
     * 로그 내용 클립보드 복사
     */
    copyLog(logId) {
        const el = document.getElementById(logId)
        if (!el) return
        const text = [...el.querySelectorAll('p, div')].map(p => p.textContent).join('\n')
        navigator.clipboard.writeText(text).then(() => {
            app.showNotification('로그가 클립보드에 복사되었습니다', 'success')
        }).catch(() => {
            app.showNotification('복사 실패', 'error')
        })
    }

    _log(msg, type = 'info') {
        const logEl = document.getElementById('collect-log')
        if (!logEl) return
        // 로그 영역 최소 높이 확보
        if (!logEl.style.minHeight) {
            logEl.style.minHeight = '200px'
            logEl.style.maxHeight = '400px'
            logEl.style.overflowY = 'auto'
        }
        const colors = { info: '#8A95B0', success: '#51CF66', error: '#FF6B6B', warn: '#FFB84D' }
        const time = new Date().toLocaleTimeString('ko-KR', { hour12: false })
        const line = document.createElement('p')
        line.style.cssText = `color:${colors[type] || colors.info}; margin:2px 0; font-size:0.8rem; font-family:monospace; line-height:1.4;`
        line.textContent = `[${time}] ${msg}`
        logEl.appendChild(line)
        logEl.scrollTop = logEl.scrollHeight
    }

    /**
     * 그룹 생성 (수집 없이 searchFilter만 등록)
     */
    async handleCollect() {
        const urlInput = document.getElementById('collect-url-bulk')
        const url = urlInput?.value?.trim()
        if (!url) { app.showNotification('URL을 입력해주세요', 'warning'); return }

        const logEl = document.getElementById('collect-log')
        if (logEl) logEl.innerHTML = ''
        this._log(`URL: ${url}`)

        try {
            if (typeof collectorManager === 'undefined') return
            const site = collectorManager.parseSiteFromUrl(url)
            const detectedName = site ? site.name : '알 수 없는 사이트'
            this._log(`사이트 감지: ${detectedName}`, site ? 'success' : 'warn')

            // 무신사 실제 수집 모드 표시
            const isRealMode = collectorManager.realModeEnabled &&
                collectorManager._isMusinsaUrl(url) &&
                collectorManager.proxyAvailable
            this._log(
                isRealMode
                    ? '수집 모드: 실제수집 (MUSINSA 프록시 연결됨)'
                    : '수집 모드: 시뮬레이션',
                isRealMode ? 'success' : 'info'
            )

            // 중복 확인
            const existing = collectorManager.filters.find(f => f.searchUrl === url)
            if (existing) {
                this._log(`이미 존재하는 그룹: "${existing.name}"`, 'warn')
                app.showNotification('이미 등록된 URL입니다', 'warning')
                return
            }

            // 그룹 생성만 (수집 X)
            const keyword = collectorManager._extractKeywordFromUrl(url)
            const filterName = `${detectedName}_${keyword || 'URL수집'}`
            const filter = await collectorManager.addFilter({
                name: filterName,
                sourceSite: detectedName,
                searchUrl: url,
                collectCount: 100
            })
            this._log(`검색그룹 생성 완료: "${filter.name}"`, 'success')
            this._log(`하단 검색그룹에서 상품수집을 실행하세요`, 'info')

            urlInput.value = ''
            await this.renderSearchFilterTable()
            app.showNotification(`그룹 "${filter.name}" 생성 완료`, 'success')
        } catch (err) {
            this._log(`오류: ${err.message}`, 'error')
            app.showNotification('그룹 생성 실패: ' + err.message, 'error')
        }
    }

    /**
     * 선택된 검색그룹 삭제
     */
    async deleteSelectedGroups() {
        const checked = [...document.querySelectorAll('#apply-group-tbody input[type=checkbox]:checked')]
        if (checked.length === 0) {
            app.showNotification('삭제할 그룹을 선택해주세요', 'warning')
            return
        }
        if (!await this.showConfirm(`선택된 ${checked.length}개 그룹을 삭제하시겠습니까?\n(그룹 내 수집상품도 함께 삭제됩니다)`, { title: '그룹 삭제', danger: true })) return

        const filterIds = checked.map(cb => cb.closest('tr')?.getAttribute('data-filter-id')).filter(Boolean)
        let totalDeleted = 0
        let totalMarket = 0

        for (const id of filterIds) {
            const result = await collectorManager.deleteFilter(id)

            if (result.skipped && result.marketRegistered > 0) {
                const forceDelete = await this.showConfirm(
                    `이 그룹에 마켓 등록된 상품이 ${result.marketRegistered}개 있습니다.\n마켓에서 먼저 삭제하는 것을 권장합니다.\n\n그래도 강제 삭제하시겠습니까?`,
                    { title: '마켓 등록 상품 경고', danger: true, confirmText: '강제 삭제' }
                )
                if (forceDelete) {
                    const forceResult = await collectorManager.deleteFilter(id, { force: true })
                    totalDeleted += forceResult.deleted
                    totalMarket += forceResult.marketRegistered
                }
            } else {
                totalDeleted += result.deleted
            }
        }

        const msg = totalMarket > 0
            ? `${filterIds.length}개 그룹 삭제 (상품 ${totalDeleted}개, 마켓등록 ${totalMarket}개 포함)`
            : `${filterIds.length}개 그룹 삭제 (상품 ${totalDeleted}개 포함)`
        app.showNotification(msg, 'success')
        await this.renderSearchFilterTable()
        await productManager.loadProducts()
        this.renderProducts()
    }

    /**
     * 선택된 그룹으로 상품수집 실행
     */
    async handleCollectGroups() {
        const checked = [...document.querySelectorAll('#apply-group-tbody input[type=checkbox]:checked')]
        if (checked.length === 0) {
            app.showNotification('수집할 그룹을 선택해주세요', 'warning')
            return
        }

        // 선택된 그룹의 tr에서 filter id 가져오기
        const filterIds = checked.map(cb => cb.closest('tr')?.getAttribute('data-filter-id')).filter(Boolean)
        if (filterIds.length === 0) {
            app.showNotification('그룹 정보를 찾을 수 없습니다', 'error')
            return
        }

        // 상세이미지 수집 토글 상태 반영
        const detailImgCheckbox = document.getElementById('collect-detail-images')
        if (typeof collectorManager !== 'undefined') {
            collectorManager.collectDetailImages = detailImgCheckbox?.checked || false
        }

        const logEl = document.getElementById('collect-log')
        if (logEl) logEl.innerHTML = ''
        this._log(`${filterIds.length}개 그룹 수집 시작...`)

        // 수집 엔진 로그를 UI에 실시간 연결
        collectorManager.onLog = (msg, type) => this._log(msg, type)

        try {
            let totalSaved = 0
            for (const filterId of filterIds) {
                await collectorManager.loadFilters()
                const filter = collectorManager.filters.find(f => f.id === filterId)
                if (!filter) continue

                const already = filter.savedCount || 0
                const target = filter.collectCount || 100
                if (already >= target) {
                    this._log(`[${filter.name}] 목표 수량 달성 (${already}/${target}), 건너뜀`, 'warn')
                    continue
                }

                const isRealMode = collectorManager.realModeEnabled &&
                    collectorManager._isMusinsaUrl(filter.searchUrl || '') &&
                    collectorManager.proxyAvailable
                this._log(
                    `[${filter.name}] 수집 시작 (${already}개 → 목표 ${target}개) [${isRealMode ? '실제수집' : '시뮬레이션'}]`,
                    isRealMode ? 'success' : 'info'
                )
                const result = await collectorManager.autoCollectAndSave(filter)

                if (result.alreadyFull) {
                    this._log(`[${filter.name}] 이미 목표 달성`, 'warn')
                } else {
                    totalSaved += result.saved
                    this._log(
                        `[${filter.name}] 저장 ${result.saved}개 완료` +
                        (result.duplicates > 0 ? ` (중복 ${result.duplicates}개 제외)` : ''),
                        result.saved > 0 ? 'success' : 'warn'
                    )
                    const newTotal = already + result.saved
                    if (newTotal >= target) {
                        this._log(`[${filter.name}] 목표 ${target}개 달성`, 'success')
                    }
                }
            }
            this._log(`수집 완료. 총 ${totalSaved}개 저장됨`, 'success')
            await this.renderSearchFilterTable()
            if (totalSaved > 0) {
                await productManager.loadProducts()
                this.updateCounts()
                app.showNotification(`${totalSaved}개 상품이 상품관리에 추가됨`, 'success')
            }
        } catch (err) {
            this._log(`오류: ${err.message}`, 'error')
            app.showNotification('수집 실패: ' + err.message, 'error')
        } finally {
            collectorManager.onLog = null
        }
    }

    /**
     * 수집 결과 동적 렌더링 (컨테이너 전체)
     */
    renderCollectResults(page = 1) {
        const container = document.getElementById('collect-results-container')
        if (!container || typeof collectorManager === 'undefined') return

        const { items, total, totalPages } = collectorManager.getResultsPage(page)

        if (items.length === 0) { container.innerHTML = ''; return }

        const rows = items.map(p => {
            const optionCount = p.options ? p.options.length : 0
            const statusBadge = p.status === 'saved'
                ? `<span style="background:rgba(81,207,102,0.15); color:#51CF66; padding:0.2rem 0.5rem; border-radius:4px; font-size:0.75rem;">저장됨</span>`
                : `<span style="background:rgba(100,100,100,0.2); color:#888; padding:0.2rem 0.5rem; border-radius:4px; font-size:0.75rem;">수집</span>`
            return `
                <tr style="border-bottom:1px solid #1A1A1A;">
                    <td style="padding:0.75rem 1rem; text-align:center;">
                        <input type="checkbox" class="collect-item-cb" value="${p.id}">
                    </td>
                    <td style="padding:0.75rem 0.5rem;">
                        <div style="width:64px; height:64px; background:#2D2D2D; border-radius:6px; overflow:hidden; display:flex; align-items:center; justify-content:center;">
                            ${p.images && p.images[0]
                                ? `<img src="${p.images[0]}" style="width:100%; height:100%; object-fit:cover;" onerror="this.style.display='none'">`
                                : `<i class="fas fa-image" style="color:#555; font-size:1.25rem;"></i>`}
                        </div>
                    </td>
                    <td style="padding:0.75rem 0.5rem;">
                        <p style="font-size:0.8125rem; color:#E5E5E5; font-weight:500; margin-bottom:0.25rem; max-width:320px;">${p.name}</p>
                        <p style="font-size:0.75rem; color:#888;">${p.brand || ''} | ${p.category || ''}</p>
                        <p style="font-size:0.75rem; color:#666; font-family:monospace;">ID: ${p.siteProductId}</p>
                        <div style="display:flex; flex-direction:column; gap:3px; margin-top:5px;">
                            <input type="text" placeholder="EN 영문명" value="${p.nameEn || ''}"
                                onchange="ui.updateCollectItemName('${p.id}','nameEn',this.value)"
                                style="width:100%; padding:2px 6px; font-size:0.72rem; background:#1A1A1A; border:1px solid #2D2D2D; color:#C5C5C5; border-radius:3px; outline:none;" />
                            <input type="text" placeholder="JP 일어명" value="${p.nameJa || ''}"
                                onchange="ui.updateCollectItemName('${p.id}','nameJa',this.value)"
                                style="width:100%; padding:2px 6px; font-size:0.72rem; background:#1A1A1A; border:1px solid #2D2D2D; color:#C5C5C5; border-radius:3px; outline:none;" />
                        </div>
                    </td>
                    <td style="padding:0.75rem 0.5rem; text-align:right; white-space:nowrap;">
                        <span style="font-size:0.9rem; color:#FFB84D; font-weight:600;">₩${this.formatNumber(p.salePrice)}</span>
                    </td>
                    <td style="padding:0.75rem 0.5rem; font-size:0.8125rem; color:#888;">${p.category || '-'}</td>
                    <td style="padding:0.75rem 0.5rem; text-align:center; font-size:0.875rem; color:#C5C5C5;">${optionCount}개</td>
                    <td style="padding:0.75rem 0.5rem; text-align:center;">
                        <div style="display:flex; flex-direction:column; gap:4px; align-items:center;">
                            ${statusBadge}
                            <a href="${p.sourceUrl}" target="_blank" style="font-size:0.7rem; color:#4C9AFF; text-decoration:none;">원문보기</a>
                        </div>
                    </td>
                </tr>`
        }).join('')

        const pagination = totalPages > 1 ? `
            <div style="display:flex; align-items:center; gap:8px; justify-content:center; padding:1rem; font-size:0.8125rem;">
                <span style="color:#888;">총 ${total}개</span>
                ${page > 1 ? `<button onclick="ui.renderCollectResults(${page-1})" style="background:rgba(40,40,40,0.8); border:1px solid #3D3D3D; color:#C5C5C5; padding:0.25rem 0.75rem; border-radius:4px;">이전</button>` : ''}
                <span style="color:#FF8C00; font-weight:600;">${page} / ${totalPages}</span>
                ${page < totalPages ? `<button onclick="ui.renderCollectResults(${page+1})" style="background:rgba(40,40,40,0.8); border:1px solid #3D3D3D; color:#C5C5C5; padding:0.25rem 0.75rem; border-radius:4px;">다음</button>` : ''}
            </div>` : ''

        container.innerHTML = `
            <div class="bg-white rounded-lg shadow" style="margin-bottom:1rem;">
                <!-- 액션 바 -->
                <div style="display:flex; align-items:center; gap:8px; padding:0.625rem 1rem; border-bottom:1px solid #2D2D2D; flex-wrap:nowrap;">
                    <label style="display:flex; align-items:center; gap:0.375rem; font-size:0.8125rem; color:#C5C5C5; cursor:pointer; white-space:nowrap; flex-shrink:0;">
                        <input type="checkbox" id="collect-select-all"
                            onchange="document.querySelectorAll('.collect-item-cb').forEach(cb => cb.checked = this.checked)">
                        전체선택
                    </label>
                    <button id="btn-save-selected" onclick="ui.handleSaveSelected()"
                        style="background:linear-gradient(135deg,#FF8C00,#FFB84D); color:#fff; padding:0.375rem 0.875rem; border-radius:6px; font-size:0.8125rem; font-weight:600; white-space:nowrap; flex-shrink:0; cursor:pointer;">
                        <i class="fas fa-save" style="margin-right:0.25rem;"></i>선택상품저장
                    </button>
                    <button id="btn-save-all" onclick="ui.handleSaveAll()"
                        style="background:rgba(50,50,50,0.8); border:1px solid #3D3D3D; color:#C5C5C5; padding:0.375rem 0.875rem; border-radius:6px; font-size:0.8125rem; white-space:nowrap; flex-shrink:0; cursor:pointer;">
                        검색된 상품 모두저장
                    </button>
                    <span style="margin-left:auto; font-size:0.8rem; color:#888;">총 <span style="color:#FF8C00; font-weight:600;">${total}</span>개</span>
                </div>
                <!-- 결과 테이블 -->
                <table class="w-full">
                    <thead>
                        <tr>
                            <th style="width:40px; padding:0.75rem 1rem;"></th>
                            <th style="width:80px; padding:0.75rem 0.5rem; text-align:left; font-size:0.75rem; color:#888;">이미지</th>
                            <th style="padding:0.75rem 0.5rem; text-align:left; font-size:0.75rem; color:#888;">상품명</th>
                            <th style="padding:0.75rem 0.5rem; text-align:right; font-size:0.75rem; color:#888;">원가</th>
                            <th style="padding:0.75rem 0.5rem; text-align:left; font-size:0.75rem; color:#888;">카테고리</th>
                            <th style="padding:0.75rem 0.5rem; text-align:center; font-size:0.75rem; color:#888;">옵션수</th>
                            <th style="padding:0.75rem 0.5rem; text-align:center; font-size:0.75rem; color:#888;">상태</th>
                        </tr>
                    </thead>
                    <tbody id="collect-results-tbody">${rows}</tbody>
                </table>
                ${pagination}
            </div>`
    }

    /**
     * 수집 상품의 영문/일어명 인라인 업데이트
     * @param {string} productId - 수집 상품 ID
     * @param {'nameEn'|'nameJa'} field - 변경할 필드명
     * @param {string} value - 입력된 값
     */
    async updateCollectItemName(productId, field, value) {
        if (typeof collectorManager === 'undefined') return
        // 메모리 내 결과 업데이트
        const item = collectorManager.collectResults.find(r => r.id === productId)
        if (item) {
            item[field] = value
            // IndexedDB에도 반영
            const stored = await storage.get('collectedProducts', productId)
            if (stored) {
                await storage.save('collectedProducts', { ...stored, [field]: value, updatedAt: new Date().toISOString() })
            }
        }
    }

    /**
     * 선택 저장
     */
    async handleSaveSelected() {
        const selected = [...document.querySelectorAll('.collect-item-cb:checked')].map(cb => cb.value)
        if (selected.length === 0) { app.showNotification('저장할 상품을 선택해주세요', 'warning'); return }

        app.showLoading(true)
        try {
            const count = await collectorManager.saveSelectedProducts(selected)
            this._log(`${count}개 상품 저장 완료 → 상품관리로 이동 가능`, 'success')
            app.showNotification(`${count}개 상품이 저장되었습니다`, 'success')
            await this.updateSavedCount()
            // 저장된 항목만 유지, 미저장 항목 즉시 삭제
            collectorManager.collectResults = collectorManager.collectResults.filter(p => selected.includes(p.id))
            this.renderCollectResults(1)
        } catch (err) {
            this._log(`저장 오류: ${err.message}`, 'error')
            app.showNotification('저장 실패: ' + err.message, 'error')
        }
        app.showLoading(false)
    }

    /**
     * 전체 저장
     */
    async handleSaveAll() {
        if (typeof collectorManager === 'undefined' || collectorManager.collectResults.length === 0) {
            app.showNotification('저장할 상품이 없습니다', 'warning'); return
        }
        if (!await this.showConfirm(`${collectorManager.collectResults.length}개 상품을 모두 저장하시겠습니까?`, { title: '전체 저장' })) return

        app.showLoading(true)
        try {
            const count = await collectorManager.saveAllProducts()
            this._log(`${count}개 전체 저장 완료 → 상품관리로 이동 가능`, 'success')
            app.showNotification(`${count}개 상품이 저장되었습니다`, 'success')
            await this.updateSavedCount()
            // 전체 저장 후 목록 초기화
            collectorManager.collectResults = []
            this.renderCollectResults(1)
        } catch (err) {
            this._log(`저장 오류: ${err.message}`, 'error')
            app.showNotification('저장 실패: ' + err.message, 'error')
        }
        app.showLoading(false)
    }

    // ==================== 정책 관리 ====================

    /**
     * 정책 드롭다운 렌더링
     */
    renderPolicyList() {
        if (typeof policyManager === 'undefined') return
        const selects = document.querySelectorAll('.policy-select-dynamic')
        selects.forEach(sel => {
            const current = sel.value
            sel.innerHTML = '<option value="">정책 선택</option>' +
                policyManager.policies.map(p => `<option value="${p.id}" ${p.id === current ? 'selected' : ''}>${p.name}</option>`).join('')
        })
    }

    /**
     * 정책 선택 시 정책명 input에 현재 이름 표시
     */
    onPolicySelect() {
        const sel = document.getElementById('policy-select')
        const input = document.getElementById('policy-name-input')
        if (!sel || !input) return
        const id = sel.value
        if (!id || typeof policyManager === 'undefined') { input.value = ''; return }
        const policy = policyManager.policies.find(p => p.id === id)
        input.value = policy ? policy.name : ''
    }

    /**
     * 선택된 정책의 이름 수정
     */
    async renameSelectedPolicy() {
        const sel = document.getElementById('policy-select')
        const input = document.getElementById('policy-name-input')
        if (!sel || !input) return
        const id = sel.value
        const newName = (input.value || '').trim()
        if (!id) { app.showNotification('정책을 선택해주세요', 'error'); return }
        if (!newName) { app.showNotification('정책명을 입력해주세요', 'error'); return }
        await policyManager.updatePolicy(id, { name: newName })
        this.renderPolicyList()
        app.showNotification(`정책명이 "${newName}"으로 수정되었습니다`, 'success')
    }

    /**
     * 신규 정책 등록 모달
     */
    async showNewPolicyModal() {
        const name = await this.showPrompt('새 정책 이름을 입력하세요', { title: '신규 정책 등록', placeholder: '예: 나이키 15% 마진' })
        if (!name || !name.trim()) return
        const policy = await policyManager.addPolicy({ name: name.trim() })
        this.renderPolicyList()
        // 신규 정책 자동 선택
        const sel = document.getElementById('policy-select')
        if (sel) { sel.value = policy.id; this.onPolicySelect() }
        app.showNotification(`정책 "${policy.name}" 등록 완료`, 'success')
    }

    // ==================== 마켓 계정 ====================

    /**
     * 전송 페이지 마켓 계정 체크박스 렌더링
     */
    renderAccountCheckboxes() {
        const container = document.getElementById('shipment-account-checkboxes')
        if (!container) return

        const labelStyle = 'display:inline-flex; align-items:center; gap:5px; font-size:0.8rem; color:#8A95B0; cursor:pointer; white-space:nowrap;'
        const cbStyle = 'accent-color:#FF8C00; flex-shrink:0; width:14px; height:14px;'

        // accountManager 계정 기반으로 동적 렌더링
        if (typeof accountManager !== 'undefined' && accountManager.accounts && accountManager.accounts.length > 0) {
            container.innerHTML = `<label style="${labelStyle}"><input type="checkbox" id="ship-market-all" style="${cbStyle}" onchange="document.querySelectorAll('.shipment-account-cb').forEach(c=>c.checked=this.checked)"> 전체</label>`
                + accountManager.accounts.map(acc => `
                    <label style="${labelStyle}">
                        <input type="checkbox" class="shipment-account-cb" value="${acc.id}" style="${cbStyle}">
                        <span style="color:#C5C5C5; font-size:0.875rem;">${acc.accountLabel} (${acc.marketName})</span>
                    </label>
                `).join('')
        } else {
            // 등록된 계정이 없는 경우 안내 메시지 표시
            container.innerHTML = `<p style="color:#666; font-size:0.8rem;">등록된 마켓 계정이 없습니다. 설정 &gt; 마켓 계정에서 추가해주세요.</p>`
        }
    }

    /**
     * 매출통계 마켓 체크박스 렌더링 (MARKET_LIST 기반)
     */
    renderAnalyticsMarkets() {
        const container = document.querySelector('.af-cb-items.af-mkt-items')
        if (!container) return
        const markets = (typeof MARKET_LIST !== 'undefined') ? MARKET_LIST : []
        const existing = container.querySelector('#af-all-mkt')?.parentElement?.outerHTML || ''
        const divider = container.querySelector('.af-cb-divider')?.outerHTML || '<div class="af-cb-divider"></div>'
        container.innerHTML = `<label class="af-cb"><input type="checkbox" id="af-all-mkt" onchange="afToggleAll('mkt',this)"> <span>전체</span></label>${divider}`
            + markets.map(m => `<label class="af-cb"><input type="checkbox" class="af-mkt" value="${m}" checked> <span>${m}</span></label>`).join('')
    }

    /**
     * 마켓별 계정 현황판 렌더링
     */
    renderAccountDashboard() {
        const container = document.getElementById('market-account-dashboard')
        if (!container || typeof accountManager === 'undefined') return

        const accounts = accountManager.accounts || []
        if (accounts.length === 0) {
            container.innerHTML = '<div style="color:#666; font-size:0.875rem; padding:1rem 0;">마켓 계정을 등록하면 여기에 현황이 표시됩니다.</div>'
            return
        }

        // 마켓별 그룹핑
        const marketIcons = {
            smartstore: { color:'#03C75A', label:'N' },
            gmarket:    { color:'#4285F4', label:'G' },
            auction:    { color:'#E63950', label:'A.' },
            coupang:    { color:'#FF0000', label:'C' },
            lotteon:    { color:'#E63950', label:'L' },
            '11st':     { color:'#FF6600', label:'11D' },
            ssg:        { color:'#FF5A5A', label:'SSG' },
            gsshop:     { color:'#006EBD', label:'GS' },
            lottehome:  { color:'#D50000', label:'LH' },
            homeand:    { color:'#4CAF50', label:'H&' },
            hmall:      { color:'#C62828', label:'HM' },
            playauto:   { color:'#6B48FF', label:'P' },
            ebay:       { color:'#E43137', label:'e' }
        }
        const marketNames = {
            smartstore:'스마트스토어', gmarket:'지마켓', auction:'옥션',
            coupang:'쿠팡', lotteon:'롯데온', '11st':'11번가',
            ssg:'SSG', gsshop:'GSSHOP', lottehome:'롯데홈쇼핑',
            homeand:'홈앤쇼핑', hmall:'HMALL', playauto:'플레이오토', ebay:'eBay'
        }

        const grouped = {}
        accounts.forEach(acc => {
            const mt = acc.marketType || 'etc'
            if (!grouped[mt]) grouped[mt] = []
            grouped[mt].push(acc)
        })

        container.innerHTML = Object.entries(grouped).map(([mType, accs]) => {
            const icon = marketIcons[mType] || { color:'#555', label:'?' }
            const name = marketNames[mType] || mType
            const accountItems = accs.map(acc => `
                <div style="display:flex; align-items:center; justify-content:space-between; padding:6px 10px; border:1px solid #2A2A2A; border-radius:6px; background:#111;">
                    <span style="font-size:0.8rem; color:#C5C5C5; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:180px;">${acc.sellerId || acc.accountLabel || '-'}</span>
                    <div style="display:flex; gap:4px; flex-shrink:0;">
                        <button onclick="ui.editAccount('${acc.id}')" style="padding:2px 8px; font-size:0.72rem; background:transparent; border:1px solid #3D3D3D; color:#9AA5C0; border-radius:4px; cursor:pointer;">수정</button>
                        <button onclick="ui.deleteAccount('${acc.id}')" style="padding:2px 8px; font-size:0.72rem; background:transparent; border:1px solid #C0392B; color:#FF6B6B; border-radius:4px; cursor:pointer;">삭제</button>
                    </div>
                </div>`).join('')

            return `
                <div style="border:1px solid #2A2A2A; border-radius:8px; overflow:hidden;">
                    <div style="display:flex; align-items:center; gap:10px; padding:8px 14px; background:#0E0E14; border-bottom:1px solid #1E2030;">
                        <div style="width:28px; height:28px; border-radius:6px; background:${icon.color}; display:flex; align-items:center; justify-content:center; font-size:0.65rem; font-weight:700; color:#fff; flex-shrink:0;">${icon.label}</div>
                        <span style="font-size:0.875rem; font-weight:600; color:#E5E5E5;">${name}</span>
                        <span style="font-size:0.75rem; color:#666;">(${accs.length}개)</span>
                    </div>
                    <div style="display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:6px; padding:10px 14px; background:#0A0C14;">
                        ${accountItems}
                    </div>
                </div>`
        }).join('')
    }

    // ==================== 카테고리 브라우저 ====================

    /**
     * 5단계 카테고리 브라우저 렌더링
     * - categoryTree 스토어(영구 보존)에서 로드
     * - 현재 수집 상품의 신규 카테고리를 트리에 병합 후 저장
     */
    async renderCategoryBrowser() {
        const container = document.getElementById('cat-browser-cols')
        if (!container) return

        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;width:100%;padding:2rem;color:#555;font-size:0.875rem;">데이터 로딩중...</div>'

        try {
            const products = await storage.getAll('collectedProducts')
            this._catProducts = products || [] // 상품수 계산용 캐시

            let catData = {}

            if (products && products.length > 0 && typeof categoryManager !== 'undefined') {
                const fromProducts = categoryManager.extractCategoriesFromProducts(products)

                // categoryTree DB 병합/로드 시도 (스토어 미생성 시 폴백)
                try {
                    await categoryManager.mergeAndSaveCategories(fromProducts)
                    catData = await categoryManager.loadCategoryTree()
                } catch (dbErr) {
                    console.warn('categoryTree DB 오류, 수집 상품 기반으로 표시:', dbErr)
                    catData = fromProducts
                }
            } else if (typeof categoryManager !== 'undefined') {
                // 상품 없어도 저장된 트리 로드 시도
                try {
                    catData = await categoryManager.loadCategoryTree()
                } catch (dbErr) {
                    console.warn('categoryTree 로드 오류:', dbErr)
                }
            }

            this._catData = catData

            if (Object.keys(this._catData).length === 0) {
                container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;width:100%;padding:2rem;color:#555;font-size:0.875rem;">카테고리 데이터가 없습니다. 먼저 상품을 수집해주세요.</div>'
                return
            }

            this.catState = { site: null, cat1: null, cat2: null, cat3: null, cat4: null }
            this._renderCatCols()
        } catch (e) {
            console.error('카테고리 브라우저 로드 실패:', e)
            container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;width:100%;padding:2rem;color:#FF6B6B;font-size:0.875rem;">로드 실패</div>'
        }
    }

    /**
     * 카테고리 브라우저 컬럼 렌더링 (선택 상태 반영)
     */
    _renderCatCols() {
        const container = document.getElementById('cat-browser-cols')
        if (!container || !this._catData) return

        const { site, cat1, cat2, cat3, cat4 } = this.catState
        const catData = this._catData

        const sites = Object.keys(catData).sort((a, b) => a.localeCompare(b, 'ko'))
        const cat1List = site ? (catData[site]?.cat1 || []) : []
        const cat2List = (site && cat1) ? (catData[site]?.cat2?.[cat1] || []) : []
        const cat3List = (site && cat1 && cat2) ? (catData[site]?.cat3?.[`${cat1}|${cat2}`] || []) : []
        const cat4List = (site && cat1 && cat2 && cat3) ? (catData[site]?.cat4?.[`${cat1}|${cat2}|${cat3}`] || []) : []

        const renderCol = (header, items, selected, onClickFn, emptyMsg) => {
            const btns = items.length === 0
                ? `<p style="padding:0.75rem; font-size:0.8rem; color:#555;">${emptyMsg}</p>`
                : items.map((item, idx) =>
                    `<button class="cat-item${selected === item ? ' selected' : ''}"
                        onclick="${onClickFn}(${idx})"
                        style="text-align:left; width:100%;">${item}</button>`
                ).join('')
            return `<div class="cat-col"><div class="cat-col-header">${header}</div>${btns}</div>`
        }

        // 사이트 컬럼: 각 항목에 삭제(×) 버튼 포함
        const siteColBtns = sites.length === 0
            ? `<p style="padding:0.75rem; font-size:0.8rem; color:#555;">수집된 사이트 없음</p>`
            : sites.map((item, idx) =>
                `<div class="cat-item${site === item ? ' selected' : ''}"
                    style="display:flex; align-items:center; justify-content:space-between; padding-right:4px; cursor:pointer;"
                    onclick="ui._catClickSite(${idx})">
                    <span>${item}</span>
                    <button onclick="event.stopPropagation(); ui._deleteSiteCatTree('${item}')"
                        style="background:none; border:none; color:#555; font-size:0.8rem; cursor:pointer; padding:0 2px; line-height:1; flex-shrink:0;"
                        title="${item} 카테고리 삭제">×</button>
                </div>`
            ).join('')
        const siteCol = `<div class="cat-col"><div class="cat-col-header">사이트</div>${siteColBtns}</div>`

        container.innerHTML =
            siteCol +
            renderCol('대분류', cat1List, cat1, 'ui._catClickCat1', site ? '카테고리 없음' : '사이트 선택') +
            renderCol('중분류', cat2List, cat2, 'ui._catClickCat2', cat1 ? '항목 없음' : '대분류 선택') +
            renderCol('소분류', cat3List, cat3, 'ui._catClickCat3', cat2 ? '항목 없음' : '중분류 선택') +
            renderCol('세분류', cat4List, cat4, 'ui._catClickCat4', cat3 ? '항목 없음' : '소분류 선택')

        // 선택 경로 표시
        const pathParts = [site, cat1, cat2, cat3, cat4].filter(Boolean)
        const pathEl = document.getElementById('cat-selected-path')
        if (pathEl) pathEl.textContent = pathParts.length > 0 ? pathParts.join(' > ') : '-'

        // 선택 카테고리에 속하는 상품 필터링 (대분류 이상 선택 시에만 표시)
        const matched = (site && cat1)
            ? (this._catProducts || []).filter(p => {
                if (p.sourceSite !== site) return false
                if (p.category1 !== cat1) return false
                if (cat2 && p.category2 !== cat2) return false
                if (cat3 && p.category3 !== cat3) return false
                if (cat4 && p.category4 !== cat4) return false
                return true
            })
            : []

        // 상품수 표시
        const countEl = document.getElementById('cat-product-count')
        if (countEl) {
            countEl.textContent = site ? `상품 ${matched.length.toLocaleString()}개` : ''
        }

        // 3열 상품 그리드 렌더링
        const gridEl = document.getElementById('cat-product-grid')
        if (gridEl) {
            if (!site || matched.length === 0) {
                gridEl.style.display = 'none'
                gridEl.innerHTML = ''
            } else {
                gridEl.style.display = 'grid'
                gridEl.innerHTML = matched.slice(0, 30).map(p => {
                    const rawImg = (p.images && p.images[0]) || p.image || p.imageUrl || ''
                    // 외부 서비스(via.placeholder.com 등) 또는 이미지 없음 → SVG 데이터 URL 생성
                    const ch = (p.brand || p.name || '?')[0]
                    let img = (rawImg && !rawImg.includes('via.placeholder.com')) ? rawImg : ''
                    if (!img) {
                        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="#1A1A1A"/><text x="100" y="140" text-anchor="middle" font-size="100" font-family="sans-serif" fill="#FF8C00">${ch}</text></svg>`
                        img = 'data:image/svg+xml,' + encodeURIComponent(svg)
                    }
                    const cost = p.cost || p.originalPrice || p.salePrice || 0
                    const name = (p.name || '-').length > 18 ? p.name.slice(0, 18) + '…' : (p.name || '-')
                    return `<div onclick="ui.navigateToProduct('${p.id}')"
                        style="cursor:pointer;background:#0F0F0F;border:1px solid #1E1E1E;border-radius:6px;overflow:hidden;transition:border-color 0.15s;"
                        onmouseover="this.style.borderColor='#FF8C00'" onmouseout="this.style.borderColor='#1E1E1E'">
                        <div style="position:relative;padding-top:100%;background:#1A1A1A;overflow:hidden;">
                            <img src="${img}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;">
                        </div>
                        <div style="padding:4px 6px;">
                            <div style="font-size:0.68rem;color:#C5C5C5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${name}</div>
                            <div style="font-size:0.68rem;color:#FF8C00;">₩${cost.toLocaleString()}</div>
                        </div>
                    </div>`
                }).join('')
                if (matched.length > 30) {
                    gridEl.innerHTML += `<div style="grid-column:1/-1;text-align:center;padding:4px;font-size:0.75rem;color:#555;">외 ${(matched.length - 30).toLocaleString()}개 더 있음</div>`
                }
            }
        }
    }

    _catClickSite(idx) {
        const sites = Object.keys(this._catData).sort((a, b) => a.localeCompare(b, 'ko'))
        this.catState = { site: sites[idx], cat1: null, cat2: null, cat3: null, cat4: null }
        this._renderCatCols()
    }

    /**
     * AI 카테고리 매핑 실행
     * 현재 선택된 카테고리 트리 기준으로 등록 마켓 카테고리를 AI가 자동 매핑
     */
    async runAiCategoryMapping() {
        const catData = this._catData || {}
        const sites = Object.keys(catData)
        if (sites.length === 0) {
            app.showNotification('카테고리 데이터가 없습니다. 먼저 상품을 수집해주세요.', 'warning')
            return
        }

        const accounts = typeof accountManager !== 'undefined' ? accountManager.accounts : []
        if (accounts.length === 0) {
            app.showNotification('등록된 마켓 계정이 없습니다.', 'warning')
            return
        }

        app.showNotification('AI 카테고리 매핑 처리 중...', 'info')

        // 소싱처 최하단 카테고리 추출 후 마켓 카테고리 자동 매핑 (TODO: Claude API 연동)
        let mapped = 0
        for (const site of sites) {
            const data = catData[site]
            if (!data) continue
            // 최하단 카테고리 수집 (cat3 > cat2 > cat1 순)
            const leafCategories = []
            for (const [k3, arr3] of Object.entries(data.cat3 || {})) {
                arr3.forEach(c3 => leafCategories.push({ site, path: k3.replace('|', ' > ') + ' > ' + c3 }))
            }
            if (leafCategories.length === 0) {
                for (const [c1, arr2] of Object.entries(data.cat2 || {})) {
                    arr2.forEach(c2 => leafCategories.push({ site, path: c1 + ' > ' + c2 }))
                }
            }
            if (leafCategories.length === 0) {
                data.cat1.forEach(c1 => leafCategories.push({ site, path: c1 }))
            }

            for (const leaf of leafCategories) {
                const exists = typeof categoryManager !== 'undefined'
                    ? categoryManager.mappings.find(m => m.sourceSite === leaf.site && m.sourceCategory === leaf.path)
                    : null
                if (!exists && typeof categoryManager !== 'undefined') {
                    await categoryManager.addMapping({ sourceSite: leaf.site, sourceCategory: leaf.path, targetMappings: {} })
                    mapped++
                }
            }
        }

        if (typeof ui !== 'undefined') ui.renderCategoryMappings()
        app.showNotification(`AI 카테고리 매핑 완료: ${mapped}개 신규 추가`, 'success')
    }

    async _deleteSiteCatTree(siteName) {
        const ok = await this.showConfirm(
            `'${siteName}' 카테고리 트리를 삭제하시겠습니까?\n(수집 상품에서 재수집하지 않으면 복구되지 않습니다)`,
            { title: '사이트 카테고리 삭제', confirmText: '삭제', danger: true }
        )
        if (!ok) return
        await categoryManager.deleteSiteCategoryTree(siteName)
        delete this._catData[siteName]
        // 선택 중인 사이트가 삭제된 경우 선택 초기화
        if (this.catState.site === siteName) {
            this.catState = { site: null, cat1: null, cat2: null, cat3: null, cat4: null }
        }
        this._renderCatCols()
    }

    _catClickCat1(idx) {
        const { site } = this.catState
        if (!site) return
        const list = this._catData[site]?.cat1 || []
        this.catState = { ...this.catState, cat1: list[idx], cat2: null, cat3: null, cat4: null }
        this._renderCatCols()
    }

    _catClickCat2(idx) {
        const { site, cat1 } = this.catState
        if (!site || !cat1) return
        const list = this._catData[site]?.cat2?.[cat1] || []
        this.catState = { ...this.catState, cat2: list[idx], cat3: null, cat4: null }
        this._renderCatCols()
    }

    _catClickCat3(idx) {
        const { site, cat1, cat2 } = this.catState
        if (!site || !cat1 || !cat2) return
        const list = this._catData[site]?.cat3?.[`${cat1}|${cat2}`] || []
        this.catState = { ...this.catState, cat3: list[idx], cat4: null }
        this._renderCatCols()
    }

    _catClickCat4(idx) {
        const { site, cat1, cat2, cat3 } = this.catState
        if (!site || !cat1 || !cat2 || !cat3) return
        const list = this._catData[site]?.cat4?.[`${cat1}|${cat2}|${cat3}`] || []
        this.catState = { ...this.catState, cat4: list[idx] }
        this._renderCatCols()
    }

    // ==================== 카테고리 매핑 목록 ====================

    /**
     * 카테고리 매핑 저장 목록 렌더링 (cat-list-tbody)
     */
    renderCategoryMappings() {
        const tbody = document.getElementById('cat-list-tbody')
        if (!tbody) return

        if (typeof categoryManager === 'undefined' || !categoryManager.mappings || categoryManager.mappings.length === 0) {
            tbody.innerHTML = `<tr><td colspan="10" style="padding:2rem; text-align:center; color:#666;">저장된 매핑이 없습니다</td></tr>`
            return
        }

        tbody.innerHTML = categoryManager.mappings.map(m => {
            // targetMappings: 마켓 카테고리 목록 (배열 또는 객체)
            const targetArr = Array.isArray(m.targetMappings)
                ? m.targetMappings
                : (m.targetMappings ? Object.values(m.targetMappings) : [])
            const targetHtml = targetArr.length > 0
                ? targetArr.map(t => `<span style="background:rgba(76,154,255,0.15); color:#4C9AFF; border:1px solid rgba(76,154,255,0.3); padding:0.1rem 0.4rem; border-radius:4px; font-size:0.75rem;">${t}</span>`).join(' ')
                : '<span style="color:#666; font-size:0.75rem;">-</span>'

            return `
                <tr style="border-bottom:1px solid #1A1A1A;">
                    <td style="width:36px; padding:0.5rem 0.75rem; text-align:center;"><input type="checkbox"></td>
                    <td style="padding:0.5rem 0.75rem; font-size:0.8125rem; color:#C5C5C5;">${m.sourceSite || '-'}</td>
                    <td style="padding:0.5rem 0.75rem; font-size:0.8125rem; color:#C5C5C5;">${m.sourceCategory || '-'}</td>
                    <td style="padding:0.5rem 0.75rem; font-size:0.8125rem; color:#888;">-</td>
                    <td style="padding:0.5rem 0.75rem; font-size:0.8125rem; color:#888;">-</td>
                    <td style="padding:0.5rem 0.75rem; font-size:0.8125rem; color:#888;">-</td>
                    <td style="padding:0.5rem 0.75rem; font-size:0.8125rem; color:#888;">-</td>
                    <td style="padding:0.5rem 0.75rem;">
                        <div style="display:flex; flex-wrap:wrap; gap:4px;">${targetHtml}</div>
                    </td>
                    <td style="padding:0.5rem 0.75rem; text-align:center; font-size:0.8125rem; color:#FF8C00; font-weight:600;">0</td>
                    <td style="padding:0.5rem 0.75rem; text-align:center;">
                        <button onclick="categoryManager.deleteMapping('${m.id}').then(()=>ui.renderCategoryMappings())" style="font-size:0.75rem; border:1px solid rgba(255,100,100,0.4); color:#FF6B6B; padding:0.2rem 0.6rem; border-radius:4px; background:transparent; cursor:pointer;">삭제</button>
                    </td>
                </tr>
            `
        }).join('')
    }

    /**
     * 계정 목록 렌더링 (설정 페이지)
     */
    renderAccountList() {
        const tbody = document.getElementById('account-list-tbody')
        if (!tbody || typeof accountManager === 'undefined') return

        const accounts = accountManager.accounts
        if (accounts.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="text-center" style="padding:2rem; color:#666;">등록된 계정이 없습니다</td></tr>`
            return
        }

        tbody.innerHTML = accounts.map(acc => {
            const market = accountManager.supportedMarkets.find(m => m.id === acc.marketType)
            return `
                <tr style="border-bottom:1px solid #2D2D2D;">
                    <td style="padding:0.625rem 0.75rem; font-size:0.8125rem; color:#E5E5E5;">${accountManager.formatAccountLabel(acc)}</td>
                    <td style="padding:0.625rem 0.75rem; font-size:0.8125rem; color:#C5C5C5;">${market ? market.name : acc.marketType}</td>
                    <td style="padding:0.625rem 0.75rem; font-size:0.8125rem; color:#888;">${acc.sellerId}</td>
                    <td style="padding:0.625rem 0.75rem; font-size:0.8125rem; color:#888;">${acc.businessName || '-'}</td>
                    <td style="padding:0.625rem 0.75rem; text-align:center;">
                        <label style="display:inline-flex; align-items:center; gap:0.5rem; cursor:pointer;">
                            <input type="checkbox" ${acc.isActive ? 'checked' : ''} onchange="ui.toggleAccount('${acc.id}')" style="accent-color:#FF8C00;">
                            <span style="font-size:0.75rem; color:${acc.isActive ? '#51CF66' : '#888'};">${acc.isActive ? '활성' : '비활성'}</span>
                        </label>
                    </td>
                    <td style="padding:0.625rem 0.75rem; text-align:center;">
                        <button onclick="ui.deleteAccount('${acc.id}')" style="color:#FF6B6B; font-size:0.8125rem; background:transparent; border:none; cursor:pointer;">삭제</button>
                    </td>
                </tr>
            `
        }).join('')
    }

    async toggleAccount(id) {
        if (typeof accountManager === 'undefined') return
        await accountManager.toggleActive(id)
        this.renderAccountList()
        this.renderAccountCheckboxes()
        this.renderAccountDashboard()
    }

    async editAccount(id) {
        const acc = accountManager.accounts.find(a => a.id === id)
        if (!acc) return
        const newLabel = await this.showPrompt('계정 라벨을 수정하세요', { title: '계정 수정', defaultValue: acc.accountLabel || acc.sellerId })
        if (newLabel === null) return
        await accountManager.updateAccount(id, { accountLabel: newLabel.trim() })
        this.renderAccountList()
        this.renderAccountCheckboxes()
        this.renderAccountDashboard()
        app.showNotification('계정이 수정되었습니다', 'success')
    }

    async deleteAccount(id) {
        if (!await this.showConfirm('계정을 삭제하시겠습니까?', { title: '계정 삭제', danger: true })) return
        await accountManager.deleteAccount(id)
        this.renderAccountList()
        this.renderAccountCheckboxes()
        this.renderAccountDashboard()
        app.showNotification('계정이 삭제되었습니다', 'success')
    }

    async addAccount() {
        const marketType = document.getElementById('acc-market-type')?.value
        const sellerId = document.getElementById('acc-seller-id')?.value?.trim()
        const accountLabel = document.getElementById('acc-label')?.value?.trim()
        const businessName = document.getElementById('acc-business')?.value?.trim()
        const apiKey = document.getElementById('acc-api-key')?.value?.trim()
        const apiSecret = document.getElementById('acc-api-secret')?.value?.trim()

        if (!marketType || !sellerId) { app.showNotification('마켓과 판매자 ID를 입력해주세요', 'warning'); return }

        await accountManager.addAccount({ marketType, sellerId, accountLabel, businessName, apiKey, apiSecret })
        this.renderAccountList()
        this.renderAccountCheckboxes()
        this.renderAccountDashboard()

        // 폼 초기화
        ;['acc-market-type','acc-seller-id','acc-label','acc-business','acc-api-key','acc-api-secret'].forEach(id => {
            const el = document.getElementById(id)
            if (el) el.value = ''
        })
        app.showNotification('계정이 추가되었습니다', 'success')
    }

    // ==================== 정책적용 (검색필터) ====================

    /**
     * 검색필터 정책적용 테이블 렌더링
     */
    async renderSearchFilterTable() {
        const tbody = document.getElementById('apply-group-tbody')
        if (!tbody || typeof collectorManager === 'undefined') return

        // 소싱사이트 드롭박스 동적 populate
        const siteFilter = document.getElementById('apply-group-site-filter')
        if (siteFilter && siteFilter.options.length <= 1 && typeof SITE_LIST !== 'undefined') {
            SITE_LIST.forEach(site => {
                const opt = document.createElement('option')
                opt.value = site
                opt.textContent = site
                siteFilter.appendChild(opt)
            })
        }

        await collectorManager.loadFilters()
        let filters = collectorManager.filters

        // 사이트 필터
        const siteFilterVal = siteFilter ? siteFilter.value : ''
        if (siteFilterVal) filters = filters.filter(f => f.sourceSite === siteFilterVal)

        if (filters.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" class="px-6 py-8 text-center" style="color:#666;">등록된 검색그룹이 없습니다. 상품수집 후 자동으로 생성됩니다.</td></tr>`
            return
        }

        // 정렬
        const sortEl = document.getElementById('apply-group-sort')
        const sortVal = sortEl ? sortEl.value : 'lastCollectedAt_desc'
        const [sortField, sortDir] = sortVal.split('_')
        filters = [...filters].sort((a, b) => {
            const va = a[sortField] || ''
            const vb = b[sortField] || ''
            return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va)
        })

        // 정책 선택 옵션 생성 (selectedId에 따라 selected 적용)
        const makePolicyOptions = (selectedId) => typeof policyManager !== 'undefined'
            ? policyManager.policies.map(p => `<option value="${p.id}" ${p.id === selectedId ? 'selected' : ''}>${p.name}</option>`).join('')
            : ''

        const fmtDate = iso => {
            if (!iso) return '<span style="color:#555;">-</span>'
            const d = new Date(iso)
            return `<span style="font-size:0.72rem; color:#888;">${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,'0')}.${String(d.getDate()).padStart(2,'0')}<br>${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}</span>`
        }

        tbody.innerHTML = filters.map(f => `
            <tr data-filter-id="${f.id}" style="border-bottom:1px solid #2D2D2D;">
                <td style="padding:0.5rem 0.75rem; text-align:center;"><input type="checkbox" class="group-row-cb" style="accent-color:#FF8C00; cursor:pointer;"></td>
                <td style="padding:0.5rem 0.75rem;">
                    <span onclick="ui.goToProductsByFilter('${f.name}')"
                        style="font-size:0.75rem; background:rgba(255,140,0,0.1); border:1px solid rgba(255,140,0,0.3); color:#FF8C00; padding:0.125rem 0.5rem; border-radius:4px; cursor:pointer;"
                        title="${f.name} 상품 보기">${f.sourceSite}</span>
                </td>
                <td style="padding:0.5rem 0.75rem; font-size:0.8125rem; color:#E5E5E5;">
                    <input type="text" value="${f.name.replace(/"/g, '&quot;')}"
                        onkeydown="if(event.key==='Enter') this.blur()"
                        onfocus="this.style.borderColor='#FF8C00'"
                        onblur="this.style.borderColor='#3D3D3D'; ui.renameFilter('${f.id}', this.value)"
                        style="background:transparent; border:1px solid #3D3D3D; border-radius:4px; padding:0.2rem 0.45rem; font-size:0.8125rem; color:#E5E5E5; width:100%; min-width:140px; outline:none; transition:border-color 0.15s;">
                </td>
                <td style="padding:0.5rem 0.75rem; max-width:360px;">
                    <a href="${f.searchUrl}" target="_blank" rel="noopener noreferrer"
                        title="${f.searchUrl}"
                        style="color:#7EB5D0; font-size:0.75rem; font-family:monospace; text-decoration:underline; display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:320px;">
                        ${f.searchUrl.substring(0, 70)}${f.searchUrl.length > 70 ? '...' : ''}
                    </a>
                </td>
                <td style="padding:0.5rem 0.75rem;">
                    <div style="display:flex; align-items:center; gap:0.5rem;">
                        <select onchange="ui.applyPolicyToFilter('${f.id}', this.value)" style="width:150px; padding:0.3rem 0.5rem; font-size:0.8125rem; background:rgba(22,22,22,0.95); border:1px solid #353535; color:#C5C5C5; border-radius:5px;">
                            <option value="" ${!f.appliedPolicyId ? 'selected' : ''}>정책 선택</option>
                            ${makePolicyOptions(f.appliedPolicyId)}
                        </select>
                        ${f.appliedPolicyId
                            ? `<button onclick="ui.removePolicyFromFilter('${f.id}')" style="font-size:0.75rem; color:#FF6B6B; background:transparent; border:1px solid rgba(255,107,107,0.3); border-radius:4px; padding:0.15rem 0.5rem;">해제</button>`
                            : ''}
                    </div>
                </td>
                <td style="padding:0.5rem 0.75rem; text-align:center; font-size:0.8125rem; color:#C5C5C5;">
                    <span onclick="ui.goToProductsByFilter('${f.name}')"
                        style="color:#FF8C00; font-weight:600; cursor:pointer; text-decoration:underline; text-underline-offset:2px;"
                        title="${f.name} 상품 보기">${f.savedCount || 0}</span>개
                </td>
                <td style="padding:0.5rem 0.75rem; text-align:center;">
                    <input type="number" value="${f.collectCount || 0}" min="1"
                        onfocus="this.style.borderColor='#FF8C00'"
                        onblur="this.style.borderColor='#3D3D3D'"
                        oninput="clearTimeout(this._t); this._t=setTimeout(()=>ui.updateCollectCount('${f.id}',this.value),700)"
                        style="background:transparent; border:1px solid #3D3D3D; border-radius:4px; padding:0.2rem 0.45rem; font-size:0.8125rem; color:#4C9AFF; font-weight:600; width:72px; outline:none; text-align:center; transition:border-color 0.15s;">
                </td>
                <td style="padding:0.5rem 0.75rem; text-align:center;">${fmtDate(f.createdAt)}</td>
                <td style="padding:0.5rem 0.75rem; text-align:center;">${fmtDate(f.lastCollectedAt)}</td>
            </tr>
        `).join('')
    }

    /**
     * 검색그룹의 상품을 상품관리 페이지에서 바로 조회
     */
    goToProductsByFilter(filterName) {
        const typeEl = document.getElementById('product-search-type')
        const searchEl = document.getElementById('product-search')
        if (typeEl) typeEl.value = 'filter'
        if (searchEl) searchEl.value = filterName
        app.navigateTo('products')
        setTimeout(() => this.renderProducts(), 80)
    }

    async applyPolicyToFilter(filterId, policyId) {
        if (!policyId) return
        await collectorManager.updateFilter(filterId, { appliedPolicyId: policyId })

        // 해당 필터에 속한 상품들에도 정책 일괄 적용
        try {
            const filterProducts = await storage.getByIndex('collectedProducts', 'searchFilterId', filterId)
            if (filterProducts && filterProducts.length > 0 && typeof policyManager !== 'undefined') {
                await policyManager.applyPolicyToProducts(policyId, filterProducts.map(p => p.id))
            }
        } catch (e) {
            console.warn('필터 상품 정책 일괄 적용 실패:', e)
        }

        app.showNotification('정책이 적용되었습니다', 'success')
        await this.renderSearchFilterTable()
    }

    async removePolicyFromFilter(filterId) {
        await collectorManager.updateFilter(filterId, { appliedPolicyId: null })
        app.showNotification('정책이 해제되었습니다', 'info')
        await this.renderSearchFilterTable()
    }

    // 개별 상품 정책 변경 (그룹 정책보다 우선 적용)
    async changeProductPolicy(productId, policyId, isCollected) {
        const storeName = isCollected ? 'collectedProducts' : 'products'
        const product = await storage.get(storeName, productId)
        if (!product) return
        const updated = { ...product, appliedPolicyId: policyId || null, updatedAt: new Date().toISOString() }
        await storage.save(storeName, updated)
        if (!isCollected) {
            const idx = productManager.products.findIndex(p => p.id === productId)
            if (idx !== -1) productManager.products[idx] = updated
        }
        app.showNotification(policyId ? '개별 정책이 적용되었습니다' : '그룹 정책으로 초기화되었습니다', 'success')
        await this.renderProducts()
    }

    // 마켓정책 탭 선택 (active 클래스 토글)
    selectMarketTab(btn) {
        const container = btn.closest('#market-policy-tabs')
        if (!container) return
        container.querySelectorAll('.market-tab').forEach(b => b.classList.remove('active'))
        btn.classList.add('active')
    }

    // 요청상품수 자동저장
    async updateCollectCount(filterId, value) {
        const count = parseInt(value)
        if (isNaN(count) || count < 1) return
        const filter = collectorManager.filters.find(f => f.id === filterId)
        if (!filter || filter.collectCount === count) return
        await collectorManager.updateFilter(filterId, { collectCount: count })
        app.showNotification('요청상품수가 저장되었습니다', 'success')
    }

    // 그룹이름 자동저장
    async renameFilter(filterId, newName) {
        const trimmed = newName.trim()
        if (!trimmed) return
        const filter = collectorManager.filters.find(f => f.id === filterId)
        if (!filter || filter.name === trimmed) return
        await collectorManager.updateFilter(filterId, { name: trimmed })
        app.showNotification('그룹이름이 저장되었습니다', 'success')
    }

    // ==================== 전송 관리 ====================

    /**
     * 전송 페이지 렌더링
     */
    async renderShipmentPage() {
        const tbody = document.getElementById('shipment-tbody')
        if (!tbody) return

        // 저장된 상품 로드 (최대 50개)
        let products = []
        try {
            if (typeof storage !== 'undefined') {
                const all = await storage.getAll('collectedProducts')
                products = all.slice(0, 100)
            }
        } catch(e) {}

        if (products.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" class="px-6 py-8 text-center" style="color:#666;">상품수집 후 상품을 저장하면 여기에 표시됩니다</td></tr>`
            return
        }

        tbody.innerHTML = products.map((p, i) => {
            const accounts = p.registeredAccounts || []

            // 등록마켓: "마켓명(최신 전송일자)" 형식
            const registeredMarketsHtml = accounts.length > 0
                ? accounts.map(acc => {
                    const dateStr = acc.lastSentAt ? acc.lastSentAt.slice(0, 10) : '-'
                    return `<span style="display:inline-block; background:rgba(255,140,0,0.1); color:#FFB84D; font-size:0.68rem; padding:1px 5px; border-radius:3px; border:1px solid rgba(255,140,0,0.2); white-space:nowrap;">${acc.marketName || acc.accountId || '마켓'}(${dateStr})</span>`
                }).join(' ')
                : `<span style="color:#444; font-size:0.75rem;">미등록</span>`

            // 전송 이력에서 최신 전송 찾기
            const productShipments = typeof shipmentManager !== 'undefined'
                ? shipmentManager.shipments.filter(s => s.productId === p.id)
                : []
            const lastShipment = productShipments.slice(-1)[0] || null
            const updateDateStr = lastShipment?.completedAt
                ? lastShipment.completedAt.slice(0, 16).replace('T', ' ')
                : (lastShipment?.createdAt ? lastShipment.createdAt.slice(0, 16).replace('T', ' ') : null)

            // 최근 데이터 수집일 (상품의 collectedAt 또는 updatedAt)
            const collectedDate = p.collectedAt || p.updatedAt || p.createdAt || null
            const collectedDateStr = collectedDate
                ? new Date(collectedDate).toLocaleString('ko-KR', { year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12: false })
                : '-'

            let statusCell
            if (lastShipment && typeof shipmentManager !== 'undefined') {
                // 전송 이력이 있는 경우: 전송 상태 + 업데이트일
                const statusLabel = shipmentManager.getStatusLabel(lastShipment.status)
                const statusStyle = shipmentManager.getStatusStyle(lastShipment.status)
                statusCell = `
                    <div style="display:flex; flex-direction:column; align-items:center; gap:2px;">
                        <span style="${statusStyle}; padding:0.15rem 0.5rem; border-radius:4px; font-size:0.75rem;">${statusLabel}</span>
                        ${updateDateStr ? `<span style="font-size:0.68rem; color:#666;">${updateDateStr}</span>` : ''}
                    </div>`
            } else {
                // 전송 이력 없음: 최근 수집일 표시
                statusCell = `
                    <div style="display:flex; flex-direction:column; align-items:center; gap:2px;">
                        <span style="font-size:0.72rem; color:#666;">${collectedDateStr}</span>
                    </div>`
            }

            return `
                <tr style="border-bottom:1px solid #1A1A1A;">
                    <td style="padding:0.625rem 0.75rem; text-align:center;">
                        <input type="checkbox" class="shipment-product-cb" value="${p.id}">
                    </td>
                    <td style="padding:0.625rem 0.75rem; font-size:0.75rem; color:#888; font-family:monospace;">${i + 1}</td>
                    <td style="padding:0.625rem 0.75rem;">
                        <span style="font-size:0.75rem; color:#FF8C00; font-weight:600;">${p.sourceSite || '-'}</span>
                    </td>
                    <td style="padding:0.625rem 0.75rem;">
                        <p style="font-size:0.8125rem; color:#E5E5E5; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:300px;">${p.name}</p>
                        <p style="font-size:0.7rem; color:#666;">${p.brand || ''}</p>
                    </td>
                    <td style="padding:0.625rem 0.75rem; display:flex; flex-wrap:wrap; gap:3px; align-items:center;">${registeredMarketsHtml}</td>
                    <td style="padding:0.625rem 0.75rem; text-align:center;">${statusCell}</td>
                </tr>
            `
        }).join('')
    }

    async startShipment() {
        const selectedProducts = [...document.querySelectorAll('.shipment-product-cb:checked')].map(cb => cb.value)
        const selectedAccounts = [...document.querySelectorAll('.shipment-account-cb:checked')].map(cb => cb.value)

        // 업데이트 항목
        const updateItems = [...document.querySelectorAll('.shipment-update-cb:checked')].map(cb => cb.value)

        if (selectedProducts.length === 0) { app.showNotification('전송할 상품을 선택해주세요', 'warning'); return }
        if (selectedAccounts.length === 0) { app.showNotification('전송할 마켓 계정을 선택해주세요', 'warning'); return }

        const progressEl = document.getElementById('shipment-progress')
        if (progressEl) progressEl.style.display = 'block'

        app.showLoading(true)
        try {
            let processed = 0
            await shipmentManager.startUpdate(
                selectedProducts,
                updateItems.length > 0 ? updateItems : ['price', 'stock'],
                selectedAccounts,
                (done, total, pid) => {
                    processed = done
                    const pct = Math.round(done / total * 100)
                    const bar = document.getElementById('shipment-progress-bar')
                    const txt = document.getElementById('shipment-progress-text')
                    if (bar) bar.style.width = pct + '%'
                    if (txt) txt.textContent = `${done} / ${total} 처리 중...`
                }
            )
            app.showNotification(`${processed}개 상품 전송 완료`, 'success')
            await this.renderShipmentPage()
        } catch (err) {
            app.showNotification('전송 오류: ' + err.message, 'error')
        }
        app.showLoading(false)
        if (progressEl) progressEl.style.display = 'none'
    }

    /**
     * 선택된 상품을 상품전송 목록(collectedProducts)에서 삭제
     */
    async deleteFromShipment() {
        const selected = [...document.querySelectorAll('.shipment-product-cb:checked')]
        if (selected.length === 0) { app.showNotification('삭제할 상품을 선택해주세요', 'warning'); return }
        if (!await this.showConfirm(`선택된 ${selected.length}개 상품을 삭제하시겠습니까?`, { title: '전송상품 삭제', danger: true })) return

        let count = 0
        for (const cb of selected) {
            try {
                await storage.delete('collectedProducts', cb.value)
                count++
            } catch(e) { console.error('삭제 오류:', cb.value, e) }
        }

        if (count > 0) app.showNotification(`${count}개 상품이 삭제되었습니다`, 'success')
        await this.renderShipmentPage()
    }

    // ==================== 금지어/삭제어 ====================

    // 금지어/삭제어 그룹 드롭박스 렌더링
    renderForbiddenWords() {
        if (typeof forbiddenManager === 'undefined') return
        this._renderGroupSelect('forbidden')
        this._renderGroupSelect('deletion')
    }

    _renderGroupSelect(type) {
        const sel = document.getElementById(`${type}-group-select`)
        if (!sel) return
        const current = sel.value
        const groups = forbiddenManager.getGroups(type)
        sel.innerHTML = `<option value="">그룹 선택</option>` +
            groups.map(g => `<option value="${g.id}" ${!g.isActive ? 'style="color:#666;"' : ''}>${g.name}${g.isActive ? '' : ' (비활성)'}</option>`).join('')
        if (current) sel.value = current
    }

    // 그룹 선택 변경 시 — input에 그룹명 채우기
    onForbiddenGroupChange(type) {
        const sel = document.getElementById(`${type}-group-select`)
        const id = sel?.value
        const nameInput = document.getElementById(`${type}-group-name`)
        const textarea = document.getElementById(`${type}-words-textarea`)

        if (!id) {
            if (nameInput) { nameInput.value = ''; nameInput.placeholder = '그룹 이름 입력 후 저장 → 새 그룹 생성' }
            if (textarea) textarea.value = ''
            this.updateForbiddenWordCount(type)
            return
        }
        const group = forbiddenManager.groups.find(g => g.id === id)
        if (!group) return
        if (nameInput) nameInput.value = group.name
        if (textarea) textarea.value = group.wordsText
        this.updateForbiddenWordCount(type)
    }

    // 단어 수 실시간 업데이트
    updateForbiddenWordCount(type) {
        const textarea = document.getElementById(`${type}-words-textarea`)
        const countEl = document.getElementById(`${type}-word-count`)
        if (!countEl) return
        const count = textarea?.value ? textarea.value.split(';').map(w => w.trim()).filter(Boolean).length : 0
        const label = type === 'forbidden' ? '금지어' : '삭제어'
        countEl.textContent = `( ${label} ${count}개 )`
    }

    // 그룹 저장 — 선택된 그룹 없으면 새 그룹 생성, 있으면 업데이트
    async saveForbiddenGroup(type) {
        const sel = document.getElementById(`${type}-group-select`)
        const nameInput = document.getElementById(`${type}-group-name`)
        const name = nameInput?.value?.trim()
        const wordsText = document.getElementById(`${type}-words-textarea`)?.value || ''

        if (!name) { app.showNotification('그룹 이름을 입력해주세요', 'warning'); nameInput?.focus(); return }

        const existingId = sel?.value
        if (existingId) {
            // 기존 그룹 수정 (이름 변경 포함)
            const g = forbiddenManager.groups.find(g => g.id === existingId)
            if (g) g.name = name
            await forbiddenManager.updateGroup(existingId, wordsText, true)
            this._renderGroupSelect(type)
            sel.value = existingId
        } else {
            // 새 그룹 생성
            const group = await forbiddenManager.addGroup(name, type)
            group.wordsText = wordsText
            await forbiddenManager.saveGroups()
            this._renderGroupSelect(type)
            if (sel) sel.value = group.id
        }
        this.updateForbiddenWordCount(type)
        app.showNotification('저장되었습니다', 'success')
    }

    // 그룹 삭제
    async deleteForbiddenGroup(type) {
        const sel = document.getElementById(`${type}-group-select`)
        const id = sel?.value
        if (!id) { app.showNotification('삭제할 그룹을 선택해주세요', 'warning'); return }
        const group = forbiddenManager.groups.find(g => g.id === id)
        if (!await this.showConfirm(`"${group?.name}" 그룹을 삭제하시겠습니까?`, { title: '금지어 그룹 삭제', danger: true })) return
        await forbiddenManager.deleteGroup(id)
        this._renderGroupSelect(type)
        this.onForbiddenGroupChange(type)
        app.showNotification('그룹이 삭제되었습니다', 'success')
    }

    // Claude API 설정 저장
    saveClaudeApiSettings() {
        const key = document.getElementById('claude-api-key')?.value?.trim()
        const model = document.getElementById('claude-model')?.value
        const status = document.getElementById('claude-api-status')

        if (!key) { app.showNotification('API Key를 입력해주세요', 'warning'); return }

        // storage에 저장 (settings 스토어)
        storage.save('settings', { key: 'claude', apiKey: key, model, updatedAt: new Date().toISOString() })
            .then(() => {
                if (status) status.innerHTML = `<span style="color:#51CF66;">✓ 저장 완료 (${new Date().toLocaleTimeString('ko-KR', { hour12: false })})</span>`
                app.showNotification('Claude API 설정이 저장되었습니다', 'success')
            })
            .catch(() => app.showNotification('저장에 실패했습니다', 'error'))
    }

    // Claude API 연결 테스트
    async testClaudeApi() {
        const key = document.getElementById('claude-api-key')?.value?.trim()
        const status = document.getElementById('claude-api-status')
        if (!key) { app.showNotification('API Key를 먼저 입력해주세요', 'warning'); return }
        if (!key.startsWith('sk-ant-')) {
            if (status) status.innerHTML = `<span style="color:#FF6B6B;">✗ 유효하지 않은 API Key 형식입니다 (sk-ant- 로 시작해야 합니다)</span>`
            return
        }
        if (status) status.innerHTML = `<span style="color:#888;">연결 테스트 중...</span>`
        // 실제 API 호출은 CORS 문제로 서버 없이 불가 → 형식 검증만 수행
        setTimeout(() => {
            if (status) status.innerHTML = `<span style="color:#FFB84D;">⚠ API Key 형식은 유효합니다. 실제 연결 확인은 저장 후 AI 기능 사용 시 확인됩니다.</span>`
        }, 800)
    }

    closeAllModals() {
        document.getElementById('product-modal')?.classList.add('hidden')
        document.getElementById('channel-modal')?.classList.add('hidden')
        document.getElementById('order-modal')?.classList.add('hidden')
        document.getElementById('sourcing-modal')?.classList.add('hidden')
    }

    formatNumber(num) {
        return new Intl.NumberFormat('ko-KR').format(num)
    }

    // ==================== SMS 전송 모달 ====================

    showSmsModal(orderId) {
        const order = orderManager.orders.find(o => o.id === orderId)
        const modal = document.getElementById('sms-modal')
        if (!modal) return

        // 주문 정보로 자동 채우기
        if (order) {
            const toPhone = document.getElementById('sms-to-phone')
            if (toPhone) toPhone.value = order.recipientPhone || order.customerPhone || ''
        }

        // 발신번호 복원 (저장된 설정)
        storage.getAll('settings').then(rows => {
            const cfg = rows.find(r => r.id === 'smsSettings')
            if (cfg) {
                const fromEl = document.getElementById('sms-from-phone')
                if (fromEl && cfg.fromPhone) fromEl.value = cfg.fromPhone
            }
        })

        // 바이트 초기화
        this.updateSmsBytes()
        modal.dataset.orderId = orderId || ''
        modal.style.display = 'flex'
    }

    closeSmsModal() {
        const modal = document.getElementById('sms-modal')
        if (modal) modal.style.display = 'none'
    }

    updateSmsBytes() {
        const ta = document.getElementById('sms-message-body')
        const countEl = document.getElementById('sms-byte-count')
        const limitEl = document.getElementById('sms-byte-limit')
        const typeEl = document.getElementById('sms-type')
        if (!ta || !countEl) return

        // 한글 2바이트, 영문/숫자 1바이트
        let bytes = 0
        for (const ch of ta.value) {
            bytes += ch.charCodeAt(0) > 127 ? 2 : 1
        }
        countEl.textContent = bytes

        const isLms = bytes > 90
        if (limitEl) limitEl.textContent = isLms ? '2000' : '90'
        if (typeEl) {
            typeEl.textContent = isLms ? 'LMS' : 'SMS'
            typeEl.style.color = isLms ? '#FFB84D' : '#888'
        }
        if (countEl) countEl.style.color = bytes > (isLms ? 2000 : 90) ? '#FF6B6B' : '#E5E5E5'
    }

    insertSmsVar(variable) {
        const ta = document.getElementById('sms-message-body')
        if (!ta) return
        const start = ta.selectionStart
        const end = ta.selectionEnd
        ta.value = ta.value.substring(0, start) + variable + ta.value.substring(end)
        const pos = start + variable.length
        ta.setSelectionRange(pos, pos)
        ta.focus()
        this.updateSmsBytes()
    }

    clearSmsMessage() {
        const ta = document.getElementById('sms-message-body')
        if (ta) ta.value = ''
        this.updateSmsBytes()
    }

    // 템플릿 카드 "발송 메시지 선택" 클릭
    selectSmsTemplate(btn) {
        const card = btn.closest('.sms-tpl-card')
        if (!card) return
        const content = card.querySelector('.sms-tpl-content')?.textContent || ''
        const ta = document.getElementById('sms-message-body')
        if (ta) ta.value = content
        this.updateSmsBytes()

        // 선택 시각 피드백
        document.querySelectorAll('.sms-tpl-card').forEach(c => c.style.borderColor = '#2D2D2D')
        card.style.borderColor = '#FF8C00'
    }

    sendSms() {
        const to = document.getElementById('sms-to-phone')?.value?.trim()
        const from = document.getElementById('sms-from-phone')?.value?.trim()
        const body = document.getElementById('sms-message-body')?.value?.trim()
        if (!to || !body) {
            app.showNotification('받는분 전화번호와 메시지를 입력해주세요', 'warning')
            return
        }

        // 발신번호 저장
        if (from) {
            storage.save('settings', { key: 'smsSettings', fromPhone: from })
        }

        // 발송 완료 처리
        const modal = document.getElementById('sms-modal')
        const orderId = modal?.dataset.orderId
        if (orderId) {
            this.smsSentOrders.add(orderId)
            // 주문 행의 버튼 즉시 업데이트
            const btn = document.getElementById(`sms-btn-${orderId}`)
            if (btn) {
                btn.textContent = '메시지 발송후'
                btn.style.background = '#0D1E14'
                btn.style.border = '1px solid #1B5C38'
                btn.style.color = '#4CAF8A'
            }
        }
        app.showNotification(`${to} 로 SMS 발송 완료 (시뮬레이션)`, 'success')
        this.closeSmsModal()
    }

    toggleSmsTemplateEditMode() {
        const grid = document.getElementById('sms-template-grid')
        const btn = document.getElementById('sms-tpl-edit-btn')
        if (!grid) return
        const isEdit = grid.dataset.editMode === 'true'
        grid.dataset.editMode = isEdit ? 'false' : 'true'
        btn.textContent = isEdit ? '템플릿 수정모드' : '수정모드 종료'
        btn.style.color = isEdit ? '#888' : '#FF8C00'
        btn.style.borderColor = isEdit ? '#3D3D3D' : 'rgba(255,140,0,0.4)'

        // 수정모드일 때 각 카드에 삭제 버튼 표시
        grid.querySelectorAll('.sms-tpl-card').forEach(card => {
            let delBtn = card.querySelector('.sms-tpl-del')
            if (!isEdit) {
                if (!delBtn) {
                    delBtn = document.createElement('button')
                    delBtn.className = 'sms-tpl-del'
                    delBtn.textContent = '삭제'
                    delBtn.style.cssText = 'padding:1px 6px; font-size:0.7rem; background:transparent; border:1px solid rgba(255,107,107,0.3); color:#FF6B6B; border-radius:4px; cursor:pointer; margin-top:2px;'
                    delBtn.onclick = () => card.remove()
                    card.appendChild(delBtn)
                }
                // 이름/내용 편집 가능
                const nameEl = card.querySelector('.sms-tpl-name')
                const contentEl = card.querySelector('.sms-tpl-content')
                if (nameEl) nameEl.contentEditable = 'true'
                if (contentEl) contentEl.contentEditable = 'true'
            } else {
                if (delBtn) delBtn.remove()
                const nameEl = card.querySelector('.sms-tpl-name')
                const contentEl = card.querySelector('.sms-tpl-content')
                if (nameEl) nameEl.contentEditable = 'false'
                if (contentEl) contentEl.contentEditable = 'false'
            }
        })
    }

    addSmsTemplate() {
        const grid = document.getElementById('sms-template-grid')
        if (!grid) return
        const addCard = grid.querySelector('.sms-tpl-card:last-child')
        const newCard = document.createElement('div')
        newCard.className = 'sms-tpl-card'
        newCard.style.cssText = 'background:#1A1A1A; border:1px solid #2D2D2D; border-radius:8px; padding:0.7rem; display:flex; flex-direction:column; gap:5px;'
        newCard.innerHTML = `
            <div class="sms-tpl-name" contenteditable="true" style="font-size:0.8rem; font-weight:600; color:#E5E5E5; outline:none; border-bottom:1px dashed #3D3D3D; padding-bottom:2px;" placeholder="템플릿 이름">새 템플릿</div>
            <div class="sms-tpl-content" contenteditable="true" style="font-size:0.72rem; color:#666; line-height:1.45; flex:1; outline:none;" placeholder="내용 입력">내용을 입력하세요.</div>
            <button onclick="ui.selectSmsTemplate(this)" style="padding:2px 0; font-size:0.72rem; background:rgba(255,140,0,0.12); border:1px solid rgba(255,140,0,0.3); color:#FF8C00; border-radius:4px; cursor:pointer; margin-top:2px;">발송 메시지 선택</button>`
        grid.insertBefore(newCard, addCard)
    }

    // ==================== 이미지 편집 모달 ====================

    /**
     * 이미지 편집 모달 열기
     */
    async openImageEditor(productId) {
        let product = await storage.get('products', productId)
        const storeKey = product ? 'products' : 'collectedProducts'
        if (!product) product = await storage.get('collectedProducts', productId)
        if (!product) { app.showNotification('상품을 찾을 수 없습니다', 'error'); return }

        const images = product.images || []
        const detailImages = product.detailImages || []
        this._imageEditorProductId = productId
        this._imageEditorStoreKey = storeKey

        // 탭: 대표이미지변경, 상품이미지, 상세페이지이미지
        const modal = document.createElement('div')
        modal.id = 'image-editor-modal'
        modal.style.cssText = 'position:fixed; inset:0; z-index:9999; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,0.7);'
        modal.onclick = (e) => { if (e.target === modal) modal.remove() }

        const thumbSrc = images[0] || ''
        const productImgs = images.slice(1)

        modal.innerHTML = `
        <div style="background:#1A1A1A; border:1px solid #333; border-radius:12px; width:780px; max-height:85vh; overflow-y:auto; box-shadow:0 20px 60px rgba(0,0,0,0.5);">
            <!-- 헤더 -->
            <div style="display:flex; align-items:center; justify-content:space-between; padding:16px 20px; border-bottom:1px solid #2D2D2D;">
                <span style="font-size:1rem; font-weight:600; color:#E5E5E5;">상품 이미지 관리</span>
                <div style="display:flex; gap:4px;">
                    <button id="img-tab-thumb" onclick="ui._switchImageTab('thumb')" style="padding:5px 14px; font-size:0.78rem; background:#FF8C00; color:#fff; border:none; border-radius:5px; cursor:pointer;">대표이미지</button>
                    <button id="img-tab-product" onclick="ui._switchImageTab('product')" style="padding:5px 14px; font-size:0.78rem; background:#2D2D2D; color:#999; border:none; border-radius:5px; cursor:pointer;">상품이미지 (${productImgs.length})</button>
                    <button id="img-tab-detail" onclick="ui._switchImageTab('detail')" style="padding:5px 14px; font-size:0.78rem; background:#2D2D2D; color:#999; border:none; border-radius:5px; cursor:pointer;">상세페이지 (${detailImages.length})</button>
                    <button onclick="this.closest('#image-editor-modal').remove()" style="margin-left:8px; padding:5px 10px; font-size:0.85rem; background:transparent; color:#888; border:1px solid #333; border-radius:5px; cursor:pointer;">✕</button>
                </div>
            </div>

            <!-- 대표이미지 탭 -->
            <div id="img-panel-thumb" style="padding:20px;">
                <p style="font-size:0.78rem; color:#888; margin-bottom:16px; line-height:1.5;">
                    ※ 대표이미지를 변경하시면 쿠팡을 제외한 모든 마켓의 대표이미지가 변경됩니다.<br>
                    ※ 동일한 이미지 URL은 한번만 변경하시면 동일한 이미지 URL에 동시에 적용됩니다.
                </p>
                <div style="display:flex; gap:20px; align-items:flex-start;">
                    <div>
                        <p style="font-size:0.78rem; color:#888; margin-bottom:8px;">[상품 대표이미지]</p>
                        <div style="width:240px; height:240px; border:1px solid #2D2D2D; border-radius:8px; overflow:hidden; background:#111; display:flex; align-items:center; justify-content:center;">
                            ${thumbSrc
                                ? `<img id="img-editor-thumb-preview" src="${thumbSrc}" style="max-width:100%; max-height:100%; object-fit:contain;">`
                                : '<span style="color:#444; font-size:0.85rem;">이미지 없음</span>'}
                        </div>
                        <p style="font-size:0.7rem; color:#555; margin-top:6px; word-break:break-all; max-width:240px;">${thumbSrc || '(URL 없음)'}</p>
                    </div>
                    <div style="display:flex; align-items:center; padding-top:100px;">
                        <span style="color:#444; font-size:1.2rem;">→</span>
                    </div>
                    <div style="flex:1;">
                        <p style="font-size:0.78rem; color:#888; margin-bottom:8px;">[변경할 이미지]</p>
                        <div id="img-editor-thumb-new" style="width:240px; height:240px; border:1px solid #2D2D2D; border-radius:8px; overflow:hidden; background:#111; display:flex; align-items:center; justify-content:center;">
                            <span style="color:#444; font-size:0.85rem;">No image</span>
                        </div>
                        <div style="margin-top:10px; display:flex; gap:6px; flex-wrap:wrap;">
                            <input id="img-editor-thumb-url" type="text" placeholder="http:// 를 포함한 이미지 경로를 입력해주세요"
                                style="flex:1; min-width:200px; padding:6px 10px; font-size:0.8rem; background:#111; border:1px solid #333; color:#C5C5C5; border-radius:5px; outline:none;">
                            <button onclick="ui._applyThumbUrl()" style="padding:6px 14px; font-size:0.78rem; background:#FF8C00; color:#fff; border:none; border-radius:5px; cursor:pointer;">변경완료</button>
                        </div>
                        <div style="margin-top:8px; display:flex; gap:6px;">
                            <button onclick="ui._selectImageFromList('thumb')" style="padding:5px 12px; font-size:0.75rem; background:#2D2D2D; color:#C5C5C5; border:none; border-radius:4px; cursor:pointer;">이미지 선택변경</button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- 상품이미지 탭 -->
            <div id="img-panel-product" style="padding:20px; display:none;">
                <p style="font-size:0.78rem; color:#888; margin-bottom:12px;">※ 상품 이미지 목록입니다. 드래그하여 순서를 변경하거나, URL을 직접 수정할 수 있습니다. (최대 9장)</p>
                <div id="img-editor-product-list" style="display:flex; flex-wrap:wrap; gap:10px;">
                    ${images.map((img, i) => `
                        <div style="position:relative; width:120px;">
                            <div style="width:120px; height:120px; border:1px solid ${i === 0 ? '#FF8C00' : '#2D2D2D'}; border-radius:6px; overflow:hidden; background:#111;">
                                <img src="${img}" style="width:100%; height:100%; object-fit:cover;" onerror="this.style.display='none'">
                            </div>
                            ${i === 0 ? '<span style="position:absolute; top:4px; left:4px; background:#FF8C00; color:#fff; font-size:0.65rem; padding:1px 6px; border-radius:3px;">대표</span>' : ''}
                            <div style="display:flex; gap:2px; margin-top:4px;">
                                <input type="text" value="${img}" data-img-idx="${i}" class="img-url-input"
                                    style="flex:1; padding:2px 4px; font-size:0.65rem; background:#111; border:1px solid #333; color:#999; border-radius:3px; outline:none; min-width:0;">
                                ${i > 0 ? `<button onclick="ui._removeProductImage(${i})" style="padding:2px 6px; font-size:0.65rem; background:transparent; color:#FF6B6B; border:1px solid rgba(255,107,107,0.3); border-radius:3px; cursor:pointer;">✕</button>` : ''}
                            </div>
                        </div>
                    `).join('')}
                    ${images.length < 9 ? `
                    <div onclick="ui._addProductImage()" style="width:120px; height:120px; border:2px dashed #333; border-radius:6px; display:flex; align-items:center; justify-content:center; cursor:pointer; flex-direction:column; gap:4px;">
                        <span style="color:#555; font-size:1.5rem;">+</span>
                        <span style="color:#555; font-size:0.7rem;">이미지 추가</span>
                    </div>` : ''}
                </div>
                <div style="margin-top:12px; text-align:right;">
                    <button onclick="ui._saveProductImages()" style="padding:6px 20px; font-size:0.8rem; background:linear-gradient(135deg,#FF8C00,#FFB84D); color:#fff; border:none; border-radius:6px; cursor:pointer;">이미지 저장</button>
                </div>
            </div>

            <!-- 상세페이지이미지 탭 -->
            <div id="img-panel-detail" style="padding:20px; display:none;">
                <p style="font-size:0.78rem; color:#888; margin-bottom:12px;">※ 수집된 상세페이지 이미지입니다. 마켓 상세페이지에 사용됩니다.</p>
                ${detailImages.length > 0 ? `
                <div style="display:flex; flex-wrap:wrap; gap:8px; max-height:400px; overflow-y:auto;">
                    ${detailImages.map((img, i) => `
                        <div style="position:relative;">
                            <img src="${img}" style="width:100px; height:100px; object-fit:cover; border:1px solid #2D2D2D; border-radius:4px;" onerror="this.style.display='none'">
                            <span style="position:absolute; top:2px; left:2px; background:rgba(0,0,0,0.6); color:#999; font-size:0.6rem; padding:1px 4px; border-radius:2px;">${i + 1}</span>
                        </div>
                    `).join('')}
                </div>
                <p style="margin-top:10px; font-size:0.75rem; color:#666;">총 ${detailImages.length}장</p>
                ` : '<p style="color:#555; font-size:0.85rem; padding:40px 0; text-align:center;">수집된 상세페이지 이미지가 없습니다.<br><span style="font-size:0.75rem; color:#444;">수집 시 "상세페이지 이미지 수집" 체크박스를 활성화해주세요.</span></p>'}
            </div>
        </div>`

        document.body.appendChild(modal)
    }

    _switchImageTab(tab) {
        const tabs = ['thumb', 'product', 'detail']
        tabs.forEach(t => {
            const panel = document.getElementById(`img-panel-${t}`)
            const btn = document.getElementById(`img-tab-${t}`)
            if (panel) panel.style.display = t === tab ? 'block' : 'none'
            if (btn) {
                btn.style.background = t === tab ? '#FF8C00' : '#2D2D2D'
                btn.style.color = t === tab ? '#fff' : '#999'
            }
        })
    }

    async _applyThumbUrl() {
        const input = document.getElementById('img-editor-thumb-url')
        const url = input?.value?.trim()
        if (!url) { app.showNotification('이미지 URL을 입력해주세요', 'warning'); return }

        // 미리보기 업데이트
        const previewDiv = document.getElementById('img-editor-thumb-new')
        if (previewDiv) previewDiv.innerHTML = `<img src="${url}" style="max-width:100%; max-height:100%; object-fit:contain;" onerror="this.outerHTML='<span style=\\'color:#FF6B6B;\\'>로드 실패</span>'">`

        // 저장
        const product = await storage.get(this._imageEditorStoreKey, this._imageEditorProductId)
        if (!product) return
        if (!product.images) product.images = []
        product.images[0] = url
        product.updatedAt = new Date().toISOString()
        await storage.save(this._imageEditorStoreKey, product)
        app.showNotification('대표이미지가 변경되었습니다', 'success')
    }

    _selectImageFromList(target) {
        const product = this._imageEditorProductId
        const modal = document.getElementById('image-editor-modal')
        if (!modal) return
        // 상품이미지 탭으로 전환하여 선택하도록 안내
        this._switchImageTab('product')
        app.showNotification('상품이미지 목록에서 대표로 사용할 이미지 URL을 복사하세요', 'info')
    }

    async _removeProductImage(idx) {
        const product = await storage.get(this._imageEditorStoreKey, this._imageEditorProductId)
        if (!product || !product.images) return
        product.images.splice(idx, 1)
        product.updatedAt = new Date().toISOString()
        await storage.save(this._imageEditorStoreKey, product)
        // 모달 새로고침
        document.getElementById('image-editor-modal')?.remove()
        this.openImageEditor(this._imageEditorProductId)
    }

    async _addProductImage() {
        const url = await this.showPrompt('추가할 이미지 URL을 입력해주세요:', { title: '이미지 추가', placeholder: 'https://...' })
        if (!url?.trim()) return
        const product = await storage.get(this._imageEditorStoreKey, this._imageEditorProductId)
        if (!product) return
        if (!product.images) product.images = []
        if (product.images.length >= 9) { app.showNotification('최대 9장까지 추가 가능합니다', 'warning'); return }
        product.images.push(url.trim())
        product.updatedAt = new Date().toISOString()
        await storage.save(this._imageEditorStoreKey, product)
        document.getElementById('image-editor-modal')?.remove()
        this.openImageEditor(this._imageEditorProductId)
    }

    async _saveProductImages() {
        const inputs = document.querySelectorAll('.img-url-input')
        const product = await storage.get(this._imageEditorStoreKey, this._imageEditorProductId)
        if (!product) return
        const newImages = []
        inputs.forEach(input => {
            const url = input.value?.trim()
            if (url) newImages.push(url)
        })
        product.images = newImages
        product.updatedAt = new Date().toISOString()
        await storage.save(this._imageEditorStoreKey, product)
        app.showNotification(`이미지 ${newImages.length}장 저장 완료`, 'success')

        // 상품 목록 UI 갱신
        if (typeof productManager !== 'undefined') {
            await productManager.loadProducts()
            this.renderProducts()
        }
    }

    /**
     * 카테고리 문자열을 계층 스타일 HTML로 변환
     * '>' 기준으로 분리, 마지막 노드는 밝게 표시
     * @param {string} catStr - 카테고리 문자열 (예: "의류 > 상의 > 티셔츠")
     * @returns {string} HTML 문자열
     */
    formatCategoryHierarchy(catStr) {
        if (!catStr || catStr === '-') return '<span style="color:#555;">-</span>'
        const parts = catStr.split(/\s*>\s*/)
        return parts.map((p, i) => {
            const color = i === 0 ? '#888' : i === parts.length - 1 ? '#E5E5E5' : '#B0B0B0'
            return `<span style="color:${color};">${p}</span>`
        }).join('<span style="color:#444; margin:0 0.25rem; font-size:0.75rem;">›</span>')
    }

    // 상품관리 1줄 로그창 업데이트
    setProductLog(msg, type = 'info') {
        const el = document.getElementById('product-log-line')
        if (!el) return
        const colors = { info: '#888', success: '#51CF66', error: '#FF6B6B', warning: '#FFB84D' }
        el.style.display = 'block'
        el.style.color = colors[type] || '#888'
        el.textContent = `[${new Date().toLocaleTimeString('ko-KR')}] ${msg}`
    }

    /**
     * 개별 상품 상세 정보 보강 (업데이트 버튼)
     * 무신사 상품의 경우 상세 페이지를 다시 수집하여 누락 필드 보강
     */
    async enrichSingleProduct(productId) {
        // 1) productManager에서 찾기 (prod_... 형식)
        let product = typeof productManager !== 'undefined'
            ? productManager.products.find(p => p.id === productId)
            : null

        // 2) 못 찾으면 collectedProducts에서 직접 조회 (col_musinsa_... 형식)
        let isCollectedOnly = false
        if (!product) {
            try {
                product = await storage.get('collectedProducts', productId)
                isCollectedOnly = !!product
            } catch {}
        }

        // 3) collectedProductId로 역추적
        if (!product && typeof productManager !== 'undefined') {
            product = productManager.products.find(p => p.collectedProductId === productId)
        }

        if (!product) {
            app.showNotification('상품을 찾을 수 없습니다', 'warning')
            return
        }

        // 무신사 상품만 실제 보강 가능
        if (product.sourceSite !== 'MUSINSA' || !product.siteProductId) {
            app.showNotification('무신사 상품만 업데이트 가능합니다', 'warning')
            return
        }

        this.setProductLog(`[${product.name?.slice(0, 20)}] 업데이트 시작...`, 'info')
        app.showNotification('상세 정보 수집 중...', 'info')

        try {
            this.setProductLog(`프록시 서버 호출 중 (goodsNo: ${product.siteProductId})...`, 'info')
            const r = await fetch(`http://localhost:3001/api/musinsa/goods/${product.siteProductId}`)
            if (!r.ok) throw new Error(`HTTP ${r.status}`)
            const d = await r.json()
            if (!d.success || !d.data) throw new Error(d.message || '상세 수집 실패')

            const detail = d.data

            // 가격/재고 이력 — 변경 여부와 무관하게 항상 스냅샷 기록
            const prevPrice = product.salePrice || product.bestBenefitPrice || 0
            const newPrice = detail.salePrice || detail.bestBenefitPrice || 0
            const priceHistory = [...(product.priceHistory || [])]

            // 옵션별 스냅샷 (최신 detail.options 기준)
            const latestOptions = (detail.options && detail.options.length > 0) ? detail.options : (product.options || [])
            const optionSnapshot = latestOptions.map(o => ({
                name: o.name || '',
                price: o.price || newPrice || 0,
                stock: o.stock ?? null,
                isSoldOut: o.isSoldOut || false,
                isBrandDelivery: o.isBrandDelivery || false
            }))

            const changeAmt = newPrice - prevPrice
            const changePct = prevPrice > 0 ? ((changeAmt / prevPrice) * 100).toFixed(1) : '0'
            priceHistory.push({
                date: new Date().toISOString(),
                price: newPrice || prevPrice,
                prevPrice,
                changeAmount: changeAmt,
                changePercent: parseFloat(changePct),
                options: optionSnapshot
            })

            if (changeAmt !== 0 && prevPrice > 0) {
                this.setProductLog(`가격 변경: ₩${this.formatNumber(prevPrice)} → ₩${this.formatNumber(newPrice)} (${changeAmt > 0 ? '+' : ''}${changePct}%)`, changeAmt > 0 ? 'warning' : 'success')
            } else {
                this.setProductLog(`가격 변동 없음 (₩${this.formatNumber(newPrice || prevPrice)}) | 옵션 ${optionSnapshot.length}개 재고 기록 완료`, 'success')
            }

            const updates = {
                category: detail.category || product.category || '',
                category1: detail.category1 || product.category1 || '',
                category2: detail.category2 || product.category2 || '',
                category3: detail.category3 || product.category3 || '',
                category4: detail.category4 || product.category4 || '',
                options: (detail.options && detail.options.length > 0) ? detail.options : product.options || [],
                origin: detail.origin || product.origin || '',
                material: detail.material || product.material || '',
                manufacturer: detail.manufacturer || product.manufacturer || '',
                season: detail.season || product.season || '',
                styleCode: detail.styleCode || product.styleCode || '',
                kcCert: detail.kcCert || product.kcCert || '',
                nameEn: detail.nameEn || product.nameEn || '',
                tags: (detail.tags && detail.tags.length > 0) ? detail.tags : product.tags || [],
                brand: detail.brand || product.brand || '',
                images: (detail.images && detail.images.length > 0) ? detail.images : product.images || [],
                detailImages: (detail.detailImages && detail.detailImages.length > 0) ? detail.detailImages : product.detailImages || [],
                detailHtml: detail.detailHtml || product.detailHtml || '',
                salePrice: detail.salePrice || product.salePrice || 0,
                bestBenefitPrice: detail.bestBenefitPrice || product.bestBenefitPrice || 0,
                originalPrice: detail.originalPrice || product.originalPrice || 0,
                couponPrice: detail.couponPrice || product.couponPrice || 0,
                discountRate: detail.discountRate ?? product.discountRate ?? 0,
                isLoggedIn: detail.isLoggedIn ?? product.isLoggedIn ?? false,
                priceHistory,
                updatedAt: new Date().toISOString()
            }

            // collectedProducts 업데이트
            if (isCollectedOnly) {
                Object.assign(product, updates)
                await storage.save('collectedProducts', product)
            }

            // products 스토어 업데이트 (bridge 상품)
            const bridgeProduct = typeof productManager !== 'undefined'
                ? productManager.products.find(p => p.collectedProductId === productId || p.id === productId)
                : null
            if (bridgeProduct) {
                Object.assign(bridgeProduct, updates)
                await storage.save('products', bridgeProduct)
            }

            // collectedProducts도 업데이트 (bridgeProduct에서 찾은 경우)
            const collectedId = bridgeProduct?.collectedProductId || productId
            if (!isCollectedOnly) {
                try {
                    const collected = await storage.get('collectedProducts', collectedId)
                    if (collected) {
                        Object.assign(collected, updates)
                        await storage.save('collectedProducts', collected)
                    }
                } catch {}
            }

            app.showNotification('상세 정보 업데이트 완료', 'success')
            await productManager.loadProducts()
            this.renderProducts()
        } catch (e) {
            this.setProductLog(`업데이트 실패: ${e.message}`, 'error')
            app.showNotification(`업데이트 실패: ${e.message}`, 'error')
        }
    }
}

// 글로벌 인스턴스
const ui = new UIManager()
