/**
 * 금지어/삭제어 관리 (ForbiddenManager)
 * 수집 시 금지어 포함 상품 제외, 상품명에서 삭제어 제거
 */

class ForbiddenManager {
    constructor() {
        this.words = []
        this.groups = []  // 그룹 목록: { id, name, type, wordsText, isActive }
    }

    async init() {
        await this.loadWords()
        await this.loadGroups()
    }

    // ==================== 그룹 CRUD ====================

    async loadGroups() {
        try {
            const cfg = await storage.get('settings', 'forbiddenGroups')
            this.groups = cfg ? cfg.groups : []
        } catch {
            this.groups = []
        }
        return this.groups
    }

    async saveGroups() {
        await storage.save('settings', { id: 'forbiddenGroups', groups: this.groups })
        // 그룹에서 개별 단어 목록 재생성 (필터링용)
        this.words = []
        for (const g of this.groups.filter(g => g.isActive)) {
            const words = g.wordsText.split(';').map(w => w.trim()).filter(Boolean)
            for (const w of words) {
                this.words.push({ id: `${g.id}_${w}`, word: w, type: g.type, scope: 'title', isActive: true, groupId: g.id })
            }
        }
    }

    async addGroup(name, type) {
        const group = {
            id: 'fg_' + Date.now(),
            name,
            type,       // 'forbidden' | 'deletion'
            wordsText: '',
            isActive: true
        }
        this.groups.push(group)
        await this.saveGroups()
        return group
    }

    async updateGroup(id, wordsText, isActive) {
        const g = this.groups.find(g => g.id === id)
        if (!g) return
        g.wordsText = wordsText
        g.isActive = isActive
        await this.saveGroups()
    }

    async deleteGroup(id) {
        this.groups = this.groups.filter(g => g.id !== id)
        await this.saveGroups()
    }

    getGroups(type) {
        return this.groups.filter(g => g.type === type)
    }

    // ==================== 기존 CRUD (하위 호환) ====================

    async loadWords() {
        // 그룹에서 개별 단어 로드 (설정 페이지 진입 시 그룹과 동기화)
        try {
            const cfg = await storage.get('settings', 'forbiddenGroups')
            const groups = cfg ? cfg.groups : []
            this.words = []
            for (const g of groups.filter(g => g.isActive)) {
                const words = g.wordsText.split(';').map(w => w.trim()).filter(Boolean)
                for (const w of words) {
                    this.words.push({ id: `${g.id}_${w}`, word: w, type: g.type, scope: 'title', isActive: true, groupId: g.id })
                }
            }
        } catch {
            this.words = []
        }
        return this.words
    }

    async addWord(data) {
        const word = {
            id: 'fw_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
            word: data.word || '',
            type: data.type || 'forbidden',    // 'forbidden' | 'deletion'
            scope: data.scope || 'title',       // 'title' | 'description' | 'both'
            isActive: data.isActive !== undefined ? data.isActive : true,
            createdAt: new Date().toISOString()
        }
        await storage.save('forbiddenWords', word)
        this.words.push(word)
        return word
    }

    async deleteWord(id) {
        await storage.delete('forbiddenWords', id)
        this.words = this.words.filter(w => w.id !== id)
    }

    async toggleWord(id) {
        const word = this.words.find(w => w.id === id)
        if (!word) return null
        const updated = { ...word, isActive: !word.isActive }
        await storage.save('forbiddenWords', updated)
        const idx = this.words.findIndex(w => w.id === id)
        if (idx !== -1) this.words[idx] = updated
        return updated
    }

    // ==================== 필터링/적용 ====================

    /**
     * 금지어 포함 상품 필터링 (수집 시 제외)
     */
    filterProducts(products) {
        const forbiddenActive = this.words.filter(w => w.type === 'forbidden' && w.isActive)
        if (forbiddenActive.length === 0) return products

        return products.filter(product => {
            for (const fw of forbiddenActive) {
                const word = fw.word.toLowerCase()
                if (fw.scope === 'title' || fw.scope === 'both') {
                    if (product.name && product.name.toLowerCase().includes(word)) return false
                }
            }
            return true
        })
    }

    /**
     * 삭제어 제거 (상품명에서)
     */
    cleanProductName(name) {
        if (!name) return name
        const deletionActive = this.words.filter(w => (w.type === 'deletion') && w.isActive && (w.scope === 'title' || w.scope === 'both'))
        let cleaned = name
        for (const dw of deletionActive) {
            const regex = new RegExp(dw.word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi')
            cleaned = cleaned.replace(regex, '').trim()
        }
        // 연속 공백 정리
        return cleaned.replace(/\s+/g, ' ').trim()
    }

    /**
     * 삭제어 제거 (상세페이지에서)
     */
    cleanDescription(text) {
        if (!text) return text
        const deletionActive = this.words.filter(w => w.type === 'deletion' && w.isActive && (w.scope === 'description' || w.scope === 'both'))
        let cleaned = text
        for (const dw of deletionActive) {
            const regex = new RegExp(dw.word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi')
            cleaned = cleaned.replace(regex, '')
        }
        return cleaned
    }

    /**
     * 상품 금지어/삭제어 검증
     */
    validateProduct(product) {
        const forbiddenFound = []
        const deletionFound = []

        for (const fw of this.words.filter(w => w.isActive)) {
            const word = fw.word.toLowerCase()
            const inTitle = product.name && product.name.toLowerCase().includes(word)

            if (inTitle && (fw.scope === 'title' || fw.scope === 'both')) {
                if (fw.type === 'forbidden') forbiddenFound.push(fw.word)
                else deletionFound.push(fw.word)
            }
        }

        return {
            isValid: forbiddenFound.length === 0,
            forbiddenFound,
            deletionFound,
            cleanName: this.cleanProductName(product.name)
        }
    }

    getForbiddenWords() {
        return this.words.filter(w => w.type === 'forbidden')
    }

    getDeletionWords() {
        return this.words.filter(w => w.type === 'deletion')
    }
}

// 글로벌 인스턴스
const forbiddenManager = new ForbiddenManager()
