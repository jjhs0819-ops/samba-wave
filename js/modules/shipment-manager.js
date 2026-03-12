/**
 * 상품 전송 관리 (ShipmentManager)
 * 마켓 계정별 상품 업데이트 & 전송 (시뮬레이션 모드)
 */

class ShipmentManager {
    constructor() {
        this.shipments = []
        this.isProcessing = false
    }

    async init() {
        await this.loadShipments()
    }

    async loadShipments() {
        this.shipments = await storage.getAll('shipments')
        return this.shipments
    }

    // ==================== 전송 실행 ====================

    /**
     * 상품 업데이트 & 마켓 전송 시작
     * @param {string[]} productIds - 전송할 상품 ID 목록
     * @param {string[]} updateItems - 업데이트 항목 ['price', 'stock', 'image', 'description']
     * @param {string[]} targetAccountIds - 전송할 마켓 계정 ID 목록
     * @param {Function} onProgress - 진행 콜백 (progress, total, current)
     */
    async startUpdate(productIds, updateItems, targetAccountIds, onProgress) {
        if (this.isProcessing) throw new Error('이미 전송 중입니다')
        this.isProcessing = true

        const total = productIds.length
        let processed = 0

        try {
            for (const productId of productIds) {
                // products / collectedProducts 양쪽에서 상품 조회 (저장소 키도 함께 추적)
                let prdStoreKey = 'products'
                let prd = await storage.get('products', productId)
                if (!prd) {
                    prd = await storage.get('collectedProducts', productId)
                    prdStoreKey = 'collectedProducts'
                }

                // marketEnabled 필터 적용: OFF인 계정은 전송 대상에서 제외
                let filteredAccounts = [...targetAccountIds]
                if (prd && prd.marketEnabled) {
                    filteredAccounts = filteredAccounts.filter(accId => {
                        // accountId로 marketName 조회
                        const acc = typeof accountManager !== 'undefined'
                            ? accountManager.accounts.find(a => a.id === accId)
                            : null
                        const key = acc ? (acc.id || acc.marketName) : accId
                        return prd.marketEnabled[key] !== false  // undefined는 기본 ON
                    })
                }

                // 정책 가격 반영: appliedPolicyId가 있으면 마켓가격 계산 후 저장
                const productForPolicy = prd && prd.appliedPolicyId ? prd : null
                if (productForPolicy && typeof policyManager !== 'undefined') {
                    const marketPrices = {}
                    for (const accountId of filteredAccounts) {
                        marketPrices[accountId] = policyManager.calculateMarketPrice(
                            productForPolicy.originalPrice || productForPolicy.salePrice || 0,
                            productForPolicy.appliedPolicyId
                        )
                    }
                    const updatedWithPrices = { ...productForPolicy, marketPrices, updatedAt: new Date().toISOString() }
                    await storage.save(prdStoreKey, updatedWithPrices)
                }

                const shipment = await this._createShipment(productId, filteredAccounts, updateItems)

                // 소싱처 정보 업데이트 (시뮬레이션)
                await this._updateProduct(shipment.id, productId, updateItems)

                // 마켓 전송 (시뮬레이션, OFF 계정 제외된 목록으로 전송)
                for (const accountId of filteredAccounts) {
                    await this._transmitToAccount(shipment.id, productId, accountId)
                }

                // 완료 처리
                await this._completeShipment(shipment.id)
                processed++
                if (onProgress) onProgress(processed, total, productId)
            }
        } finally {
            this.isProcessing = false
        }

        return processed
    }

    /**
     * Shipment 레코드 생성
     */
    async _createShipment(productId, targetAccountIds, updateItems) {
        const shipment = {
            id: 'shp_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
            productId,
            targetAccountIds: [...targetAccountIds],
            updateItems: [...updateItems],
            status: 'pending',
            updateResult: {},
            transmitResult: {},
            error: null,
            createdAt: new Date().toISOString(),
            completedAt: null
        }
        await storage.save('shipments', shipment)
        this.shipments.push(shipment)
        return shipment
    }

    /**
     * 소싱처 상품 정보 업데이트 (시뮬레이션)
     */
    async _updateProduct(shipmentId, productId, updateItems) {
        const shipment = await storage.get('shipments', shipmentId)
        if (!shipment) return

        // 업데이트 중 상태로 변경
        await this._updateShipmentStatus(shipmentId, 'updating')

        // 시뮬레이션 딜레이
        await this._delay(300 + Math.random() * 400)

        // 결과 시뮬레이션 (95% 성공률)
        const result = {}
        for (const item of updateItems) {
            result[item] = Math.random() > 0.05 ? 'success' : 'failed'
        }

        const updated = {
            ...shipment,
            status: 'transmitting',
            updateResult: result,
            updatedAt: new Date().toISOString()
        }
        await storage.save('shipments', updated)
        const idx = this.shipments.findIndex(s => s.id === shipmentId)
        if (idx !== -1) this.shipments[idx] = updated
    }

    /**
     * 마켓 계정에 전송 (시뮬레이션)
     */
    async _transmitToAccount(shipmentId, productId, accountId) {
        const shipment = await storage.get('shipments', shipmentId)
        if (!shipment) return

        await this._delay(200 + Math.random() * 300)

        // 카테고리 매핑 조회
        let mappedCategory = null
        const product = await storage.get('collectedProducts', productId)
        if (product && typeof categoryManager !== 'undefined') {
            const mapping = categoryManager.findMapping(product.sourceSite, product.category)
            if (mapping) mappedCategory = mapping.targetMappings
        }

        // 시뮬레이션 결과 (90% 성공률)
        const success = Math.random() > 0.10

        // 해외 마켓 여부 판단 (영문/일어명 검증용)
        const account = typeof accountManager !== 'undefined'
            ? accountManager.accounts.find(a => a.id === accountId)
            : null
        const overseasMarkets = ['ebay', 'lazada', 'shopee', 'qoo10', 'quten']
        const isOverseas = account && overseasMarkets.includes(account.marketType)

        // 해외 마켓 전송 성공 시 영문/일어명 확인 로그
        if (isOverseas && success && product) {
            console.log(`[해외전송] 마켓: ${account.marketType} | ID: ${productId}`)
            console.log(`  EN: ${product.nameEn || '(미입력)'}`)
            console.log(`  JP: ${product.nameJa || '(미입력)'}`)
            if (!product.nameEn) console.warn('  ⚠ 영문 상품명(nameEn)이 없습니다. 역직구 노출에 영향을 줄 수 있습니다.')
        }

        const updated = {
            ...shipment,
            transmitResult: {
                ...shipment.transmitResult,
                [accountId]: success ? 'success' : 'failed' // 항상 문자열 'success'/'failed' 유지
            },
            // 카테고리 매핑 정보 저장
            mappedCategories: {
                ...(shipment.mappedCategories || {}),
                [accountId]: mappedCategory
            }
        }
        await storage.save('shipments', updated)
        const idx = this.shipments.findIndex(s => s.id === shipmentId)
        if (idx !== -1) this.shipments[idx] = updated

        // 상품 registeredAccounts 업데이트 (위에서 조회한 product 재사용)
        if (success) {
            if (product) {
                const registeredAccounts = product.registeredAccounts || []
                if (!registeredAccounts.includes(accountId)) {
                    const updatedProduct = {
                        ...product,
                        registeredAccounts: [...registeredAccounts, accountId],
                        status: 'registered',
                        updatedAt: new Date().toISOString()
                    }
                    await storage.save('collectedProducts', updatedProduct)
                }
            }
        }
    }

    /**
     * Shipment 완료 처리
     */
    async _completeShipment(shipmentId) {
        const shipment = await storage.get('shipments', shipmentId)
        if (!shipment) return

        // 전체 성공 여부 판단
        const transmitValues = Object.values(shipment.transmitResult || {})
        const allSuccess = transmitValues.length > 0 && transmitValues.every(v => v === 'success')
        const anyFailed = transmitValues.some(v => v === 'failed')

        const status = allSuccess ? 'completed' : (anyFailed ? 'partial' : 'completed')

        const updated = {
            ...shipment,
            status,
            completedAt: new Date().toISOString()
        }
        await storage.save('shipments', updated)
        const idx = this.shipments.findIndex(s => s.id === shipmentId)
        if (idx !== -1) this.shipments[idx] = updated

        // 전송 성공한 계정에 대해 주문 자동 생성
        if (typeof orderManager !== 'undefined' && (status === 'completed' || status === 'partial')) {
            const product = await storage.get('collectedProducts', shipment.productId)
            for (const accountId of (shipment.targetAccountIds || [])) {
                if ((updated.transmitResult || {})[accountId] === 'success') {
                    const account = typeof accountManager !== 'undefined'
                        ? accountManager.accounts.find(a => a.id === accountId)
                        : null
                    try {
                        await orderManager.addOrder({
                            channelId: accountId,
                            channelName: account ? account.accountLabel : accountId,
                            productId: shipment.productId,
                            productName: product ? product.name : '',
                            customerName: '위탁판매',
                            customerPhone: '',
                            salePrice: product ? (product.marketPrices?.[accountId] || product.salePrice || 0) : 0,
                            cost: product ? product.originalPrice : 0,
                            feeRate: 0,
                            status: 'pending',
                            source: 'shipment',
                            shipmentId: shipment.id
                        })
                    } catch (e) {
                        console.warn('전송 완료 후 주문 자동 생성 실패:', e)
                    }
                }
            }
        }
    }

    /**
     * Shipment 상태 업데이트
     */
    async _updateShipmentStatus(shipmentId, status) {
        const shipment = await storage.get('shipments', shipmentId)
        if (!shipment) return
        const updated = { ...shipment, status }
        await storage.save('shipments', updated)
        const idx = this.shipments.findIndex(s => s.id === shipmentId)
        if (idx !== -1) this.shipments[idx] = updated
    }

    // ==================== 조회 ====================

    async getTransmitLog(productId) {
        return this.shipments.filter(s => s.productId === productId)
    }

    async retransmit(shipmentId) {
        const shipment = this.shipments.find(s => s.id === shipmentId)
        if (!shipment) return null

        // 실패한 계정만 재전송
        const failedAccounts = Object.entries(shipment.transmitResult || {})
            .filter(([, v]) => v === 'failed')
            .map(([k]) => k)

        if (failedAccounts.length === 0) return shipment

        for (const accountId of failedAccounts) {
            await this._transmitToAccount(shipmentId, shipment.productId, accountId)
        }
        await this._completeShipment(shipmentId)
        return await storage.get('shipments', shipmentId)
    }

    async deleteFromMarket(productId, accountId) {
        // 시뮬레이션: 마켓 상품 삭제
        const product = await storage.get('collectedProducts', productId)
        if (product) {
            const registeredAccounts = (product.registeredAccounts || []).filter(id => id !== accountId)
            const updated = {
                ...product,
                registeredAccounts,
                status: registeredAccounts.length === 0 ? 'saved' : 'registered',
                updatedAt: new Date().toISOString()
            }
            await storage.save('collectedProducts', updated)
        }
        return true
    }

    getStatusLabel(status) {
        const labels = {
            'pending': '대기중',
            'updating': '업데이트중',
            'transmitting': '전송중',
            'completed': '완료',
            'partial': '부분완료',
            'failed': '실패'
        }
        return labels[status] || status
    }

    getStatusStyle(status) {
        const styles = {
            'pending': 'background:rgba(100,100,100,0.2); color:#888;',
            'updating': 'background:rgba(76,154,255,0.15); color:#4C9AFF;',
            'transmitting': 'background:rgba(255,211,61,0.15); color:#FFD93D;',
            'completed': 'background:rgba(81,207,102,0.15); color:#51CF66;',
            'partial': 'background:rgba(255,140,0,0.15); color:#FF8C00;',
            'failed': 'background:rgba(255,107,107,0.15); color:#FF6B6B;'
        }
        return styles[status] || ''
    }

    _delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms))
    }
}

// 글로벌 인스턴스
const shipmentManager = new ShipmentManager()
