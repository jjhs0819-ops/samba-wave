/**
 * 상품 관리 모듈
 * 상품 CRUD, 가공, 추적 기능
 */

class ProductManager {
    constructor() {
        this.products = [];
        this.currentEditId = null;
    }

    /**
     * 모든 상품 조회
     */
    async loadProducts() {
        try {
            this.products = await storage.getAll('products');
            return this.products;
        } catch (error) {
            console.error('상품 로드 실패:', error);
            return [];
        }
    }

    /**
     * 상품 추가
     */
    async addProduct(productData) {
        try {
            const product = {
                id: this.generateId(),
                sourceUrl: productData.sourceUrl,
                sourcePrice: parseFloat(productData.sourcePrice),
                name: productData.name,
                description: productData.description || '',
                category: productData.category || '',
                images: productData.images || [],
                options: productData.options || [],
                cost: parseFloat(productData.cost),
                marginRate: parseFloat(productData.marginRate) || 30,
                channels: {},
                status: 'active',
                trackingHistory: [],
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString()
            };

            await storage.save('products', product);
            this.products.push(product);
            app.showNotification('상품이 추가되었습니다', 'success');
            return product;
        } catch (error) {
            console.error('상품 추가 실패:', error);
            app.showNotification('상품 추가에 실패했습니다', 'error');
            return null;
        }
    }

    /**
     * 상품 수정
     */
    async updateProduct(id, updates) {
        try {
            const product = await storage.get('products', id);
            if (!product) {
                app.showNotification('상품을 찾을 수 없습니다', 'error');
                return null;
            }

            const updated = {
                ...product,
                ...updates,
                updatedAt: new Date().toISOString()
            };

            await storage.save('products', updated);
            const index = this.products.findIndex(p => p.id === id);
            if (index !== -1) {
                this.products[index] = updated;
            }
            app.showNotification('상품이 수정되었습니다', 'success');
            return updated;
        } catch (error) {
            console.error('상품 수정 실패:', error);
            app.showNotification('상품 수정에 실패했습니다', 'error');
            return null;
        }
    }

    /**
     * 상품 삭제
     */
    async deleteProduct(id) {
        try {
            await storage.delete('products', id);
            this.products = this.products.filter(p => p.id !== id);
            app.showNotification('상품이 삭제되었습니다', 'success');
            return true;
        } catch (error) {
            console.error('상품 삭제 실패:', error);
            app.showNotification('상품 삭제에 실패했습니다', 'error');
            return false;
        }
    }

    /**
     * 상품별 판매 가격 계산
     */
    calculateChannelPrice(cost, marginRate) {
        return Math.ceil(cost / (1 - marginRate / 100));
    }

    /**
     * 판매처별 수수료 반영 계산
     */
    calculateProfit(salePrice, cost, feeRate) {
        const revenue = salePrice * (1 - feeRate / 100);
        const profit = revenue - cost;
        const profitRate = ((profit / revenue) * 100).toFixed(2);
        return { revenue, profit, profitRate };
    }

    /**
     * ID 생성
     */
    generateId() {
        return 'prod_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    /**
     * 상품 검색
     */
    searchProducts(query) {
        return this.products.filter(product =>
            product.name.toLowerCase().includes(query.toLowerCase()) ||
            product.sourceUrl.toLowerCase().includes(query.toLowerCase())
        );
    }

    /**
     * 상품 필터링
     */
    filterByStatus(status) {
        return this.products.filter(product => product.status === status);
    }

    /**
     * 가격 변동 추적
     */
    trackPriceChange(productId, currentPrice) {
        const product = this.products.find(p => p.id === productId);
        if (!product) return null;

        const priceChange = currentPrice - product.sourcePrice;
        const changePercent = ((priceChange / product.sourcePrice) * 100).toFixed(2);

        if (!product.trackingHistory) {
            product.trackingHistory = [];
        }

        product.trackingHistory.push({
            date: new Date().toISOString(),
            price: currentPrice,
            changePercent: parseFloat(changePercent)
        });

        return { priceChange, changePercent };
    }
}

// 글로벌 인스턴스
const productManager = new ProductManager();
