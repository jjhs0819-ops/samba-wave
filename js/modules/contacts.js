/**
 * 고객 연락 관리 모듈
 * 주문과 연동된 문자/알림톡 발송 관리
 */

class ContactManager {
    constructor() {
        this.contactLogs = [];
        this.templates = this.getDefaultTemplates();
    }

    /**
     * 모든 연락 로그 조회
     */
    async loadContactLogs() {
        try {
            this.contactLogs = await storage.getAll('contactLogs');
            return this.contactLogs;
        } catch (error) {
            console.error('연락 로그 로드 실패:', error);
            return [];
        }
    }

    /**
     * 연락 발송
     */
    async sendContact(contactData) {
        try {
            const contact = {
                id: this.generateId(),
                orderId: contactData.orderId,
                type: contactData.type, // 'sms', 'kakao', 'email'
                recipient: contactData.recipient,
                template: contactData.template,
                customMessage: contactData.customMessage,
                message: contactData.message,
                status: 'pending', // pending, sent, failed
                sentAt: null,
                readAt: null,
                createdAt: new Date().toISOString()
            };

            await storage.save('contactLogs', contact);
            this.contactLogs.push(contact);

            // 실제로는 여기서 API 호출하여 문자/알림톡 발송
            // 현재는 시뮬레이션
            await this.simulateSendContact(contact);

            app.showNotification(`고객 연락이 발송되었습니다 (${contact.type})`, 'success');
            return contact;
        } catch (error) {
            console.error('연락 발송 실패:', error);
            app.showNotification('연락 발송에 실패했습니다', 'error');
            return null;
        }
    }

    /**
     * 연락 발송 시뮬레이션
     */
    simulateSendContact(contact) {
        return new Promise((resolve) => {
            // 2초 후 발송 완료 처리
            setTimeout(() => {
                contact.status = 'sent'
                contact.sentAt = new Date().toISOString()
                storage.save('contactLogs', contact).then(() => {
                    const index = this.contactLogs.findIndex(c => c.id === contact.id)
                    if (index !== -1) {
                        this.contactLogs[index] = contact
                    }
                    resolve(contact)
                })
            }, 2000)
        })
    }

    /**
     * 주문별 연락 로그 조회
     */
    getContactsByOrder(orderId) {
        return this.contactLogs.filter(c => c.orderId === orderId)
            .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    }

    /**
     * 연락 타입별 조회
     */
    getContactsByType(type) {
        return this.contactLogs.filter(c => c.type === type);
    }

    /**
     * 기본 템플릿
     */
    getDefaultTemplates() {
        return {
            'sms': {
                'order_received': {
                    name: '주문 접수',
                    message: '[주문 접수]\n주문번호: {orderNumber}\n상품: {productName}\n금액: {amount}원\n\n주문해주셔서 감사합니다!'
                },
                'shipping': {
                    name: '배송 알림',
                    message: '[배송 알림]\n주문번호: {orderNumber}\n배송사: {shippingCompany}\n송장번호: {trackingNumber}\n\n배송이 시작되었습니다.'
                },
                'delivered': {
                    name: '배송 완료',
                    message: '[배송 완료]\n주문번호: {orderNumber}\n\n상품이 배송 완료되었습니다. 감사합니다!'
                },
                'refund': {
                    name: '환불 안내',
                    message: '[환불 안내]\n주문번호: {orderNumber}\n환불금액: {refundAmount}원\n\n환불 처리가 완료되었습니다.'
                }
            },
            'kakao': {
                'order_received': {
                    name: '주문 접수',
                    message: '주문해주셔서 감사합니다! 🎉\n\n주문번호: {orderNumber}\n상품: {productName}\n금액: {amount}원\n\n곧 배송을 시작하겠습니다.'
                },
                'shipping': {
                    name: '배송 알림',
                    message: '상품이 배송되었습니다! 🚚\n\n주문번호: {orderNumber}\n배송사: {shippingCompany}\n송장번호: {trackingNumber}'
                },
                'delivered': {
                    name: '배송 완료',
                    message: '상품이 도착했습니다! 📦\n\n주문번호: {orderNumber}\n\n감사합니다!'
                }
            },
            'email': {
                'order_received': {
                    name: '주문 접수',
                    message: '<h2>주문이 접수되었습니다</h2><p>주문번호: {orderNumber}</p><p>상품: {productName}</p><p>금액: {amount}원</p>'
                }
            }
        };
    }

    /**
     * 템플릿 메시지 파싱
     */
    parseTemplate(template, variables) {
        let message = template;
        Object.keys(variables).forEach(key => {
            message = message.replaceAll(`{${key}}`, variables[key]);
        });
        return message;
    }

    /**
     * 연락 통계
     */
    getContactStats() {
        const stats = {
            total: this.contactLogs.length,
            sent: this.contactLogs.filter(c => c.status === 'sent').length,
            failed: this.contactLogs.filter(c => c.status === 'failed').length,
            pending: this.contactLogs.filter(c => c.status === 'pending').length,
            bySms: this.contactLogs.filter(c => c.type === 'sms').length,
            byKakao: this.contactLogs.filter(c => c.type === 'kakao').length,
            byEmail: this.contactLogs.filter(c => c.type === 'email').length
        };
        return stats;
    }

    /**
     * 오늘의 발송 건수
     */
    getTodayContactCount() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        return this.contactLogs.filter(c => {
            const created = new Date(c.createdAt);
            created.setHours(0, 0, 0, 0);
            return created.getTime() === today.getTime();
        }).length;
    }

    /**
     * ID 생성
     */
    generateId() {
        return 'con_' + Date.now() + '_' + Math.random().toString(36).substring(2, 11);
    }

    /**
     * 연락 타입 라벨
     */
    getContactTypeLabel(type) {
        const labels = {
            'sms': '문자 (SMS)',
            'kakao': '알림톡',
            'email': '이메일'
        };
        return labels[type] || '기타';
    }

    /**
     * 상태 라벨
     */
    getStatusLabel(status) {
        const labels = {
            'pending': '대기중',
            'sent': '발송완료',
            'failed': '발송실패'
        };
        return labels[status] || '알 수 없음';
    }

    /**
     * 연락 삭제
     */
    async deleteContact(id) {
        try {
            await storage.delete('contactLogs', id);
            this.contactLogs = this.contactLogs.filter(c => c.id !== id);
            return true;
        } catch (error) {
            console.error('연락 삭제 실패:', error);
            return false;
        }
    }
}

// 글로벌 인스턴스
const contactManager = new ContactManager();
