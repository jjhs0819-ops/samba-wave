/**
 * 로컬 스토리지 관리
 * IndexedDB 또는 localStorage를 사용하여 데이터 저장
 */

class StorageManager {
    constructor() {
        this.dbName = 'SambaWave';
        this.version = 1;
        this.db = null;
        this.useIndexedDB = true;
    }

    /**
     * 초기화 - IndexedDB 설정
     */
    async init() {
        try {
            this.db = await this.openIndexedDB();
            console.log('StorageManager 초기화 완료');
        } catch (error) {
            console.warn('IndexedDB 사용 불가, localStorage로 대체:', error);
            this.useIndexedDB = false;
        }
    }

    /**
     * IndexedDB 열기
     */
    openIndexedDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.dbName, this.version);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result);

            request.onupgradeneeded = (event) => {
                const db = event.target.result;

                // Object Stores 생성
                const stores = [
                    { name: 'products', keyPath: 'id', indexes: [{ name: 'sourceUrl', unique: false }] },
                    { name: 'channels', keyPath: 'id', indexes: [] },
                    { name: 'orders', keyPath: 'id', indexes: [{ name: 'channelId', unique: false }, { name: 'date', unique: false }] },
                    { name: 'sourcingSites', keyPath: 'id', indexes: [] },
                    { name: 'analytics', keyPath: 'id', indexes: [{ name: 'date', unique: false }] },
                    { name: 'contactLogs', keyPath: 'id', indexes: [{ name: 'orderId', unique: false }, { name: 'status', unique: false }] },
                    { name: 'returns', keyPath: 'id', indexes: [{ name: 'orderId', unique: false }, { name: 'status', unique: false }] },
                    { name: 'settings', keyPath: 'key', indexes: [] }
                ];

                stores.forEach(store => {
                    if (!db.objectStoreNames.contains(store.name)) {
                        const objectStore = db.createObjectStore(store.name, { keyPath: store.keyPath });
                        store.indexes.forEach(index => {
                            objectStore.createIndex(index.name, index.name, { unique: index.unique });
                        });
                    }
                });
            };
        });
    }

    /**
     * 데이터 저장
     */
    async save(storeName, data) {
        if (this.useIndexedDB) {
            return new Promise((resolve, reject) => {
                const transaction = this.db.transaction([storeName], 'readwrite');
                const objectStore = transaction.objectStore(storeName);
                const request = objectStore.put(data);

                request.onerror = () => reject(request.error);
                request.onsuccess = () => resolve(request.result);
            });
        } else {
            // localStorage 대체 구현
            const key = `${storeName}_${data.id}`;
            localStorage.setItem(key, JSON.stringify(data));
            return data.id;
        }
    }

    /**
     * 데이터 조회
     */
    async get(storeName, id) {
        if (this.useIndexedDB) {
            return new Promise((resolve, reject) => {
                const transaction = this.db.transaction([storeName], 'readonly');
                const objectStore = transaction.objectStore(storeName);
                const request = objectStore.get(id);

                request.onerror = () => reject(request.error);
                request.onsuccess = () => resolve(request.result);
            });
        } else {
            const key = `${storeName}_${id}`;
            const data = localStorage.getItem(key);
            return data ? JSON.parse(data) : null;
        }
    }

    /**
     * 모든 데이터 조회
     */
    async getAll(storeName) {
        if (this.useIndexedDB) {
            return new Promise((resolve, reject) => {
                const transaction = this.db.transaction([storeName], 'readonly');
                const objectStore = transaction.objectStore(storeName);
                const request = objectStore.getAll();

                request.onerror = () => reject(request.error);
                request.onsuccess = () => resolve(request.result);
            });
        } else {
            const prefix = `${storeName}_`;
            const result = [];
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key.startsWith(prefix)) {
                    result.push(JSON.parse(localStorage.getItem(key)));
                }
            }
            return result;
        }
    }

    /**
     * 데이터 삭제
     */
    async delete(storeName, id) {
        if (this.useIndexedDB) {
            return new Promise((resolve, reject) => {
                const transaction = this.db.transaction([storeName], 'readwrite');
                const objectStore = transaction.objectStore(storeName);
                const request = objectStore.delete(id);

                request.onerror = () => reject(request.error);
                request.onsuccess = () => resolve();
            });
        } else {
            const key = `${storeName}_${id}`;
            localStorage.removeItem(key);
        }
    }

    /**
     * Store 전체 삭제
     */
    async clear(storeName) {
        if (this.useIndexedDB) {
            return new Promise((resolve, reject) => {
                const transaction = this.db.transaction([storeName], 'readwrite');
                const objectStore = transaction.objectStore(storeName);
                const request = objectStore.clear();

                request.onerror = () => reject(request.error);
                request.onsuccess = () => resolve();
            });
        } else {
            const prefix = `${storeName}_`;
            const keysToRemove = [];
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key.startsWith(prefix)) {
                    keysToRemove.push(key);
                }
            }
            keysToRemove.forEach(key => localStorage.removeItem(key));
        }
    }

    /**
     * 인덱스로 조회
     */
    async getByIndex(storeName, indexName, value) {
        if (!this.useIndexedDB) {
            const all = await this.getAll(storeName);
            return all.filter(item => item[indexName] === value);
        }

        return new Promise((resolve, reject) => {
            const transaction = this.db.transaction([storeName], 'readonly');
            const objectStore = transaction.objectStore(storeName);
            const index = objectStore.index(indexName);
            const request = index.getAll(value);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result);
        });
    }

    /**
     * 전체 데이터베이스 백업 (JSON 형식)
     */
    async exportData() {
        const backup = {};
        const stores = ['products', 'channels', 'orders', 'sourcingSites', 'analytics', 'settings'];

        for (const storeName of stores) {
            backup[storeName] = await this.getAll(storeName);
        }

        return backup;
    }

    /**
     * 백업 데이터 복구
     */
    async importData(backup) {
        for (const [storeName, items] of Object.entries(backup)) {
            await this.clear(storeName);
            for (const item of items) {
                await this.save(storeName, item);
            }
        }
    }

    /**
     * 백업 파일 다운로드
     */
    async downloadBackup() {
        const data = await this.exportData();
        const json = JSON.stringify(data, null, 2);
        const blob = new Blob([json], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `samba-wave-backup-${new Date().toISOString().slice(0, 10)}.json`;
        a.click();
        URL.revokeObjectURL(url);
    }

    /**
     * 백업 파일 업로드
     */
    async uploadBackup(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = async (event) => {
                try {
                    const backup = JSON.parse(event.target.result);
                    await this.importData(backup);
                    resolve(true);
                } catch (error) {
                    reject(error);
                }
            };
            reader.onerror = () => reject(reader.error);
            reader.readAsText(file);
        });
    }
}

// 글로벌 인스턴스 생성
const storage = new StorageManager();

// 앱 시작 시 초기화
document.addEventListener('DOMContentLoaded', () => {
    storage.init();
});
