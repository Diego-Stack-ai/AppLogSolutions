import { initializeApp, getApps } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import { 
    initializeFirestore, 
    getFirestore, 
    persistentLocalCache, 
    persistentMultipleTabManager,
    getDocs, getDoc, getDocsFromCache, getDocFromCache
} from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";
import { initializeAuth, indexedDBLocalPersistence, browserLocalPersistence, getAuth } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js";
import { firebaseConfig } from "../firebase-config.js";

const app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApps()[0];

let db;
try {
    db = initializeFirestore(app, {
        localCache: persistentLocalCache({ tabManager: persistentMultipleTabManager() })
    });
    console.log("[Firebase Init] ✅ Offline persistence attiva (IndexedDB, Multi-tab).");
} catch (e) {
    db = getFirestore(app);
    console.warn("Offline persistence non abilitata o già inizializzata.");
}

let auth;
try {
    auth = initializeAuth(app, {
        persistence: [indexedDBLocalPersistence, browserLocalPersistence]
    });
} catch (e) {
    console.warn("[Firebase Init] initializeAuth già registrata, uso getAuth(app)");
    auth = getAuth(app);
}

// Inizializzazione dati in memoria (Global State)
window.appData = window.appData || {
    lista_clienti: [],
    lista_autisti: [],
    lista_mezzi: [],
    currentUser: {},
    activeTenant: localStorage.getItem('activeTenant') || 'DNR' // Tenant di default
};

// --- FUNZIONI GLOBALI DI FALLBACK OFFLINE ---
window.getDocsConFallback = async function(q, timeoutMs = 2500) {
    const isOffline = !navigator.onLine || (window.connectivityService && window.connectivityService.getStatus() === 'offline');
    if (isOffline) {
        console.log("[Offline Fallback] Rete disconnessa, carico da cache...");
        return await getDocsFromCache(q);
    }
    try {
        return await Promise.race([
            getDocs(q),
            new Promise((_, reject) => setTimeout(() => reject(new Error("Timeout_Firestore")), timeoutMs))
        ]);
    } catch (err) {
        console.warn("[Offline Fallback] Timeout o errore di rete. Ripiego su cache...", err.message);
        return await getDocsFromCache(q);
    }
};

window.getDocConFallback = async function(docRef, timeoutMs = 2500) {
    const isOffline = !navigator.onLine || (window.connectivityService && window.connectivityService.getStatus() === 'offline');
    if (isOffline) {
        console.log("[Offline Fallback] Rete disconnessa, carico da cache...");
        return await getDocFromCache(docRef);
    }
    try {
        return await Promise.race([
            getDoc(docRef),
            new Promise((_, reject) => setTimeout(() => reject(new Error("Timeout_Firestore")), timeoutMs))
        ]);
    } catch (err) {
        console.warn("[Offline Fallback] Timeout o errore di rete. Ripiego su cache...", err.message);
        return await getDocFromCache(docRef);
    }
};

export { app, db, auth };
