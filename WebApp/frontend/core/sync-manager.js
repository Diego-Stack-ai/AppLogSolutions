// sync-manager.js
import { db } from "./firebase-init.js";
import { connectivityService } from "./connectivity-service.js";
import { doc, getDoc, updateDoc, waitForPendingWrites } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";
import { getStorage, ref as sRef, uploadBytesResumable, getDownloadURL } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-storage.js";

const DB_NAME = 'AppLogSolutionsDB';
const DB_VERSION = 1;
const WATCHDOG_TIMEOUT_MS = 5 * 60 * 1000; // 5 minuti
const MAX_QUEUE_ITEMS = 5000;
const MAX_QUEUE_SIZE_MB = 100;

class SyncManager {
    constructor() {
        this.isProcessing = false;
        this.watchdogIntervalId = null;
        this.telemetry = this.loadTelemetry();
        this.init();
    }

    init() {
        // Ascolta lo stato di connettività
        connectivityService.addEventListener((status) => {
            if (status === 'online') {
                console.log("[SyncManager] Connessione stabile rilevata. Avvio sincronizzazione...");
                this.processQueue();
            } else {
                console.log("[SyncManager] Stato offline o instabile. Sincronizzazione sospesa.");
                this.isProcessing = false;
            }
        });

        // Avvia il watchdog per sbloccare eventuali caricamenti appesi
        this.startWatchdog();
        // Svuota periodicamente elementi scaduti
        this.cleanExpiredItems();
    }

    // ─── INDEXED DB SETUP ────────────────────────────────────────────────────────
    openDB() {
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onupgradeneeded = (event) => {
                const idb = event.target.result;
                if (!idb.objectStoreNames.contains('syncQueue')) {
                    idb.createObjectStore('syncQueue', { keyPath: 'id' });
                }
                if (!idb.objectStoreNames.contains('offlinePhotos')) {
                    idb.createObjectStore('offlinePhotos', { keyPath: 'id' });
                }
                if (!idb.objectStoreNames.contains('distances')) {
                    idb.createObjectStore('distances', { keyPath: 'key' });
                }
            };
            request.onsuccess = (event) => resolve(event.target.result);
            request.onerror = (event) => reject(event.target.error);
        });
    }

    // ─── GESTIONE CODA DI SINCRONIZZAZIONE (SyncQueue) ───────────────────────────
    async addOperation(type, payload, priority = 'Normal', expiresDays = 30) {
        const idb = await this.openDB();
        const tx = idb.transaction('syncQueue', 'readwrite');
        const store = tx.objectStore('syncQueue');

        // Verifica limite coda prima di aggiungere
        const count = await this.getStoreCount(store);
        if (count >= MAX_QUEUE_ITEMS) {
            console.warn("[SyncManager] Limite massimo elementi in coda raggiunto. Rinvio o eliminazione FIFO...");
            await this.makeRoomInQueue(store);
        }

        const operation = {
            id: `${type}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
            type,
            payload,
            priority, // 'Critical' | 'High' | 'Normal' | 'Low'
            retryCount: 0,
            status: 'queued', // 'queued' | 'uploading' | 'failed'
            lastError: null,
            expiresAt: Date.now() + (expiresDays * 24 * 60 * 60 * 1000),
            createdAt: Date.now()
        };

        store.put(operation);

        return new Promise((resolve, reject) => {
            tx.oncomplete = () => {
                console.log(`[SyncManager] Accodata operazione ${type} [ID: ${operation.id}]`);
                this.updateTelemetryMetric('added');
                // Tenta di processare se siamo online
                if (connectivityService.getStatus() === 'online') {
                    this.processQueue();
                }
                resolve(operation.id);
            };
            tx.onerror = (e) => reject(e.target.error);
        });
    }

    async getStoreCount(store) {
        return new Promise((resolve) => {
            const req = store.count();
            req.onsuccess = () => resolve(req.result);
        });
    }

    async makeRoomInQueue(store) {
        // FIFO semplice: elimina le vecchie operazioni a priorità Low o Normal
        return new Promise((resolve) => {
            const req = store.openCursor();
            req.onsuccess = (event) => {
                const cursor = event.target.result;
                if (cursor) {
                    const op = cursor.value;
                    if (op.priority === 'Low' || op.priority === 'Normal') {
                        cursor.delete();
                        console.log(`[SyncManager] Coda piena, eliminata operazione obsoleta: ${op.id}`);
                        resolve();
                        return;
                    }
                    cursor.continue();
                } else {
                    resolve();
                }
            };
        });
    }

    async processQueue() {
        if (this.isProcessing) return;
        if (connectivityService.getStatus() !== 'online') return;

        const idb = await this.openDB();
        const tx = idb.transaction('syncQueue', 'readonly');
        const store = tx.objectStore('syncQueue');

        // Leggi tutte le operazioni pendenti
        const operations = [];
        const req = store.openCursor();
        await new Promise((resolve) => {
            req.onsuccess = (e) => {
                const cursor = e.target.result;
                if (cursor) {
                    operations.push(cursor.value);
                    cursor.continue();
                } else {
                    resolve();
                }
            };
        });

        if (operations.length === 0) {
            // Verifica anche se Firestore ha scritture in sospeso nativamente
            this.checkFirestorePendingWrites();
            return;
        }

        this.isProcessing = true;

        // Ordina per priorità: Critical -> High -> Normal -> Low
        const priorityOrder = { 'Critical': 4, 'High': 3, 'Normal': 2, 'Low': 1 };
        operations.sort((a, b) => {
            const orderA = priorityOrder[a.priority] || 2;
            const orderB = priorityOrder[b.priority] || 2;
            if (orderA !== orderB) return orderB - orderA;
            return a.createdAt - b.createdAt; // FIFO a parità di priorità
        });

        console.log(`[SyncManager] Trovate ${operations.length} operazioni da sincronizzare. Avvio processamento.`);

        for (const op of operations) {
            if (!this.isProcessing || connectivityService.getStatus() !== 'online') {
                break;
            }

            // Se l'operazione ha fallito troppe volte, salta fino al prossimo ripristino manuale o riavvio
            if (op.retryCount >= 4) {
                const backoff = this.getBackoffDelay(op.retryCount);
                const nextAllowed = op.lastAttemptAt + backoff;
                if (Date.now() < nextAllowed) {
                    continue;
                }
            }

            await this.executeOperation(op);
        }

        this.isProcessing = false;
        
        // Verifica finale scritture native Firestore
        this.checkFirestorePendingWrites();
    }

    async executeOperation(op) {
        console.log(`[SyncManager] Esecuzione operazione: ${op.type} [ID: ${op.id}]`);
        await this.updateOperationStatus(op.id, 'uploading');

        const startTime = Date.now();
        try {
            switch (op.type) {
                case 'UPLOAD_PHOTO':
                    await this.handleUploadPhoto(op.payload);
                    break;
                case 'UPLOAD_STORAGE_STRING':
                    await this.handleUploadStorageString(op.payload);
                    break;
                // Altri tipi di operazione futuri possono essere inseriti qui
                default:
                    throw new Error(`Tipo operazione non supportato: ${op.type}`);
            }

            // Operazione riuscita: eliminala dalla coda
            await this.deleteOperation(op.id);
            this.updateTelemetryMetric('success', Date.now() - startTime);
            console.log(`[SyncManager] ✅ Operazione ${op.id} completata con successo.`);
        } catch (error) {
            console.error(`[SyncManager] ❌ Fallimento operazione ${op.id}:`, error);
            op.retryCount++;
            op.status = 'failed';
            op.lastError = error.message || 'Errore sconosciuto';
            op.lastAttemptAt = Date.now();

            await this.updateOperationRecord(op);
            this.updateTelemetryMetric('failure');

            // Notifica errore se critico
            if (op.priority === 'Critical') {
                this.dispatchUIEvent('sync-error', { id: op.id, error: op.lastError });
            }
        }
    }

    getBackoffDelay(retryCount) {
        if (retryCount === 1) return 10000;  // 10s
        if (retryCount === 2) return 30000;  // 30s
        if (retryCount === 3) return 120000; // 2m
        if (retryCount === 4) return 600000; // 10m
        return 0;
    }

    async updateOperationStatus(id, status) {
        const idb = await this.openDB();
        const tx = idb.transaction('syncQueue', 'readwrite');
        const store = tx.objectStore('syncQueue');
        const req = store.get(id);
        req.onsuccess = () => {
            const op = req.result;
            if (op) {
                op.status = status;
                if (status === 'uploading') {
                    op.startedUploadingAt = Date.now();
                }
                store.put(op);
            }
        };
    }

    async updateOperationRecord(op) {
        const idb = await this.openDB();
        const tx = idb.transaction('syncQueue', 'readwrite');
        tx.objectStore('syncQueue').put(op);
        await new Promise(r => tx.oncomplete = r);
    }

    async deleteOperation(id) {
        const idb = await this.openDB();
        const tx = idb.transaction('syncQueue', 'readwrite');
        tx.objectStore('syncQueue').delete(id);
        await new Promise(r => tx.oncomplete = r);
    }

    // ─── GESTIONE FOTO OFFLINE (IndexedDB & Storage) ──────────────────────────
    async savePhotoOffline(photoId, blob, tripId, anomaliaId = null) {
        const idb = await this.openDB();
        const tx = idb.transaction('offlinePhotos', 'readwrite');
        const store = tx.objectStore('offlinePhotos');

        const record = {
            id: photoId,
            blob,
            status: 'queued', // 'queued' | 'uploading' | 'uploaded' | 'failed'
            lastError: null,
            tripId,
            anomaliaId,
            createdAt: Date.now()
        };

        store.put(record);

        return new Promise((resolve, reject) => {
            tx.oncomplete = () => {
                console.log(`[SyncManager] Foto salvata in IndexedDB [ID: ${photoId}]`);
                resolve(true);
            };
            tx.onerror = (e) => reject(e.target.error);
        });
    }

    async handleUploadPhoto(payload) {
        const { photoId, docPath, fieldName } = payload;
        
        // 1. Recupera il blob da IndexedDB
        const idb = await this.openDB();
        const tx = idb.transaction('offlinePhotos', 'readwrite');
        const store = tx.objectStore('offlinePhotos');
        const record = await new Promise((resolve, reject) => {
            const req = store.get(photoId);
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.onerror);
        });

        if (!record) {
            throw new Error(`Immagine non trovata nel database locale [ID: ${photoId}]`);
        }

        record.status = 'uploading';
        store.put(record);

        const storage = getStorage();
        // File path su Storage: CONSEGNE/CONSEGNE_[DATA]/photoId.jpg
        const fileRef = sRef(storage, `CONSEGNE/OFFLINE_CONSEGNE/${photoId}.jpg`);

        try {
            // 2. Esegui l'upload reale su Firebase Storage
            const uploadTask = uploadBytesResumable(fileRef, record.blob);
            
            await new Promise((resolve, reject) => {
                uploadTask.on('state_changed', 
                    null, 
                    (err) => reject(err), 
                    () => resolve()
                );
            });

            const downloadUrl = await getDownloadURL(fileRef);

            // 3. Aggiorna il rispettivo documento Firestore (con supporto per array nidificati)
            const docRef = doc(db, ...docPath.split('/'));
            const docSnap = await getDoc(docRef);
            if (docSnap.exists()) {
                const data = docSnap.data();
                if (fieldName.includes('.')) {
                    const parts = fieldName.split('.');
                    if (parts[0] === 'attivitaAggiuntive') {
                        const idx = parseInt(parts[1]);
                        const arr = data.attivitaAggiuntive || [];
                        if (arr[idx]) {
                            arr[idx].fotoUrl = downloadUrl;
                            await updateDoc(docRef, {
                                attivitaAggiuntive: arr,
                                updatedAt: new Date()
                            });
                        }
                    } else if (parts[0] === 'anomalie') {
                        const idx = parseInt(parts[1]);
                        const arr = data.anomalie || [];
                        if (arr[idx]) {
                            arr[idx].fotoUrl = downloadUrl;
                            await updateDoc(docRef, {
                                anomalie: arr,
                                updatedAt: new Date()
                            });
                        }
                    }
                } else {
                    await updateDoc(docRef, {
                        [fieldName]: downloadUrl,
                        updatedAt: new Date()
                    });
                }
            } else {
                // Se non esiste ancora (es. non ancora propagato in Firestore remoto, sebbene raro), ritenta
                throw new Error(`Documento non trovato per collegamento foto: ${docPath}`);
            }

            // 4. Aggiorna stato in IndexedDB
            record.status = 'uploaded';
            record.lastError = null;
            const tx2 = idb.transaction('offlinePhotos', 'readwrite');
            tx2.objectStore('offlinePhotos').put(record);
            await new Promise(r => tx2.oncomplete = r);
            
            console.log(`[SyncManager] Foto caricata su Storage e collegata a Firestore [URL: ${downloadUrl}]`);
        } catch (e) {
            record.status = 'failed';
            record.lastError = e.message;
            const tx2 = idb.transaction('offlinePhotos', 'readwrite');
            tx2.objectStore('offlinePhotos').put(record);
            await new Promise(r => tx2.oncomplete = r);
            throw e;
        }
    }

    async handleUploadStorageString(payload) {
        const { path, data, contentType } = payload;
        const storage = getStorage();
        const fileRef = sRef(storage, path);
        const { uploadString } = await import("https://www.gstatic.com/firebasejs/10.8.0/firebase-storage.js");
        await uploadString(fileRef, data, 'raw', { contentType });
        console.log(`[SyncManager] File testuale caricato su Storage [Percorso: ${path}]`);
    }

    // ─── VERIFICA SCRITTURE FIRESTORE (waitForPendingWrites) ─────────────────
    async checkFirestorePendingWrites() {
        if (connectivityService.getStatus() === 'online') {
            try {
                // Attende che tutte le scritture locali in sospeso vengano confermate da Firestore Cloud
                await waitForPendingWrites(db);
                console.log("[SyncManager] Firestore allineato. Tutte le scritture locali sono state sincronizzate.");
                this.dispatchUIEvent('sync-completed', { timestamp: Date.now() });
            } catch (e) {
                console.warn("[SyncManager] Errore durante l'attesa di allineamento Firestore:", e.message);
            }
        }
    }

    // ─── WATCHDOG DI SICUREZZA ───────────────────────────────────────────────────
    startWatchdog() {
        this.stopWatchdog();
        this.watchdogIntervalId = setInterval(async () => {
            const idb = await this.openDB();
            const tx = idb.transaction('syncQueue', 'readwrite');
            const store = tx.objectStore('syncQueue');

            const req = store.openCursor();
            req.onsuccess = (e) => {
                const cursor = e.target.result;
                if (cursor) {
                    const op = cursor.value;
                    // Se l'operazione è in uploading da più di 5 minuti, resettala a failed
                    if (op.status === 'uploading' && op.startedUploadingAt && (Date.now() - op.startedUploadingAt) > WATCHDOG_TIMEOUT_MS) {
                        console.warn(`[SyncManager Watchdog] Rilevata operazione bloccata in uploading [ID: ${op.id}]. Reset a failed.`);
                        op.status = 'failed';
                        op.lastError = 'Timeout di caricamento (Watchdog reset)';
                        cursor.update(op);
                        this.updateTelemetryMetric('failure');
                    }
                    cursor.continue();
                }
            };
        }, 60000); // Controlla ogni minuto
    }

    stopWatchdog() {
        if (this.watchdogIntervalId) {
            clearInterval(this.watchdogIntervalId);
            this.watchdogIntervalId = null;
        }
    }

    async cleanExpiredItems() {
        const idb = await this.openDB();
        const tx = idb.transaction('syncQueue', 'readwrite');
        const store = tx.objectStore('syncQueue');

        const req = store.openCursor();
        req.onsuccess = (e) => {
            const cursor = e.target.result;
            if (cursor) {
                const op = cursor.value;
                if (op.expiresAt && Date.now() > op.expiresAt) {
                    console.log(`[SyncManager] Eliminata operazione scaduta dalla coda [ID: ${op.id}]`);
                    cursor.delete();
                }
                cursor.continue();
            }
        };
    }

    async bootstrapDistanceCache(onProgress) {
        try {
            if (connectivityService.getStatus() !== 'online') {
                throw new Error("Devi essere online per scaricare la cache delle distanze.");
            }

            console.log("[SyncManager] Avvio bootstrap cache distanze...");
            if (onProgress) onProgress("Inizializzazione download...");

            const storage = getStorage();
            const fileRef = sRef(storage, "caches/distanze_reali_cache.json");
            const url = await getDownloadURL(fileRef);

            if (onProgress) onProgress("Download file di cache (1.75 MB)...");
            const response = await fetch(url);
            if (!response.ok) throw new Error("Errore durante il download del file di cache delle distanze.");
            
            const cacheData = await response.json();
            const keys = Object.keys(cacheData);
            const total = keys.length;

            if (onProgress) onProgress(`Importazione di ${total} distanze in IndexedDB...`);
            
            const idb = await this.openDB();
            const CHUNK_SIZE = 500;
            
            for (let i = 0; i < total; i += CHUNK_SIZE) {
                const chunkKeys = keys.slice(i, i + CHUNK_SIZE);
                const tx = idb.transaction('distances', 'readwrite');
                const store = tx.objectStore('distances');
                
                chunkKeys.forEach(key => {
                    store.put({
                        key,
                        dist: cacheData[key].dist,
                        dur: cacheData[key].dur
                    });
                });
                
                await new Promise((resolve, reject) => {
                    tx.oncomplete = () => resolve();
                    tx.onerror = (e) => reject(e.target.error);
                });

                if (onProgress) {
                    const percent = Math.round(((i + chunkKeys.length) / total) * 100);
                    onProgress(`Importazione: ${percent}% (${i + chunkKeys.length}/${total})`);
                }
            }

            console.log("[SyncManager] ✅ Cache distanze importata con successo.");
            if (onProgress) onProgress("Sincronizzazione completata!");
            return true;
        } catch (e) {
            console.error("[SyncManager] Errore bootstrap cache distanze:", e);
            throw e;
        }
    }

    // ─── STRUMENTI DI DIAGNOSTICA E TELEMETRIA ──────────────────────────────
    loadTelemetry() {
        const def = { success: 0, failure: 0, added: 0, totalDuration: 0 };
        try {
            const cached = localStorage.getItem('sync_telemetry');
            return cached ? JSON.parse(cached) : def;
        } catch (e) {
            return def;
        }
    }

    saveTelemetry() {
        try {
            localStorage.setItem('sync_telemetry', JSON.stringify(this.telemetry));
        } catch (e) {}
    }

    updateTelemetryMetric(type, duration = 0) {
        if (type === 'success') {
            this.telemetry.success++;
            this.telemetry.totalDuration += duration;
        } else if (type === 'failure') {
            this.telemetry.failure++;
        } else if (type === 'added') {
            this.telemetry.added++;
        }
        this.saveTelemetry();
        this.dispatchUIEvent('telemetry-updated', this.telemetry);
    }

    async getQueueDiagnostics() {
        const idb = await this.openDB();
        
        const getStoreList = (storeName) => {
            return new Promise((resolve) => {
                const tx = idb.transaction(storeName, 'readonly');
                const store = tx.objectStore(storeName);
                const items = [];
                store.openCursor().onsuccess = (e) => {
                    const cursor = e.target.result;
                    if (cursor) {
                        items.push(cursor.value);
                        cursor.continue();
                    } else {
                        resolve(items);
                    }
                };
            });
        };

        const syncQueue = await getStoreList('syncQueue');
        const offlinePhotos = await getStoreList('offlinePhotos');

        return {
            connettivita: connectivityService.getStatus(),
            telemetria: this.telemetry,
            coda: {
                totale: syncQueue.length,
                dettagli: syncQueue.map(q => ({ id: q.id, type: q.type, status: q.status, priority: q.priority, retry: q.retryCount, error: q.lastError }))
            },
            foto: {
                totale: offlinePhotos.length,
                dettagli: offlinePhotos.map(f => ({ id: f.id, status: f.status, tripId: f.tripId, error: f.lastError }))
            }
        };
    }

    async getQueueItems() {
        const idb = await this.openDB();
        return new Promise((resolve) => {
            const tx = idb.transaction('syncQueue', 'readonly');
            const store = tx.objectStore('syncQueue');
            const items = [];
            store.openCursor().onsuccess = (e) => {
                const cursor = e.target.result;
                if (cursor) {
                    items.push(cursor.value);
                    cursor.continue();
                } else {
                    resolve(items);
                }
            };
        });
    }

    dispatchUIEvent(name, detail) {
        const event = new CustomEvent(name, { detail });
        window.dispatchEvent(event);
    }
}

export const syncManager = new SyncManager();
