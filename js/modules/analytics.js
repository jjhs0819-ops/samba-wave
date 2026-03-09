/**
 * 통계/분석 모듈
 * 매출 분석, 수익 통계, 추이 분석
 */

class AnalyticsManager {
    constructor() {
        this.analyticsData = [];
    }

    /**
     * 모든 분석 데이터 조회
     */
    async loadAnalytics() {
        try {
            this.analyticsData = await storage.getAll('analytics');
            return this.analyticsData;
        } catch (error) {
            console.error('분석 데이터 로드 실패:', error);
            return [];
        }
    }

    /**
     * 오늘의 통계 계산
     */
    getTodayStats() {
        const today = new Date();
        today.setHours(0, 0, 0, 0);

        const todayOrders = orderManager.orders.filter(order => {
            const orderDate = new Date(order.createdAt);
            orderDate.setHours(0, 0, 0, 0);
            return orderDate.getTime() === today.getTime();
        });

        return {
            totalSales: todayOrders.reduce((sum, o) => sum + o.salePrice, 0),
            totalOrders: todayOrders.length,
            totalProfit: todayOrders.reduce((sum, o) => sum + o.profit, 0),
            avgOrderValue: todayOrders.length > 0 ? Math.round(todayOrders.reduce((sum, o) => sum + o.salePrice, 0) / todayOrders.length) : 0,
            profitRate: todayOrders.length > 0 ? (todayOrders.reduce((sum, o) => sum + parseFloat(o.profitRate), 0) / todayOrders.length).toFixed(2) : 0
        };
    }

    /**
     * 기간별 통계 계산
     */
    getStatsByDateRange(startDate, endDate) {
        const orders = orderManager.orders.filter(order => {
            const orderDate = new Date(order.createdAt);
            return orderDate >= startDate && orderDate <= endDate;
        });

        return {
            totalSales: orders.reduce((sum, o) => sum + o.salePrice, 0),
            totalOrders: orders.length,
            totalProfit: orders.reduce((sum, o) => sum + o.profit, 0),
            avgOrderValue: orders.length > 0 ? Math.round(orders.reduce((sum, o) => sum + o.salePrice, 0) / orders.length) : 0,
            profitRate: orders.length > 0 ? (orders.reduce((sum, o) => sum + parseFloat(o.profitRate), 0) / orders.length).toFixed(2) : 0
        };
    }

    /**
     * 판매처별 매출 통계
     */
    getSalesByChannel() {
        const channelStats = {};

        channelManager.channels.forEach(channel => {
            const channelOrders = orderManager.orders.filter(o => o.channelId === channel.id);
            channelStats[channel.id] = {
                channelName: channel.name,
                sales: channelOrders.reduce((sum, o) => sum + o.salePrice, 0),
                orders: channelOrders.length,
                profit: channelOrders.reduce((sum, o) => sum + o.profit, 0),
                avgPrice: channelOrders.length > 0 ? Math.round(channelOrders.reduce((sum, o) => sum + o.salePrice, 0) / channelOrders.length) : 0,
                feeRate: channel.feeRate
            };
        });

        return Object.values(channelStats).sort((a, b) => b.sales - a.sales);
    }

    /**
     * 상품별 판매 통계
     */
    getSalesByProduct() {
        const productStats = {};

        productManager.products.forEach(product => {
            const productOrders = orderManager.orders.filter(o => o.productId === product.id);
            productStats[product.id] = {
                productName: product.name,
                sales: productOrders.reduce((sum, o) => sum + o.salePrice, 0),
                orders: productOrders.length,
                profit: productOrders.reduce((sum, o) => sum + o.profit, 0),
                units: productOrders.reduce((sum, o) => sum + o.quantity, 0),
                avgPrice: productOrders.length > 0 ? Math.round(productOrders.reduce((sum, o) => sum + o.salePrice, 0) / productOrders.length) : 0
            };
        });

        return Object.values(productStats).sort((a, b) => b.sales - a.sales);
    }

    /**
     * 일별 매출 추이 (최근 30일)
     */
    getDailyTrend(days = 30) {
        const trend = {};
        const today = new Date();

        for (let i = days - 1; i >= 0; i--) {
            const date = new Date(today);
            date.setDate(date.getDate() - i);
            const dateStr = date.toISOString().slice(0, 10);

            const dayOrders = orderManager.orders.filter(order => {
                return order.createdAt.slice(0, 10) === dateStr;
            });

            trend[dateStr] = {
                date: dateStr,
                sales: dayOrders.reduce((sum, o) => sum + o.salePrice, 0),
                orders: dayOrders.length,
                profit: dayOrders.reduce((sum, o) => sum + o.profit, 0)
            };
        }

        return Object.values(trend);
    }

    /**
     * 수익률 분석
     */
    getProfitAnalysis() {
        const orders = orderManager.orders;
        if (orders.length === 0) return null;

        const totalRevenue = orders.reduce((sum, o) => sum + (o.salePrice * (1 - o.feeRate / 100)), 0);
        const totalCost = orders.reduce((sum, o) => sum + o.cost, 0);
        const totalProfit = totalRevenue - totalCost;

        return {
            totalRevenue,
            totalCost,
            totalProfit,
            profitRate: ((totalProfit / totalRevenue) * 100).toFixed(2),
            orderCount: orders.length,
            avgProfitPerOrder: Math.round(totalProfit / orders.length)
        };
    }

    /**
     * 상태별 주문 통계
     */
    getOrderStatusStats() {
        const stats = {
            pending: 0,
            shipped: 0,
            delivered: 0,
            cancelled: 0,
            returned: 0
        };

        orderManager.orders.forEach(order => {
            if (stats.hasOwnProperty(order.status)) {
                stats[order.status]++;
            }
        });

        return stats;
    }

    /**
     * 월별 매출 비교
     */
    getMonthlyComparison() {
        const monthlyData = {};

        orderManager.orders.forEach(order => {
            const date = new Date(order.createdAt);
            const monthKey = date.toISOString().slice(0, 7); // YYYY-MM

            if (!monthlyData[monthKey]) {
                monthlyData[monthKey] = {
                    month: monthKey,
                    sales: 0,
                    orders: 0,
                    profit: 0
                };
            }

            monthlyData[monthKey].sales += order.salePrice;
            monthlyData[monthKey].orders += 1;
            monthlyData[monthKey].profit += order.profit;
        });

        return Object.values(monthlyData).sort((a, b) => a.month.localeCompare(b.month));
    }

    /**
     * 상품별 수익률
     */
    getProductProfitMargin() {
        const margins = {};

        productManager.products.forEach(product => {
            const productOrders = orderManager.orders.filter(o => o.productId === product.id);
            if (productOrders.length === 0) return;

            const totalRevenue = productOrders.reduce((sum, o) => sum + (o.salePrice * (1 - o.feeRate / 100)), 0);
            const totalCost = productOrders.reduce((sum, o) => sum + o.cost, 0);
            const margin = ((totalRevenue - totalCost) / totalRevenue * 100).toFixed(2);

            margins[product.id] = {
                productName: product.name,
                margin: parseFloat(margin),
                marginRate: product.marginRate,
                sales: totalRevenue,
                orders: productOrders.length
            };
        });

        return Object.values(margins).sort((a, b) => b.margin - a.margin);
    }

    /**
     * 채널별 수익률
     */
    getChannelProfitMargin() {
        const margins = {};

        channelManager.channels.forEach(channel => {
            const channelOrders = orderManager.orders.filter(o => o.channelId === channel.id);
            if (channelOrders.length === 0) return;

            const totalRevenue = channelOrders.reduce((sum, o) => sum + (o.salePrice * (1 - o.feeRate / 100)), 0);
            const totalCost = channelOrders.reduce((sum, o) => sum + o.cost, 0);
            const margin = ((totalRevenue - totalCost) / totalRevenue * 100).toFixed(2);

            margins[channel.id] = {
                channelName: channel.name,
                margin: parseFloat(margin),
                feeRate: channel.feeRate,
                sales: totalRevenue,
                orders: channelOrders.length
            };
        });

        return Object.values(margins).sort((a, b) => b.margin - a.margin);
    }

    /**
     * 핵심 KPI 요약
     */
    getKPISummary() {
        const today = this.getTodayStats();
        const monthStart = new Date();
        monthStart.setDate(1);
        const monthStats = this.getStatsByDateRange(monthStart, new Date());
        const profitAnalysis = this.getProfitAnalysis();

        return {
            todaySales: today.totalSales,
            todayProfit: today.totalProfit,
            monthSales: monthStats.totalSales,
            monthProfit: monthStats.totalProfit,
            totalOrders: orderManager.orders.length,
            overallProfitRate: profitAnalysis ? profitAnalysis.profitRate : 0,
            topChannel: this.getSalesByChannel()[0],
            topProduct: this.getSalesByProduct()[0]
        };
    }
}

// 글로벌 인스턴스
const analyticsManager = new AnalyticsManager();
