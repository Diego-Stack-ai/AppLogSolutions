import { app, db, auth } from "./firebase-init.js";
import { signInWithEmailAndPassword, onAuthStateChanged, signOut, browserLocalPersistence, setPersistence, updatePassword } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js";
import { connectivityService } from "./connectivity-service.js";

// ABILITAZIONE PERSISTENZA SESSIONE (localStorage)
// [DEBUG] setPersistence rimosso per evitare deadlock offline (browserLocalPersistence è il default)

// --- GESTIONE EMERGENZA (DEBUG) ---
window.forcePasswordResetDebug = async (newPassword) => {
    const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    if (!isLocal) {
        console.warn("Funzione forcePasswordResetDebug disabilitata in produzione.");
        return;
    }
    const user = auth.currentUser;
    if (!user) {
        alert("Nessun utente loggato per il reset.");
        return;
    }
    try {
        await updatePassword(user, newPassword);
        console.log(`[DEBUG] Password aggiornata correttamente per ${user.email}`);
        alert("Password aggiornata con successo via SDK Client.");
    } catch (e) {
        console.error("Errore reset debug:", e);
        alert("Errore reset: " + e.message);
    }
};

let isLoggingOut = false;
window.logoutFirebase = async () => {
    console.log("Auth: Avvio procedura di logout...");
    isLoggingOut = true;
    try {
        window.appData.currentUser = {};
        try { localStorage.removeItem('ls_cached_user'); } catch(e) {}
        await signOut(auth);
        console.log("Auth: Logout Firebase completato. Reindirizzamento...");
        window.location.replace('login.html');
    } catch (error) {
        console.error("Auth: Errore durante il logout:", error);
        isLoggingOut = false;
        window.location.replace('login.html');
    }
};


let profileAlreadyLoaded = false; // Guard: evita ri-trigger al cambio rete

// FALLBACK OFFLINE TIMEOUT: Se Firebase Auth tentenna a rispondere offline, usa il profilo in cache
let authStateFired = false;
const offlineAuthFallbackTimer = setTimeout(() => {
    if (!authStateFired && !profileAlreadyLoaded) {
        console.warn("[Auth Fallback Offline] onAuthStateChanged non ha risposto in 1200ms. Verifico cache locale...");
        try {
            const cachedUserStr = localStorage.getItem('ls_cached_user');
            if (cachedUserStr) {
                const cachedUser = JSON.parse(cachedUserStr);
                
                // Ricalcolo strict in cache
                const role = (cachedUser.ruolo || 'autista').toString().toLowerCase().trim();
                cachedUser.isAdmin = role === 'amministratore';
                
                console.log("[Auth Fallback Offline] ✅ Utente ripristinato da ls_cached_user:", cachedUser.email || cachedUser.id);
                window.appData = window.appData || {};
                window.appData.currentUser = cachedUser;
                profileAlreadyLoaded = true;
                if (typeof window.onUserProfileLoaded === 'function') {
                    window.onUserProfileLoaded(cachedUser);
                }
                
                // REDIRECT SE SIAMO SU PAGINA PUBBLICA
                const path = window.location.pathname;
                const page = path.split('/').pop() || 'index.html';
                if (page === 'login.html' || page === 'index.html' || page === '') {
                    console.log("[Auth Fallback Offline] Pagina pubblica, reindirizzamento alla dashboard.");
                    window.location.replace('dashboard.html');
                }
            } else {
                console.warn("[Auth Fallback Offline] Nessun utente salvato in ls_cached_user.");
            }
        } catch (e) {
            console.error("[Auth Fallback Offline] Errore lettura ls_cached_user:", e);
        }
    }
}, 1200);

onAuthStateChanged(auth, async (user) => {
    authStateFired = true;
    clearTimeout(offlineAuthFallbackTimer);
    if (isLoggingOut) {
        console.log("Auth Listener: Logout in corso, salto controlli.");
        return;
    }
    const path = window.location.pathname;
    const page = path.split('/').pop() || 'index.html';
    
    // Classificazione Pagine
    const isPublicPage = page === 'login.html' || page === 'index.html' || page === '';

    console.log(`Auth Listener: Utente = ${user ? user.uid : 'NULL'}, Pagina Corrente = ${page}`);

    if (user) {
        // Se il profilo è già caricato per questo utente, non rieseguire tutto il ciclo
        if (profileAlreadyLoaded && window.appData?.currentUser?.id === user.uid) {
            console.log("Auth Listener: Profilo già caricato per questo utente, salto ri-inizializzazione.");
            if (isPublicPage) {
                console.log("Auth Listener: Pagina pubblica, reindirizzamento alla dashboard.");
                window.location.replace('dashboard.html');
            }
            return;
        }
        try {
            // DYNAMIC IMPORT FIRESTORE ONLY IF AUTHENTICATED
            const { doc, getDoc, getDocFromCache, updateDoc, setDoc } = await import("https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js");

            // Funzione helper per evitare l'hang delle chiamate online in assenza reale di rete
            const getDocWithTimeout = (docRef, timeoutMs = 2000) => {
                return Promise.race([
                    getDoc(docRef),
                    new Promise((_, reject) => setTimeout(() => reject(new Error("Timeout Firestore")), timeoutMs))
                ]);
            };

            let userDoc = null;
            const isOffline = connectivityService.getStatus() === 'offline';
            if (isOffline) {
                console.log("Auth: Rilevato stato offline. Carico il profilo dipendente direttamente da cache...");
                try {
                    userDoc = await getDocFromCache(doc(db, "dipendenti", user.uid));
                    console.log("Auth: Profilo caricato correttamente da cache offline.");
                } catch (cacheErr) {
                    console.error("Auth: Profilo dipendente non trovato in cache locale offline.", cacheErr);
                    throw new Error("Impossibile caricare il profilo offline. È necessario effettuare l'accesso online almeno una volta su questo dispositivo.");
                }
            } else {
                try {
                    // Tenta prima il recupero online del profilo con timeout di 2 secondi
                    userDoc = await getDocWithTimeout(doc(db, "dipendenti", user.uid), 2000);
                    console.log("Auth: Profilo caricato online con successo.");
                } catch (fetchErr) {
                    console.warn("Auth: Connessione fallita o timeout sul server. Provo a caricare il profilo dipendente dalla cache locale...", fetchErr);
                    try {
                        userDoc = await getDocFromCache(doc(db, "dipendenti", user.uid));
                        console.log("Auth: Profilo caricato correttamente dalla cache offline.");
                    } catch (cacheErr) {
                        console.error("Auth: Profilo dipendente non trovato in cache locale.", cacheErr);
                        throw new Error("Impossibile caricare il profilo offline. È necessario effettuare l'accesso online almeno una volta su questo dispositivo.");
                    }
                }
            }
            
            if (userDoc && userDoc.exists()) {
                const userData = userDoc.data();

                if (userData.needsPasswordChange) {
                    console.warn("Auth: Cambio password richiesto.");
                    const newPassword = prompt("Primo Accesso: Inserisci la tua nuova password definitiva (min 6 caratteri):");
                    if (newPassword && newPassword.length >= 6) {
                        try {
                            await updatePassword(user, newPassword);
                            await updateDoc(doc(db, "dipendenti", user.uid), { needsPasswordChange: false });
                            alert("Password aggiornata con successo! Benvenuto nel sistema.");
                        } catch (e) {
                            alert("Errore durante l'aggiornamento della password: " + e.message + "\nEffettua nuovamente il login.");
                            await signOut(auth);
                            window.location.replace('login.html');
                            return;
                        }
                    } else {
                        alert("Devi cambiare la password per poter accedere al sistema.");
                        await signOut(auth);
                        window.location.replace('login.html');
                        return;
                    }
                }

                const role = (userData.ruolo || 'autista').toString().toLowerCase().trim();
                const isAdmin = role === 'amministratore';

                window.appData.currentUser = { id: user.uid, email: user.email, ...userData, ruolo: role, isAdmin: isAdmin };
                profileAlreadyLoaded = true; // Segna il profilo come caricato
                
                // Persistenza del profilo in localStorage per il rendering immediato offline
                try {
                    localStorage.setItem('ls_cached_user', JSON.stringify(window.appData.currentUser));
                } catch(e) { /* ignora errori storage */ }

                console.log(`Auth: Profilo caricato [${userData.nome}], Ruolo: "${role}", IsAdmin: ${isAdmin}`);

                let permessiDoc = null;
                if (isOffline) {
                    try {
                        permessiDoc = await getDocFromCache(doc(db, "config", "permessi_dashboard"));
                        console.log("Auth: Permessi dashboard caricati da cache offline.");
                    } catch (e) {
                        console.warn("Auth: Permessi dashboard non trovati in cache offline", e);
                    }
                } else {
                    try {
                        // Tenta recupero online con timeout di 1.5 secondi
                        permessiDoc = await getDocWithTimeout(doc(db, "config", "permessi_dashboard"), 1500);
                        console.log("Auth: Permessi dashboard caricati online.");
                    } catch(e) {
                        console.warn("Auth: Impossibile scaricare permessi dashboard online (errore o timeout), provo da cache...", e);
                        try {
                            permessiDoc = await getDocFromCache(doc(db, "config", "permessi_dashboard"));
                            console.log("Auth: Permessi dashboard caricati da cache offline.");
                        } catch (cacheErr) {
                            console.warn("Auth: Permessi dashboard non disponibili offline", cacheErr);
                        }
                    }
                }
                
                const permessiData = permessiDoc && permessiDoc.exists() ? permessiDoc.data() : {};
                window.appData.permessiDashboard = permessiData;

                const triggerUserProfileLoaded = () => {
                    if (typeof window.onUserProfileLoaded === 'function') {
                        window.onUserProfileLoaded(window.appData.currentUser);
                        return true;
                    }
                    return false;
                };

                if (!triggerUserProfileLoaded()) {
                    console.log("Auth: window.onUserProfileLoaded non ancora pronto, avvio polling di attesa...");
                    let attempts = 0;
                    const interval = setInterval(() => {
                        attempts++;
                        if (triggerUserProfileLoaded()) {
                            console.log("Auth: window.onUserProfileLoaded eseguito con successo tramite polling.");
                            clearInterval(interval);
                        } else if (attempts > 30) {
                            console.warn("Auth: Timeout polling window.onUserProfileLoaded.");
                            clearInterval(interval);
                        }
                    }, 100);
                } else {
                    console.log("Auth: window.onUserProfileLoaded eseguito immediatamente.");
                    setTimeout(() => {
                        triggerUserProfileLoaded();
                    }, 300);
                }

                // Call startRealtimeSync if loaded
                if (typeof window.startRealtimeSync === 'function') {
                    window.startRealtimeSync(isAdmin);
                }

                if (isPublicPage) {
                    const home = 'dashboard.html';
                    console.log(`REDIRECT DEBUG: Pagina pubblica [${page}] -> Home corretta [${home}]`);
                    window.location.replace(home);
                    return;
                }

                if (page !== 'dashboard.html' && page !== 'login.html') {
                    const pageKey = page.replace('.html', '');
                    window.appData.isReadOnly = false;

                    if (role !== 'amministratore') {
                        let permLevel = 'none';
                        if (permessiData[pageKey] && typeof permessiData[pageKey][role] !== 'undefined') {
                            const val = permessiData[pageKey][role];
                            if (val === 'write' || val === true) permLevel = 'write';
                            else if (val === 'read') permLevel = 'read';
                            else if (typeof val === 'object' && val.access === 'advanced') permLevel = 'write';
                            else permLevel = 'none';
                        } else {
                            if (role === 'impiegata') {
                                permLevel = 'write';
                            } else if (role === 'fornitore') {
                                permLevel = (page === 'gestione_mezzi.html') ? 'write' : 'none';
                            } else {
                                permLevel = (page === 'inserimento.html' || page === 'presenze.html') ? 'write' : 'none';
                            }
                        }

                        if (permLevel === 'none') {
                            console.error(`REDIRECT DEBUG: Accesso negato a [${page}] per ruolo [${role}]. Reindirizzamento a dashboard.html.`);
                            window.location.replace('dashboard.html');
                            return;
                        }

                        if (permLevel === 'read') {
                            window.appData.isReadOnly = true;
                            console.log(`AUTH DEBUG: Accesso in modalità SOLO LETTURA a [${page}] per ruolo [${role}].`);
                        }
                    }

                    if (window.appData.isReadOnly) {
                        const applyReadOnlyShield = () => {
                            document.querySelectorAll('input:not([id*="search" i]):not([class*="search" i]):not([id*="filter" i]):not([class*="filter" i]), select:not([id*="search" i]):not([class*="search" i]):not([id*="filter" i]):not([class*="filter" i]), textarea').forEach(el => {
                                el.disabled = true;
                                el.style.backgroundColor = '#f8fafc';
                            });
                            document.querySelectorAll('button[type="submit"], .btn-primary, .btn-success, .btn-delete, .btn-add, .delete-btn, .btn-edit, #btnSalva, #updateBtn').forEach(btn => {
                                if (btn.title && btn.title.toLowerCase().includes('mappa')) return;
                                if (!btn.className.toLowerCase().includes('search') && !btn.id.toLowerCase().includes('search') && !btn.className.toLowerCase().includes('tab')) {
                                    btn.style.display = 'none';
                                }
                            });
                            if (typeof window.toggleLockRow === 'function') {
                                document.querySelectorAll('.lock-btn').forEach(btn => btn.style.display = 'none');
                            }
                        };

                        if (document.readyState === 'loading') {
                            document.addEventListener('DOMContentLoaded', applyReadOnlyShield);
                        } else {
                            applyReadOnlyShield();
                        }

                        const observer = new MutationObserver((mutations) => {
                            let shouldReapply = false;
                            for (const mut of mutations) {
                                if (mut.addedNodes.length > 0) {
                                    shouldReapply = true;
                                    break;
                                }
                            }
                            if (shouldReapply) applyReadOnlyShield();
                        });
                        observer.observe(document.body, { childList: true, subtree: true });
                        
                        setTimeout(() => {
                            const banner = document.createElement('div');
                            banner.innerHTML = '<span class="material-icons-round" style="font-size: 16px;">visibility</span> Modalità Solo Lettura. Non hai i permessi per modificare i dati in questa pagina.';
                            banner.style.cssText = 'position:fixed; top:0; left:0; right:0; background:#f59e0b; color:white; text-align:center; padding:6px; font-size:13px; font-weight:bold; z-index:999999; display:flex; justify-content:center; align-items:center; gap:6px; box-shadow:0 2px 10px rgba(0,0,0,0.1);';
                            document.body.appendChild(banner);
                            document.body.style.paddingTop = '32px';
                        }, 500);
                    }
                }

            } else {
                console.warn("Auth: Sessione attiva ma profilo Firestore mancante.");
                const confirmCreate = confirm("ATTENZIONE: Il tuo utente Firebase esiste, ma il profilo nel database è stato cancellato.\n\nVuoi ricreare automaticamente il tuo profilo come AMMINISTRATORE per poter accedere?");
                if (confirmCreate) {
                    try {
                        const newUserData = {
                            email: user.email,
                            nome: user.email.split('@')[0],
                            ruolo: "amministratore",
                            needsPasswordChange: false
                        };
                        await setDoc(doc(db, "dipendenti", user.uid), newUserData);
                        alert("Profilo ricreato con successo! Ora ricaricheremo la pagina per farti entrare.");
                        window.location.reload();
                        return;
                    } catch(e) {
                        alert("Impossibile ricreare il profilo. Controlla le regole Firestore. Dettaglio: " + e.message);
                    }
                }
                alert("ACCESSO NEGATO: Utente autenticato, ma manca il profilo nel Database (Collection 'dipendenti'). L'account potrebbe essere stato disabilitato o cancellato.");
                await window.logoutFirebase();
            }
        } catch (err) {
            console.error("Auth: Errore recupero profilo Firestore:", err);
            let contextMsg = "";
            if (err.message && err.message.includes('permission')) {
                contextMsg = " (Controllo permessi su dipendenti/" + user.uid + ")";
            }
            alert("Errore di connessione al database durante il login: " + err.message + contextMsg);
            await window.logoutFirebase();
        }
    } else {
        window.appData.currentUser = {};
        profileAlreadyLoaded = false; // Reset al logout
        console.log(`Auth Listener: Utente non autenticato. Pagina corrente = ${page}`);
        if (!isPublicPage) {
            window.location.replace('login.html');
        }
    }
});

window.loginWithFirebase = async (email, password) => {
    try {
        const userCredential = await signInWithEmailAndPassword(auth, email, password);
        return userCredential.user;
    } catch (error) {
        console.error("Errore Login Firebase:", error.code, error.message);
        throw error;
    }
};

export { auth };
