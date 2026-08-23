import { initializeApp, getApps } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import { getFirestore, collection, doc, getDoc, updateDoc, setDoc, deleteDoc, onSnapshot, addDoc, query, where } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";
import { getAuth, signInWithEmailAndPassword, onAuthStateChanged, signOut, sendPasswordResetEmail, browserLocalPersistence, setPersistence, updatePassword, sendEmailVerification, createUserWithEmailAndPassword } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js";
import { getPerformance } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-performance.js";
import { firebaseConfig } from "./firebase-config.js";

const app = initializeApp(firebaseConfig);



const db = getFirestore(app);
const auth = getAuth(app);
// const perf = getPerformance(app); // Disabilitato per evitare errore 403 su Installations API

// ABILITAZIONE PERSISTENZA SESSIONE (localStorage)
setPersistence(auth, browserLocalPersistence)
    .catch((error) => console.error("Errore persistenza:", error));

// Inizializzazione dati in memoria (Global State)
window.appData = window.appData || {
    lista_clienti: [],
    lista_autisti: [],
    lista_mezzi: [],
    currentUser: {},
    activeTenant: localStorage.getItem('activeTenant') || 'DNR' // Tenant di default
};


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

// --- FUNZIONI DI SERVIZIO AUTH REMOSSE POICHE' GESTITE CENTRALMENTE ---// --- GESTIONE LOGOUT GLOBALE ---
let isLoggingOut = false;
window.logoutFirebase = async () => {
    console.log("Auth: Avvio procedura di logout...");
    isLoggingOut = true;
    try {
        // Puliamo lo stato in memoria prima del logout
        window.appData.currentUser = {};
        
        // Disconnessione da Firebase
        await signOut(auth);
        
        console.log("Auth: Logout Firebase completato. Reindirizzamento...");
        
        // Reindirizzamento alla login pulendo l'URL da eventuali parametri
        window.location.replace('login.html');
        
    } catch (error) {
        console.error("Auth: Errore durante il logout:", error);
        isLoggingOut = false;
        // Fallback: forziamo il reindirizzamento
        window.location.replace('login.html');
    }
};

onAuthStateChanged(auth, async (user) => {
    if (isLoggingOut) {
        console.log("Auth Listener: Logout in corso, salto controlli.");
        return;
    }
    const path = window.location.pathname;
    const page = path.split('/').pop() || 'index.html';
    
    // Classificazione Pagine
    const isPublicPage = page === 'login.html' || page === 'index.html' || page === '';
    const isAdminOnlyPage = ['clienti.html', 'impostazioni.html', 'visualizzazione.html', 'mappa_consegne.html', 'dashboard.html', 'link_viaggi.html'].includes(page);
    const isAutistaOnlyPage = ['inserimento.html', 'presenze.html'].includes(page);

    console.log(`Auth Listener: Utente = ${user ? user.uid : 'NULL'}, Pagina Corrente = ${page}`);

    if (user) {
        try {
            // Implementiamo un semplice retry per connessioni mobili instabili
            let userDoc = null;
            let retries = 3;
            while (retries > 0) {
                try {
                    userDoc = await getDoc(doc(db, "dipendenti", user.uid));
                    break;
                } catch (fetchErr) {
                    retries--;
                    if (retries === 0) throw fetchErr;
                    console.warn(`Auth: getDoc fallito, ritento... tentativi rimasti: ${retries}`, fetchErr);
                    await new Promise(r => setTimeout(r, 1000)); // aspetta 1 secondo
                }
            }
            
            if (userDoc && userDoc.exists()) {
                const userData = userDoc.data();

                // --- 2. CONTROLLO CAMBIO PASSWORD FORZATO ---
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

                // Normalizzazione ruolo (sempre minuscolo e senza spazi)
                const role = (userData.ruolo || 'autista').toString().toLowerCase().trim();
                const nomeUtente = (userData.nome || '').toLowerCase();
                // Diego Boschetto è sempre amministratore a prescindere dal database
                const isDiego = nomeUtente.includes('boschetto diego') || nomeUtente.includes('diego boschetto');
                const isAdmin = role === 'amministratore' || role === 'impiegata' || isDiego;

                window.appData.currentUser = { id: user.uid, email: user.email, ...userData, ruolo: role, isAdmin: isAdmin };
                
                console.log(`Auth: Profilo caricato [${userData.nome}], Ruolo: "${role}", IsAdmin: ${isAdmin}`);

                // Scarica configurazione permessi dashboard
                let permessiDoc = null;
                try {
                    permessiDoc = await getDoc(doc(db, "config", "permessi_dashboard"));
                } catch(e) {
                    console.warn("Auth: Impossibile scaricare permessi dashboard", e);
                }
                
                const permessiData = permessiDoc && permessiDoc.exists() ? permessiDoc.data() : {};
                window.appData.permessiDashboard = permessiData;


                // Hook per aggiornamenti UI nelle pagine
                // Chiamata immediata + retry dopo 300ms per sicurezza su mobile
                if (typeof window.onUserProfileLoaded === 'function') {
                    window.onUserProfileLoaded(window.appData.currentUser);
                    // Retry per dispositivi mobili dove il DOM potrebbe non essere ancora pronto
                    setTimeout(() => {
                        if (typeof window.onUserProfileLoaded === 'function') {
                            window.onUserProfileLoaded(window.appData.currentUser);
                        }
                    }, 300);
                }

                // Avviamo i listener ricaricando i permessi appropriati
                startRealtimeSync(isAdmin);

                // --- LOGICA DI NAVIGAZIONE E PROTEZIONE ---
                
                // 1. Se loggato e su pagina pubblica -> Vai alla home corretta (sempre dashboard ora)
                if (isPublicPage) {
                    const home = 'dashboard.html';
                    console.log(`REDIRECT DEBUG: Pagina pubblica [${page}] -> Home corretta [${home}]`);
                    window.location.replace(home);
                    return;
                }

                // 2. Protezione dinamica: controlla se l'utente ha il permesso per la pagina corrente
                if (page !== 'dashboard.html' && page !== 'login.html') {
                    const pageKey = page.replace('.html', '');
                    
                    window.appData.isReadOnly = false;

                    if (role !== 'amministratore' && !isDiego) {
                        let permLevel = 'none'; // 'none', 'read', 'write'
                        
                        if (permessiData[pageKey] && typeof permessiData[pageKey][role] !== 'undefined') {
                            // Se c'è la configurazione specifica per questa pagina e ruolo
                            const val = permessiData[pageKey][role];
                            if (val === 'write' || val === true) permLevel = 'write';
                            else if (val === 'read') permLevel = 'read';
                            else permLevel = 'none';
                        } else {
                            // Fallback alla vecchia logica se la configurazione non esiste ancora
                            if (role === 'impiegata') {
                                permLevel = 'write'; // Impiegata vedeva tutto come admin
                            } else {
                                // Autista vedeva solo inserimento e presenze
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
                            console.log(`AUTH DEBUG: Accesso in modalità  SOLO LETTURA a [${page}] per ruolo [${role}].`);
                        }
                    }

                    // Se è in sola lettura, applichiamo lo scudo protettivo universale
                    if (window.appData.isReadOnly) {
                        const applyReadOnlyShield = () => {
                            // Disabilita input di scrittura
                            document.querySelectorAll('input:not([id*="search" i]):not([class*="search" i]):not([id*="filter" i]):not([class*="filter" i]), select:not([id*="search" i]):not([class*="search" i]):not([id*="filter" i]):not([class*="filter" i]), textarea').forEach(el => {
                                el.disabled = true;
                                el.style.backgroundColor = '#f8fafc'; // feedback visivo
                            });
                            // Nasconde i tasti di salvataggio/modifica
                            document.querySelectorAll('button[type="submit"], .btn-primary, .btn-success, .btn-delete, .btn-add, .delete-btn, .btn-edit, #btnSalva, #updateBtn').forEach(btn => {
                                // Escludiamo i bottoni di navigazione/mappa che hanno la classe btn-edit per mostrare dati
                                if (btn.title && btn.title.toLowerCase().includes('mappa')) return;
                                if (!btn.className.toLowerCase().includes('search') && !btn.id.toLowerCase().includes('search') && !btn.className.toLowerCase().includes('tab')) {
                                    btn.style.display = 'none';
                                }
                            });
                            
                            // Disabilita specificamente le interazioni sui drag&drop o lock in pianificazione
                            if (typeof window.toggleLockRow === 'function') {
                                document.querySelectorAll('.lock-btn').forEach(btn => btn.style.display = 'none');
                            }
                        };

                        // Applica all'avvio
                        if (document.readyState === 'loading') {
                            document.addEventListener('DOMContentLoaded', applyReadOnlyShield);
                        } else {
                            applyReadOnlyShield();
                        }

                        // MutationObserver per bloccare anche gli elementi caricati dinamicamente (es. righe tabelle, modali)
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
                        
                        // Mostra banner di avviso all'utente (dopo che l'UI è caricata)
                        setTimeout(() => {
                            const banner = document.createElement('div');
                            banner.innerHTML = '<span class="material-icons-round" style="font-size: 16px;">visibility</span> Modalità  Solo Lettura. Non hai i permessi per modificare i dati in questa pagina.';
                            banner.style.cssText = 'position:fixed; top:0; left:0; right:0; background:#f59e0b; color:white; text-align:center; padding:6px; font-size:13px; font-weight:bold; z-index:999999; display:flex; justify-content:center; align-items:center; gap:6px; box-shadow:0 2px 10px rgba(0,0,0,0.1);';
                            document.body.appendChild(banner);
                            document.body.style.paddingTop = '32px';
                        }, 500);
                    }
                }

            } else {
                console.warn("Auth: Sessione attiva ma profilo Firestore mancante.");
                
                // --- AUTO-FIX DI EMERGENZA ---
                // Se l'utente si è appena loggato con Firebase Auth ma il suo documento in 'dipendenti' non esiste
                // (ad es. database azzerato), chiediamo se vogliamo ricrearlo come amministratore.
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
        // Nessun utente rilevato
        window.appData.currentUser = {};
        if (!isPublicPage) {
            console.log(`REDIRECT DEBUG: Utente non loggato su pagina privata [${page}] -> Redirect a login.html`);
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

// Inizializzazione Listener Realtime (Condizionali ai permessi)
let activeListeners = [];
function startRealtimeSync(isAdmin) {
    console.log(`Attivazione sincronizzazione realtime (Admin: ${isAdmin})...`);

    // Pulizia listener precedenti se esistenti
    activeListeners.forEach(unsub => unsub());
    activeListeners = [];

    // Listener per Clienti (Punti di Consegna DNR - Progetto Scuole)
    const unsubCustomers = onSnapshot(collection(db, "clienti", "DNR", "raccolta clienti"), { includeMetadataChanges: true }, (snapshot) => {
        const clienti = [];
        snapshot.forEach((d) => {
            const data = d.data();
            clienti.push({ 
                id: d.id, 
                ...data,
                nome: data.cliente || data.nome_consegna || data.nome || '',
                codiceFrutta: data.codice_frutta || data.codiceFrutta || '',
                codiceLatte: data.codice_latte || data.codiceLatte || '',
                provincia: data.prov || data.provincia || '',
                lng: data.lon || data.lng || '',
                orarioMin: data.orariomin || data.orarioMin || '',
                orarioMax: data.orariomax || data.orarioMax || '',
                tipologiaGrado: data.tipologia_grado || data.tipologiaGrado || ''
            });
        });
        window.appData.lista_clienti = clienti; // Popola correttamente clienti.html
        if (typeof window.renderClienti === 'function') window.renderClienti();
        if (typeof window.renderClientiInserimento === 'function') window.renderClientiInserimento();
    });
    activeListeners.push(unsubCustomers);

    // Listener per Articoli DNR - Progetto Scuole
    const unsubArticoli = onSnapshot(collection(db, "customers", "DNR", "anagrafica_articoli"), { includeMetadataChanges: true }, (snapshot) => {
        const articoli = [];
        snapshot.forEach((d) => {
            articoli.push({ id: d.id, ...d.data() });
        });
        window.appData.lista_articoli = articoli; // Popola eventuali griglie articoli
        if (typeof window.renderArticoli === 'function') window.renderArticoli();
    });
    activeListeners.push(unsubArticoli);

    // Listener per Autisti/Utenti
    // Se Admin scarica tutti, altrimenti NON scarica nulla (o solo se stesso, già  fatto in Auth)
    if (isAdmin) {
        const unsubUsers = onSnapshot(collection(db, "dipendenti"), { includeMetadataChanges: true }, (snapshot) => {
            const autisti = [];
            snapshot.forEach((d) => {
                autisti.push({ id: d.id, ...d.data() });
            });
            window.appData.lista_autisti = autisti;
            if (typeof window.renderAutisti === 'function') window.renderAutisti();
            if (typeof window.renderAutistiDropdown === 'function') window.renderAutistiDropdown();
        });
        activeListeners.push(unsubUsers);
    }

    // Listener per Mezzi (mezzi)
    const unsubMezzi = onSnapshot(collection(db, "mezzi"), { includeMetadataChanges: true }, (snapshot) => {
        const mezzi = [];
        snapshot.forEach((d) => {
            mezzi.push({ id: d.id, ...d.data() });
        });
        window.appData.lista_mezzi = mezzi;
        if (typeof window.renderLista === 'function') window.renderLista();
        if (typeof window.renderMezziInserimento === 'function') window.renderMezziInserimento();
        if (typeof window.renderMezzi === 'function') window.renderMezzi();
    });
    activeListeners.push(unsubMezzi);

    // Listener per Progetti (clienti con viaggi associati)
    const unsubProgetti = onSnapshot(collection(db, "progetti"), { includeMetadataChanges: true }, (snapshot) => {
        const progetti = [];
        snapshot.forEach((d) => {
            progetti.push({ id: d.id, ...d.data(), isProgetto: true });
        });
        window.appData.lista_progetti = progetti;
        if (typeof window.renderProgettiInserimento === 'function') window.renderProgettiInserimento();
        if (typeof window.renderProgettiImpostazioni === 'function') window.renderProgettiImpostazioni();
        if (typeof window.renderProgetti === 'function') window.renderProgetti();
    });
    activeListeners.push(unsubProgetti);

    // Listeners per le 4 liste delle Scalette Navette
    const setupScalettaListener = (tipo, globalProp) => {
        const unsub = onSnapshot(collection(db, "clienti/DNR/" + tipo), { includeMetadataChanges: true }, (snapshot) => {
            const dataList = [];
            snapshot.forEach((d) => dataList.push({ id: d.id, ...d.data() }));
            window.appData[globalProp] = dataList;
            // Aggiorna interfaccia impostazioni se aperta
            if (typeof window.renderScaletteItems === 'function') window.renderScaletteItems(tipo);
            // Aggiornerà  interfaccia inserimento se necessario in futuro
        });
        activeListeners.push(unsub);
    };

    setupScalettaListener('scaletta_partenze', 'lista_scaletta_partenze');
    setupScalettaListener('scaletta_carico', 'lista_scaletta_carico');
    setupScalettaListener('scaletta_clienti', 'lista_scaletta_clienti');
    setupScalettaListener('scaletta_destinazioni_merce', 'lista_scaletta_destinazioni_merce');

    // Listeners per le 4 liste della Navetta Pura
    setupScalettaListener('navetta_partenze', 'lista_navetta_partenze');
    setupScalettaListener('navetta_carico', 'lista_navetta_carico');
    setupScalettaListener('navetta_clienti', 'lista_navetta_clienti');
    setupScalettaListener('navetta_destinazioni_merce', 'lista_navetta_destinazioni_merce');

    // Listener per la lista delle Sedi Magazzino
    setupScalettaListener('magazzini_sedi', 'lista_magazzini_sedi');

    // Listener per Giustificativi (Ferie, Malattia, ecc.)
    const unsubGiustificativi = onSnapshot(collection(db, "giustificativi"), { includeMetadataChanges: true }, (snapshot) => {
        const giustificativi = [];
        snapshot.forEach((d) => {
            giustificativi.push({ id: d.id, ...d.data() });
        });
        window.appData.lista_giustificativi = giustificativi;
        if (typeof window.renderGiustificativi === 'function') window.renderGiustificativi();
    });
    activeListeners.push(unsubGiustificativi);

      // NOTIFICHE RESI/RITIRI IN TEMPO REALE (Solo per Admin)
      if (isAdmin) {
          const todayStr = new Date().toISOString().split("T")[0]; // YYYY-MM-DD
          const qResi = query(
              collection(db, "clienti", "DNR", "resi_e_ritiri"),
              where("data_evento", "==", todayStr),
              where("letto_da_ufficio", "==", false)
          );
          const unsubResi = onSnapshot(qResi, { includeMetadataChanges: true }, (snapshot) => {
              snapshot.docChanges().forEach((change) => {
                  const data = change.doc.data();
                  if (change.type === "added") {
                      if (!data.visto_da_ufficio) {
                          showResoToast(change.doc.id, data, db);
                      }
                  }
                  if (change.type === "removed" || change.type === "modified") {
                      if(data.letto_da_ufficio || data.visto_da_ufficio || change.type === "removed") {
                          const toast = document.getElementById(`toast-${change.doc.id}`);
                          if(toast) toast.remove();
                      }
                  }
              });
          });
          activeListeners.push(unsubResi);
      }
  }

function showResoToast(docId, data, db) {
    if(document.getElementById(`toast-${docId}`)) return;
    
    const container = document.getElementById("toast-container") || createToastContainer();
    
    const t = document.createElement("div");
    t.id = `toast-${docId}`;
    t.style.cssText = "background:white; border-left:5px solid #ef4444; border-radius:8px; box-shadow:0 4px 15px rgba(0,0,0,0.15); padding:15px; margin-bottom:15px; width:300px; font-family:'Outfit',sans-serif; animation: slideIn 0.3s ease-out; position:relative;";
    
    const iconStr = data.tipo_segnalazione === "merce_rotta" ? "🔴 Rifiuto/Rotta" : "🔵 Reso/Ritiro";
    
    t.innerHTML = `
        <h4 style="margin:0 0 5px 0; font-size:14px;">${iconStr}</h4>
        <p style="margin:0 0 5px 0; font-size:13px; color:#475569;">Cliente: <b>${data.nome_cliente || data.codice_cliente}</b></p>
        <p style="margin:0 0 10px 0; font-size:12px; color:#94a3b8;">Giro: ${data.id_viaggio}</p>
        <div style="display:flex; gap:10px;">
            <a href="${data.url_foto}" target="_blank" style="flex:1; background:#f1f5f9; color:#475569; padding:8px; text-align:center; text-decoration:none; border-radius:6px; font-size:12px; font-weight:bold;">Vedi Foto</a>
            <button id="btn-letto-${docId}" style="flex:1; background:#10b981; color:white; border:none; padding:8px; border-radius:6px; cursor:pointer; font-size:12px; font-weight:bold;">Letto</button>
        </div>
    `;
    
    container.appendChild(t);
    
    document.getElementById(`btn-letto-${docId}`).addEventListener('click', async () => {
        try {
            document.getElementById(`btn-letto-${docId}`).innerText = "...";
            await updateDoc(doc(db, "clienti", "DNR", "resi_e_ritiri", docId), { visto_da_ufficio: true });
            t.remove();
        } catch(e) {
            console.error("Errore segna come letto", e);
            document.getElementById(`btn-letto-${docId}`).innerText = "Letto";
        }
    });
}

function createToastContainer() {
    const c = document.createElement("div");
    c.id = "toast-container";
    c.style.cssText = "position:fixed; top:70px; right:20px; z-index:99999;";
    
    const style = document.createElement("style");
    style.innerHTML = "@keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }";
    document.head.appendChild(style);
    
    document.body.appendChild(c);
    return c;
}


// âââ CRUD PROGETTI ââââââââââââââââââââââââââââââââââââââââââââââââââââââââââââ
window.saveProgetto = async function(id, data) {
    try {
        if (id) {
            await updateDoc(doc(db, "progetti", id), data);
        } else {
            await addDoc(collection(db, "progetti"), data);
        }
        return true;
    } catch (e) {
        console.error("Errore saveProgetto:", e);
        throw e;
    }
};

window.deleteProgetto = async function(id) {
    try {
        await deleteDoc(doc(db, "progetti", id));
        return true;
    } catch (e) {
        console.error("Errore deleteProgetto:", e);
        throw e;
    }
};

// âââ CRUD GIUSTIFICATIVI âââââââââââââââââââââââââââââââââââââââââââââââââââââââ
window.saveGiustificativo = async function(id, data) {
    try {
        if (id) {
            await updateDoc(doc(db, "giustificativi", id), data);
        } else {
            await addDoc(collection(db, "giustificativi"), data);
        }
        return true;
    } catch (e) {
        console.error("Errore salvataggio Giustificativo:", e);
        throw e;
    }
};

window.deleteGiustificativo = async function(id) {
    try {
        await deleteDoc(doc(db, "giustificativi", id));
        return true;
    } catch (e) {
        console.error("Errore deleteGiustificativo:", e);
        throw e;
    }
};

// âââ ALTRI CRUD (mezzi, utenti, ecc.) âââââââââââââââââââââââââââââââââââââââââ

window.deleteProgetto = async function(id) {
    try {
        await deleteDoc(doc(db, "progetti", id));
        return true;
    } catch (e) {
        console.error("Errore eliminazione Progetto:", e);
        throw e;
    }
};

// Funzione di salvataggio/creazione remoto per i clienti (Progetto Scuole DNR)
window.updateCustomer = async function(id, data) {
    try {
        const { id: _, ...updateData } = data;
        let docId = id;
        
        if (!docId) {
            // Se non c'è id creiamo il documento col codice frutta o latte (oppure usiamo addDoc ma setDoc è meglio)
            // Lavoriamo con doc() senza id per generarlo
            const docRef = doc(collection(db, "clienti", "DNR", "raccolta clienti"));
            await setDoc(docRef, updateData);
        } else {
            const docRef = doc(db, "clienti", "DNR", "raccolta clienti", id);
            await setDoc(docRef, updateData, { merge: true }); // setDoc merge previene crash se vuoto
        }
        return true;
    } catch (e) {
        console.error("Errore salvataggio Cliente:", e);
    }
};

// Alias per chiarezza
window.addCustomer = (data) => window.updateCustomer(null, data);

// Funzione di salvataggio/creazione per gli utenti (Solo per Admin)
window.updateUser = async function(id, data) {
    try {
        const { id: _, ...updateData } = data;
        if (id) {
            const docRef = doc(db, "dipendenti", id);
            await updateDoc(docRef, updateData);
        } else {
            console.warn("La creazione di nuovi account richiede l'uso della console Firebase Auth o Cloud Functions.");
        }
        return true;
    } catch (e) {
        console.error("Errore salvataggio Utente:", e);
        throw e;
    }
}

// Funzione per creare un nuovo utente tramite istanza Auth temporanea
window.registerNewUserCloud = async function(email, password, nome, cognome, ruolo, turno, canElevate) {
    const tempApp = getApps().find(a => a.name === "UserCreationApp") || initializeApp(firebaseConfig, "UserCreationApp");
    const tempAuth = getAuth(tempApp);

    try {
        // Crea l'utente nel database Auth in modo isolato
        const userCredential = await createUserWithEmailAndPassword(tempAuth, email, password);
        const uid = userCredential.user.uid;

        // Salva il documento profilo in Firestore nella collezione "dipendenti"
        await setDoc(doc(db, "dipendenti", uid), {
            uid: uid,
            nome: nome,
            cognome: cognome,
            email: email,          // Salvata email reale per busta paga
            ruolo: ruolo,
            tipoTurno: turno,
            canElevate: canElevate,
            needsPasswordChange: false,
            createdAt: new Date()
        });

        await signOut(tempAuth);
        return uid;
    } catch (e) {
        console.error("Errore registrazione temporanea:", e);
        throw e;
    }
};

// Funzione di salvataggio/creazione per i mezzi
window.updateMezzo = async function(id, data) {
    try {
        const { id: _, ...updateData } = data;
        const targetId = id || updateData.targa;
        if (!targetId) {
            throw new Error("Targa mancante.");
        }
        
        const docRef = doc(db, "mezzi", targetId);
        // Usa setDoc con merge per aggiornare o creare usando la targa come ID
        await setDoc(docRef, updateData, { merge: true });
        return true;
    } catch (e) {
        console.error("Errore salvataggio Mezzo:", e);
        throw e;
    }
}

// Funzione di eliminazione generica
window.deleteFromFirebase = async function(collectionName, id) {
    try {
        const docRef = doc(db, collectionName, id);
        await deleteDoc(docRef);
        return true;
    } catch (e) {
        console.error("Errore eliminazione Firebase:", e);
        throw e;
    }
}


