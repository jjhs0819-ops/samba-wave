/**
 * 상품 수집 엔진 (CollectorManager)
 * 11개 소싱사이트 시뮬레이션 모드 지원, 10만건 대응
 */

// 무신사 실제 수집 프록시 서버 URL
const MUSINSA_PROXY_URL = 'http://localhost:3001'

class CollectorManager {
    constructor() {
        this.proxyAvailable = false        // 프록시 서버 연결 여부
        this.realModeEnabled = true        // 실제수집 모드 활성화 여부
        this._proxyChecked = false         // 프록시 확인 완료 여부

        // 지원 소싱사이트 목록 (9개)
        this.supportedSites = [
            { id: 'abcmart', name: 'ABCmart', domain: 'a-rt.com', label: 'ABCmart' },
            { id: 'folderstyle', name: 'FOLDERStyle', domain: 'folderstyle.com', label: 'FOLDERStyle' },
            { id: 'grandstage', name: 'GrandStage', domain: 'a-rt.com/grand', label: 'GrandStage' },
            { id: 'gsshop', name: 'GSShop', domain: 'gsshop.com', label: 'GSShop' },
            { id: 'lotteon', name: 'LOTTEON', domain: 'lotteon.com', label: 'LOTTEON' },
            { id: 'musinsa', name: 'MUSINSA', domain: 'musinsa.com', label: 'MUSINSA' },
            { id: 'nike', name: 'Nike', domain: 'nike.com', label: 'Nike' },
            { id: 'oliveyoung', name: 'OliveYoung', domain: 'oliveyoung.co.kr', label: 'OliveYoung' },
            { id: 'ssg', name: 'SSG', domain: 'ssg.com', label: 'SSG' }
        ]

        this.filters = []           // SearchFilter 목록
        this.collectResults = []    // 현재 수집 결과 (임시)
        this.currentPage = 1
        this.pageSize = 50
        this.isCollecting = false
        this._lastSearchFilterId = null  // 마지막 수집에 사용된 필터 ID
    }

    /**
     * 초기화 - 저장된 필터 로드 + 프록시 서버 연결 확인
     */
    async init() {
        await this.loadFilters()
        // 프록시 서버 연결 확인 (비동기 - 실패해도 앱 동작)
        this.checkProxyServer().catch(() => {})
    }

    // ==================== 프록시 서버 / 실제 수집 ====================

    /**
     * 프록시 서버 연결 확인
     * 무신사 실제 수집을 위해 localhost:3001 프록시 서버가 필요
     */
    async checkProxyServer() {
        try {
            const res = await fetch(`${MUSINSA_PROXY_URL}/api/health`, {
                signal: AbortSignal.timeout(2000)
            })
            const data = await res.json()
            this.proxyAvailable = data.status === 'ok'
            this._proxyChecked = true
            console.log('[Collector] 프록시 서버 연결됨 - 실제 수집 모드 활성화')
        } catch {
            this.proxyAvailable = false
            this._proxyChecked = true
            console.log('[Collector] 프록시 서버 없음 - 시뮬레이션 모드')
        }
        return this.proxyAvailable
    }

    /**
     * 무신사 URL 여부 확인
     */
    _isMusinsaUrl(url) {
        return url && (url.includes('musinsa.com') || url.includes('msscdn.net'))
    }

    /**
     * 무신사 URL에서 goodsNo 추출
     * /app/goods/3900000 또는 /goods/3900000 형태 지원
     */
    _extractMusinsaGoodsNo(url) {
        const match = url.match(/\/(?:app\/)?goods\/(\d{5,8})/)
        return match ? match[1] : null
    }

    /**
     * 무신사 실제 단일 상품 수집 (프록시 서버 사용)
     * @param {string} url - 무신사 상품 URL
     * @returns {object|null} 상품 데이터 또는 null
     */
    async _collectMusinsaSingle(url) {
        const goodsNo = this._extractMusinsaGoodsNo(url)
        if (!goodsNo) throw new Error('무신사 상품 URL에서 상품번호를 찾을 수 없습니다.')

        const res = await fetch(`${MUSINSA_PROXY_URL}/api/musinsa/goods/${goodsNo}`)
        if (!res.ok) throw new Error(`프록시 응답 오류: ${res.status}`)
        const data = await res.json()
        if (!data.success) throw new Error(data.message || '상품 수집 실패')
        return data.data
    }

    /**
     * 무신사 실제 범위 수집 (프록시 서버 사용)
     * URL에서 startId를 추출하거나 기본 범위를 스캔
     * @param {string} url - 무신사 URL (카테고리/검색/상품 URL)
     * @param {object} options - { count, keyword, storeCode }
     * @returns {Array} 수집된 상품 목록
     */
    async _collectMusinsaBulk(url, options = {}) {
        const count = Math.min(options.count || 30, 100)
        const keyword = options.keyword || ''
        const storeCode = options.storeCode || ''

        // goodsNo가 포함된 URL이면 해당 ID 근처 범위 스캔
        const goodsNo = this._extractMusinsaGoodsNo(url)
        const startId = goodsNo ? parseInt(goodsNo) : 3900000
        const endId = startId + count + 10 // 무신사는 연속 ID 채번율이 높아 버퍼 10개면 충분

        const params = new URLSearchParams({
            startId, endId,
            ...(keyword && { keyword }),
            ...(storeCode && { storeCode })
        })

        const res = await fetch(`${MUSINSA_PROXY_URL}/api/musinsa/bulk?${params}`)
        if (!res.ok) throw new Error(`프록시 응답 오류: ${res.status}`)
        const data = await res.json()
        if (!data.success) throw new Error('범위 수집 실패')

        // count 제한 적용
        return data.data.slice(0, count)
    }

    // ==================== 검색필터 CRUD ====================

    async loadFilters() {
        this.filters = await storage.getAll('searchFilters')
        return this.filters
    }

    async addFilter(data) {
        const filter = {
            id: 'sf_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
            name: data.name || '',
            sourceSite: data.sourceSite || '',
            searchUrl: data.searchUrl || '',
            collectCount: data.collectCount || 100,
            savedCount: 0,
            collectConditions: data.collectConditions || { maxItems: 500, priceMin: 0, priceMax: 999999 },
            appliedPolicyId: null,
            lastCollectedAt: null,
            createdAt: new Date().toISOString()
        }
        await storage.save('searchFilters', filter)
        this.filters.push(filter)
        return filter
    }

    async updateFilter(id, data) {
        const filter = this.filters.find(f => f.id === id)
        if (!filter) return null
        const updated = { ...filter, ...data, updatedAt: new Date().toISOString() }
        await storage.save('searchFilters', updated)
        const idx = this.filters.findIndex(f => f.id === id)
        if (idx !== -1) this.filters[idx] = updated
        return updated
    }

    async deleteFilter(id) {
        await storage.delete('searchFilters', id)
        this.filters = this.filters.filter(f => f.id !== id)
    }

    // ==================== URL 파싱 ====================

    /**
     * URL에서 사이트 자동 감지
     */
    parseSiteFromUrl(url) {
        if (!url) return null
        const lower = url.toLowerCase()
        for (const site of this.supportedSites) {
            if (lower.includes(site.domain)) return site
        }
        // 추가 패턴 매핑
        if (lower.includes('musinsa')) return this.supportedSites.find(s => s.id === 'musinsa')
        if (lower.includes('nike')) return this.supportedSites.find(s => s.id === 'nike')
        if (lower.includes('ssg')) return this.supportedSites.find(s => s.id === 'ssg')
        if (lower.includes('lotteon') || lower.includes('lotte')) return this.supportedSites.find(s => s.id === 'lotteon')
        if (lower.includes('oliveyoung') || lower.includes('olive')) return this.supportedSites.find(s => s.id === 'oliveyoung')
        if (lower.includes('gsshop') || lower.includes('gs25')) return this.supportedSites.find(s => s.id === 'gsshop')
        if (lower.includes('abc') || lower.includes('a-rt')) return this.supportedSites.find(s => s.id === 'abcmart')
        return null
    }

    // ==================== 수집 실행 ====================

    /**
     * URL 기반 수집 (대량수집 모드)
     * 무신사 URL + 프록시 서버 가용 시: 실제 수집
     * 그 외: 시뮬레이션 수집
     */
    async collectFromUrl(url, options = {}) {
        if (!url) throw new Error('URL을 입력해주세요')
        const site = this.parseSiteFromUrl(url)
        const siteName = site ? site.name : '알 수 없는 사이트'
        const count = options.count || 30

        this.isCollecting = true

        try {
            // 무신사 URL + 실제 수집 모드 + 프록시 가용
            if (this.realModeEnabled && this._isMusinsaUrl(url) && this.proxyAvailable) {
                console.log('[Collector] 무신사 실제 수집 시작...')
                // keyword는 ID 범위 스캔 방식이므로 필터로 전달하지 않음
                let products = await this._collectMusinsaBulk(url, { ...options, count })

                // 금지어/삭제어 필터링 적용
                if (typeof forbiddenManager !== 'undefined') {
                    products = forbiddenManager.filterProducts(products)
                    products = products.map(p => ({ ...p, name: forbiddenManager.cleanProductName(p.name) }))
                }

                this.collectResults = products
                this.currentPage = 1
                console.log(`[Collector] 실제 수집 완료: ${products.length}개`)
                return products
            }

            // 시뮬레이션 수집 (기본)
            const keyword = this._extractKeywordFromUrl(url)
            await this._delay(800 + Math.random() * 600)
            let products = this._generateSimulatedProducts(siteName, keyword, count, site)

            if (typeof forbiddenManager !== 'undefined') {
                products = forbiddenManager.filterProducts(products)
                products = products.map(p => ({ ...p, name: forbiddenManager.cleanProductName(p.name) }))
            }

            this.collectResults = products
            this.currentPage = 1
            return products

        } finally {
            this.isCollecting = false
        }
    }

    /**
     * 개별 상품 수집 (상세페이지 URL)
     * 무신사 상품 URL + 프록시 가용 시: 실제 수집
     * 그 외: 시뮬레이션 수집
     */
    async collectSingle(detailUrl) {
        if (!detailUrl) throw new Error('상품 URL을 입력해주세요')

        this.isCollecting = true

        try {
            // 무신사 개별 상품 실제 수집
            if (this.realModeEnabled && this._isMusinsaUrl(detailUrl) && this.proxyAvailable) {
                const goodsNo = this._extractMusinsaGoodsNo(detailUrl)
                if (goodsNo) {
                    console.log(`[Collector] 무신사 상품 실제 수집: ${goodsNo}`)
                    const product = await this._collectMusinsaSingle(detailUrl)
                    this.collectResults = [product]
                    this.currentPage = 1
                    return [product]
                }
            }

            // 시뮬레이션 수집 (기본)
            const site = this.parseSiteFromUrl(detailUrl)
            const siteName = site ? site.name : '알 수 없는 사이트'
            await this._delay(400)
            const product = this._generateSingleProduct(siteName, site, detailUrl)
            this.collectResults = [product]
            this.currentPage = 1
            return [product]

        } finally {
            this.isCollecting = false
        }
    }

    /**
     * 사이트별 시뮬레이션 상품 생성 (10개 사이트 대응)
     */
    _generateSimulatedProducts(siteName, keyword, count, site) {
        const siteData = this._getSiteProductData(siteName)
        const products = []

        for (let i = 0; i < count; i++) {
            const baseProduct = siteData[i % siteData.length]
            const variation = i > 0 ? ` ${i + 1}` : ''
            const priceVariation = Math.floor(Math.random() * 30000) - 10000
            const basePrice = baseProduct.price + priceVariation

            const productName = (keyword ? keyword + ' ' : '') + baseProduct.name + variation

            products.push({
                id: 'col_' + Date.now() + '_' + i + '_' + Math.random().toString(36).substring(2, 6),
                sourceSite: siteName,
                siteProductId: String(Math.floor(Math.random() * 9000000) + 1000000),
                sourceUrl: `https://www.${site ? site.domain : 'example.com'}/product/${Math.floor(Math.random() * 999999)}`,
                searchFilterId: null,
                name: productName,
                nameEn: '', // 영문 상품명 (역직구용)
                nameJa: '', // 일어 상품명 (역직구용)
                brand: baseProduct.brand,
                category: baseProduct.category,
                images: [
                    `https://via.placeholder.com/200x200/1A1A1A/FF8C00?text=${encodeURIComponent(baseProduct.brand)}`
                ],
                options: baseProduct.options.map(opt => ({
                    ...opt,
                    price: Math.max(9900, basePrice + Math.floor(Math.random() * 5000))
                })),
                originalPrice: Math.max(9900, basePrice),
                salePrice: Math.max(9900, basePrice),
                status: 'collected',
                appliedPolicyId: null,
                marketPrices: {},
                updateEnabled: true,
                priceUpdateEnabled: true,
                stockUpdateEnabled: true,
                marketTransmitEnabled: true,
                registeredAccounts: [],
                collectedAt: new Date().toISOString(),
                updatedAt: new Date().toISOString()
            })
        }
        return products
    }

    /**
     * 단일 상품 생성 (개별수집)
     */
    _generateSingleProduct(siteName, site, url) {
        const siteData = this._getSiteProductData(siteName)
        const baseProduct = siteData[Math.floor(Math.random() * siteData.length)]
        return {
            id: 'col_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
            sourceSite: siteName,
            siteProductId: String(Math.floor(Math.random() * 9000000) + 1000000),
            sourceUrl: url,
            searchFilterId: null,
            name: baseProduct.name,
            nameEn: '', // 영문 상품명 (역직구용)
            nameJa: '', // 일어 상품명 (역직구용)
            brand: baseProduct.brand,
            category: baseProduct.category,
            images: [`https://via.placeholder.com/200x200/1A1A1A/FF8C00?text=${encodeURIComponent(baseProduct.brand)}`],
            options: baseProduct.options,
            originalPrice: baseProduct.price,
            salePrice: baseProduct.price,
            status: 'collected',
            appliedPolicyId: null,
            marketPrices: {},
            updateEnabled: true,
            priceUpdateEnabled: true,
            stockUpdateEnabled: true,
            marketTransmitEnabled: true,
            registeredAccounts: [],
            collectedAt: new Date().toISOString(),
            updatedAt: new Date().toISOString()
        }
    }

    /**
     * 사이트별 시뮬레이션 상품 데이터
     */
    _getSiteProductData(siteName) {
        const data = {
            'MUSINSA': [
                { name: '오버핏 크루넥 스웨트셔츠', brand: 'MUSINSA STANDARD', category: '상의 > 맨투맨/스웨트', price: 39900, options: [{name: 'S', price: 39900, stock: 15, stockStatus: '재고'},{name: 'M', price: 39900, stock: 22, stockStatus: '재고'},{name: 'L', price: 39900, stock: 18, stockStatus: '재고'},{name: 'XL', price: 39900, stock: 5, stockStatus: '재고'}] },
                { name: '와이드 치노 팬츠', brand: 'MUSINSA STANDARD', category: '하의 > 면/치노팬츠', price: 44900, options: [{name: '28', price: 44900, stock: 8, stockStatus: '재고'},{name: '30', price: 44900, stock: 12, stockStatus: '재고'},{name: '32', price: 44900, stock: 7, stockStatus: '재고'}] },
                { name: '레귤러 데님 자켓', brand: 'MUSINSA STANDARD', category: '아우터 > 데님자켓', price: 69900, options: [{name: 'S', price: 69900, stock: 5, stockStatus: '재고'},{name: 'M', price: 69900, stock: 10, stockStatus: '재고'}] },
                { name: '코튼 반팔 티셔츠', brand: 'MUSINSA STANDARD', category: '상의 > 반팔 티셔츠', price: 19900, options: [{name: 'S', price: 19900, stock: 30, stockStatus: '재고'},{name: 'M', price: 19900, stock: 25, stockStatus: '재고'},{name: 'L', price: 19900, stock: 20, stockStatus: '재고'}] },
                { name: '슬림 슬랙스', brand: 'MUSINSA STANDARD', category: '하의 > 슬랙스', price: 49900, options: [{name: '28', price: 49900, stock: 6, stockStatus: '재고'},{name: '30', price: 49900, stock: 9, stockStatus: '재고'}] }
            ],
            'Nike': [
                { name: '에어 포스 1 07 스니커즈', brand: 'Nike', category: '신발 > 스니커즈', price: 109000, options: [{name: '255', price: 109000, stock: 5, stockStatus: '재고'},{name: '260', price: 109000, stock: 8, stockStatus: '재고'},{name: '265', price: 109000, stock: 10, stockStatus: '재고'},{name: '270', price: 109000, stock: 7, stockStatus: '재고'},{name: '275', price: 109000, stock: 4, stockStatus: '재고'}] },
                { name: '줌 플라이 5 런닝화', brand: 'Nike', category: '신발 > 런닝화', price: 179000, options: [{name: '255', price: 179000, stock: 3, stockStatus: '재고'},{name: '260', price: 179000, stock: 5, stockStatus: '재고'},{name: '265', price: 179000, stock: 6, stockStatus: '재고'}] },
                { name: '드라이핏 런닝 반팔티', brand: 'Nike', category: '상의 > 반팔 티셔츠', price: 39000, options: [{name: 'S', price: 39000, stock: 15, stockStatus: '재고'},{name: 'M', price: 39000, stock: 20, stockStatus: '재고'},{name: 'L', price: 39000, stock: 18, stockStatus: '재고'}] },
                { name: '클럽 풀오버 후디', brand: 'Nike', category: '상의 > 후디', price: 89000, options: [{name: 'S', price: 89000, stock: 8, stockStatus: '재고'},{name: 'M', price: 89000, stock: 12, stockStatus: '재고'},{name: 'L', price: 89000, stock: 6, stockStatus: '재고'}] },
                { name: '에어맥스 90 클래식', brand: 'Nike', category: '신발 > 스니커즈', price: 149000, options: [{name: '255', price: 149000, stock: 4, stockStatus: '재고'},{name: '260', price: 149000, stock: 7, stockStatus: '재고'},{name: '265', price: 149000, stock: 5, stockStatus: '품절'}] }
            ],
            'LOTTEON': [
                { name: '프리미엄 면 스웨터', brand: 'LOTTE', category: '상의 > 니트/스웨터', price: 35000, options: [{name: 'S', price: 35000, stock: 10, stockStatus: '재고'},{name: 'M', price: 35000, stock: 15, stockStatus: '재고'},{name: 'L', price: 35000, stock: 8, stockStatus: '재고'}] },
                { name: '데일리 캐주얼 팬츠', brand: 'LOTTE', category: '하의 > 면/치노팬츠', price: 29900, options: [{name: '28', price: 29900, stock: 12, stockStatus: '재고'},{name: '30', price: 29900, stock: 10, stockStatus: '재고'}] },
                { name: '스트라이프 셔츠', brand: 'LOTTE', category: '상의 > 셔츠/블라우스', price: 45000, options: [{name: 'S', price: 45000, stock: 6, stockStatus: '재고'},{name: 'M', price: 45000, stock: 9, stockStatus: '재고'}] }
            ],
            'SSG': [
                { name: '리넨 블라우스', brand: 'SSG Fashion', category: '상의 > 셔츠/블라우스', price: 59000, options: [{name: 'S', price: 59000, stock: 7, stockStatus: '재고'},{name: 'M', price: 59000, stock: 11, stockStatus: '재고'},{name: 'L', price: 59000, stock: 5, stockStatus: '재고'}] },
                { name: '플리츠 미디 스커트', brand: 'SSG Fashion', category: '하의 > 스커트', price: 49000, options: [{name: 'S', price: 49000, stock: 8, stockStatus: '재고'},{name: 'M', price: 49000, stock: 10, stockStatus: '재고'}] },
                { name: '더블 버튼 코트', brand: 'SSG Fashion', category: '아우터 > 코트', price: 189000, options: [{name: 'S', price: 189000, stock: 4, stockStatus: '재고'},{name: 'M', price: 189000, stock: 6, stockStatus: '재고'}] }
            ],
            'ABCmart': [
                { name: 'ABCmart 에어쿠션 스니커즈', brand: 'ABCmart', category: '신발 > 스니커즈', price: 79000, options: [{name: '240', price: 79000, stock: 5, stockStatus: '재고'},{name: '250', price: 79000, stock: 8, stockStatus: '재고'},{name: '260', price: 79000, stock: 10, stockStatus: '재고'},{name: '270', price: 79000, stock: 6, stockStatus: '재고'}] },
                { name: '레더 로퍼', brand: 'ABCmart', category: '신발 > 구두/로퍼', price: 129000, options: [{name: '245', price: 129000, stock: 3, stockStatus: '재고'},{name: '255', price: 129000, stock: 5, stockStatus: '재고'}] }
            ],
            'OliveYoung': [
                { name: '세럼 에센스 50ml', brand: 'COSRX', category: '스킨케어 > 에센스/세럼', price: 32000, options: [{name: '기본', price: 32000, stock: 50, stockStatus: '재고'}] },
                { name: '선크림 SPF50+ PA++++', brand: 'Klairs', category: '스킨케어 > 선케어', price: 22000, options: [{name: '50ml', price: 22000, stock: 30, stockStatus: '재고'}] },
                { name: '비타민C 토너 150ml', brand: 'Some By Mi', category: '스킨케어 > 토너', price: 19800, options: [{name: '150ml', price: 19800, stock: 40, stockStatus: '재고'}] }
            ],
            'GSShop': [
                { name: '홈쇼핑 특가 패딩 조끼', brand: 'GSShop', category: '아우터 > 패딩/다운', price: 55000, options: [{name: 'S', price: 55000, stock: 20, stockStatus: '재고'},{name: 'M', price: 55000, stock: 25, stockStatus: '재고'},{name: 'L', price: 55000, stock: 15, stockStatus: '재고'}] },
                { name: '기능성 언더웨어 세트', brand: 'GSShop', category: '이너웨어 > 속옷세트', price: 39900, options: [{name: 'M', price: 39900, stock: 30, stockStatus: '재고'},{name: 'L', price: 39900, stock: 25, stockStatus: '재고'}] }
            ],
            'FOLDERStyle': [
                { name: '스트리트 그래픽 티셔츠', brand: 'FOLDER', category: '상의 > 반팔 티셔츠', price: 29900, options: [{name: 'S', price: 29900, stock: 12, stockStatus: '재고'},{name: 'M', price: 29900, stock: 18, stockStatus: '재고'},{name: 'L', price: 29900, stock: 10, stockStatus: '재고'}] },
                { name: '힙합 와이드 조거팬츠', brand: 'FOLDER', category: '하의 > 조거/트레이닝', price: 49900, options: [{name: 'S', price: 49900, stock: 8, stockStatus: '재고'},{name: 'M', price: 49900, stock: 12, stockStatus: '재고'}] }
            ],
            'GrandStage': [
                { name: '프리미엄 드레스 슈즈', brand: 'GrandStage', category: '신발 > 드레스화', price: 159000, options: [{name: '255', price: 159000, stock: 3, stockStatus: '재고'},{name: '260', price: 159000, stock: 5, stockStatus: '재고'}] }
            ]
        }
        // 기본 데이터 (사이트 미매핑 시)
        const defaultData = data['MUSINSA']
        return data[siteName] || defaultData
    }

    /**
     * URL에서 키워드 추출
     */
    _extractKeywordFromUrl(url) {
        try {
            const u = new URL(url)
            const keyword = u.searchParams.get('keyword') ||
                           u.searchParams.get('query') ||
                           u.searchParams.get('q') ||
                           u.searchParams.get('search') || ''
            return decodeURIComponent(keyword).replace(/\+/g, ' ').trim()
        } catch {
            return ''
        }
    }

    _delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms))
    }

    // ==================== 저장 ====================

    /**
     * 선택된 상품들을 IndexedDB에 저장
     */
    async saveSelectedProducts(productIds) {
        const toSave = this.collectResults.filter(p => productIds.includes(p.id))
        if (toSave.length === 0) return 0

        // 중복 체크 후 저장
        const saved = []
        for (const p of toSave) {
            const existing = await storage.getByIndex('collectedProducts', 'siteProductId', p.siteProductId)
            if (!existing || existing.length === 0) {
                p.status = 'saved'
                saved.push(p)
            }
        }
        await storage.batchSave('collectedProducts', saved)

        // products 스토어에도 브릿지 저장 (다른 모듈과 연동)
        for (const p of saved) {
            try {
                // sourceUrl 중복 체크
                const existingInProducts = await storage.getByIndex('products', 'sourceUrl', p.sourceUrl || p.siteProductUrl || '')
                if (existingInProducts && existingInProducts.length > 0) continue

                const bridgeProduct = {
                    id: 'prod_' + Date.now() + '_' + p.id.slice(-6),
                    name: p.name,
                    category: p.category,
                    sourceUrl: p.sourceUrl || p.siteProductUrl || '',
                    sourcePrice: p.originalPrice,
                    cost: p.originalPrice,
                    marginRate: 15,
                    salePrice: Math.ceil(p.originalPrice * 1.15),
                    description: '',
                    status: 'active',
                    images: p.images || [],
                    brand: p.brand || '',
                    sourceSite: p.sourceSite,
                    collectedProductId: p.id,  // 역참조 링크
                    createdAt: new Date().toISOString(),
                    updatedAt: new Date().toISOString()
                }
                await storage.save('products', bridgeProduct)
                // 메모리 동기화
                if (typeof productManager !== 'undefined') {
                    productManager.products.push(bridgeProduct)
                }
            } catch (e) {
                console.warn('products 브릿지 저장 실패:', e)
            }
        }

        // 검색필터 카운터 업데이트
        await this._updateFilterCount(saved.length)

        return saved.length
    }

    /**
     * 수집 결과 전체 저장
     */
    async saveAllProducts() {
        const ids = this.collectResults.map(p => p.id)
        return await this.saveSelectedProducts(ids)
    }

    /**
     * 필터 savedCount 업데이트
     */
    async _updateFilterCount(addCount) {
        if (this._lastSearchFilterId) {
            const filter = this.filters.find(f => f.id === this._lastSearchFilterId)
            if (filter) {
                await this.updateFilter(filter.id, { savedCount: (filter.savedCount || 0) + addCount })
            }
        }
    }

    /**
     * 수집 + 자동 필터 저장
     */
    async collectAndSaveFilter(url, options = {}) {
        const site = this.parseSiteFromUrl(url)
        const keyword = this._extractKeywordFromUrl(url)
        const siteName = site ? site.name : '알 수 없는 사이트'
        const filterName = `${siteName}_${keyword || 'URL수집'}_${new Date().toLocaleDateString('ko-KR')}`

        // 검색필터 자동 생성 (중복 방지)
        let filter = this.filters.find(f => f.searchUrl === url)
        if (!filter) {
            filter = await this.addFilter({
                name: filterName,
                sourceSite: siteName,
                searchUrl: url,
                collectCount: options.count || 30
            })
        }
        this._lastSearchFilterId = filter.id

        // 수집 실행
        const products = await this.collectFromUrl(url, options)
        // 수집 결과에 filterID 연결
        products.forEach(p => { p.searchFilterId = filter.id })
        this.collectResults = products

        return { filter, products }
    }

    // ==================== 페이지네이션 로드 ====================

    /**
     * 저장된 상품 페이지네이션 로드
     */
    async loadProductsPaginated(filterOptions = {}, page = 1, pageSize = 50) {
        if (filterOptions.searchFilterId) {
            return await storage.getByIndexPaginated('collectedProducts', 'searchFilterId', filterOptions.searchFilterId, page, pageSize)
        }
        if (filterOptions.status) {
            return await storage.getByIndexPaginated('collectedProducts', 'status', filterOptions.status, page, pageSize)
        }
        if (filterOptions.sourceSite) {
            return await storage.getByIndexPaginated('collectedProducts', 'sourceSite', filterOptions.sourceSite, page, pageSize)
        }
        // 전체 로드 (페이지네이션)
        const all = await storage.getAll('collectedProducts')
        const start = (page - 1) * pageSize
        return all.slice(start, start + pageSize)
    }

    /**
     * 저장된 상품 총 개수
     */
    async getTotalSavedCount() {
        const all = await storage.getAll('collectedProducts')
        return all.length
    }

    /**
     * 현재 수집 결과 페이지네이션
     */
    getResultsPage(page = 1, pageSize = 50) {
        const start = (page - 1) * pageSize
        return {
            items: this.collectResults.slice(start, start + pageSize),
            total: this.collectResults.length,
            page,
            pageSize,
            totalPages: Math.ceil(this.collectResults.length / pageSize)
        }
    }

    /**
     * 선택된 상품 저장 (collectedProducts IndexedDB)
     * @param {string[]} ids - 저장할 상품 ID 목록
     * @returns {number} 저장된 개수
     */
    async saveSelectedProducts(ids) {
        const toSave = this.collectResults.filter(p => ids.includes(p.id))
        let count = 0
        for (const p of toSave) {
            const saved = { ...p, status: 'saved', savedAt: new Date().toISOString() }
            await storage.save('collectedProducts', saved)
            // 메모리 내 상태 업데이트
            const mem = this.collectResults.find(r => r.id === p.id)
            if (mem) mem.status = 'saved'
            count++
        }
        // 필터별 savedCount 업데이트
        await this._updateFilterCounts(toSave)
        return count
    }

    /**
     * 현재 수집 결과 전체 저장
     * @returns {number} 저장된 개수
     */
    async saveAllProducts() {
        return this.saveSelectedProducts(this.collectResults.map(p => p.id))
    }

    /**
     * 필터별 savedCount 일괄 업데이트
     */
    async _updateFilterCounts(products) {
        const counts = {}
        products.forEach(p => {
            if (p.searchFilterId) counts[p.searchFilterId] = (counts[p.searchFilterId] || 0) + 1
        })
        for (const [filterId, cnt] of Object.entries(counts)) {
            const filter = this.filters.find(f => f.id === filterId)
            if (filter) {
                await this.updateFilter(filterId, { savedCount: (filter.savedCount || 0) + cnt })
            }
        }
    }

    /**
     * 중복 제거 + 자동저장 + 목표 수량 도달 시 중지
     * @param {object} filter - searchFilter 객체
     * @returns {{ saved, duplicates, skipped, alreadyFull }}
     */
    async autoCollectAndSave(filter) {
        const target = filter.collectCount || 100
        const already = filter.savedCount || 0

        // 이미 목표 달성
        if (already >= target) {
            return { saved: 0, duplicates: 0, skipped: 0, alreadyFull: true }
        }

        const needed = target - already

        // 기존 저장된 siteProductId 목록 (중복 체크)
        const existingList = await storage.getByIndex('collectedProducts', 'searchFilterId', filter.id)
        const existingIds = new Set(existingList.map(p => p.siteProductId))

        // 중복 제거 후 needed개 확보를 위해 넉넉하게 수집
        const collectTarget = Math.min(Math.ceil(needed * 1.5), needed + 50)
        const products = await this.collectFromUrl(filter.searchUrl, { count: collectTarget })

        let saved = 0
        let duplicates = 0

        for (const p of products) {
            if (saved >= needed) break
            if (existingIds.has(p.siteProductId)) { duplicates++; continue }

            const saveData = { ...p, searchFilterId: filter.id, status: 'saved', savedAt: new Date().toISOString() }
            await storage.save('collectedProducts', saveData)
            existingIds.add(p.siteProductId)
            saved++
        }

        const skipped = products.length - saved - duplicates

        await this.updateFilter(filter.id, {
            savedCount: already + saved,
            lastCollectedAt: new Date().toISOString()
        })
        await this.loadFilters()

        return { saved, duplicates, skipped, alreadyFull: false }
    }
}

// 글로벌 인스턴스
const collectorManager = new CollectorManager()
