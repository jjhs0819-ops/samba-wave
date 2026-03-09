/**
 * 판매처 관리 모듈
 * 판매처 CRUD, 수수료 설정, 상품 연동
 */

class ChannelManager {
    constructor() {
        this.channels = [];
    }

    /**
     * 모든 판매처 조회
     */
    async loadChannels() {
        try {
            this.channels = await storage.getAll('channels');
            return this.channels;
        } catch (error) {
            console.error('판매처 로드 실패:', error);
            return [];
        }
    }

    /**
     * 판매처 추가
     */
    async addChannel(channelData) {
        try {
            const channel = {
                id: this.generateId(),
                name: channelData.name,
                type: channelData.type, // "open-market", "mall", "resale", "overseas"
                platform: channelData.platform, // "coupang", "11st", "musinsusa", "ssg", etc
                feeRate: parseFloat(channelData.feeRate) || 0,
                products: [],
                status: 'active',
                apiKey: channelData.apiKey || '',
                apiSecret: channelData.apiSecret || '',
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString()
            };

            await storage.save('channels', channel);
            this.channels.push(channel);
            app.showNotification('판매처가 추가되었습니다', 'success');
            return channel;
        } catch (error) {
            console.error('판매처 추가 실패:', error);
            app.showNotification('판매처 추가에 실패했습니다', 'error');
            return null;
        }
    }

    /**
     * 판매처 수정
     */
    async updateChannel(id, updates) {
        try {
            const channel = await storage.get('channels', id);
            if (!channel) {
                app.showNotification('판매처를 찾을 수 없습니다', 'error');
                return null;
            }

            const updated = {
                ...channel,
                ...updates,
                updatedAt: new Date().toISOString()
            };

            await storage.save('channels', updated);
            const index = this.channels.findIndex(c => c.id === id);
            if (index !== -1) {
                this.channels[index] = updated;
            }
            app.showNotification('판매처가 수정되었습니다', 'success');
            return updated;
        } catch (error) {
            console.error('판매처 수정 실패:', error);
            app.showNotification('판매처 수정에 실패했습니다', 'error');
            return null;
        }
    }

    /**
     * 판매처 삭제
     */
    async deleteChannel(id) {
        try {
            await storage.delete('channels', id);
            this.channels = this.channels.filter(c => c.id !== id);
            app.showNotification('판매처가 삭제되었습니다', 'success');
            return true;
        } catch (error) {
            console.error('판매처 삭제 실패:', error);
            app.showNotification('판매처 삭제에 실패했습니다', 'error');
            return false;
        }
    }

    /**
     * 판매처 유형별 기본 수수료율
     */
    getDefaultFeeRate(type) {
        const feeRates = {
            'open-market': 8.5,      // 쿠팡, 11번가 등
            'mall': 4.5,              // SSG, 롯데온 등
            'resale': 10,             // 무신사 등
            'overseas': 15            // 아마존, 이베이 등
        };
        return feeRates[type] || 0;
    }

    /**
     * 판매처 유형별 라벨
     */
    getChannelTypeLabel(type) {
        const labels = {
            'open-market': '오픈마켓',
            'mall': '종합몰',
            'resale': '리셀플랫폼',
            'overseas': '해외플랫폼'
        };
        return labels[type] || '기타';
    }

    /**
     * 플랫폼 정보
     */
    getPlatformInfo(platform) {
        const platforms = {
            'coupang': { name: '쿠팡', icon: '🔴', type: 'open-market' },
            '11st': { name: '11번가', icon: '🟠', type: 'open-market' },
            'ssg': { name: 'SSG', icon: '🟣', type: 'mall' },
            'lotte': { name: '롯데온', icon: '🔵', type: 'mall' },
            'musinsusa': { name: '무신사', icon: '🌿', type: 'resale' },
            'amazon': { name: '아마존', icon: '🟠', type: 'overseas' },
            'ebay': { name: '이베이', icon: '🔴', type: 'overseas' }
        };
        return platforms[platform] || { name: '기타', icon: '⚪', type: 'other' };
    }

    /**
     * 상품을 판매처에 연동
     */
    async linkProductToChannel(channelId, productId) {
        try {
            const channel = await storage.get('channels', channelId);
            if (!channel) return null;

            if (!channel.products.includes(productId)) {
                channel.products.push(productId);
                await storage.save('channels', channel);

                const index = this.channels.findIndex(c => c.id === channelId);
                if (index !== -1) {
                    this.channels[index] = channel;
                }
            }
            return channel;
        } catch (error) {
            console.error('상품 연동 실패:', error);
            return null;
        }
    }

    /**
     * 판매처에서 상품 해제
     */
    async unlinkProductFromChannel(channelId, productId) {
        try {
            const channel = await storage.get('channels', channelId);
            if (!channel) return null;

            channel.products = channel.products.filter(id => id !== productId);
            await storage.save('channels', channel);

            const index = this.channels.findIndex(c => c.id === channelId);
            if (index !== -1) {
                this.channels[index] = channel;
            }
            return channel;
        } catch (error) {
            console.error('상품 해제 실패:', error);
            return null;
        }
    }

    /**
     * ID 생성
     */
    generateId() {
        return 'ch_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }

    /**
     * 판매처 검색
     */
    searchChannels(query) {
        return this.channels.filter(channel =>
            channel.name.toLowerCase().includes(query.toLowerCase()) ||
            channel.platform.toLowerCase().includes(query.toLowerCase())
        );
    }
}

// 글로벌 인스턴스
const channelManager = new ChannelManager();
