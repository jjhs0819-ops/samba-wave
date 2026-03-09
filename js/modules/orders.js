/**
 * 주문/CS 관리 모듈
 * 주문 CRUD, 배송 추적, 반품 관리
 */

class OrderManager {
    constructor() {
        this.orders = [];
    }

    /**
     * 모든 주문 조회
     */
    async loadOrders() {
        try {
            this.orders = await storage.getAll('orders');
            return this.orders.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
        } catch (error) {
            console.error('주문 로드 실패:', error);
            return [];
        }
    }

    /**
     * 주문 추가
     */
    async addOrder(orderData) {
        try {
            const order = {
                id: this.generateId(),
                orderNumber: this.generateOrderNumber(),
                channelId: orderData.channelId,
                productId: orderData.productId,
                quantity: parseInt(orderData.quantity) || 1,
                customerName: orderData.customerName,
                customerPhone: orderData.customerPhone || '',
                customerAddress: orderData.customerAddress || '',
                salePrice: parseFloat(orderData.salePrice),
                cost: parseFloat(orderData.cost),
                feeRate: parseFloat(orderData.feeRate) || 0,
                status: 'pending', // pending, shipped, delivered, cancelled, returned
                paymentStatus: 'completed', // completed, pending, failed
                shippingStatus: 'preparing', // preparing, shipped, delivered
                shippingCompany: orderData.shippingCompany || '',
                trackingNumber: orderData.trackingNumber || '',
                notes: orderData.notes || '',
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString(),
                shippedAt: null,
                deliveredAt: null
            };

            // 수익 계산
            order.revenue = order.salePrice * (1 - order.feeRate / 100);
            order.profit = order.revenue - order.cost;
            order.profitRate = ((order.profit / order.revenue) * 100).toFixed(2);

            await storage.save('orders', order);
            this.orders.push(order);
            app.showNotification('주문이 추가되었습니다', 'success');
            return order;
        } catch (error) {
            console.error('주문 추가 실패:', error);
            app.showNotification('주문 추가에 실패했습니다', 'error');
            return null;
        }
    }

    /**
     * 주문 상태 수정
     */
    async updateOrderStatus(id, newStatus) {
        try {
            const order = await storage.get('orders', id);
            if (!order) {
                app.showNotification('주문을 찾을 수 없습니다', 'error');
                return null;
            }

            order.status = newStatus;
            order.updatedAt = new Date().toISOString();

            if (newStatus === 'shipped') {
                order.shippedAt = new Date().toISOString();
                order.shippingStatus = 'shipped';
            } else if (newStatus === 'delivered') {
                order.deliveredAt = new Date().toISOString();
                order.shippingStatus = 'delivered';
            }

            await storage.save('orders', order);
            const index = this.orders.findIndex(o => o.id === id);
            if (index !== -1) {
                this.orders[index] = order;
            }
            app.showNotification('주문 상태가 업데이트되었습니다', 'success');
            return order;
        } catch (error) {
            console.error('주문 상태 업데이트 실패:', error);
            app.showNotification('주문 상태 업데이트에 실패했습니다', 'error');
            return null;
        }
    }

    /**
     * 주문 수정
     */
    async updateOrder(id, updates) {
        try {
            const order = await storage.get('orders', id);
            if (!order) return null;

            const updated = {
                ...order,
                ...updates,
                updatedAt: new Date().toISOString()
            };

            await storage.save('orders', updated);
            const index = this.orders.findIndex(o => o.id === id);
            if (index !== -1) {
                this.orders[index] = updated;
            }
            return updated;
        } catch (error) {
            console.error('주문 수정 실패:', error);
            return null;
        }
    }

    /**
     * 주문 삭제
     */
    async deleteOrder(id) {
        try {
            await storage.delete('orders', id);
            this.orders = this.orders.filter(o => o.id !== id);
            app.showNotification('주문이 삭제되었습니다', 'success');
            return true;
        } catch (error) {
            console.error('주문 삭제 실패:', error);
            app.showNotification('주문 삭제에 실패했습니다', 'error');
            return false;
        }
    }

    /**
     * 주문 ID 생성
     */
    generateId() {
        return 'ord_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    /**
     * 주문번호 생성 (YYMMDDHHmm + 3자리 숫자)
     */
    generateOrderNumber() {
        const now = new Date();
        const yymmdd = now.toISOString().slice(2, 10).replace(/-/g, '');
        const hhmm = String(now.getHours()).padStart(2, '0') + String(now.getMinutes()).padStart(2, '0');
        const random = String(Math.floor(Math.random() * 1000)).padStart(3, '0');
        return yymmdd + hhmm + random;
    }

    /**
     * 상태별 주문 조회
     */
    getOrdersByStatus(status) {
        return this.orders.filter(order => order.status === status);
    }

    /**
     * 판매처별 주문 조회
     */
    getOrdersByChannel(channelId) {
        return this.orders.filter(order => order.channelId === channelId);
    }

    /**
     * 상품별 주문 조회
     */
    getOrdersByProduct(productId) {
        return this.orders.filter(order => order.productId === productId);
    }

    /**
     * 기간별 주문 조회
     */
    getOrdersByDateRange(startDate, endDate) {
        return this.orders.filter(order => {
            const orderDate = new Date(order.createdAt);
            return orderDate >= startDate && orderDate <= endDate;
        });
    }

    /**
     * 미배송 주문 조회
     */
    getPendingOrders() {
        return this.orders.filter(order =>
            order.status === 'pending' || order.shippingStatus === 'preparing'
        );
    }

    /**
     * 상태 라벨
     */
    getStatusLabel(status) {
        const labels = {
            'pending': '대기중',
            'shipped': '배송중',
            'delivered': '배송완료',
            'cancelled': '취소됨',
            'returned': '반품됨'
        };
        return labels[status] || '알 수 없음';
    }

    /**
     * 배송사 정보
     */
    getShippingCompanies() {
        return [
            { id: 'cj', name: 'CJ대한통운', code: 'kr.cjlogistics' },
            { id: 'hp', name: '편의점택배', code: 'kr.cupost' },
            { id: 'lotte', name: '롯데택배', code: 'kr.lotte' },
            { id: 'gs', name: 'GS편의점택배', code: 'kr.gspostcode' },
            { id: 'epost', name: '우체국택배', code: 'kr.epost' }
        ];
    }

    /**
     * 주문 검색
     */
    searchOrders(query) {
        return this.orders.filter(order =>
            order.orderNumber.includes(query) ||
            order.customerName.toLowerCase().includes(query.toLowerCase()) ||
            order.customerPhone.includes(query)
        );
    }
}

// 글로벌 인스턴스
const orderManager = new OrderManager();
