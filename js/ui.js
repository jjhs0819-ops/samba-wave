/**
 * UI 관리 모듈
 * 모달, 테이블, 폼 렌더링 및 이벤트 처리
 */

class UIManager {
    constructor() {
        this.currentProductEditId = null;
        this.currentChannelEditId = null;
        this.currentOrderFilter = 'all';
        this.init();
    }

    /**
     * 초기화
     */
    async init() {
        // DOM 로드 대기
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.setupEventListeners());
        } else {
            this.setupEventListeners();
        }
    }

    /**
     * 이벤트 리스너 설정
     */
    async setupEventListeners() {
        // 모달 폼 제출
        document.getElementById('product-form')?.addEventListener('submit', (e) => this.handleProductSubmit(e));
        document.getElementById('channel-form')?.addEventListener('submit', (e) => this.handleChannelSubmit(e));
        document.getElementById('order-form')?.addEventListener('submit', (e) => this.handleOrderSubmit(e));
        document.getElementById('sourcing-form')?.addEventListener('submit', (e) => this.handleSourcingSubmit(e));
        document.getElementById('contact-form')?.addEventListener('submit', (e) => this.handleContactSubmit(e));
        document.getElementById('return-form')?.addEventListener('submit', (e) => this.handleReturnSubmit(e));

        // 상품 검색 및 필터
        document.getElementById('product-search')?.addEventListener('input', () => this.renderProducts());
        document.getElementById('product-status')?.addEventListener('change', () => this.renderProducts());

        // 주문 상태 탭
        document.querySelectorAll('.order-tab').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.currentOrderFilter = e.target.getAttribute('data-status');
                document.querySelectorAll('.order-tab').forEach(b => b.classList.remove('bg-blue-50', 'text-blue-600'));
                e.target.classList.add('bg-blue-50', 'text-blue-600');
                this.renderOrders();
            });
        });

        // 통계 탭
        document.querySelectorAll('.analytics-tab').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const tab = e.target.getAttribute('data-tab');
                document.querySelectorAll('.analytics-tab').forEach(b => b.classList.remove('bg-blue-50', 'text-blue-600'));
                document.querySelectorAll('.analytics-content').forEach(c => c.classList.add('hidden'));
                e.target.classList.add('bg-blue-50', 'text-blue-600');
                document.getElementById(`analytics-${tab}`)?.classList.remove('hidden');
            });
        });

        // 모달 닫기 (ESC 키)
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeAllModals();
            }
        });

        // 초기 데이터 로드 및 렌더링
        await this.loadAndRenderAll();

        console.log('UIManager 초기화 완료');
    }

    /**
     * 모든 데이터 로드 및 렌더링
     */
    async loadAndRenderAll() {
        await productManager.loadProducts();
        await channelManager.loadChannels();
        await orderManager.loadOrders();
        await sourcingManager.loadSourcingSites();
        await analyticsManager.loadAnalytics();
        await contactManager.loadContactLogs();
        await returnManager.loadReturns();

        this.renderDashboard();
        this.renderProducts();
        this.renderChannels();
        this.renderOrders();
        this.renderSourcing();
        this.renderAnalytics();
        this.renderCharts();
        this.renderContacts();
        this.renderReturns();
        this.updateCounts();
    }

    /**
     * === 대시보드 ===
     */

    renderDashboard() {
        const todayStats = analyticsManager.getTodayStats();
        const pending = orderManager.getPendingOrders();

        document.getElementById('dash-sales').textContent = '₩' + this.formatNumber(todayStats.totalSales);
        document.getElementById('dash-orders').textContent = todayStats.totalOrders;
        document.getElementById('dash-profit').textContent = '₩' + this.formatNumber(todayStats.totalProfit);
        document.getElementById('dash-rate').textContent = todayStats.profitRate + '%';
        document.getElementById('dash-avg').textContent = '₩' + this.formatNumber(todayStats.avgOrderValue);
        document.getElementById('dash-pending').textContent = pending.length;
    }

    /**
     * === 상품 관리 ===
     */

    showProductModal(productId = null) {
        const modal = document.getElementById('product-modal');
        const form = document.getElementById('product-form');
        const title = document.getElementById('modal-title');

        form.reset();
        this.currentProductEditId = null;

        // 이미지 미리보기 초기화
        document.getElementById('product-image-preview').innerHTML = '<i class="fas fa-image text-gray-400 text-2xl"></i>';
        document.getElementById('product-image-analysis').classList.add('hidden');
        document.getElementById('product-estimated-price').textContent = '₩0';

        if (productId) {
            const product = productManager.products.find(p => p.id === productId);
            if (product) {
                title.textContent = '상품 수정';
                form.name.value = product.name;
                form.category.value = product.category;
                form.sourceUrl.value = product.sourceUrl;
                form.sourcePrice.value = product.sourcePrice;
                form.cost.value = product.cost;
                form.marginRate.value = product.marginRate;
                form.description.value = product.description;
                this.currentProductEditId = productId;
            }
        } else {
            title.textContent = '상품 추가';
        }

        modal.classList.remove('hidden');
    }

    /**
     * AI 상품명 개선
     */
    async improveProductName() {
        const nameInput = document.getElementById('product-name-input');
        const category = document.getElementById('product-category').value;

        if (!nameInput.value) {
            app.showNotification('상품명을 입력해주세요', 'warning');
            return;
        }

        app.showLoading(true);
        const improved = await aiProcessor.improveProductName(nameInput.value, category);
        nameInput.value = improved;
        app.showLoading(false);

        app.showNotification('상품명이 개선되었습니다', 'success');
    }

    /**
     * 상품 이미지 분석
     */
    async analyzeProductImage() {
        const imageInput = document.getElementById('product-image-input');
        const file = imageInput.files[0];

        if (!file) return;

        app.showLoading(true);

        try {
            // 미리보기 생성
            const preview = await aiProcessor.generatePreview(file);
            document.getElementById('product-image-preview').innerHTML = `<img src="${preview}" class="w-full h-full object-cover rounded-lg">`;

            // 이미지 분석
            const analysis = await aiProcessor.analyzeImage(file);

            // 분석 결과 표시
            const analysisDiv = document.getElementById('product-image-analysis');
            const tipsList = document.getElementById('product-image-tips');

            if (analysis.recommendations) {
                tipsList.innerHTML = analysis.recommendations
                    .map(rec => `<li>${rec}</li>`)
                    .join('');
                analysisDiv.classList.remove('hidden');
            }

            app.showNotification('이미지 분석 완료', 'success');
        } catch (error) {
            app.showNotification('이미지 분석 실패', 'error');
        }

        app.showLoading(false);
    }

    /**
     * 판매가 계산
     */
    calculateSalePrice() {
        const sourcePrice = parseFloat(document.getElementById('product-source-price').value) || 0;
        const cost = parseFloat(document.getElementById('product-cost').value) || 0;
        const marginRate = parseFloat(document.getElementById('product-margin-rate').value) || 30;

        // 판매가 = 원가 / (1 - 마진율/100)
        const salePrice = Math.ceil(cost / (1 - marginRate / 100));

        document.getElementById('product-estimated-price').textContent = '₩' + this.formatNumber(salePrice);
    }

    /**
     * AI 마진율 제안
     */
    suggestMarginRate() {
        const category = document.getElementById('product-category').value;
        const suggested = aiProcessor.calculateRecommendedMargin(0, category);

        document.getElementById('product-margin-rate').value = suggested;
        this.calculateSalePrice();

        app.showNotification(`${category}의 추천 마진율: ${suggested}%`, 'info');
    }

    /**
     * 카테고리 변경 시 마진율 제안
     */
    updateMarginSuggestion() {
        // 자동으로 마진율 업데이트하지 않음 (사용자가 명시적으로 버튼을 눌러야 함)
    }

    closeProductModal() {
        document.getElementById('product-modal').classList.add('hidden');
        this.currentProductEditId = null;
    }

    async handleProductSubmit(e) {
        e.preventDefault();
        const form = e.target;
        const data = new FormData(form);

        const productData = {
            name: data.get('name'),
            category: data.get('category'),
            sourceUrl: data.get('sourceUrl'),
            sourcePrice: data.get('sourcePrice'),
            cost: data.get('cost'),
            marginRate: data.get('marginRate'),
            description: data.get('description')
        };

        if (this.currentProductEditId) {
            await productManager.updateProduct(this.currentProductEditId, productData);
        } else {
            await productManager.addProduct(productData);
        }

        this.closeProductModal();
        this.renderProducts();
        this.updateCounts();
    }

    async renderProducts() {
        const tbody = document.getElementById('products-tbody');
        let products = productManager.products;

        // 검색 필터
        const searchQuery = document.getElementById('product-search')?.value || '';
        if (searchQuery) {
            products = productManager.searchProducts(searchQuery);
        }

        // 상태 필터
        const statusFilter = document.getElementById('product-status')?.value || '';
        if (statusFilter) {
            products = products.filter(p => p.status === statusFilter);
        }

        if (products.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="px-6 py-8 text-center text-gray-500">상품이 없습니다</td></tr>';
            return;
        }

        tbody.innerHTML = products.map(product => `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-4">
                    <div>
                        <p class="font-medium text-gray-900">${product.name}</p>
                        <p class="text-xs text-gray-500">${product.category || '카테고리 없음'}</p>
                    </div>
                </td>
                <td class="px-6 py-4">
                    <span class="text-sm text-gray-600">${product.channels ? Object.keys(product.channels).length : 0}개</span>
                </td>
                <td class="px-6 py-4 text-right">
                    <span class="font-medium text-gray-900">₩${this.formatNumber(product.cost)}</span>
                </td>
                <td class="px-6 py-4 text-right">
                    <span class="text-sm font-medium text-blue-600">${product.marginRate}%</span>
                </td>
                <td class="px-6 py-4">
                    <span class="inline-block px-3 py-1 rounded-full text-xs font-medium ${product.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}">
                        ${product.status === 'active' ? '활성' : '비활성'}
                    </span>
                </td>
                <td class="px-6 py-4 text-center">
                    <button onclick="ui.showProductModal('${product.id}')" class="text-blue-600 hover:text-blue-800 text-sm font-medium mr-3">수정</button>
                    <button onclick="ui.deleteProduct('${product.id}')" class="text-red-600 hover:text-red-800 text-sm font-medium">삭제</button>
                </td>
            </tr>
        `).join('');
    }

    async deleteProduct(productId) {
        if (confirm('정말 삭제하시겠습니까?')) {
            await productManager.deleteProduct(productId);
            this.renderProducts();
            this.updateCounts();
        }
    }

    /**
     * === 판매처 관리 ===
     */

    showChannelModal(channelId = null) {
        const modal = document.getElementById('channel-modal');
        const form = document.getElementById('channel-form');

        form.reset();
        this.currentChannelEditId = null;

        if (channelId) {
            const channel = channelManager.channels.find(c => c.id === channelId);
            if (channel) {
                form.name.value = channel.name;
                form.type.value = channel.type;
                form.platform.value = channel.platform;
                form.feeRate.value = channel.feeRate;
                this.currentChannelEditId = channelId;
            }
        }

        modal.classList.remove('hidden');
    }

    closeChannelModal() {
        document.getElementById('channel-modal').classList.add('hidden');
        this.currentChannelEditId = null;
    }

    async handleChannelSubmit(e) {
        e.preventDefault();
        const form = e.target;
        const data = new FormData(form);

        const channelData = {
            name: data.get('name'),
            type: data.get('type'),
            platform: data.get('platform'),
            feeRate: data.get('feeRate')
        };

        if (this.currentChannelEditId) {
            await channelManager.updateChannel(this.currentChannelEditId, channelData);
        } else {
            await channelManager.addChannel(channelData);
        }

        this.closeChannelModal();
        this.renderChannels();
        this.updateCounts();
        this.updateChannelSelects();
    }

    async renderChannels() {
        const grid = document.getElementById('channels-grid');

        if (channelManager.channels.length === 0) {
            grid.innerHTML = '<div class="col-span-3 bg-white rounded-lg shadow p-6 text-center text-gray-500">판매처를 추가해주세요</div>';
            return;
        }

        grid.innerHTML = channelManager.channels.map(channel => {
            const typeLabel = channelManager.getChannelTypeLabel(channel.type);
            return `
                <div class="bg-white rounded-lg shadow p-6 border-l-4 border-blue-500">
                    <div class="flex justify-between items-start mb-4">
                        <div>
                            <h4 class="font-bold text-gray-900">${channel.name}</h4>
                            <p class="text-xs text-gray-500">${typeLabel}</p>
                        </div>
                        <div class="flex gap-2">
                            <button onclick="ui.showChannelModal('${channel.id}')" class="text-blue-600 hover:text-blue-800">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button onclick="ui.deleteChannel('${channel.id}')" class="text-red-600 hover:text-red-800">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                    <div class="space-y-2 text-sm">
                        <p><span class="text-gray-600">수수료:</span> <span class="font-bold">${channel.feeRate}%</span></p>
                        <p><span class="text-gray-600">등록상품:</span> <span class="font-bold">${channel.products.length}개</span></p>
                        <p><span class="text-gray-600">상태:</span> <span class="font-bold text-green-600">${channel.status === 'active' ? '활성' : '비활성'}</span></p>
                    </div>
                </div>
            `;
        }).join('');
    }

    async deleteChannel(channelId) {
        if (confirm('정말 삭제하시겠습니까?')) {
            await channelManager.deleteChannel(channelId);
            this.renderChannels();
            this.updateCounts();
            this.updateChannelSelects();
        }
    }

    /**
     * === 주문/CS 관리 ===
     */

    showOrderModal(orderId = null) {
        const modal = document.getElementById('order-modal');
        const form = document.getElementById('order-form');

        form.reset();
        this.updateChannelSelects();
        this.updateProductSelects();

        if (orderId) {
            const order = orderManager.orders.find(o => o.id === orderId);
            if (order) {
                form.channelId.value = order.channelId;
                form.productId.value = order.productId;
                form.customerName.value = order.customerName;
                form.customerPhone.value = order.customerPhone;
                form.customerAddress.value = order.customerAddress;
                form.quantity.value = order.quantity;
                form.salePrice.value = order.salePrice;
                form.cost.value = order.cost;
                form.feeRate.value = order.feeRate;
                form.shippingCompany.value = order.shippingCompany;
                form.notes.value = order.notes;
            }
        }

        modal.classList.remove('hidden');
    }

    closeOrderModal() {
        document.getElementById('order-modal').classList.add('hidden');
    }

    updateChannelSelects() {
        const select = document.getElementById('order-channel-select');
        if (!select) return;

        select.innerHTML = '<option value="">선택하세요</option>' +
            channelManager.channels.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
    }

    updateProductSelects() {
        const select = document.getElementById('order-product-select');
        if (!select) return;

        select.innerHTML = '<option value="">선택하세요</option>' +
            productManager.products.map(p => `<option value="${p.id}">${p.name}</option>`).join('');
    }

    async handleOrderSubmit(e) {
        e.preventDefault();
        const form = e.target;
        const data = new FormData(form);

        const orderData = {
            channelId: data.get('channelId'),
            productId: data.get('productId'),
            customerName: data.get('customerName'),
            customerPhone: data.get('customerPhone'),
            customerAddress: data.get('customerAddress'),
            quantity: data.get('quantity'),
            salePrice: data.get('salePrice'),
            cost: data.get('cost'),
            feeRate: data.get('feeRate'),
            shippingCompany: data.get('shippingCompany'),
            notes: data.get('notes')
        };

        await orderManager.addOrder(orderData);
        this.closeOrderModal();
        this.renderOrders();
        this.updateCounts();
    }

    async renderOrders() {
        const tbody = document.getElementById('orders-tbody');
        let orders = orderManager.orders;

        // 상태 필터
        if (this.currentOrderFilter !== 'all') {
            orders = orders.filter(o => o.status === this.currentOrderFilter);
        }

        if (orders.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="px-6 py-8 text-center text-gray-500">주문이 없습니다</td></tr>';
            return;
        }

        tbody.innerHTML = orders.map(order => {
            const channel = channelManager.channels.find(c => c.id === order.channelId);
            const statusColor = {
                'pending': 'bg-yellow-100 text-yellow-800',
                'shipped': 'bg-blue-100 text-blue-800',
                'delivered': 'bg-green-100 text-green-800',
                'cancelled': 'bg-red-100 text-red-800'
            }[order.status] || 'bg-gray-100 text-gray-800';

            return `
                <tr class="hover:bg-gray-50">
                    <td class="px-6 py-4 font-mono text-sm font-medium text-gray-900">${order.orderNumber}</td>
                    <td class="px-6 py-4">
                        <div>
                            <p class="font-medium text-gray-900">${order.customerName}</p>
                            <p class="text-xs text-gray-500">${order.customerPhone}</p>
                        </div>
                    </td>
                    <td class="px-6 py-4 text-sm">${channel ? channel.name : '알 수 없음'}</td>
                    <td class="px-6 py-4 text-right font-bold text-gray-900">₩${this.formatNumber(order.salePrice)}</td>
                    <td class="px-6 py-4 text-center">
                        <span class="inline-block px-3 py-1 rounded-full text-xs font-medium ${statusColor}">
                            ${orderManager.getStatusLabel(order.status)}
                        </span>
                    </td>
                    <td class="px-6 py-4 text-center space-x-1">
                        <button onclick="ui.updateOrderStatus('${order.id}', 'shipped')" class="text-blue-600 hover:text-blue-800 text-sm">배송</button>
                        <button onclick="ui.showReturnModal('${order.id}')" class="text-orange-600 hover:text-orange-800 text-sm" title="반품/교환/취소">↩️</button>
                        <button onclick="ui.deleteOrder('${order.id}')" class="text-red-600 hover:text-red-800 text-sm">삭제</button>
                    </td>
                </tr>
            `;
        }).join('');
    }

    async updateOrderStatus(orderId, newStatus) {
        await orderManager.updateOrderStatus(orderId, newStatus);
        this.renderOrders();
        this.updateCounts();
    }

    async deleteOrder(orderId) {
        if (confirm('정말 삭제하시겠습니까?')) {
            await orderManager.deleteOrder(orderId);
            this.renderOrders();
            this.updateCounts();
        }
    }

    /**
     * === 소싱 추적 ===
     */

    showSourcingModal() {
        const modal = document.getElementById('sourcing-modal');
        const form = document.getElementById('sourcing-form');
        form.reset();
        modal.classList.remove('hidden');
    }

    closeSourcingModal() {
        document.getElementById('sourcing-modal').classList.add('hidden');
    }

    async handleSourcingSubmit(e) {
        e.preventDefault();
        const form = e.target;
        const data = new FormData(form);

        const siteData = {
            name: data.get('name'),
            url: data.get('url'),
            type: data.get('type')
        };

        await sourcingManager.addSourcingSite(siteData);
        this.closeSourcingModal();
        this.renderSourcing();
    }

    async renderSourcing() {
        const tbody = document.getElementById('sourcing-tbody');

        if (sourcingManager.sourcingSites.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="px-6 py-8 text-center text-gray-500">추적 중인 사이트가 없습니다</td></tr>';
        } else {
            tbody.innerHTML = sourcingManager.sourcingSites.map(site => `
                <tr class="hover:bg-gray-50">
                    <td class="px-6 py-4 font-medium text-gray-900">${site.name}</td>
                    <td class="px-6 py-4 text-sm">${sourcingManager.getSiteTypeLabel(site.type)}</td>
                    <td class="px-6 py-4">
                        <span class="inline-block px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">활성</span>
                    </td>
                    <td class="px-6 py-4 text-sm text-gray-500">${site.lastChecked ? new Date(site.lastChecked).toLocaleDateString('ko-KR') : '아직 없음'}</td>
                    <td class="px-6 py-4 text-center">
                        <button onclick="ui.deleteSourcingSite('${site.id}')" class="text-red-600 hover:text-red-800 text-sm">삭제</button>
                    </td>
                </tr>
            `).join('');
        }

        // 모니터링 요약 업데이트
        const summary = sourcingManager.getPriceMonitoringSummary();
        document.getElementById('sourcing-tracked').textContent = summary.totalTracked;
        document.getElementById('sourcing-today').textContent = summary.todayUpdates;
        document.getElementById('sourcing-alerts').textContent = summary.priceAlerts;
        document.getElementById('sourcing-low-stock').textContent = summary.lowStockCount;
    }

    async deleteSourcingSite(siteId) {
        if (confirm('정말 삭제하시겠습니까?')) {
            await sourcingManager.deleteSourcingSite(siteId);
            this.renderSourcing();
        }
    }

    /**
     * === 통계/분석 ===
     */

    async renderAnalytics() {
        // 월간 통계
        const monthStart = new Date();
        monthStart.setDate(1);
        const monthStats = analyticsManager.getStatsByDateRange(monthStart, new Date());

        document.getElementById('analytics-month-sales').textContent = '₩' + this.formatNumber(monthStats.totalSales);
        document.getElementById('analytics-month-profit').textContent = '₩' + this.formatNumber(monthStats.totalProfit);
        document.getElementById('analytics-month-orders').textContent = monthStats.totalOrders;
        document.getElementById('analytics-profit-rate').textContent = monthStats.profitRate + '%';
        document.getElementById('analytics-avg-order').textContent = '₩' + this.formatNumber(monthStats.avgOrderValue);
        document.getElementById('analytics-total-orders').textContent = orderManager.orders.length;
        document.getElementById('analytics-delivered').textContent = orderManager.orders.filter(o => o.status === 'delivered').length;

        // 판매처별 분석
        this.renderAnalyticsChannel();
        // 상품별 분석
        this.renderAnalyticsProduct();
        // 주문 상태 분석
        this.renderAnalyticsStatus();
    }

    renderAnalyticsChannel() {
        const tbody = document.getElementById('analytics-channel-tbody');
        const channels = analyticsManager.getSalesByChannel();

        if (channels.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="px-6 py-8 text-center text-gray-500">데이터가 없습니다</td></tr>';
            return;
        }

        tbody.innerHTML = channels.map(ch => `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-4 font-medium text-gray-900">${ch.channelName}</td>
                <td class="px-6 py-4 text-right font-bold text-gray-900">₩${this.formatNumber(ch.sales)}</td>
                <td class="px-6 py-4 text-right font-bold text-green-600">₩${this.formatNumber(ch.profit)}</td>
                <td class="px-6 py-4 text-right text-gray-700">${ch.orders}개</td>
                <td class="px-6 py-4 text-right text-gray-700">₩${this.formatNumber(ch.avgPrice)}</td>
            </tr>
        `).join('');
    }

    renderAnalyticsProduct() {
        const tbody = document.getElementById('analytics-product-tbody');
        const products = analyticsManager.getSalesByProduct();

        if (products.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="px-6 py-8 text-center text-gray-500">데이터가 없습니다</td></tr>';
            return;
        }

        tbody.innerHTML = products.map(p => `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-4 font-medium text-gray-900">${p.productName}</td>
                <td class="px-6 py-4 text-right font-bold text-gray-900">₩${this.formatNumber(p.sales)}</td>
                <td class="px-6 py-4 text-right text-gray-700">${p.units}개</td>
                <td class="px-6 py-4 text-right font-bold text-green-600">₩${this.formatNumber(p.profit)}</td>
                <td class="px-6 py-4 text-right text-gray-700">₩${this.formatNumber(p.avgPrice)}</td>
            </tr>
        `).join('');
    }

    renderAnalyticsStatus() {
        const status = analyticsManager.getOrderStatusStats();
        const profit = analyticsManager.getProfitAnalysis();
        const total = Object.values(status).reduce((a, b) => a + b, 0);

        // 상태 진행률 업데이트
        if (total > 0) {
            document.querySelector('#status-pending').parentElement.querySelector('div').style.width = (status.pending / total * 100) + '%';
            document.querySelector('#status-shipped').parentElement.querySelector('div').style.width = (status.shipped / total * 100) + '%';
            document.querySelector('#status-delivered').parentElement.querySelector('div').style.width = (status.delivered / total * 100) + '%';
        }

        document.getElementById('status-pending').textContent = status.pending;
        document.getElementById('status-shipped').textContent = status.shipped;
        document.getElementById('status-delivered').textContent = status.delivered;

        if (profit) {
            document.getElementById('profit-total').textContent = '₩' + this.formatNumber(profit.totalRevenue);
            document.getElementById('profit-cost').textContent = '₩' + this.formatNumber(profit.totalCost);
            document.getElementById('profit-net').textContent = '₩' + this.formatNumber(profit.totalProfit);
        }
    }

    /**
     * === 차트 시각화 ===
     */

    renderCharts() {
        if (!document.getElementById('daily-sales-chart')) return;

        // 일별 매출 추이
        this.renderDailySalesChart();
        // 판매처별 매출 비율
        this.renderChannelSalesChart();
        // 상품별 판매량 TOP 5
        this.renderProductSalesChart();
        // 주문 상태 분포
        this.renderOrderStatusChart();

        // 차트 섹션 표시
        document.getElementById('analytics-charts').classList.remove('hidden');
    }

    renderDailySalesChart() {
        const ctx = document.getElementById('daily-sales-chart').getContext('2d');
        const trend = analyticsManager.getDailyTrend(30);

        const labels = trend.map(d => {
            const date = new Date(d.date);
            return date.toLocaleDateString('ko-KR', { month: 'numeric', day: 'numeric' });
        });

        const data = {
            labels,
            datasets: [
                {
                    label: '매출',
                    data: trend.map(d => d.sales),
                    borderColor: '#FF8C00',
                    backgroundColor: 'rgba(255, 140, 0, 0.1)',
                    tension: 0.4,
                    fill: true
                },
                {
                    label: '순이익',
                    data: trend.map(d => d.profit),
                    borderColor: '#FFB84D',
                    backgroundColor: 'rgba(255, 184, 77, 0.1)',
                    tension: 0.4,
                    fill: true
                }
            ]
        };

        new Chart(ctx, {
            type: 'line',
            data,
            options: {
                responsive: true,
                plugins: { legend: { position: 'top' } },
                scales: { y: { beginAtZero: true, ticks: { callback: v => '₩' + (v / 1000000).toFixed(0) + 'M' } } }
            }
        });
    }

    renderChannelSalesChart() {
        const ctx = document.getElementById('channel-sales-chart').getContext('2d');
        const channels = analyticsManager.getSalesByChannel();

        const data = {
            labels: channels.map(c => c.channelName),
            datasets: [{
                data: channels.map(c => c.sales),
                backgroundColor: [
                    '#FF8C00', '#FFB84D', '#FFA500', '#FF6B00',
                    '#FF7700', '#FF9500', '#FF8500', '#FFAA55'
                ]
            }]
        };

        new Chart(ctx, {
            type: 'doughnut',
            data,
            options: {
                responsive: true,
                plugins: {
                    legend: { position: 'right' },
                    tooltip: { callbacks: { label: ctx => '₩' + this.formatNumber(ctx.parsed) } }
                }
            }
        });
    }

    renderProductSalesChart() {
        const ctx = document.getElementById('product-sales-chart').getContext('2d');
        const products = analyticsManager.getSalesByProduct().slice(0, 5);

        const data = {
            labels: products.map(p => p.productName),
            datasets: [{
                label: '판매량',
                data: products.map(p => p.units),
                backgroundColor: '#FF8C00'
            }]
        };

        new Chart(ctx, {
            type: 'bar',
            data,
            options: {
                indexAxis: 'y',
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { x: { beginAtZero: true } }
            }
        });
    }

    renderOrderStatusChart() {
        const ctx = document.getElementById('order-status-chart').getContext('2d');
        const status = analyticsManager.getOrderStatusStats();

        const data = {
            labels: ['대기중', '배송중', '배송완료', '취소됨'],
            datasets: [{
                data: [status.pending, status.shipped, status.delivered, status.cancelled],
                backgroundColor: ['#FFC107', '#2196F3', '#4CAF50', '#F44336']
            }]
        };

        new Chart(ctx, {
            type: 'pie',
            data,
            options: {
                responsive: true,
                plugins: { legend: { position: 'bottom' } }
            }
        });
    }

    /**
     * === 반품/교환/취소 ===
     */

    showReturnModal(orderId) {
        const order = orderManager.orders.find(o => o.id === orderId);
        if (!order) return;

        const modal = document.getElementById('return-modal');
        const form = document.getElementById('return-form');

        form.reset();
        document.getElementById('return-order-id').value = orderId;
        document.getElementById('return-order-info').value = `${order.orderNumber} - ${order.customerName}`;
        document.getElementById('return-reason-select').innerHTML = '<option value="">사유를 선택하세요</option>';

        modal.classList.remove('hidden');
    }

    closeReturnModal() {
        document.getElementById('return-modal').classList.add('hidden');
    }

    updateReturnReasons() {
        const type = document.querySelector('select[name="type"]').value;
        const reasons = returnManager.getReturnReasons()[type] || [];
        const select = document.getElementById('return-reason-select');

        select.innerHTML = '<option value="">사유를 선택하세요</option>' +
            reasons.map(r => `<option value="${r.value}">${r.label}</option>`).join('');
    }

    async handleReturnSubmit(e) {
        e.preventDefault();
        const form = e.target;
        const data = new FormData(form);

        const returnData = {
            orderId: data.get('orderId'),
            type: data.get('type'),
            reason: data.get('reason'),
            description: data.get('description'),
            quantity: parseInt(data.get('quantity')),
            requestedAmount: parseFloat(data.get('requestedAmount'))
        };

        await returnManager.createReturn(returnData);
        this.closeReturnModal();
        this.renderReturns();
        this.updateCounts();
    }

    async renderReturns() {
        const tbody = document.getElementById('returns-tbody');
        const returns = returnManager.returns.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

        if (returns.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="px-6 py-8 text-center text-gray-500">반품/교환/취소 요청이 없습니다</td></tr>';
        } else {
            tbody.innerHTML = returns.map(ret => {
                const order = orderManager.orders.find(o => o.id === ret.orderId);
                const statusColor = {
                    'requested': 'bg-yellow-100 text-yellow-800',
                    'approved': 'bg-blue-100 text-blue-800',
                    'completed': 'bg-green-100 text-green-800',
                    'rejected': 'bg-red-100 text-red-800',
                    'cancelled': 'bg-gray-100 text-gray-800'
                }[ret.status] || 'bg-gray-100 text-gray-800';

                return `
                    <tr class="hover:bg-gray-50">
                        <td class="px-6 py-4 font-mono text-sm font-medium text-gray-900">${order?.orderNumber || '-'}</td>
                        <td class="px-6 py-4">
                            <p class="font-medium text-gray-900">${order?.customerName || '-'}</p>
                        </td>
                        <td class="px-6 py-4 text-sm">
                            <span class="px-2 py-1 rounded-full text-xs font-medium ${ret.type === 'return' ? 'bg-orange-100 text-orange-800' : ret.type === 'exchange' ? 'bg-blue-100 text-blue-800' : 'bg-red-100 text-red-800'}">
                                ${returnManager.getTypeLabel(ret.type)}
                            </span>
                        </td>
                        <td class="px-6 py-4 text-sm text-gray-600">${ret.reason}</td>
                        <td class="px-6 py-4 text-right font-bold text-gray-900">₩${this.formatNumber(ret.requestedAmount)}</td>
                        <td class="px-6 py-4 text-center">
                            <span class="inline-block px-3 py-1 rounded-full text-xs font-medium ${statusColor}">
                                ${returnManager.getStatusLabel(ret.status)}
                            </span>
                        </td>
                        <td class="px-6 py-4 text-sm text-gray-500">${new Date(ret.createdAt).toLocaleDateString('ko-KR')}</td>
                        <td class="px-6 py-4 text-center space-x-2">
                            ${ret.status === 'requested' ? `
                                <button onclick="ui.approveReturn('${ret.id}')" class="text-green-600 hover:text-green-800 text-sm">승인</button>
                                <button onclick="ui.rejectReturn('${ret.id}')" class="text-red-600 hover:text-red-800 text-sm">거부</button>
                            ` : ret.status === 'approved' ? `
                                <button onclick="ui.completeReturn('${ret.id}')" class="text-blue-600 hover:text-blue-800 text-sm">완료</button>
                            ` : '-'}
                        </td>
                    </tr>
                `;
            }).join('');
        }

        // 통계 업데이트
        const stats = returnManager.getReturnStats();
        document.getElementById('return-total').textContent = stats.total;
        document.getElementById('return-requested').textContent = stats.requested;
        document.getElementById('return-approved').textContent = stats.approved;
        document.getElementById('return-completed').textContent = stats.completed;
        document.getElementById('returns-badge').textContent = stats.requested;
    }

    async approveReturn(returnId) {
        await returnManager.approveReturn(returnId);
        this.renderReturns();
    }

    async rejectReturn(returnId) {
        const reason = prompt('거부 사유를 입력해주세요:');
        if (reason !== null) {
            await returnManager.rejectReturn(returnId, reason);
            this.renderReturns();
        }
    }

    async completeReturn(returnId) {
        await returnManager.completeReturn(returnId);
        this.renderReturns();
    }

    /**
     * === 고객 연락 ===
     */

    showContactModal() {
        const modal = document.getElementById('contact-modal');
        const form = document.getElementById('contact-form');
        form.reset();

        // 주문 목록 업데이트
        this.updateContactOrders();
        // 템플릿 업데이트
        this.updateContactTemplates();

        modal.classList.remove('hidden');
    }

    closeContactModal() {
        document.getElementById('contact-modal').classList.add('hidden');
    }

    updateContactOrders() {
        const select = document.getElementById('contact-order-select');
        if (!select) return;

        select.innerHTML = '<option value="">선택하세요</option>' +
            orderManager.orders.map(o => {
                const channel = channelManager.channels.find(c => c.id === o.channelId);
                const product = productManager.products.find(p => p.id === o.productId);
                return `<option value="${o.id}">${o.orderNumber} - ${product?.name || '상품'} (${o.customerName})</option>`;
            }).join('');

        // 주문 선택 시 고객 정보 자동 입력
        select.addEventListener('change', () => this.updateContactRecipient());
    }

    updateContactRecipient() {
        const orderId = document.querySelector('select[name="orderId"]').value;
        const order = orderManager.orders.find(o => o.id === orderId);

        if (order) {
            document.getElementById('contact-recipient').value = `${order.customerName} (${order.customerPhone})`;
        }
    }

    updateContactTemplates() {
        const type = document.querySelector('select[name="type"]').value;
        const templates = contactManager.templates[type] || {};
        const select = document.getElementById('contact-template-select');

        select.innerHTML = '<option value="">템플릿을 선택하세요</option>' +
            Object.entries(templates).map(([key, template]) => {
                return `<option value="${key}">${template.name}</option>`;
            }).join('');

        // 템플릿 선택 시 메시지 자동 입력
        select.addEventListener('change', () => {
            const selectedKey = select.value;
            if (selectedKey && templates[selectedKey]) {
                document.querySelector('textarea[name="message"]').value = templates[selectedKey].message;
            }
        });
    }

    async handleContactSubmit(e) {
        e.preventDefault();
        const form = e.target;
        const data = new FormData(form);

        const orderId = data.get('orderId');
        const order = orderManager.orders.find(o => o.id === orderId);

        if (!order) {
            app.showNotification('주문을 선택해주세요', 'error');
            return;
        }

        // 변수 대체
        let message = data.get('message');
        const product = productManager.products.find(p => p.id === order.productId);

        message = message
            .replace('{orderNumber}', order.orderNumber)
            .replace('{productName}', product?.name || '상품')
            .replace('{amount}', this.formatNumber(order.salePrice))
            .replace('{shippingCompany}', order.shippingCompany || '미정')
            .replace('{trackingNumber}', order.trackingNumber || '미정');

        const contactData = {
            orderId,
            type: data.get('type'),
            template: data.get('template'),
            message,
            recipient: order.customerPhone,
            customMessage: data.get('message')
        };

        await contactManager.sendContact(contactData);
        this.closeContactModal();
        this.renderContacts();
        this.updateCounts();
    }

    async renderContacts() {
        const tbody = document.getElementById('contacts-tbody');
        const logs = contactManager.contactLogs.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

        if (logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="px-6 py-8 text-center text-gray-500">발송된 연락이 없습니다</td></tr>';
        } else {
            tbody.innerHTML = logs.map(log => {
                const order = orderManager.orders.find(o => o.id === log.orderId);
                const statusColor = {
                    'sent': 'bg-green-100 text-green-800',
                    'pending': 'bg-yellow-100 text-yellow-800',
                    'failed': 'bg-red-100 text-red-800'
                }[log.status] || 'bg-gray-100 text-gray-800';

                return `
                    <tr class="hover:bg-gray-50">
                        <td class="px-6 py-4 font-mono text-sm font-medium text-gray-900">${order?.orderNumber || '-'}</td>
                        <td class="px-6 py-4">
                            <div>
                                <p class="font-medium text-gray-900">${order?.customerName || '-'}</p>
                                <p class="text-xs text-gray-500">${log.recipient}</p>
                            </div>
                        </td>
                        <td class="px-6 py-4 text-sm">${contactManager.getContactTypeLabel(log.type)}</td>
                        <td class="px-6 py-4 text-sm text-gray-600 max-w-sm truncate">${log.message}</td>
                        <td class="px-6 py-4 text-center">
                            <span class="inline-block px-3 py-1 rounded-full text-xs font-medium ${statusColor}">
                                ${contactManager.getStatusLabel(log.status)}
                            </span>
                        </td>
                        <td class="px-6 py-4 text-sm text-gray-500">${log.sentAt ? new Date(log.sentAt).toLocaleString('ko-KR') : '-'}</td>
                        <td class="px-6 py-4 text-center">
                            <button onclick="ui.deleteContact('${log.id}')" class="text-red-600 hover:text-red-800 text-sm">삭제</button>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        // 통계 업데이트
        const stats = contactManager.getContactStats();
        document.getElementById('contact-total').textContent = stats.total;
        document.getElementById('contact-sent').textContent = stats.sent;
        document.getElementById('contact-pending').textContent = stats.pending;
        document.getElementById('contact-failed').textContent = stats.failed;
        document.getElementById('contact-today').textContent = contactManager.getTodayContactCount();
    }

    async deleteContact(contactId) {
        if (confirm('정말 삭제하시겠습니까?')) {
            await contactManager.deleteContact(contactId);
            this.renderContacts();
        }
    }

    /**
     * === 공통 ===
     */

    async updateCounts() {
        document.getElementById('product-count').textContent = productManager.products.length;
        document.getElementById('channel-count').textContent = channelManager.channels.length;
        document.getElementById('total-orders').textContent = orderManager.orders.length;
        document.getElementById('pending-count').textContent = orderManager.getPendingOrders().length;
    }

    closeAllModals() {
        document.getElementById('product-modal')?.classList.add('hidden');
        document.getElementById('channel-modal')?.classList.add('hidden');
        document.getElementById('order-modal')?.classList.add('hidden');
        document.getElementById('sourcing-modal')?.classList.add('hidden');
    }

    formatNumber(num) {
        return new Intl.NumberFormat('ko-KR').format(num);
    }
}

// 글로벌 인스턴스
const ui = new UIManager();
