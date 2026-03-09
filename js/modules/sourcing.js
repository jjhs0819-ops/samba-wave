/**
 * 소싱 추적 모듈
 * 소싱사이트의 가격/재고 변동 모니터링
 */

class SourcingManager {
    constructor() {
        this.sourcingSites = [];
        this.priceHistory = [];
    }

    /**
     * 모든 소싱사이트 조회
     */
    async loadSourcingSites() {
        try {
            this.sourcingSites = await storage.getAll('sourcingSites');
            return this.sourcingSites;
        } catch (error) {
            console.error('소싱사이트 로드 실패:', error);
            return [];
        }
    }

    /**
     * 소싱사이트 추가
     */
    async addSourcingSite(siteData) {
        try {
            const site = {
                id: this.generateId(),
                name: siteData.name,
                url: siteData.url,
                type: siteData.type, // "brand", "marketplace", "wholesale"
                status: 'active',
                lastChecked: null,
                createdAt: new Date().toISOString()
            };

            await storage.save('sourcingSites', site);
            this.sourcingSites.push(site);
            app.showNotification('소싱사이트가 추가되었습니다', 'success');
            return site;
        } catch (error) {
            console.error('소싱사이트 추가 실패:', error);
            app.showNotification('소싱사이트 추가에 실패했습니다', 'error');
            return null;
        }
    }

    /**
     * 소싱사이트 삭제
     */
    async deleteSourcingSite(id) {
        try {
            await storage.delete('sourcingSites', id);
            this.sourcingSites = this.sourcingSites.filter(s => s.id !== id);
            app.showNotification('소싱사이트가 삭제되었습니다', 'success');
            return true;
        } catch (error) {
            console.error('소싱사이트 삭제 실패:', error);
            return false;
        }
    }

    /**
     * 상품 가격 추적 기록 추가
     */
    async trackProductPrice(productId, siteId, currentPrice, stock) {
        try {
            const tracking = {
                id: this.generateId(),
                productId,
                siteId,
                price: currentPrice,
                stock,
                timestamp: new Date().toISOString()
            };

            // 로컬 배열에 저장 (장기 보관은 따로)
            this.priceHistory.push(tracking);

            // 변동 감지
            return this.detectPriceChange(productId, siteId, currentPrice);
        } catch (error) {
            console.error('가격 추적 실패:', error);
            return null;
        }
    }

    /**
     * 가격 변동 감지
     */
    detectPriceChange(productId, siteId, currentPrice) {
        // 같은 상품의 이전 가격 찾기
        const history = this.priceHistory
            .filter(h => h.productId === productId && h.siteId === siteId)
            .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

        if (history.length < 2) return null;

        const previousPrice = history[1].price;
        const change = currentPrice - previousPrice;
        const changePercent = ((change / previousPrice) * 100).toFixed(2);

        return {
            change,
            changePercent,
            type: change < 0 ? 'down' : change > 0 ? 'up' : 'same',
            alert: Math.abs(parseFloat(changePercent)) >= 5 // 5% 이상 변동시 알림
        };
    }

    /**
     * 상품의 가격 추이 조회
     */
    getPriceHistory(productId, siteId, days = 30) {
        const cutoffDate = new Date();
        cutoffDate.setDate(cutoffDate.getDate() - days);

        return this.priceHistory
            .filter(h =>
                h.productId === productId &&
                h.siteId === siteId &&
                new Date(h.timestamp) >= cutoffDate
            )
            .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    }

    /**
     * 재고 부족 상품 조회
     */
    getLowStockProducts(threshold = 5) {
        const products = productManager.products;
        const alerts = [];

        products.forEach(product => {
            const latestTracking = this.priceHistory
                .filter(h => h.productId === product.id)
                .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))[0];

            if (latestTracking && latestTracking.stock <= threshold) {
                alerts.push({
                    productId: product.id,
                    productName: product.name,
                    stock: latestTracking.stock,
                    lastUpdated: latestTracking.timestamp
                });
            }
        });

        return alerts;
    }

    /**
     * 가격이 내려간 상품
     */
    getPriceDropProducts(days = 7) {
        const cutoffDate = new Date();
        cutoffDate.setDate(cutoffDate.getDate() - days);

        const drops = [];
        const products = productManager.products;

        products.forEach(product => {
            const history = this.priceHistory
                .filter(h => h.productId === product.id && new Date(h.timestamp) >= cutoffDate)
                .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

            if (history.length >= 2) {
                const oldPrice = history[0].price;
                const newPrice = history[history.length - 1].price;
                const change = newPrice - oldPrice;

                if (change < 0) {
                    drops.push({
                        productId: product.id,
                        productName: product.name,
                        oldPrice,
                        newPrice,
                        change,
                        changePercent: ((change / oldPrice) * 100).toFixed(2)
                    });
                }
            }
        });

        return drops;
    }

    /**
     * 가격 모니터링 요약
     */
    getPriceMonitoringSummary() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        const todayHistory = this.priceHistory.filter(h => {
            const hDate = new Date(h.timestamp);
            hDate.setHours(0, 0, 0, 0);
            return hDate.getTime() === today.getTime();
        });

        const priceAlerts = todayHistory.filter(h => {
            const change = this.detectPriceChange(h.productId, h.siteId, h.price);
            return change && change.alert;
        }).length;

        return {
            totalTracked: this.priceHistory.length,
            todayUpdates: todayHistory.length,
            priceAlerts: priceAlerts,
            lowStockCount: this.getLowStockProducts().length
        };
    }

    /**
     * ID 생성
     */
    generateId() {
        return 'src_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    /**
     * 소싱사이트 유형별 라벨
     */
    getSiteTypeLabel(type) {
        const labels = {
            'brand': '브랜드 직영몰',
            'marketplace': '종합몰',
            'wholesale': '도매사이트'
        };
        return labels[type] || '기타';
    }
}

// 글로벌 인스턴스
const sourcingManager = new SourcingManager();
