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
        this.collectDetailImages = false   // 상세페이지 이미지 수집 여부
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
        this.onLog = null           // UI 로그 콜백: (msg, type) => void
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

            // 프록시 연결 확인 후 Chrome 쿠키 자동 로그인 시도
            if (this.proxyAvailable && !data.isLoggedIn) {
                this._autoLogin().catch(() => {})
            }
        } catch {
            this.proxyAvailable = false
            this._proxyChecked = true
            console.log('[Collector] 프록시 서버 없음 - 시뮬레이션 모드')
        }
        return this.proxyAvailable
    }

    async _autoLogin() {
        try {
            const r = await fetch(`${MUSINSA_PROXY_URL}/api/musinsa/chrome-login`)
            const d = await r.json()
            if (d.success && d.isLoggedIn) {
                console.log(`[Collector] 무신사 자동 로그인: ${d.memberId}`)
                if (typeof ui !== 'undefined') ui._refreshAuthStatusUI()
            }
        } catch {
            // 자동 로그인 실패 시 조용히 무시 (수동 로그인으로 처리 가능)
        }
    }

    /**
     * 무신사 URL 여부 확인
     */
    _isMusinsaUrl(url) {
        return url && (
            url.includes('musinsa.com') ||
            url.includes('msscdn.net') ||
            url.includes('musinsa.onelink.me')
        )
    }

    /**
     * 무신사 URL에서 goodsNo 추출
     * /app/goods/3900000, /goods/3900000, /products/3900000 패턴 지원
     */
    _extractMusinsaGoodsNo(url) {
        const match = url.match(/\/(?:app\/)?(?:goods|products)\/(\d{5,8})/)
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
     * 1순위: 검색 API (keyword 기반) → 빠르고 정확
     * 2순위: URL 리다이렉트 처리 (onelink 등)
     * 3순위: 단일 상품 수집 (goodsNo URL)
     * @param {string} url - 무신사 URL (카테고리/검색/상품 URL)
     * @param {object} options - { count, keyword, storeCode }
     * @returns {Array} 수집된 상품 목록
     */
    async _collectMusinsaBulk(url, options = {}) {
        const count = options.count || 30
        const keyword = this._extractKeywordFromUrl(url) || options.keyword || ''
        const goodsNo = this._extractMusinsaGoodsNo(url)

        const log = (msg, type = 'info') => {
            console.log(`[수집] ${msg}`)
            if (this.onLog) this.onLog(msg, type)
        }

        // 1순위: 검색 키워드가 있으면 검색 API 직접 호출 (가장 빠르고 정확)
        if (keyword) {
            try {
                // 페이지네이션: 100개씩 나눠서 요청
                const pageSize = 100
                const totalPages = Math.ceil(count / pageSize)
                let allBasicProducts = []

                for (let page = 1; page <= totalPages; page++) {
                    const reqSize = Math.min(pageSize, count - allBasicProducts.length)
                    log(`검색 API 호출: "${keyword}" (${page}/${totalPages}페이지, ${reqSize}개 요청)`)
                    const params = new URLSearchParams({ keyword, page: String(page), size: String(reqSize) })
                    const searchRes = await fetch(`${MUSINSA_PROXY_URL}/api/musinsa/search-api?${params}`)

                    if (!searchRes.ok) {
                        log(`검색 API 실패: HTTP ${searchRes.status}`, 'error')
                        break
                    }
                    const searchData = await searchRes.json()
                    if (!searchData.success || !searchData.data?.length) {
                        log(`검색 결과 없음 (${page}페이지)`, 'warn')
                        break
                    }

                    const pageProducts = searchData.data.filter(p => !p.isSoldOut)
                    const soldOut = searchData.data.length - pageProducts.length
                    log(`${page}페이지: ${pageProducts.length}개 (품절 ${soldOut}개 제외) / 총 ${searchData.totalCount || 0}개`)
                    allBasicProducts.push(...pageProducts)

                    if (allBasicProducts.length >= count) break
                    if (searchData.data.length < reqSize) break // 마지막 페이지
                }

                if (allBasicProducts.length > 0) {
                    // 요청 수량에 맞게 자르기
                    allBasicProducts = allBasicProducts.slice(0, count)

                    // 상세 정보 보강 (옵션, 소재, 제조국 등)
                    log(`상세 정보 보강 수집 시작 (${allBasicProducts.length}개)...`)
                    const enriched = await this._enrichProducts(allBasicProducts, log)
                    log(`수집 완료: ${enriched.length}개 (상세 보강 완료)`, 'success')
                    return enriched
                }
                log(`검색 결과 0개 (keyword: "${keyword}")`, 'warn')
            } catch (e) {
                log(`검색 API 예외: ${e.message}`, 'error')
            }
        }

        // 2순위: onelink 등 리다이렉트 URL → 상품번호 추출
        if (!goodsNo && !keyword) {
            try {
                log(`URL 리다이렉트 분석: ${url.slice(0, 60)}...`)
                const searchRes = await fetch(
                    `${MUSINSA_PROXY_URL}/api/musinsa/search?url=${encodeURIComponent(url)}`
                )
                if (searchRes.ok) {
                    const searchData = await searchRes.json()
                    if (searchData.success && searchData.goodsNos?.length > 0) {
                        log(`${searchData.goodsNos.length}개 상품번호 추출 (source: ${searchData.source})`)
                        const products = []
                        const targetNos = searchData.goodsNos.slice(0, count)
                        for (let i = 0; i < targetNos.length; i++) {
                            const no = targetNos[i]
                            try {
                                log(`  상품 ${no} 수집 중... (${i + 1}/${targetNos.length})`)
                                const r = await fetch(`${MUSINSA_PROXY_URL}/api/musinsa/goods/${no}`)
                                if (r.ok) {
                                    const d = await r.json()
                                    if (d.success && d.data) {
                                        products.push(d.data)
                                        log(`  → ${d.data.name} | ${d.data.salePrice?.toLocaleString()}원`, 'success')
                                    } else {
                                        log(`  → 상품 ${no} 파싱 실패`, 'warn')
                                    }
                                } else {
                                    log(`  → 상품 ${no} HTTP ${r.status}`, 'warn')
                                }
                            } catch (e) {
                                log(`  → 상품 ${no} 오류: ${e.message}`, 'error')
                            }
                            if (i < targetNos.length - 1) await new Promise(r => setTimeout(r, 2000))
                        }
                        if (products.length > 0) {
                            log(`URL 기반 수집 완료: ${products.length}개`, 'success')
                            return products
                        }
                    } else {
                        log('URL에서 상품번호 추출 실패', 'warn')
                    }
                }
            } catch (e) {
                log(`URL 분석 예외: ${e.message}`, 'error')
            }
        }

        // 3순위: 단일 상품 goodsNo URL
        if (goodsNo) {
            try {
                log(`단일 상품 수집: goodsNo=${goodsNo}`)
                const r = await fetch(`${MUSINSA_PROXY_URL}/api/musinsa/goods/${goodsNo}`)
                if (r.ok) {
                    const d = await r.json()
                    if (d.success && d.data) {
                        log(`→ ${d.data.name} | ${d.data.salePrice?.toLocaleString()}원`, 'success')
                        return [d.data]
                    }
                }
                log(`단일 상품 ${goodsNo} 수집 실패`, 'error')
            } catch (e) {
                log(`단일 상품 오류: ${e.message}`, 'error')
            }
        }

        log('모든 수집 방식 실패', 'error')
        return []
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

    /**
     * 검색 필터(그룹) 삭제 - 연관 데이터 cascade 삭제
     * 1) 마켓 등록 상품 확인 → 경고
     * 2) collectedProducts 삭제
     * 3) products(bridge) 삭제
     * 4) searchFilters 삭제
     * @param {string} id - 필터 ID
     * @param {object} options - { force: boolean } 마켓 등록 상품 강제 삭제 여부
     * @returns {{ deleted: number, marketRegistered: number, skipped: boolean }}
     */
    async deleteFilter(id, options = {}) {
        // 1) 이 필터와 연결된 collectedProducts 조회
        const collectedList = await storage.getByIndex('collectedProducts', 'searchFilterId', id)
        const collectedIds = collectedList.map(p => p.id)

        // 2) 마켓 등록 상품 확인
        const marketRegistered = collectedList.filter(p =>
            p.registeredAccounts && p.registeredAccounts.length > 0
        )

        if (marketRegistered.length > 0 && !options.force) {
            // 마켓 등록 상품이 있으면 삭제 중단, 호출자에게 알림
            return {
                deleted: 0,
                marketRegistered: marketRegistered.length,
                skipped: true,
                marketProducts: marketRegistered.map(p => ({
                    name: p.name?.slice(0, 40),
                    accounts: p.registeredAccounts
                }))
            }
        }

        // 3) collectedProducts 삭제
        if (collectedIds.length > 0) {
            await storage.batchDelete('collectedProducts', collectedIds)
        }

        // 4) products(bridge) 삭제 - searchFilterId 또는 collectedProductId로 연결된 것
        const allProducts = await storage.getAll('products')
        const bridgeIds = allProducts
            .filter(p => p.searchFilterId === id || collectedIds.includes(p.collectedProductId))
            .map(p => p.id)
        if (bridgeIds.length > 0) {
            await storage.batchDelete('products', bridgeIds)
            // productManager 메모리 동기화
            if (typeof productManager !== 'undefined') {
                productManager.products = productManager.products.filter(p => !bridgeIds.includes(p.id))
            }
        }

        // 5) searchFilters 삭제
        await storage.delete('searchFilters', id)
        this.filters = this.filters.filter(f => f.id !== id)

        return {
            deleted: collectedIds.length + bridgeIds.length,
            marketRegistered: marketRegistered.length,
            skipped: false
        }
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
        if (this.isCollecting) throw new Error('수집이 이미 진행 중입니다')

        const site = this.parseSiteFromUrl(url)
        const siteName = site ? site.name : '알 수 없는 사이트'
        const count = options.count || 30

        this.isCollecting = true

        try {
            // 무신사 URL + 실제 수집 모드 + 프록시 가용
            if (this.realModeEnabled && this._isMusinsaUrl(url) && this.proxyAvailable) {
                // 로그인 안 된 상태면 자동 로그인 재시도
                const authStatus = await fetch(`${MUSINSA_PROXY_URL}/api/musinsa/auth/status`).then(r => r.json()).catch(() => ({}))
                if (!authStatus.isLoggedIn) await this._autoLogin()

                console.log('[Collector] 무신사 실제 수집 시작...')
                let products = await this._collectMusinsaBulk(url, { ...options, count })

                // 상세이미지 수집 비활성화 시 제거
                if (!this.collectDetailImages) {
                    products = products.map(p => ({ ...p, detailImages: [], detailHtml: '' }))
                }

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

            // 시뮬레이션 수집 (기본) - 개당 딜레이는 autoCollectAndSave에서 처리
            const keyword = this._extractKeywordFromUrl(url)
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
        if (this.isCollecting) throw new Error('수집이 이미 진행 중입니다')

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
                nameEn: '',
                nameJa: '',
                brand: baseProduct.brand,
                category: baseProduct.category,
                ...this._parseCategoryLevels(baseProduct.category),
                images: [this._genPlaceholderImg(baseProduct.brand)],
                detailImages: [],
                detailHtml: '',
                options: baseProduct.options.map(opt => ({
                    ...opt,
                    originalStock: opt.stock,
                    stockStatus: opt.stockStatus || (opt.stock > 0 ? '재고' : '품절'),
                    isSoldOut: opt.stockStatus === '품절' || opt.stock === 0,
                    price: Math.max(9900, basePrice + Math.floor(Math.random() * 5000))
                })),
                originalPrice: Math.max(9900, basePrice),
                salePrice: Math.max(9900, basePrice),
                discountRate: 0,
                origin: baseProduct.origin || '대한민국',
                material: baseProduct.material || '',
                manufacturer: baseProduct.manufacturer || baseProduct.brand,
                season: baseProduct.season || '2025 S/S',
                styleCode: baseProduct.styleCode || '',
                kcCert: '',
                tags: [],
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
     * 검색 API 결과를 상세 페이지로 보강
     * 배치 3개씩 병렬 처리, 배치 간 2초 딜레이 (무신사 rate limit 대응)
     * @param {Array} basicProducts - 검색 API에서 받은 기본 상품 목록
     * @param {Function} log - 로그 함수
     * @returns {Array} 상세 정보가 보강된 상품 목록
     */
    async _enrichProducts(basicProducts, log) {
        const batchSize = 3
        const enriched = []

        for (let i = 0; i < basicProducts.length; i += batchSize) {
            const batch = basicProducts.slice(i, i + batchSize)
            const promises = batch.map(async (item, idx) => {
                const globalIdx = i + idx + 1
                const goodsNo = item.siteProductId
                try {
                    const r = await fetch(`${MUSINSA_PROXY_URL}/api/musinsa/goods/${goodsNo}`)
                    if (r.ok) {
                        const d = await r.json()
                        if (d.success && d.data) {
                            const optCount = d.data.options?.length || 0
                            log(`  ${globalIdx}/${basicProducts.length} ${d.data.name} | 옵션 ${optCount}개 | ${d.data.origin || '-'}`, 'success')
                            // 상세 데이터 사용, id는 원본 유지
                            return { ...d.data, id: item.id }
                        }
                    }
                    log(`  ${globalIdx}/${basicProducts.length} ${item.name} → 상세 수집 실패, 기본 정보 사용`, 'warn')
                    return item
                } catch (e) {
                    log(`  ${globalIdx}/${basicProducts.length} ${item.name} → 오류: ${e.message}`, 'warn')
                    return item
                }
            })

            const results = await Promise.all(promises)
            enriched.push(...results)

            // 배치 간 rate limit 딜레이
            if (i + batchSize < basicProducts.length) {
                await this._delay(2000)
            }
        }

        return enriched
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
            nameEn: '',
            nameJa: '',
            brand: baseProduct.brand,
            category: baseProduct.category,
            ...this._parseCategoryLevels(baseProduct.category),
            images: [this._genPlaceholderImg(baseProduct.brand)],
            detailImages: [],
            detailHtml: '',
            options: baseProduct.options.map(opt => ({
                ...opt,
                originalStock: opt.stock,
                stockStatus: opt.stockStatus || (opt.stock > 0 ? '재고' : '품절'),
                isSoldOut: opt.stockStatus === '품절' || opt.stock === 0
            })),
            originalPrice: baseProduct.price,
            salePrice: baseProduct.price,
            discountRate: 0,
            origin: baseProduct.origin || '대한민국',
            material: baseProduct.material || '',
            manufacturer: baseProduct.manufacturer || baseProduct.brand,
            season: baseProduct.season || '2025 S/S',
            styleCode: '',
            kcCert: '',
            tags: [],
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
                { name: '오버핏 크루넥 스웨트셔츠', brand: 'MUSINSA STANDARD', category: '패션의류 > 남성의류 > 상의 > 맨투맨/스웨트', price: 39900, origin: '대한민국', material: '면 80%, 폴리에스터 20%', season: '2025 S/S', options: [{name: 'S', price: 39900, stock: 15, stockStatus: '재고'},{name: 'M', price: 39900, stock: 22, stockStatus: '재고'},{name: 'L', price: 39900, stock: 18, stockStatus: '재고'},{name: 'XL', price: 39900, stock: 5, stockStatus: '재고'}] },
                { name: '와이드 치노 팬츠', brand: 'MUSINSA STANDARD', category: '패션의류 > 남성의류 > 하의 > 면/치노팬츠', price: 44900, origin: '중국', material: '면 98%, 스판덱스 2%', season: '2025 S/S', options: [{name: '28', price: 44900, stock: 8, stockStatus: '재고'},{name: '30', price: 44900, stock: 12, stockStatus: '재고'},{name: '32', price: 44900, stock: 7, stockStatus: '재고'}] },
                { name: '레귤러 데님 자켓', brand: 'MUSINSA STANDARD', category: '패션의류 > 남성의류 > 아우터 > 데님자켓', price: 69900, origin: '방글라데시', material: '면 100%', season: '2025 F/W', options: [{name: 'S', price: 69900, stock: 5, stockStatus: '재고'},{name: 'M', price: 69900, stock: 10, stockStatus: '재고'}] },
                { name: '코튼 반팔 티셔츠', brand: 'MUSINSA STANDARD', category: '패션의류 > 남성의류 > 상의 > 반팔티셔츠', price: 19900, origin: '대한민국', material: '면 100%', season: '2025 S/S', options: [{name: 'S', price: 19900, stock: 30, stockStatus: '재고'},{name: 'M', price: 19900, stock: 25, stockStatus: '재고'},{name: 'L', price: 19900, stock: 20, stockStatus: '재고'}] },
                { name: '슬림 슬랙스', brand: 'MUSINSA STANDARD', category: '패션의류 > 남성의류 > 하의 > 슬랙스', price: 49900, origin: '베트남', material: '폴리에스터 65%, 레이온 30%, 스판덱스 5%', season: '2024 F/W', options: [{name: '28', price: 49900, stock: 6, stockStatus: '재고'},{name: '30', price: 49900, stock: 9, stockStatus: '재고'}] }
            ],
            'Nike': [
                { name: '에어 포스 1 07 스니커즈', brand: 'Nike', category: '패션잡화 > 신발 > 스니커즈 > 라이프스타일', price: 109000, origin: '베트남', material: '천연가죽, 합성가죽', season: '2025 S/S', options: [{name: '255', price: 109000, stock: 5, stockStatus: '재고'},{name: '260', price: 109000, stock: 8, stockStatus: '재고'},{name: '265', price: 109000, stock: 10, stockStatus: '재고'},{name: '270', price: 109000, stock: 7, stockStatus: '재고'},{name: '275', price: 109000, stock: 4, stockStatus: '재고'}] },
                { name: '줌 플라이 5 런닝화', brand: 'Nike', category: '스포츠/레저 > 러닝 > 신발 > 런닝화', price: 179000, origin: '중국', material: '합성섬유, 합성수지', season: '2025 S/S', options: [{name: '255', price: 179000, stock: 3, stockStatus: '재고'},{name: '260', price: 179000, stock: 5, stockStatus: '재고'},{name: '265', price: 179000, stock: 6, stockStatus: '재고'}] },
                { name: '드라이핏 런닝 반팔티', brand: 'Nike', category: '스포츠/레저 > 러닝 > 상의 > 반팔티셔츠', price: 39000, origin: '캄보디아', material: '폴리에스터 100%', season: '2025 S/S', options: [{name: 'S', price: 39000, stock: 15, stockStatus: '재고'},{name: 'M', price: 39000, stock: 20, stockStatus: '재고'},{name: 'L', price: 39000, stock: 18, stockStatus: '재고'}] },
                { name: '클럽 풀오버 후디', brand: 'Nike', category: '패션의류 > 남성의류 > 상의 > 후디/집업', price: 89000, origin: '베트남', material: '면 80%, 폴리에스터 20%', season: '2024 F/W', options: [{name: 'S', price: 89000, stock: 8, stockStatus: '재고'},{name: 'M', price: 89000, stock: 12, stockStatus: '재고'},{name: 'L', price: 89000, stock: 6, stockStatus: '재고'}] },
                { name: '에어맥스 90 클래식', brand: 'Nike', category: '패션잡화 > 신발 > 스니커즈 > 레트로', price: 149000, origin: '인도네시아', material: '천연가죽, 합성섬유, 고무', season: '2025 S/S', options: [{name: '255', price: 149000, stock: 4, stockStatus: '재고'},{name: '260', price: 149000, stock: 7, stockStatus: '재고'},{name: '265', price: 149000, stock: 0, stockStatus: '품절'}] }
            ],
            'LOTTEON': [
                { name: '프리미엄 면 스웨터', brand: 'LOTTE', category: '패션의류 > 남성의류 > 상의 > 니트/스웨터', price: 35000, origin: '대한민국', material: '면 60%, 아크릴 40%', season: '2024 F/W', options: [{name: 'S', price: 35000, stock: 10, stockStatus: '재고'},{name: 'M', price: 35000, stock: 15, stockStatus: '재고'},{name: 'L', price: 35000, stock: 8, stockStatus: '재고'}] },
                { name: '데일리 캐주얼 팬츠', brand: 'LOTTE', category: '패션의류 > 남성의류 > 하의 > 면/치노팬츠', price: 29900, origin: '중국', material: '면 97%, 스판덱스 3%', season: '2025 S/S', options: [{name: '28', price: 29900, stock: 12, stockStatus: '재고'},{name: '30', price: 29900, stock: 10, stockStatus: '재고'}] },
                { name: '스트라이프 셔츠', brand: 'LOTTE', category: '패션의류 > 여성의류 > 상의 > 셔츠/블라우스', price: 45000, origin: '베트남', material: '면 100%', season: '2025 S/S', options: [{name: 'S', price: 45000, stock: 6, stockStatus: '재고'},{name: 'M', price: 45000, stock: 9, stockStatus: '재고'}] }
            ],
            'SSG': [
                { name: '리넨 블라우스', brand: 'SSG Fashion', category: '패션의류 > 여성의류 > 상의 > 셔츠/블라우스', price: 59000, origin: '대한민국', material: '리넨 100%', season: '2025 S/S', options: [{name: 'S', price: 59000, stock: 7, stockStatus: '재고'},{name: 'M', price: 59000, stock: 11, stockStatus: '재고'},{name: 'L', price: 59000, stock: 5, stockStatus: '재고'}] },
                { name: '플리츠 미디 스커트', brand: 'SSG Fashion', category: '패션의류 > 여성의류 > 하의 > 스커트', price: 49000, origin: '대한민국', material: '폴리에스터 100%', season: '2025 S/S', options: [{name: 'S', price: 49000, stock: 8, stockStatus: '재고'},{name: 'M', price: 49000, stock: 10, stockStatus: '재고'}] },
                { name: '더블 버튼 코트', brand: 'SSG Fashion', category: '패션의류 > 여성의류 > 아우터 > 코트', price: 189000, origin: '이탈리아', material: '울 70%, 폴리에스터 30%', season: '2024 F/W', options: [{name: 'S', price: 189000, stock: 4, stockStatus: '재고'},{name: 'M', price: 189000, stock: 6, stockStatus: '재고'}] }
            ],
            'ABCmart': [
                { name: 'ABCmart 에어쿠션 스니커즈', brand: 'ABCmart', category: '패션잡화 > 신발 > 스니커즈 > 캐주얼', price: 79000, origin: '중국', material: '합성가죽, 고무', season: '2025 S/S', options: [{name: '240', price: 79000, stock: 5, stockStatus: '재고'},{name: '250', price: 79000, stock: 8, stockStatus: '재고'},{name: '260', price: 79000, stock: 10, stockStatus: '재고'},{name: '270', price: 79000, stock: 6, stockStatus: '재고'}] },
                { name: '레더 로퍼', brand: 'ABCmart', category: '패션잡화 > 신발 > 구두/로퍼 > 클래식로퍼', price: 129000, origin: '포르투갈', material: '천연가죽', season: '2025 S/S', options: [{name: '245', price: 129000, stock: 3, stockStatus: '재고'},{name: '255', price: 129000, stock: 5, stockStatus: '재고'}] }
            ],
            'OliveYoung': [
                { name: '세럼 에센스 50ml', brand: 'COSRX', category: '뷰티 > 스킨케어 > 에센스/세럼 > 수분에센스', price: 32000, origin: '대한민국', material: '화장품 (성분표 별도)', season: '', options: [{name: '기본', price: 32000, stock: 50, stockStatus: '재고'}] },
                { name: '선크림 SPF50+ PA++++', brand: 'Klairs', category: '뷰티 > 스킨케어 > 선케어 > 선크림', price: 22000, origin: '대한민국', material: '화장품 (성분표 별도)', season: '', options: [{name: '50ml', price: 22000, stock: 30, stockStatus: '재고'}] },
                { name: '비타민C 토너 150ml', brand: 'Some By Mi', category: '뷰티 > 스킨케어 > 토너/스킨 > 기능성토너', price: 19800, origin: '대한민국', material: '화장품 (성분표 별도)', season: '', options: [{name: '150ml', price: 19800, stock: 40, stockStatus: '재고'}] }
            ],
            'GSShop': [
                { name: '홈쇼핑 특가 패딩 조끼', brand: 'GSShop', category: '패션의류 > 남성의류 > 아우터 > 패딩/다운', price: 55000, origin: '중국', material: '나일론, 오리털 80%', season: '2024 F/W', options: [{name: 'S', price: 55000, stock: 20, stockStatus: '재고'},{name: 'M', price: 55000, stock: 25, stockStatus: '재고'},{name: 'L', price: 55000, stock: 15, stockStatus: '재고'}] },
                { name: '기능성 언더웨어 세트', brand: 'GSShop', category: '패션의류 > 남성의류 > 이너웨어 > 속옷세트', price: 39900, origin: '대한민국', material: '나일론 85%, 스판덱스 15%', season: '', options: [{name: 'M', price: 39900, stock: 30, stockStatus: '재고'},{name: 'L', price: 39900, stock: 25, stockStatus: '재고'}] }
            ],
            'FOLDERStyle': [
                { name: '스트리트 그래픽 티셔츠', brand: 'FOLDER', category: '패션의류 > 남성의류 > 상의 > 반팔티셔츠', price: 29900, origin: '대한민국', material: '면 100%', season: '2025 S/S', options: [{name: 'S', price: 29900, stock: 12, stockStatus: '재고'},{name: 'M', price: 29900, stock: 18, stockStatus: '재고'},{name: 'L', price: 29900, stock: 10, stockStatus: '재고'}] },
                { name: '힙합 와이드 조거팬츠', brand: 'FOLDER', category: '패션의류 > 남성의류 > 하의 > 조거/트레이닝', price: 49900, origin: '중국', material: '폴리에스터 95%, 스판덱스 5%', season: '2025 S/S', options: [{name: 'S', price: 49900, stock: 8, stockStatus: '재고'},{name: 'M', price: 49900, stock: 12, stockStatus: '재고'}] }
            ],
            'GrandStage': [
                { name: '프리미엄 드레스 슈즈', brand: 'GrandStage', category: '패션잡화 > 신발 > 드레스화 > 옥스포드', price: 159000, origin: '이탈리아', material: '천연가죽, 고무', season: '2025 S/S', options: [{name: '255', price: 159000, stock: 3, stockStatus: '재고'},{name: '260', price: 159000, stock: 5, stockStatus: '재고'}] }
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

    /**
     * 카테고리 문자열을 대분류~세분류 필드로 분리
     * @param {string} catStr - '대분류 > 중분류 > 소분류 > 세분류'
     * @returns {{ category1, category2, category3, category4 }}
     */
    // 브랜드 첫 글자를 이용한 SVG 플레이스홀더 이미지 생성 (외부 서비스 미사용)
    _genPlaceholderImg(brand) {
        const ch = (brand || '?')[0]
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="200" height="200" fill="#1A1A1A"/><text x="100" y="140" text-anchor="middle" font-size="100" font-family="sans-serif" fill="#FF8C00">${ch}</text></svg>`
        return 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svg)))
    }

    _parseCategoryLevels(catStr) {
        const parts = (catStr || '').split(/\s*>\s*/)
        return {
            category1: parts[0] || '',
            category2: parts[1] || '',
            category3: parts[2] || '',
            category4: parts[3] || ''
        }
    }

    /**
     * 가격/재고 스냅샷 생성
     * 수집 시점의 가격과 옵션별 재고 상태를 기록
     */
    _createPriceSnapshot(product) {
        const snapshot = {
            date: new Date().toISOString(),
            price: product.originalPrice || product.salePrice || product.price || 0,
            discountRate: product.discountRate || 0,
            options: (product.options || []).map(opt => ({
                name: opt.name || opt.optionName || '',
                price: opt.price || product.originalPrice || product.salePrice || 0,
                // 재고: 숫자면 그대로, 품절이면 0, 알 수 없으면 null
                stock: typeof opt.originalStock === 'number' ? opt.originalStock
                    : opt.isSoldOut ? 0
                    : opt.stockStatus === 'soldout' ? 0
                    : null,
                isSoldOut: opt.isSoldOut || false
            }))
        }
        return snapshot
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
                const saveData = { ...p, status: 'saved' }
                saved.push(saveData)
            }
        }
        await storage.batchSave('collectedProducts', saved)

        // products 스토어에도 브릿지 저장 (다른 모듈과 연동)
        for (const p of saved) {
            try {
                const srcUrl = p.sourceUrl || p.siteProductUrl || ''
                const existingInProducts = await storage.getByIndex('products', 'sourceUrl', srcUrl)

                if (existingInProducts && existingInProducts.length > 0) {
                    // 기존 상품 업데이트: 수집 데이터로 누락 필드 보강
                    const existing = existingInProducts[0]
                    const snapshot = this._createPriceSnapshot(p)
                    const updatedFields = {
                        category: p.category || existing.category || '',
                        category1: p.category1 || existing.category1 || '',
                        category2: p.category2 || existing.category2 || '',
                        category3: p.category3 || existing.category3 || '',
                        category4: p.category4 || existing.category4 || '',
                        options: (p.options && p.options.length > 0) ? p.options.map(o => ({ ...o })) : existing.options || [],
                        origin: p.origin || existing.origin || '',
                        material: p.material || existing.material || '',
                        manufacturer: p.manufacturer || existing.manufacturer || '',
                        season: p.season || existing.season || '',
                        styleCode: p.styleCode || existing.styleCode || '',
                        kcCert: p.kcCert || existing.kcCert || '',
                        tags: (p.tags && p.tags.length > 0) ? p.tags : existing.tags || [],
                        brand: p.brand || existing.brand || '',
                        images: (p.images && p.images.length > 0) ? p.images : existing.images || [],
                        detailImages: (p.detailImages && p.detailImages.length > 0) ? p.detailImages : existing.detailImages || [],
                        detailHtml: p.detailHtml || existing.detailHtml || '',
                        discountRate: p.discountRate || existing.discountRate || 0,
                        sourcePrice: p.originalPrice || existing.sourcePrice || 0,
                        cost: p.originalPrice || existing.cost || 0,
                        siteProductId: p.siteProductId || existing.siteProductId || '',
                        sourceSite: p.sourceSite || existing.sourceSite || '',
                        collectedProductId: p.id,
                        priceHistory: [...(existing.priceHistory || []), snapshot],
                        updatedAt: new Date().toISOString()
                    }
                    await storage.save('products', { ...existing, ...updatedFields })
                    // 메모리 동기화
                    if (typeof productManager !== 'undefined') {
                        const idx = productManager.products.findIndex(pp => pp.id === existing.id)
                        if (idx >= 0) Object.assign(productManager.products[idx], updatedFields)
                    }
                } else {
                    // 신규 상품 생성
                    const bridgeProduct = {
                        id: 'prod_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
                        name: p.name,
                        nameEn: p.nameEn || '',
                        nameJa: p.nameJa || '',
                        category: p.category,
                        category1: p.category1 || '',
                        category2: p.category2 || '',
                        category3: p.category3 || '',
                        category4: p.category4 || '',
                        sourceUrl: srcUrl,
                        sourcePrice: p.originalPrice,
                        cost: p.originalPrice,
                        marginRate: 15,
                        salePrice: Math.ceil(p.originalPrice * 1.15),
                        description: '',
                        status: 'active',
                        images: p.images || [],
                        detailImages: p.detailImages || [],
                        detailHtml: p.detailHtml || '',
                        options: (p.options || []).map(o => ({ ...o })),
                        brand: p.brand || '',
                        brandCode: p.brandCode || '',
                        sourceSite: p.sourceSite,
                        siteProductId: p.siteProductId || '',
                        searchFilterId: p.searchFilterId || null,
                        collectedProductId: p.id,
                        origin: p.origin || '',
                        material: p.material || '',
                        manufacturer: p.manufacturer || '',
                        season: p.season || '',
                        styleCode: p.styleCode || '',
                        kcCert: p.kcCert || '',
                        tags: p.tags || [],
                        discountRate: p.discountRate || 0,
                        priceHistory: [this._createPriceSnapshot(p)],
                        createdAt: new Date().toISOString(),
                        updatedAt: new Date().toISOString()
                    }
                    await storage.save('products', bridgeProduct)
                    if (typeof productManager !== 'undefined') {
                        productManager.products.push(bridgeProduct)
                    }
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

        // 이미 저장된 수량을 오프셋으로 전달 (재수집 시 중복 범위 회피)
        const savedOffset = filter.savedCount || 0

        // 수집 실행
        const products = await this.collectFromUrl(url, { ...options, savedOffset })
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
     * 필터별 savedCount 일괄 업데이트 (searchFilterId 기준)
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
        const log = (msg, type = 'info') => {
            console.log(`[자동저장] ${msg}`)
            if (this.onLog) this.onLog(msg, type)
        }

        const target = filter.collectCount || 100
        const already = filter.savedCount || 0

        if (already >= target) {
            return { saved: 0, duplicates: 0, skipped: 0, alreadyFull: true }
        }

        const needed = target - already
        log(`필요 수량: ${needed}개 (현재 ${already}/${target})`)

        // 잔존 데이터 정리: savedCount가 0인데 collectedProducts에 데이터가 남아있으면 삭제
        if (already === 0) {
            const orphaned = await storage.getByIndex('collectedProducts', 'searchFilterId', filter.id)
            if (orphaned.length > 0) {
                for (const o of orphaned) {
                    await storage.delete('collectedProducts', o.id)
                }
                log(`잔존 데이터 ${orphaned.length}개 정리 완료`)
            }
        }

        // 현재 필터 내 기존 siteProductId (같은 그룹 내 중복만 체크)
        const existingList = await storage.getByIndex('collectedProducts', 'searchFilterId', filter.id)
        const existingIds = new Set(existingList.map(p => p.siteProductId))
        if (existingIds.size > 0) log(`기존 저장 ${existingIds.size}개 (중복 체크용)`)

        // 수집 실행 — 중복 여유분 포함하여 넉넉히 요청
        const collectTarget = Math.min(Math.ceil(needed * 1.5), needed + 50)
        const products = await this.collectFromUrl(filter.searchUrl, { count: collectTarget })
        log(`수집 결과: ${products.length}개 → 저장 시작`)

        let saved = 0
        let duplicates = 0

        // 시뮬레이션 모드 여부 확인 (실제수집은 수집 단계에서 이미 딜레이 적용됨)
        const isSimulation = !(this.realModeEnabled &&
            this._isMusinsaUrl(filter.searchUrl || '') &&
            this.proxyAvailable)

        for (const p of products) {
            if (saved >= needed) break

            // 시뮬레이션 모드: 개당 0.5~1.5초 딜레이 (실제 수집 속도 시뮬레이션)
            if (isSimulation) {
                await this._delay(500 + Math.random() * 1000)
            }

            if (existingIds.has(p.siteProductId)) {
                duplicates++
                log(`  중복 건너뜀: ${p.name?.slice(0, 30)}`, 'warn')
                continue
            }

            const saveData = { ...p, searchFilterId: filter.id, status: 'saved', savedAt: new Date().toISOString() }
            await storage.save('collectedProducts', saveData)
            existingIds.add(p.siteProductId)
            saved++
            log(`  저장 ${saved}/${needed}: ${p.name?.slice(0, 40)} | ${(p.salePrice || 0).toLocaleString()}원`, 'success')

            // products 스토어에 bridge 저장
            try {
                const srcUrl = saveData.sourceUrl || ''
                const existingInProducts = srcUrl
                    ? await storage.getByIndex('products', 'sourceUrl', srcUrl)
                    : []

                if (existingInProducts && existingInProducts.length > 0) {
                    // 기존 상품 업데이트: 수집 데이터로 누락 필드 보강
                    const existing = existingInProducts[0]
                    const snapshot = this._createPriceSnapshot(saveData)
                    const updatedFields = {
                        category: saveData.category || existing.category || '',
                        category1: saveData.category1 || existing.category1 || '',
                        category2: saveData.category2 || existing.category2 || '',
                        category3: saveData.category3 || existing.category3 || '',
                        category4: saveData.category4 || existing.category4 || '',
                        options: (saveData.options && saveData.options.length > 0) ? saveData.options.map(o => ({ ...o })) : existing.options || [],
                        origin: saveData.origin || existing.origin || '',
                        material: saveData.material || existing.material || '',
                        manufacturer: saveData.manufacturer || existing.manufacturer || '',
                        season: saveData.season || existing.season || '',
                        styleCode: saveData.styleCode || existing.styleCode || '',
                        kcCert: saveData.kcCert || existing.kcCert || '',
                        tags: (saveData.tags && saveData.tags.length > 0) ? saveData.tags : existing.tags || [],
                        brand: saveData.brand || existing.brand || '',
                        images: (saveData.images && saveData.images.length > 0) ? saveData.images : existing.images || [],
                        detailImages: (saveData.detailImages && saveData.detailImages.length > 0) ? saveData.detailImages : existing.detailImages || [],
                        detailHtml: saveData.detailHtml || existing.detailHtml || '',
                        discountRate: saveData.discountRate || existing.discountRate || 0,
                        sourcePrice: saveData.originalPrice || saveData.salePrice || existing.sourcePrice || 0,
                        cost: saveData.originalPrice || saveData.salePrice || existing.cost || 0,
                        siteProductId: saveData.siteProductId || existing.siteProductId || '',
                        sourceSite: saveData.sourceSite || existing.sourceSite || '',
                        collectedProductId: saveData.id,
                        priceHistory: [...(existing.priceHistory || []), snapshot],
                        updatedAt: new Date().toISOString()
                    }
                    await storage.save('products', { ...existing, ...updatedFields })
                    if (typeof productManager !== 'undefined') {
                        const idx = productManager.products.findIndex(pp => pp.id === existing.id)
                        if (idx >= 0) Object.assign(productManager.products[idx], updatedFields)
                    }
                } else {
                    // 신규 상품 생성
                    const cost = saveData.originalPrice || saveData.salePrice || 0
                    const bridgeProduct = {
                        id: 'prod_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
                        name: saveData.name,
                        nameEn: saveData.nameEn || '',
                        nameJa: saveData.nameJa || '',
                        category: saveData.category || '',
                        category1: saveData.category1 || '',
                        category2: saveData.category2 || '',
                        category3: saveData.category3 || '',
                        category4: saveData.category4 || '',
                        sourceUrl: srcUrl,
                        sourcePrice: cost,
                        cost,
                        marginRate: 15,
                        salePrice: Math.ceil(cost * 1.15),
                        description: '',
                        status: 'active',
                        images: saveData.images || [],
                        detailImages: saveData.detailImages || [],
                        detailHtml: saveData.detailHtml || '',
                        options: (saveData.options || []).map(o => ({ ...o })),
                        brand: saveData.brand || '',
                        brandCode: saveData.brandCode || '',
                        sourceSite: saveData.sourceSite || '',
                        siteProductId: saveData.siteProductId || '',
                        searchFilterId: filter.id,
                        collectedProductId: saveData.id,
                        origin: saveData.origin || '',
                        material: saveData.material || '',
                        manufacturer: saveData.manufacturer || '',
                        season: saveData.season || '',
                        styleCode: saveData.styleCode || '',
                        kcCert: saveData.kcCert || '',
                        tags: saveData.tags || [],
                        discountRate: saveData.discountRate || 0,
                        priceHistory: [this._createPriceSnapshot(saveData)],
                        createdAt: new Date().toISOString(),
                        updatedAt: new Date().toISOString()
                    }
                    await storage.save('products', bridgeProduct)
                    if (typeof productManager !== 'undefined') {
                        productManager.products.push(bridgeProduct)
                    }
                }
            } catch (e) {
                log(`  bridge 저장 실패: ${e.message}`, 'warn')
            }
        }

        log(`저장 완료: ${saved}개 저장${duplicates > 0 ? `, ${duplicates}개 중복 제외` : ''}`)

        await this.updateFilter(filter.id, {
            savedCount: already + saved,
            lastCollectedAt: new Date().toISOString()
        })
        await this.loadFilters()

        return { saved, duplicates, alreadyFull: false }
    }
}

// 글로벌 인스턴스
const collectorManager = new CollectorManager()
