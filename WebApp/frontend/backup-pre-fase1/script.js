/**
 * script.js - v1.95
 * Modulo principale per la gestione della UI, validazioni e wizard.
 * Logica di persistenza spostata su firestore-service.js
 */

const APP_VERSION = "6.037";

// Esposta su window per lettura globale (es. da qualsiasi pagina o modulo)
window.APP_VERSION = APP_VERSION;
console.log("%c[App] Log Solution PWA - versione " + APP_VERSION, "color: #4f46e5; font-weight: bold; font-size: 12px;");

// --- SENTRY ERROR MONITORING ---
window.addEventListener("load", () => {
    const sentryScript = document.createElement("script");
    sentryScript.src = "https://js-de.sentry-cdn.com/6d8e6633a889531df8d60cd252352d1e.min.js";
    sentryScript.crossOrigin = "anonymous";
    sentryScript.defer = true;
    document.head.appendChild(sentryScript);

    window.Sentry = window.Sentry || {};
    window.Sentry.onLoad = function() {
        Sentry.init({
            release: "log-solution-pwa@" + APP_VERSION,
            environment: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' ? 'development' : 'production'
        });
    };
});

// --- BANNER MEMORIA "VERSIONE SVILUPPO" ---
document.addEventListener("DOMContentLoaded", () => {
    const hostname = window.location.hostname;
    if (hostname.includes('log-solutions-sviluppo') || hostname.includes('--sviluppo') || hostname.includes('localhost') || hostname.includes('127.0.0.1')) {
        const devBanner = document.createElement("div");
        devBanner.id = "dev-env-banner";
        devBanner.innerText = "VERSIONE SVILUPPO";
        devBanner.style.cssText = "background-color: #ef4444; color: white; text-align: center; font-weight: bold; padding: 6px 12px; font-size: 14px; letter-spacing: 2px; text-transform: uppercase; box-shadow: 0 2px 4px rgba(0,0,0,0.2); position: sticky; top: 0; z-index: 99999;";
        
        const firstChild = document.body.firstChild;
        if (firstChild) {
            document.body.insertBefore(devBanner, firstChild);
        } else {
            document.body.appendChild(devBanner);
        }
    }
});


// --- STATO GLOBALE ---
window.appData = window.appData || {
    lista_clienti: [],
    lista_autisti: [],
    lista_mezzi: [],
    currentUser: {}
};

// --- HELPERS TEMPO ---
window.getTimeValue = (id) => {
    const h = document.getElementById(id + 'HH')?.value;
    const m = document.getElementById(id + 'MM')?.value;
    if (!h || !m) return "";
    return `${h}:${m}`;
};

window.setTimeValue = (id, val) => {
    if (!val || !val.includes(':')) return;
    const [h, m] = val.split(':');
    const hEl = document.getElementById(id + 'HH');
    const mEl = document.getElementById(id + 'MM');
    if (hEl) hEl.value = h;
    if (mEl) mEl.value = m;
};

// Funzione mostrare/nascondere password
window.togglePasswordVisibility = function() {
    const passwordInput = document.getElementById('password');
    const toggleIcon = document.getElementById('toggleIcon');
    if (!passwordInput || !toggleIcon) return;
    
    if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        toggleIcon.textContent = 'visibility_off';
    } else {
        passwordInput.type = 'password';
        toggleIcon.textContent = 'visibility';
    }
};

// --- NAVIGAZIONE ---
window.navigateWithState = (page) => window.location.href = page;

// --- GESTIONE TURNI (WIZARD) ---
let currentStep = 1;
const totalSteps = 2;

window.nextStep = (step) => {
    currentStep = step;
    updateStepUI();
    saveDraft();
};

window.prevStep = (step) => {
    currentStep = step;
    updateStepUI();
};

function updateStepUI() {
    const containers = document.querySelectorAll('.step-container');
    if (containers.length === 0) return;

    containers.forEach(c => c.classList.remove('active'));
    document.getElementById(`step-${currentStep}`)?.classList.add('active');

    for (let i = 1; i <= totalSteps; i++) {
        const dot = document.getElementById(`dot-${i}`);
        if (!dot) continue;
        if (i < currentStep) { dot.classList.add('completed'); dot.innerHTML = '✓ '; }
        else if (i === currentStep) { dot.classList.add('active'); dot.classList.remove('completed'); dot.innerHTML = i; }
        else { dot.classList.remove('active', 'completed'); dot.innerHTML = i; }
    }
    
    // Disabilita campi step precedenti
    if (currentStep > 1) {
        document.querySelectorAll('#step-1 input, #step-1 select').forEach(el => {
            el.classList.add('readonly-field');
            el.disabled = true;
        });
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
    if (typeof calcolaTutto === 'function') calcolaTutto();
}

// --- CALCOLI KM E ORE ---
function calcolaTutto() {
    const kmP = parseFloat(document.getElementById('kmPartenza')?.value) || 0;
    const kmA = parseFloat(document.getElementById('kmArrivo')?.value) || 0;
    const deltaEl = document.getElementById('deltaKm');
    if (deltaEl) deltaEl.value = (kmA - kmP) > 0 ? (kmA - kmP) : '-';

    const mI = window.getTimeValue('mattinaInizio');
    const mF = window.getTimeValue('mattinaFine');
    const pI = window.getTimeValue('pomeriggioInizio');
    const pF = window.getTimeValue('pomeriggioFine');

    let totalM = 0;
    if (mI && mF) totalM += diffMin(mI, mF);
    if (pI && pF) totalM += diffMin(pI, pF);
    if (mI && pF && !mF && !pI) totalM = diffMin(mI, pF); // Turno unico

    if (totalM > 0) {
        const ordM = Math.min(totalM, 480);
        const straM = Math.max(0, totalM - 480);
        document.getElementById('totaleOre').value = formatHHMM(totalM);
        document.getElementById('oreOrdinarie').value = formatHHMM(ordM);
        document.getElementById('oreStraordinario').value = formatHHMM(straM);
    }
}

function diffMin(s, e) {
    const [h1, m1] = s.split(':').map(Number);
    const [h2, m2] = e.split(':').map(Number);
    let diff = (h2 * 60 + m2) - (h1 * 60 + m1);
    if (diff < 0) diff += 24 * 60; // Supporto scavalco mezzanotte
    return diff;
}

function formatHHMM(min) {
    const h = Math.floor(min / 60);
    const m = min % 60;
    return `${h}:${m.toString().padStart(2, '0')}`;
}

// --- BOZZE ---
function saveDraft() {
    const draft = { step: currentStep, data: {}, timestamp: Date.now() };
    const ids = ['data', 'automezzo', 'clienteSelect', 'viaggioSelect', 'kmPartenza', 'kmArrivo', 'importo', 'litri', 'nota'];
    ids.forEach(id => { const el = document.getElementById(id); if (el) draft.data[id] = el.value; });
    ['mattinaInizio', 'mattinaFine', 'pomeriggioInizio', 'pomeriggioFine'].forEach(id => { draft.data[id] = window.getTimeValue(id); });
    draft.data.attivitaAggiuntive = window.attivitaAggiuntive || [];
    sessionStorage.setItem('currentDraft', JSON.stringify(draft));
}

window.resumeDraft = () => {
    const saved = sessionStorage.getItem('currentDraft');
    if (!saved) return;
    const draft = JSON.parse(saved);
    Object.keys(draft.data).forEach(id => {
        if (id === 'attivitaAggiuntive') {
            window.attivitaAggiuntive = draft.data[id] || [];
        } else if (id.includes('Inizio') || id.includes('Fine')) {
            window.setTimeValue(id, draft.data[id]);
        } else {
            const el = document.getElementById(id);
            if (el) el.value = draft.data[id];
        }
    });
    if (typeof window.updateNomeGiorno === 'function') window.updateNomeGiorno();
    if (document.getElementById('clienteSelect')?.value) window.updateViaggi();
    
    if (typeof window.renderAttivitaRows === 'function') window.renderAttivitaRows();
    if (typeof window.aggiornaVisibilitaAttivita === 'function') window.aggiornaVisibilitaAttivita();
    
    // Ripristina Tracking se necessario
    if (window.recoverGPSTracking) window.recoverGPSTracking();

    currentStep = draft.step;
    updateStepUI();
    document.getElementById('recoveryTripModal')?.classList.remove('active');
};

window.discardDraft = () => {
    sessionStorage.clear();
    window.location.reload();
};

// --- MENU DINAMICI ---
window.renderMezziInserimento = function() {
    const select = document.getElementById('automezzo');
    if (!select) return;
    const mezzi = window.appData.lista_mezzi || [];
    const currentVal = select.value;
    
    select.innerHTML = '<option value="">Seleziona targa...</option>';
    mezzi.sort((a,b) => a.targa.localeCompare(b.targa)).forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.targa;
        let label = m.targa;
        const modelloPulito = m.modello && m.modello !== 'undefined' && m.modello !== 'null' ? m.modello.trim() : '';
        if (modelloPulito) label += ` (${modelloPulito})`;
        if (m.patente) label += ` [${m.patente}]`;
        opt.textContent = label;
        select.appendChild(opt);
    });
    if (currentVal) select.value = currentVal;
};

window.renderClientiInserimento = function() {
    const select = document.getElementById('clienteSelect');
    if (!select) return;

    // 1. Usa lista_progetti da Firestore se disponibile
    const progetti = window.appData.lista_progetti || [];
    let nomi = progetti.map(p => p.nome).filter(Boolean);

    // 2. Fallback hardcoded se Firestore è vuoto
    if (nomi.length === 0) {
        nomi = ["PROGETTO SCUOLE", "CATTEL", "GRAN CHEF", "BAUER"];
    }

    const currentVal = select.value;
    select.innerHTML = '<option value="">Seleziona cliente</option>';
    nomi.sort().forEach(nome => {
        const opt = document.createElement('option');
        opt.value = nome;
        opt.textContent = nome.toUpperCase();
        select.appendChild(opt);
    });

    // Aggiungi sempre NAVETTA come voce separata
    const navOpt = document.createElement('option');
    navOpt.value = 'NAVETTA';
    navOpt.textContent = 'NAVETTA';
    select.appendChild(navOpt);

    if (currentVal) select.value = currentVal;
};

// Alias usato dal listener realtime
window.renderProgettiInserimento = window.renderClientiInserimento;

window.updateNomeGiorno = function() {
    const dataInput = document.getElementById('data');
    const nomeGiornoEl = document.getElementById('nomeGiorno');
    if (!dataInput || !nomeGiornoEl) return;
    
    const dateVal = dataInput.value;
    if (!dateVal) {
        nomeGiornoEl.textContent = "";
        return;
    }
    
    const parts = dateVal.split('-');
    const date = new Date(parts[0], parts[1] - 1, parts[2]);
    if (isNaN(date.getTime())) {
        nomeGiornoEl.textContent = "";
        return;
    }
    const options = { weekday: 'long' };
    const dayName = date.toLocaleDateString('it-IT', options);
    nomeGiornoEl.textContent = dayName;
};

window.updateViaggi = async function() {
    const clienteNome = document.getElementById("clienteSelect")?.value || "";
    const viaggioSelect = document.getElementById("viaggioSelect");
    const viaggioWrapper = viaggioSelect?.closest('.input-group');
    const navettaContainer = document.getElementById('navettaFieldsContainer');

    // Reset link mappa
    const linkMappa = document.getElementById('linkMappaViaggio');
    if (linkMappa) {
        linkMappa.href = '#';
        linkMappa.style.display = 'none';
    }
    window.viaggiLinksMap = {};

    // ────────────────────────────────────────────────────────────────────────
    if (clienteNome.toUpperCase() === 'NAVETTA') {
        // Nascondi il select viaggio standard
        if (viaggioWrapper) viaggioWrapper.style.display = 'none';
        if (viaggioSelect) { viaggioSelect.required = false; viaggioSelect.disabled = true; viaggioSelect.value = ''; }

        // Mostra solo il campo Partenza / Rientro
        if (navettaContainer) { navettaContainer.style.display = 'block'; }

        // Popola solo navettaPartenzaSelect
        const fillSelect = (id, items) => {
            const sel = document.getElementById(id);
            if (!sel) return;
            const cur = sel.value;
            sel.innerHTML = '<option value="">' + sel.options[0].text + '</option>';
            (items || []).sort((a,b) => (a.nome||'').localeCompare(b.nome||'')).forEach(item => {
                const o = document.createElement('option');
                o.value = item.nome; o.textContent = item.nome;
                sel.appendChild(o);
            });
            if (cur) sel.value = cur;
        };

        fillSelect('navettaPartenzaSelect', window.appData.lista_navetta_partenze);
        return;
    }

    // ────────────────────────────────────────────────────────────────────────
    if (clienteNome.toUpperCase() === 'MAGAZZINO') {
        // Nascondi i campi navetta
        if (navettaContainer) { navettaContainer.style.display = 'none'; }
        
        // Ripristina e popola il select viaggio (sedi magazzino)
        if (viaggioWrapper) viaggioWrapper.style.display = '';
        if (viaggioSelect) { 
            viaggioSelect.innerHTML = '<option value="">Seleziona sede magazzino</option>';
            const sedi = window.appData.lista_magazzini_sedi || [];
            sedi.sort((a,b) => (a.nome||'').localeCompare(b.nome||'')).forEach(sede => {
                const opt = document.createElement('option');
                opt.value = sede.nome; opt.textContent = sede.nome.toUpperCase();
                viaggioSelect.appendChild(opt);
            });
            viaggioSelect.disabled = false;
            viaggioSelect.required = true;
        }
        return;
    }

    // ────────────────────────────────────────────────────────────────────────
    // Ripristina il select viaggio
    if (viaggioWrapper) viaggioWrapper.style.display = '';
    if (viaggioSelect) { viaggioSelect.required = true; }
    // Nascondi i campi navetta
    if (navettaContainer) { navettaContainer.style.display = 'none'; }

    if (!viaggioSelect) return;
    viaggioSelect.innerHTML = '<option value="">Seleziona viaggio</option>';
    viaggioSelect.disabled = true;

    const selectedDate = document.getElementById("data")?.value;
    
    // Trova il progetto su Firestore (lista_progetti) per ottenere i viaggi configurati
    const progetto = (window.appData.lista_progetti || []).find(
        p => (p.nome || '').toUpperCase() === clienteNome.toUpperCase()
    );
    const viaggiConfigurati = progetto ? (progetto.viaggi || []).map(v => v.toUpperCase()) : [];

    let options = [];
    let loadedFromManifest = false;

    let formattedDate = selectedDate || "";
    if (selectedDate && selectedDate.includes('-')) {
        const parts = selectedDate.split('-');
        if (parts.length === 3 && parts[0].length === 4) {
            // Converts YYYY-MM-DD to DD-MM-YYYY
            formattedDate = `${parts[2]}-${parts[1]}-${parts[0]}`;
        }
    }

    if (formattedDate && (clienteNome.toUpperCase() === 'GRAN CHEF' || clienteNome.toUpperCase() === 'GRAND CHEF' || clienteNome.toUpperCase() === 'PROGETTO SCUOLE')) {
        try {
            const storage = window.firebaseStorage || (typeof firebaseStorage !== 'undefined' ? firebaseStorage : null);
            const sRef = window.sRef;
            const getDownloadURL = window.getDownloadURL;

            if (storage && sRef && getDownloadURL) {
                const fileRef = sRef(storage, `REPORTS/${formattedDate}/manifest_link_viaggi.json`);
                const downloadUrl = await getDownloadURL(fileRef);
                const response = await fetch(downloadUrl);
                if (response.ok) {
                    const data = await response.json();
                    const links = data.links || [];
                    
                    // Salva la mappa dei link
                    links.forEach(l => {
                        if (l.v_id && l.url) {
                            window.viaggiLinksMap[l.v_id.toUpperCase()] = l.url;
                        }
                    });
                    
                    // Filtra dal manifest solo i viaggi configurati nelle impostazioni per questo cliente
                    options = links
                        .map(l => l.v_id)
                        .filter(v_id => v_id && viaggiConfigurati.includes(v_id.toUpperCase()));
                    
                    if (options.length > 0) {
                        loadedFromManifest = true;
                        console.log(`[updateViaggi] Caricati ${options.length} viaggi dal manifest di Storage per ${formattedDate}.`);
                    }
                }
            }
        } catch (err) {
            console.warn("[updateViaggi] Manifest non trovato o errore nel recupero: ", err.message);
        }
    }

    if (!loadedFromManifest) {
        options = viaggiConfigurati;

        // Fallback hardcoded rimosso per evitare flash di vecchi dati
        if (options.length === 0) {
            options = [];
        }
    }

    if (options.length > 0) {
        options.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v; opt.textContent = v.toUpperCase();
            viaggioSelect.appendChild(opt);
        });
        viaggioSelect.disabled = false;
    }
};

// --- INITIALIZATION ---
document.addEventListener('DOMContentLoaded', () => {
    // 0. Aggiorna dinamicamente tutti i badge di versione nella UI
    document.querySelectorAll('.app-version-badge').forEach(el => {
        el.textContent = 'v' + APP_VERSION;
    });

    // 1. Gestione Login
    const loginBtn = document.getElementById('loginBtn');
    if (loginBtn) {
        const handleLoginSubmit = async () => {
            let email = document.getElementById('username')?.value.trim().toLowerCase();
            if (email) {
                // Rimuove caratteri invisibili
                email = email.replace(/[\u200B-\u200D\uFEFF]/g, '');
                
                if (!email.includes('@')) {
                    // Trasforma gli spazi in punti (es. "ayoub berradia" -> "ayoub.berradia")
                    email = email.replace(/\s+/g, '.');
                    // Rimuove punti consecutivi o punti all'inizio/fine che causano invalid-email
                    email = email.replace(/\.+/g, '.').replace(/^\.|\.$/g, '');
                    email += '@logsolution.app';
                } else {
                    // Rimuovi eventuali spazi accidentali
                    email = email.replace(/\s+/g, '');
                }
            }
            const password = document.getElementById('password')?.value.trim();
            const alertEl = document.getElementById('authAlert');

            if (!email || !password) {
                if (alertEl) {
                    alertEl.style.display = 'block';
                    alertEl.style.background = '#fef2f2';
                    alertEl.style.color = '#991b1b';
                    alertEl.style.borderColor = '#fee2e2';
                    alertEl.textContent = "Inserisci nome utente e password.";
                }
                return;
            }

            loginBtn.disabled = true;
            loginBtn.innerHTML = 'Accesso in corso...';
            if (alertEl) { alertEl.style.display = 'none'; }

            try {
                if (typeof window.loginWithFirebase === 'function') {
                    await window.loginWithFirebase(email, password);
                    console.log("[Auth] Login avviato con successo.");
                } else {
                    throw new Error("Modulo Firebase non caricato correttamente.");
                }
            } catch (err) {
                console.error("[Auth] Errore di accesso:", err);
                if (alertEl) {
                    alertEl.style.display = 'block';
                    alertEl.style.background = '#fef2f2';
                    alertEl.style.color = '#991b1b';
                    alertEl.style.borderColor = '#fee2e2';
                    alertEl.textContent = "Errore: " + (err.code === 'auth/invalid-credential' ? 'Credenziali non valide' : err.message);
                } else {
                    alert("Errore Accesso: " + err.message);
                }
                loginBtn.disabled = false;
                loginBtn.innerHTML = 'Accedi ora';
            }
        };

        loginBtn.addEventListener('click', handleLoginSubmit);

        // Permetti l'invio con il tasto Invio negli input
        const loginInputs = document.querySelectorAll('#username, #password');
        loginInputs.forEach(input => {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    handleLoginSubmit();
                }
            });
        });
    }

    // 2. Popola Ore nelle select
    document.querySelectorAll('.hour-select').forEach(select => {
        for (let i = 0; i < 24; i++) {
            const opt = document.createElement('option');
            const val = i.toString().padStart(2, '0');
            opt.value = val; opt.textContent = val;
            select.appendChild(opt);
        }
    });

    // Event Listeners
    document.getElementById('clienteSelect')?.addEventListener('change', window.updateViaggi);
    document.getElementById('kmArrivo')?.addEventListener('input', calcolaTutto);
    
    const dataInput = document.getElementById('data');
    if (dataInput && !dataInput.value) {
        dataInput.value = new Date().toISOString().split('T')[0];
    }

    // Inizializza e ascolta i cambiamenti della data per aggiornare il nome del giorno
    if (dataInput) {
        if (typeof window.updateNomeGiorno === 'function') {
            window.updateNomeGiorno();
        }
        dataInput.addEventListener('change', () => {
            if (typeof window.updateNomeGiorno === 'function') window.updateNomeGiorno();
            const client = document.getElementById('clienteSelect')?.value?.toUpperCase();
            if (client === 'BAUER' || client === 'GRAN CHEF' || client === 'GRAND CHEF' || client === 'PROGETTO SCUOLE') {
                if (typeof window.updateViaggi === 'function') window.updateViaggi();
            }
        });
        dataInput.addEventListener('input', () => {
            if (typeof window.updateNomeGiorno === 'function') window.updateNomeGiorno();
            const client = document.getElementById('clienteSelect')?.value?.toUpperCase();
            if (client === 'BAUER' || client === 'GRAN CHEF' || client === 'GRAND CHEF' || client === 'PROGETTO SCUOLE') {
                if (typeof window.updateViaggi === 'function') window.updateViaggi();
            }
        });
    }

    // PWA: Bonifica automatica vecchi Service Worker obsoleti e registrazione sw.js costante
    if ('serviceWorker' in navigator) {
        // 1. Rileva e disinstalla vecchi Service Worker con nomi specifici di versione (es. sw_v207.js)
        navigator.serviceWorker.getRegistrations().then(registrations => {
            let clearedOldSw = false;
            for (let reg of registrations) {
                const scriptUrl = reg.active?.scriptURL || reg.installing?.scriptURL || reg.waiting?.scriptURL || '';
                if (scriptUrl && !scriptUrl.endsWith('/sw.js')) {
                    console.warn('[SW Cleanup] Rilevato Service Worker obsoleto, rimozione in corso:', scriptUrl);
                    reg.unregister();
                    clearedOldSw = true;
                }
            }
            if (clearedOldSw) {
                console.log('[SW Cleanup] Bonifica completata. Svuoto la cache e ricarico...');
                caches.keys().then(names => Promise.all(names.map(name => caches.delete(name)))).then(() => {
                    window.location.reload();
                });
            }
        });

        // 2. Registrazione del Service Worker standard sw.js
        navigator.serviceWorker.register('./sw.js').then(reg => {
            console.log('[SW] Registrato correttamente sw.js con versione ' + APP_VERSION);

            // Se c'è già un SW in attesa (tab rimasto aperto durante aggiornamento)
            // - invia subito SKIP_WAITING per forzare l'attivazione
            if (reg.waiting) {
                console.log('[SW] SW in attesa trovato -> invio SKIP_WAITING.');
                reg.waiting.postMessage({ type: 'SKIP_WAITING' });
                showUpdateToast(reg);
            }

            reg.addEventListener('updatefound', () => {
                const newWorker = reg.installing;
                newWorker.addEventListener('statechange', () => {
                    if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                        console.log('[SW] Nuova versione installata, mostro banner aggiornamento.');
                        showUpdateToast(reg);
                    }
                });
            });
        }).catch(err => {
            console.error('[SW] Errore registrazione:', err);
        });

        // ⚡ CRITICO: Quando il nuovo SW prende il controllo, ricarica la pagina automaticamente
        // Questo garantisce che il telefono non rimanga su una versione vecchia.
        let swRefreshing = false;
        navigator.serviceWorker.addEventListener('controllerchange', () => {
            if (swRefreshing) return;
            swRefreshing = true;
            console.log('[SW] Nuova versione attiva -> ricarico la pagina...');
            window.location.reload();
        });
    }
});

function showUpdateToast(reg) {
    // Evita duplicati se il toast è già presente
    if (document.getElementById('sw-update-toast')) return;

    const toast = document.createElement('div');
    toast.id = 'sw-update-toast';
    toast.className = 'sw-update-toast show';
    toast.innerHTML = `
        <div style="flex:1;">🚀 Nuova versione disponibile!</div>
        <button class="btn-update" id="btn-sw-update">Aggiorna ora</button>
    `;
    document.body.appendChild(toast);

    // Il pulsante invia SKIP_WAITING al SW in attesa, poi il controllerchange ricarica
    document.getElementById('btn-sw-update').addEventListener('click', () => {
        if (reg.waiting) {
            console.log('[SW] Utente ha cliccato Aggiorna -> invio SKIP_WAITING.');
            reg.waiting.postMessage({ type: 'SKIP_WAITING' });
        } else {
            // Fallback: nessun SW in attesa, ricarica direttamente
            window.location.reload();
        }
    });
}

// --- AUTH HOOKS ---
window.onUserProfileLoaded = (user) => {
    const autistaEl = document.getElementById('autistaNome');
    if (autistaEl) autistaEl.value = user.nome || '';
    
    const role = (user.ruolo || 'autista').toLowerCase();
    
    // Gestione pulsante Dashboard / Home
    const dashBtn = document.getElementById('dashboardBtn');
    if (dashBtn) {
        if (role === 'amministratore' || role === 'impiegata') {
            dashBtn.style.display = 'flex';
            dashBtn.title = "Dashboard";
            dashBtn.onclick = () => window.navigateWithState('dashboard.html');
            const icon = dashBtn.querySelector('.material-icons-round');
            if (icon) icon.textContent = 'dashboard';
        } else {
            // Se autista
            const isInserimentoPage = window.location.pathname.includes('inserimento.html');
            if (isInserimentoPage) {
                // Non serve il tasto Home se siamo già  in inserimento.html
                dashBtn.style.display = 'none';
            } else {
                dashBtn.style.display = 'flex';
                dashBtn.title = "Inserimento Turno";
                dashBtn.onclick = () => window.navigateWithState('inserimento.html');
                const icon = dashBtn.querySelector('.material-icons-round');
                if (icon) icon.textContent = 'home';
            }
        }
    }

    // Gestione pulsante Le Mie Presenze per autisti
    const presenzeBtn = document.getElementById('presenzeBtn');
    if (presenzeBtn) {
        presenzeBtn.style.display = (role === 'autista') ? 'flex' : 'none';
    }

    // Inizializza i menu a tendina dinamici se i dati sono già  pronti
    if (typeof window.renderMezziInserimento === 'function') window.renderMezziInserimento();
    if (typeof window.renderClientiInserimento === 'function') window.renderClientiInserimento();

    // Se siamo in inserimento e c'è una bozza, mostriamo il modale
    if (document.getElementById('presenzeForm') && sessionStorage.getItem('currentDraft')) {
        document.getElementById('recoveryTripModal')?.classList.add('active');
    }
};

window.closeConfirmModal = () => document.getElementById('confirmModal')?.classList.remove('active');

window.caricaFotoDDT = async function(inputEl, index) {
    const file = inputEl.files[0];
    if (!file) return;

    try {
        const storage = window.firebaseStorage || (typeof firebaseStorage !== 'undefined' ? firebaseStorage : null);
        if (!storage) {
            alert("Errore: Firebase Storage non inizializzato.");
            return;
        }

        // Recupera le funzioni modulari da Firebase Storage
        const { ref: sRef, uploadBytes, getDownloadURL } = await import("https://www.gstatic.com/firebasejs/10.7.1/firebase-storage.js");

        // Crea un nome univoco basato sulla data odierna
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, '0');
        const dd = String(today.getDate()).padStart(2, '0');
        const formattedDate = `${yyyy}-${mm}-${dd}`;
        
        const timestamp = Date.now();
        const username = window.appData?.currentUser?.nome || 'sconosciuto';
        const safeUsername = username.replace(/\s+/g, '_').toLowerCase();
        
        const path = `DDT_NAVETTE/${formattedDate}/DDT_${safeUsername}_${timestamp}.jpg`;
        const fileRef = sRef(storage, path);

        // Upload
        const snapshot = await uploadBytes(fileRef, file);
        const downloadUrl = await getDownloadURL(snapshot.ref);

        // Salva nell'array
        window.attivitaAggiuntive[index].fotoUrl = downloadUrl;

        // Mostra il check visivo
        const previewEl = document.getElementById(`previewDDT_${index}`);
        if (previewEl) {
            previewEl.style.display = 'block';
        }

        // Salva in bozza
        if (typeof window.saveDraft === 'function') window.saveDraft();
        
    } catch (e) {
        console.error("Errore caricamento foto DDT:", e);
        alert("Errore durante il caricamento della foto: " + e.message);
    }
};
