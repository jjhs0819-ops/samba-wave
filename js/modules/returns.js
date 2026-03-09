/**
 * 반품/교환/취소 관리 모듈
 * 주문의 반품, 교환, 취소 처리
 */

class ReturnManager {
    constructor() {
        this.returns = [];
    }

    /**
     * 모든 반품/교환/취소 조회
     */
    async loadReturns() {
        try {
            this.returns = await storage.getAll('returns');
            return this.returns;
        } catch (error) {
            console.error('반품 데이터 로드 실패:', error);
            return [];
        }
    }

    /**
     * 반품/교환/취소 요청 생성
     */
    async createReturn(returnData) {
        try {
            const returnRecord = {
                id: this.generateId(),
                orderId: returnData.orderId,
                type: returnData.type, // 'return', 'exchange', 'cancel'
                reason: returnData.reason,
                description: returnData.description,
                quantity: returnData.quantity || 1,
                requestedAmount: returnData.requestedAmount, // 환불/교환 요청액
                status: 'requested', // requested, approved, rejected, completed, cancelled
                approvalDate: null,
                completionDate: null,
                notes: [],
                attachments: [],
                timeline: [
                    {
                        date: new Date().toISOString(),
                        status: 'requested',
                        message: '반품/교환/취소 요청됨'
                    }
                ],
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString()
            };

            await storage.save('returns', returnRecord);
            this.returns.push(returnRecord);

            // 주문 상태 업데이트
            const order = orderManager.orders.find(o => o.id === returnData.orderId);
            if (order) {
                order.returnStatus = 'requested';
                await storage.save('orders', order);
            }

            app.showNotification('반품/교환/취소 요청이 생성되었습니다', 'success');
            return returnRecord;
        } catch (error) {
            console.error('반품 요청 생성 실패:', error);
            app.showNotification('요청 생성에 실패했습니다', 'error');
            return null;
        }
    }

    /**
     * 반품/교환/취소 승인
     */
    async approveReturn(returnId) {
        try {
            const returnRecord = await storage.get('returns', returnId);
            if (!returnRecord) return null;

            returnRecord.status = 'approved';
            returnRecord.approvalDate = new Date().toISOString();
            returnRecord.timeline.push({
                date: new Date().toISOString(),
                status: 'approved',
                message: '승인됨'
            });

            await storage.save('returns', returnRecord);
            const index = this.returns.findIndex(r => r.id === returnId);
            if (index !== -1) {
                this.returns[index] = returnRecord;
            }

            app.showNotification('반품/교환/취소가 승인되었습니다', 'success');
            return returnRecord;
        } catch (error) {
            console.error('승인 실패:', error);
            return null;
        }
    }

    /**
     * 반품/교환/취소 거부
     */
    async rejectReturn(returnId, reason = '') {
        try {
            const returnRecord = await storage.get('returns', returnId);
            if (!returnRecord) return null;

            returnRecord.status = 'rejected';
            returnRecord.timeline.push({
                date: new Date().toISOString(),
                status: 'rejected',
                message: '거부됨: ' + reason
            });

            await storage.save('returns', returnRecord);
            const index = this.returns.findIndex(r => r.id === returnId);
            if (index !== -1) {
                this.returns[index] = returnRecord;
            }

            app.showNotification('반품/교환/취소가 거부되었습니다', 'warning');
            return returnRecord;
        } catch (error) {
            console.error('거부 실패:', error);
            return null;
        }
    }

    /**
     * 반품/교환/취소 완료
     */
    async completeReturn(returnId) {
        try {
            const returnRecord = await storage.get('returns', returnId);
            if (!returnRecord) return null;

            returnRecord.status = 'completed';
            returnRecord.completionDate = new Date().toISOString();
            returnRecord.timeline.push({
                date: new Date().toISOString(),
                status: 'completed',
                message: '완료됨'
            });

            await storage.save('returns', returnRecord);
            const index = this.returns.findIndex(r => r.id === returnId);
            if (index !== -1) {
                this.returns[index] = returnRecord;
            }

            // 주문 상태도 업데이트
            const order = orderManager.orders.find(o => o.id === returnRecord.orderId);
            if (order) {
                if (returnRecord.type === 'return') {
                    order.returnStatus = 'completed';
                } else if (returnRecord.type === 'exchange') {
                    order.returnStatus = 'exchanged';
                } else if (returnRecord.type === 'cancel') {
                    order.status = 'cancelled';
                }
                await storage.save('orders', order);
            }

            app.showNotification('반품/교환/취소가 완료되었습니다', 'success');
            return returnRecord;
        } catch (error) {
            console.error('완료 처리 실패:', error);
            return null;
        }
    }

    /**
     * 반품/교환/취소 취소 (요청 취소)
     */
    async cancelReturn(returnId) {
        try {
            const returnRecord = await storage.get('returns', returnId);
            if (!returnRecord) return null;

            returnRecord.status = 'cancelled';
            returnRecord.timeline.push({
                date: new Date().toISOString(),
                status: 'cancelled',
                message: '요청 취소됨'
            });

            await storage.save('returns', returnRecord);
            const index = this.returns.findIndex(r => r.id === returnId);
            if (index !== -1) {
                this.returns[index] = returnRecord;
            }

            app.showNotification('반품/교환/취소 요청이 취소되었습니다', 'info');
            return returnRecord;
        } catch (error) {
            console.error('요청 취소 실패:', error);
            return null;
        }
    }

    /**
     * 반품 메모 추가
     */
    async addReturnNote(returnId, note) {
        try {
            const returnRecord = await storage.get('returns', returnId);
            if (!returnRecord) return null;

            returnRecord.notes.push({
                date: new Date().toISOString(),
                message: note
            });

            await storage.save('returns', returnRecord);
            const index = this.returns.findIndex(r => r.id === returnId);
            if (index !== -1) {
                this.returns[index] = returnRecord;
            }

            return returnRecord;
        } catch (error) {
            console.error('메모 추가 실패:', error);
            return null;
        }
    }

    /**
     * 주문별 반품/교환/취소 조회
     */
    getReturnsByOrder(orderId) {
        return this.returns.filter(r => r.orderId === orderId)
            .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    }

    /**
     * 타입별 조회
     */
    getReturnsByType(type) {
        return this.returns.filter(r => r.type === type);
    }

    /**
     * 상태별 조회
     */
    getReturnsByStatus(status) {
        return this.returns.filter(r => r.status === status);
    }

    /**
     * 반품/교환/취소 통계
     */
    getReturnStats() {
        const stats = {
            total: this.returns.length,
            requested: this.returns.filter(r => r.status === 'requested').length,
            approved: this.returns.filter(r => r.status === 'approved').length,
            rejected: this.returns.filter(r => r.status === 'rejected').length,
            completed: this.returns.filter(r => r.status === 'completed').length,
            returns: this.returns.filter(r => r.type === 'return').length,
            exchanges: this.returns.filter(r => r.type === 'exchange').length,
            cancels: this.returns.filter(r => r.type === 'cancel').length
        };

        // 총 환불액 계산
        stats.totalRefundAmount = this.returns
            .filter(r => r.status === 'completed' && r.type === 'return')
            .reduce((sum, r) => sum + (r.requestedAmount || 0), 0);

        return stats;
    }

    /**
     * 환불 가능 여부 확인
     */
    canRefund(orderId) {
        const order = orderManager.orders.find(o => o.id === orderId);
        if (!order) return false;

        // 배송완료 후 7일 이내만 환불 가능
        const deliveredDate = order.deliveredAt ? new Date(order.deliveredAt) : null;
        if (!deliveredDate) return false;

        const today = new Date();
        const daysDiff = Math.floor((today - deliveredDate) / (1000 * 60 * 60 * 24));

        return daysDiff <= 7;
    }

    /**
     * 반품 사유 목록
     */
    getReturnReasons() {
        return {
            'return': [
                { value: 'defective', label: '상품 불량' },
                { value: 'damaged', label: '상품 손상' },
                { value: 'wrong_item', label: '잘못된 상품' },
                { value: 'not_as_described', label: '상품 설명과 다름' },
                { value: 'changed_mind', label: '단순 변심' },
                { value: 'size_fit', label: '사이즈 맞지 않음' },
                { value: 'other', label: '기타' }
            ],
            'exchange': [
                { value: 'wrong_size', label: '잘못된 사이즈' },
                { value: 'wrong_color', label: '잘못된 색상' },
                { value: 'defective', label: '불량 상품' },
                { value: 'other', label: '기타' }
            ],
            'cancel': [
                { value: 'not_ordered', label: '실수로 주문함' },
                { value: 'changed_mind', label: '구매 취소' },
                { value: 'price_drop', label: '가격 하락' },
                { value: 'out_of_stock', label: '재고 부족' },
                { value: 'other', label: '기타' }
            ]
        };
    }

    /**
     * ID 생성
     */
    generateId() {
        return 'ret_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    /**
     * 타입 라벨
     */
    getTypeLabel(type) {
        const labels = {
            'return': '반품',
            'exchange': '교환',
            'cancel': '취소'
        };
        return labels[type] || '기타';
    }

    /**
     * 상태 라벨
     */
    getStatusLabel(status) {
        const labels = {
            'requested': '요청됨',
            'approved': '승인됨',
            'rejected': '거부됨',
            'completed': '완료됨',
            'cancelled': '취소됨'
        };
        return labels[status] || '알 수 없음';
    }

    /**
     * 상태 색상
     */
    getStatusColor(status) {
        const colors = {
            'requested': 'yellow',
            'approved': 'blue',
            'rejected': 'red',
            'completed': 'green',
            'cancelled': 'gray'
        };
        return colors[status] || 'gray';
    }
}

// 글로벌 인스턴스
const returnManager = new ReturnManager();
