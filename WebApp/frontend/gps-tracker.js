/**
 * gps-tracker.js — v1.32
 * Tracking GPS professionale con IndexedDB (buffer offline), batch Firestore,
 * idempotenza log, heartbeat corretto, retry automatico.
 *
 * API pubblica (window.*):
 *   - startGPSTracking(tripId, initialKm)
 *   - stopGPSTracking()
 *   - recoverGPSTracking()
 *   - getGPSStatus()
 *   - updateTrackingStatus(status)
 */

import {
    collection,
    doc,
    writeBatch,
    serverTimestamp,
    Timestamp
} from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";
import { db } from "./core/firebase-init.js";

// ─── Costanti di configurazione ─────────────────────────────────────────────
const IDB_NAME          = 'gpsLogsDB';   // Nome del database IndexedDB
const IDB_STORE         = 'bufferedLogs'; // Nome dell'object store
const IDB_VERSION       = 1;              // Versione schema IndexedDB
const MAX_ACCURACY_M    = 50;   // Accuratezza GPS massima accettabile (metri)
const MIN_SPEED_MS      = 0.5;  // Velocità minima per loggare (m/s ≈ 1.8 km/h)
const MIN_DISTANCE_M    = 0;    // Non utilizzato dal filtro temporale stretto, ma mantenuto per chiarezza
const MIN_TIME_S        = 90;   // Intervallo minimo tra due log (secondi)
const HEARTBEAT_S       = 90;   // Frequenza heartbeat forzato (secondi)
const BATCH_SIZE        = 10;   // Numero di log per ogni batch Firestore
const MAX_BUFFER_PER_TRIP = 500; // Limite massimo di log in buffer per singolo viaggio

// ─── Stato interno del modulo ────────────────────────────────────────────────
let idbInstance    = null;   // Connessione attiva al database IndexedDB
let watchId        = null;   // ID restituito da watchPosition (per clearWatch)
let heartbeatTimer = null;   // ID intervallo heartbeat (per clearInterval)
let isTracking     = false;  // True se il tracking è attivo
let isSyncing      = false;  // Mutex: impedisce processBuffer() paralleli (race condition)
let currentTripId  = null;   // ID del viaggio corrente su Firestore
let lastPosition   = null;   // Ultima posizione salvata { lat, lng } — usata per filtro distanza
let lastTimestamp  = 0;      // Timestamp (ms) dell'ultimo log salvato — usato per filtro tempo
let lastKnownPos   = null;   // Ultima posizione ricevuta da watchPosition (aggiornata sempre)

// ─── IndexedDB Setup ──────────────────────────────────────────────────────────

function openIDB() {
    return new Promise((resolve, reject) => {
        if (idbInstance) { resolve(idbInstance); return; }

        const req = indexedDB.open(IDB_NAME, IDB_VERSION);

        req.onupgradeneeded = (e) => {
            const idb = e.target.result;
            if (!idb.objectStoreNames.contains(IDB_STORE)) {
                // keyPath = id generato → garantisce idempotenza
                idb.createObjectStore(IDB_STORE, { keyPath: 'id' });
                console.log('[IDB] Object store creato:', IDB_STORE);
            }
        };

        req.onsuccess = (e) => {
            idbInstance = e.target.result;
            console.log('[IDB] ✅ Connessione aperta.');
            resolve(idbInstance);
        };

        req.onerror = (e) => {
            console.error('[IDB] ❌ Errore apertura:', e.target.error);
            reject(e.target.error);
        };
    });
}

async function idbPut(log) {
    const idb = await openIDB();
    return new Promise((resolve, reject) => {
        const tx    = idb.transaction(IDB_STORE, 'readwrite');
        const store = tx.objectStore(IDB_STORE);
        store.put(log);                         // put = upsert: se id esiste, sovrascrive
        tx.oncomplete = () => resolve(true);
        tx.onerror    = (e) => reject(e.target.error);
    });
}

async function idbGetBatch(limit = BATCH_SIZE) {
    const idb = await openIDB();
    return new Promise((resolve, reject) => {
        const tx    = idb.transaction(IDB_STORE, 'readonly');
        const store = tx.objectStore(IDB_STORE);
        const logs  = [];
        const req   = store.openCursor();
        req.onsuccess = (e) => {
            const cursor = e.target.result;
            if (cursor && logs.length < limit) {
                logs.push(cursor.value);
                cursor.continue();
            } else {
                resolve(logs);
            }
        };
        req.onerror = (e) => reject(e.target.error);
    });
}

async function idbDelete(ids) {
    if (!ids || ids.length === 0) return;
    const idb = await openIDB();
    return new Promise((resolve, reject) => {
        const tx    = idb.transaction(IDB_STORE, 'readwrite');
        const store = tx.objectStore(IDB_STORE);
        ids.forEach(id => store.delete(id));
        tx.oncomplete = () => resolve(true);
        tx.onerror    = (e) => reject(e.target.error);
    });
}

async function idbCount() {
    // Conta TUTTI i log nel buffer (usato per info generali)
    const idb = await openIDB();
    return new Promise((resolve, reject) => {
        const tx    = idb.transaction(IDB_STORE, 'readonly');
        const store = tx.objectStore(IDB_STORE);
        const req   = store.count();
        req.onsuccess = () => resolve(req.result);
        req.onerror   = (e) => reject(e.target.error);
    });
}

async function idbCountByTrip(tripId) {
    // Conta i log nel buffer FILTRANDO per tripId — usato per il limite per-viaggio
    const idb = await openIDB();
    return new Promise((resolve, reject) => {
        const tx    = idb.transaction(IDB_STORE, 'readonly');
        const store = tx.objectStore(IDB_STORE);
        let count = 0;
        const req = store.openCursor();
        req.onsuccess = (e) => {
            const cursor = e.target.result;
            if (cursor) {
                if (cursor.value.tripId === tripId) count++;
                cursor.continue();
            } else {
                resolve(count);
            }
        };
        req.onerror = (e) => reject(e.target.error);
    });
}

// ─── ID univoco log (per idempotenza) ────────────────────────────────────────
// Stesso punto inviato due volte → stesso ID → Firebase sovrascrive con dati identici.
function generateLogId(tripId, lat, lng, timestamp) {
    return `${tripId}_${timestamp}_${lat.toFixed(5)}_${lng.toFixed(5)}`;
}

// ─── UI: Banner fisso + #trackingStatus inline ────────────────────────────────

window.updateTrackingStatus = function(status) {
    const el = document.getElementById('trackingStatus');
    const states = {
        active:  '🟢 Tracking attivo',
        stopped: '🔴 Tracking fermo',
        error:   '⚠️ GPS non disponibile',
        syncing: '🔄 Sincronizzazione log offline...'
    };
    if (el) el.textContent = states[status] || status;
};

function updateBanner(status, message) {
    let banner = document.getElementById('__tracking_banner');
    if (!banner) {
        banner = document.createElement('div');
        banner.id = '__tracking_banner';
        banner.style.cssText = `
            position:fixed; bottom:80px; left:16px; right:16px; z-index:9999;
            color:white; padding:10px 16px; border-radius:12px; font-size:13px;
            font-family:inherit; display:flex; align-items:center; gap:8px;
            box-shadow:0 4px 20px rgba(0,0,0,0.2);
            transition:background 0.3s ease, opacity 0.3s ease;
        `;
        document.body.appendChild(banner);
    }
    const colors = { active:'#0f766e', stopped:'#64748b', error:'#ef4444', syncing:'#7c3aed' };
    const icons  = { active:'gps_fixed', stopped:'pause_circle', error:'gps_off', syncing:'sync' };
    banner.style.background = colors[status] || '#64748b';
    banner.innerHTML = `<span class="material-icons-round" style="font-size:18px;">${icons[status]||'gps_off'}</span> ${message}`;
    banner.style.display = 'flex';
    banner.style.opacity = '1';
}

function hideBanner() {
    const b = document.getElementById('__tracking_banner');
    if (b) { b.style.opacity = '0'; setTimeout(() => b.style.display = 'none', 350); }
}

// ─── Haversine ────────────────────────────────────────────────────────────────

function getDistance(pos1, pos2) {
    if (!pos1 || !pos2) return Infinity;
    const R  = 6371e3;
    const φ1 = pos1.lat * Math.PI / 180;
    const φ2 = pos2.lat * Math.PI / 180;
    const Δφ = (pos2.lat - pos1.lat) * Math.PI / 180;
    const Δλ = (pos2.lng - pos1.lng) * Math.PI / 180;
    const a  = Math.sin(Δφ/2)**2 + Math.cos(φ1)*Math.cos(φ2)*Math.sin(Δλ/2)**2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

// ─── Salva log in IndexedDB (sempre) + tenta flush immediato ──────────────────

async function saveLogToBuffer(tripId, logData, isHeartbeat = false) {
    // Verifica il limite per-viaggio (MAX_BUFFER_PER_TRIP = 500)
    // Questo evita overflow se il device rimane offline per molto tempo
    const tripCount = await idbCountByTrip(tripId);
    if (tripCount >= MAX_BUFFER_PER_TRIP) {
        console.warn(`[GPS Buffer] ⚠️ Limite ${MAX_BUFFER_PER_TRIP} log raggiunto per viaggio ${tripId}. Log scartato.`);
        updateBanner('error', `Buffer pieno (${MAX_BUFFER_PER_TRIP} log) — riconnetti per svuotarlo`);
        return;
    }

    const ts  = Date.now();
    const log = {
        id:          generateLogId(tripId, logData.lat, logData.lng, ts), // ID univoco per idempotenza
        tripId,
        lat:         logData.lat,
        lng:         logData.lng,
        accuracy:    logData.accuracy,
        speed:       logData.speed,
        km:          logData.km,
        timestamp:   ts,
        isHeartbeat: isHeartbeat
        // NOTA: fromBuffer NON viene settato qui.
        // Viene aggiunto in processBuffer() solo al momento dell'invio su Firestore.
    };

    await idbPut(log); // idbPut usa put() = upsert: se stessa id esiste, sovrascrive
    const totalCount = await idbCount();
    console.log(`[GPS] 📦 Log in IDB [${isHeartbeat ? 'HEARTBEAT' : 'NORMALE'}] viaggio:${tripId} (${tripCount + 1}/${MAX_BUFFER_PER_TRIP}) totale buffer:${totalCount}`);

    // Flush immediato se la rete è disponibile, altrimenti mostra stato offline
    if (navigator.onLine) {
        await processBuffer();
    } else {
        updateBanner('error', `Offline — ${totalCount} log bufferizzati localmente`);
    }
}

// ─── Flush batch → Firestore (with mutex) ─────────────────────────────────────

async function processBuffer() {
    if (isSyncing) {
        console.log('[GPS Buffer] Sync già in corso, salto.');
        return;
    }

    // Verifica se c'è qualcosa da sync
    const initialCount = await idbCount();
    if (initialCount === 0) return;

    isSyncing = true;
    console.log(`[GPS Buffer] 🔄 Avvio sync: ${initialCount} log in IDB...`);
    updateBanner('syncing', `Sync ${initialCount} log offline...`);
    window.updateTrackingStatus('syncing');

    try {
        // Loop a batch (no ricorsione → nessun rischio stack overflow)
        let remaining = true;
        while (remaining) {
            const logs = await idbGetBatch(BATCH_SIZE);
            if (!logs || logs.length === 0) { remaining = false; break; }

            // Crea batch Firestore (SDK v10 modulare)
            const batch   = writeBatch(db);
            const toDelete = [];

            logs.forEach(log => {
                // Percorso: viaggi/{tripId}/logs/{log.id}
                // Usare doc con ID generato garantisce idempotenza
                const docRef = doc(db, 'viaggi', log.tripId, 'logs', log.id);
                batch.set(docRef, {
                    lat:         log.lat,
                    lng:         log.lng,
                    accuracy:    log.accuracy,
                    speed:       log.speed,
                    km:          log.km || null,
                    timestamp:   Timestamp.fromMillis(log.timestamp),
                    isHeartbeat: log.isHeartbeat || false,
                    fromBuffer:  true
                }, { merge: true });   // merge: true → sicuro contro sovrascritture parziali
                toDelete.push(log.id);
            });

            await batch.commit();
            await idbDelete(toDelete);

            const newCount = await idbCount();
            console.log(`[GPS Buffer] ✅ Batch ${logs.length} inviato. Rimanenti: ${newCount}`);

            if (newCount === 0) remaining = false;
        }

        console.log('[GPS Buffer] ✅ Sync completato.');
        const t = new Date().toLocaleTimeString('it-IT', { hour:'2-digit', minute:'2-digit' });

        if (isTracking) {
            updateBanner('active', `Tracking attivo — sync ${t}`);
            window.updateTrackingStatus('active');
        } else {
            hideBanner();
            window.updateTrackingStatus('stopped');
        }

    } catch (e) {
        console.warn('[GPS Buffer] ❌ Batch fallito — riprovo al prossimo evento online:', e.message);
        const pendingCount = await idbCount();
        updateBanner('error', `Offline — ${pendingCount} log in sospeso`);
    } finally {
        isSyncing = false;
    }
}

// ─── Elaborazione posizione watchPosition ─────────────────────────────────────

async function processLocation(pos, km = null, isHeartbeat = false) {
    if (!currentTripId) return;

    const { latitude: lat, longitude: lng, accuracy, speed } = pos.coords;
    const now = Date.now();

    // Salva sempre l'ultima posizione nota (usata dal heartbeat)
    lastKnownPos = { lat, lng, accuracy, speed };

    // FILTRO 1: Accuratezza GPS scarsa
    if (accuracy > MAX_ACCURACY_M) {
        console.log(`[GPS] 🚫 Skip: acc ${accuracy.toFixed(1)}m > ${MAX_ACCURACY_M}m`);
        return;
    }

    // FILTRO 2: Velocità troppo bassa (solo su log normali, non heartbeat)
    if (!isHeartbeat && speed !== null && speed < MIN_SPEED_MS) {
        console.log(`[GPS] 🚫 Skip: fermo ${(speed*3.6).toFixed(1)} km/h (heartbeat attivo)`);
        return;
    }

    const currentPos = { lat, lng };

    // FILTRO 3: Limita frequenza a MIN_TIME_S (es. 90 secondi)
    if (!isHeartbeat && lastPosition) {
        const timeDiff = (now - lastTimestamp) / 1000;
        if (timeDiff < MIN_TIME_S) {
            console.log(`[GPS] 🚫 Skip: timeDelta=${timeDiff.toFixed(0)}s < ${MIN_TIME_S}s`);
            return;
        }
    }

    // Aggiorna stato filtri per il prossimo confronto
    lastPosition  = currentPos;
    lastTimestamp = now;

    await saveLogToBuffer(currentTripId, {
        lat,
        lng,
        accuracy: parseFloat(accuracy.toFixed(1)),
        speed:    speed !== null ? parseFloat((speed * 3.6).toFixed(1)) : null,
        km:       (km !== null && km !== '') ? Number(km) : null
    }, isHeartbeat);

    // Resetta il timer dell'heartbeat per evitare accavallamenti
    if (!isHeartbeat) {
        startHeartbeat(km);
    }
}

// ─── Heartbeat corretto: usa lastKnownPos da watchPosition ───────────────────

function startHeartbeat(km) {
    stopHeartbeat();
    heartbeatTimer = setInterval(async () => {
        if (!isTracking || !currentTripId) return;

        // CORRETTO: usa lastKnownPos (non dal buffer), con bypass filtri
        if (lastKnownPos) {
            console.log('[GPS] 💓 Heartbeat: log forzato da lastKnownPos');
            await saveLogToBuffer(currentTripId, {
                lat:      lastKnownPos.lat,
                lng:      lastKnownPos.lng,
                accuracy: lastKnownPos.accuracy,
                speed:    lastKnownPos.speed !== null ? parseFloat((lastKnownPos.speed * 3.6).toFixed(1)) : 0,
                km
            }, true);
            
            // Aggiorna stato locale per evitare log simultanei da watchPosition
            lastPosition = { lat: lastKnownPos.lat, lng: lastKnownPos.lng };
            lastTimestamp = Date.now();
        } else {
            // Fallback: richiedi posizione fresca via getCurrentPosition
            console.log('[GPS] 💓 Heartbeat: nessuna lastKnownPos, richiedo GPS...');
            navigator.geolocation.getCurrentPosition(
                (pos) => processLocation(pos, km, true),
                (err) => console.warn('[GPS Heartbeat] Errore GPS:', err.message),
                { enableHighAccuracy: true, timeout: 8000, maximumAge: 5000 }
            );
        }
    }, HEARTBEAT_S * 1000);
    console.log(`[GPS] Heartbeat avviato ogni ${HEARTBEAT_S}s`);
}

function stopHeartbeat() {
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
}

// ─── API PUBBLICA ─────────────────────────────────────────────────────────────

window.startGPSTracking = async function(tripId, initialKm = null) {
    if (isTracking) { console.warn('[GPS] Già attivo.'); return; }
    if (!navigator.geolocation) {
        console.error('[GPS] ❌ Geolocation non supportata.');
        updateBanner('error', 'GPS non supportato');
        window.updateTrackingStatus('error');
        return;
    }

    // Assicura che IDB sia pronto
    await openIDB();

    currentTripId = tripId;
    isTracking    = true;

    console.log(`[GPS] 🚀 Avvio tracking viaggio: ${tripId}`);
    updateBanner('active', 'Ricerca segnale GPS...');
    window.updateTrackingStatus('active');

    // Flush immediato di log offline residui
    if (navigator.onLine) processBuffer();

    watchId = navigator.geolocation.watchPosition(
        (pos) => processLocation(pos, initialKm),
        (err) => {
            console.error(`[GPS] ❌ Geolocation err(${err.code}): ${err.message}`);
            updateBanner('error', `Errore GPS: ${err.message}`);
            window.updateTrackingStatus('error');
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );

    startHeartbeat(initialKm);
};

window.stopGPSTracking = function() {
    if (watchId !== null) {
        navigator.geolocation.clearWatch(watchId);
        watchId = null;
    }
    stopHeartbeat();

    isTracking    = false;
    currentTripId = null;
    lastPosition  = null;
    lastTimestamp = 0;
    lastKnownPos  = null;

    hideBanner();
    window.updateTrackingStatus('stopped');
    console.log('[GPS] 🛑 Tracking fermato.');

    // Flush finale
    if (navigator.onLine) processBuffer();
};

window.recoverGPSTracking = async function() {
    const savedId = sessionStorage.getItem('currentTripId');
    if (savedId && !isTracking) {
        const km = document.getElementById('kmPartenza')?.value || null;
        console.log(`[GPS] ♻️ Recupero tracking per viaggio: ${savedId}`);
        await window.startGPSTracking(savedId, km);
    }
};

window.getGPSStatus = async function() {
    const count = await idbCount().catch(() => -1);
    return { isTracking, currentTripId, bufferSize: count };
};

// ─── Listener rete e avvio ────────────────────────────────────────────────────

window.addEventListener('online', () => {
    console.log('[GPS] 📶 Rete tornata — flush buffer...');
    processBuffer();
});

window.addEventListener('offline', () => {
    console.log('[GPS] 📴 Rete offline — i log vengono bufferizzati.');
    if (isTracking) updateBanner('error', 'Offline — log salvati localmente');
});

document.addEventListener('DOMContentLoaded', async () => {
    await openIDB();
    const count = await idbCount().catch(() => 0);

    if (count > 0) {
        console.log(`[GPS] 📦 ${count} log offline trovati — sync tra 2s...`);
        updateBanner('syncing', `${count} log offline da sincronizzare...`);
        setTimeout(processBuffer, 2000);
    }

    const savedId = sessionStorage.getItem('currentTripId');
    if (savedId && !isTracking) {
        updateBanner('stopped', '⚠️ Viaggio non concluso — riprendi dal modale');
    }
});
