/**
 * 메인 애플리케이션 로직
 * 페이지 네비게이션, 기본 이벤트 처리
 */

class SambaWaveApp {
    constructor() {
        this.currentPage = 'dashboard';
        this.init();
    }

    /**
     * 앱 초기화
     */
    init() {
        // DOM 로드 완료 대기
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setupEventListeners());
        } else {
            this.setupEventListeners();
        }
    }

    /**
     * 이벤트 리스너 설정
     */
    setupEventListeners() {
        // 네비게이션 버튼
        document.querySelectorAll('.nav-item').forEach(button => {
            button.addEventListener('click', (e) => {
                const pageName = button.getAttribute('data-page');
                this.navigateTo(pageName);
            });
        });

        console.log('SambaWaveApp 초기화 완료');
    }

    /**
     * 페이지 전환
     */
    navigateTo(pageName) {
        // 활성 페이지 콘텐츠 숨기기
        document.querySelectorAll('.page-content').forEach(page => {
            page.classList.add('hidden');
        });

        // 활성 네비게이션 항목 업데이트
        document.querySelectorAll('.nav-item').forEach(button => {
            button.classList.remove('sidebar-active');
        });

        // 새 페이지 표시
        const pageElement = document.getElementById(`page-${pageName}`);
        if (pageElement) {
            pageElement.classList.remove('hidden');
        }

        // 활성 네비게이션 강조
        const activeButton = document.querySelector(`[data-page="${pageName}"]`);
        if (activeButton) {
            activeButton.classList.add('sidebar-active');
        }

        this.currentPage = pageName;

        // URL 업데이트 (필요시)
        window.history.pushState({ page: pageName }, '', `#${pageName}`);
    }

    /**
     * URL에 따라 페이지 복원 (새로고침 시)
     */
    restorePageFromUrl() {
        const hash = window.location.hash.slice(1);
        const validPages = ['dashboard', 'products', 'channels', 'sourcing', 'orders', 'analytics', 'settings'];

        if (validPages.includes(hash)) {
            this.navigateTo(hash);
        }
    }

    /**
     * 알림 표시
     */
    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `fixed top-4 right-4 px-6 py-3 rounded-lg text-white font-medium shadow-lg z-50 animate-slide-in`;

        const bgColor = {
            'success': 'bg-green-500',
            'error': 'bg-red-500',
            'warning': 'bg-yellow-500',
            'info': 'bg-blue-500'
        }[type] || 'bg-blue-500';

        notification.className += ` ${bgColor}`;
        notification.textContent = message;

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.remove();
        }, 3000);
    }

    /**
     * 로딩 표시
     */
    showLoading(show = true) {
        let loader = document.getElementById('global-loader');
        if (!loader) {
            loader = document.createElement('div');
            loader.id = 'global-loader';
            loader.innerHTML = `
                <div class="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-40">
                    <div class="bg-white rounded-lg p-6 flex flex-col items-center gap-4">
                        <div class="w-8 h-8 border-4 border-gray-200 border-t-blue-500 rounded-full animate-spin"></div>
                        <p class="text-gray-700 font-medium">로딩 중...</p>
                    </div>
                </div>
            `;
            document.body.appendChild(loader);
        }
        loader.style.display = show ? 'block' : 'none';
    }
}

// 앱 인스턴스 생성
const app = new SambaWaveApp();

// URL 기반 페이지 복원
window.addEventListener('load', async () => {
    app.restorePageFromUrl();

    // 초기 더미 데이터 추가 (처음 실행 시)
    await initializeDummyData();
});

// 뒤로가기/앞으로가기 지원
window.addEventListener('popstate', (event) => {
    if (event.state && event.state.page) {
        app.navigateTo(event.state.page);
    }
});

/**
 * 초기 더미 데이터 생성
 */
async function initializeDummyData() {
    // 이미 데이터가 있으면 스킵
    const existingProducts = await storage.getAll('products');
    if (existingProducts.length > 0) return;

    // 판매처 추가
    const channels = [
        { name: '쿠팡', type: 'open-market', platform: 'coupang', feeRate: 8.5 },
        { name: '무신사', type: 'resale', platform: 'musinsusa', feeRate: 10 },
        { name: 'SSG', type: 'mall', platform: 'ssg', feeRate: 4.5 },
        { name: '11번가', type: 'open-market', platform: '11st', feeRate: 8.5 }
    ];

    const savedChannels = {};
    for (const ch of channels) {
        const channel = await channelManager.addChannel(ch);
        if (channel) savedChannels[ch.platform] = channel.id;
    }

    // 상품 추가
    const products = [
        {
            name: '프리미엄 스니커즈',
            category: '신발',
            sourceUrl: 'https://example.com/product1',
            sourcePrice: 45000,
            cost: 35000,
            marginRate: 35,
            description: '편한 착용감의 캐주얼 스니커즈'
        },
        {
            name: 'T셔츠 (화이트)',
            category: '의류',
            sourceUrl: 'https://example.com/product2',
            sourcePrice: 12000,
            cost: 8000,
            marginRate: 40,
            description: '순면 100% 기본 티셔츠'
        },
        {
            name: '백팩 (블랙)',
            category: '가방',
            sourceUrl: 'https://example.com/product3',
            sourcePrice: 65000,
            cost: 48000,
            marginRate: 30,
            description: '내구성 좋은 일상용 백팩'
        }
    ];

    for (const prod of products) {
        await productManager.addProduct(prod);
    }

    // 샘플 주문 추가
    const sampleOrders = [
        {
            channelId: Object.values(savedChannels)[0],
            productId: productManager.products[0]?.id,
            customerName: '김철수',
            customerPhone: '010-1234-5678',
            salePrice: 58000,
            cost: 35000,
            feeRate: 8.5
        },
        {
            channelId: Object.values(savedChannels)[1],
            productId: productManager.products[1]?.id,
            customerName: '이영희',
            customerPhone: '010-9876-5432',
            salePrice: 18000,
            cost: 8000,
            feeRate: 10
        }
    ];

    for (const order of sampleOrders) {
        if (order.channelId && order.productId) {
            await orderManager.addOrder(order);
        }
    }

    console.log('더미 데이터 초기화 완료');
}
