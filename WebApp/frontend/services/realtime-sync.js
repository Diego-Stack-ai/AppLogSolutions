import { app, db } from "../core/firebase-init.js";
import { getApps, initializeApp } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import { firebaseConfig } from "../firebase-config.js";
import { getAuth, createUserWithEmailAndPassword, signOut } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-auth.js";
import { collection, onSnapshot, query, where, doc, updateDoc, setDoc, deleteDoc, addDoc } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";
// Inizializzazione Listener Realtime (Condizionali ai permessi)
window.activeListeners = window.activeListeners || [];
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
            const tuttiDipendenti = [];
            snapshot.forEach((d) => {
                tuttiDipendenti.push({ id: d.id, ...d.data() });
            });
            
            window.appData.lista_dipendenti_completa = tuttiDipendenti;
            // Sostituito filtro statico con flag inRegistroPresenze dinamico (con fallback retrocompatibile sui ruoli per vecchi record)
            window.appData.lista_autisti = tuttiDipendenti.filter(d => {
                const ruolo = (d.ruolo || '').toLowerCase();
                const fallbackPresenze = (ruolo !== 'fornitore' && ruolo !== 'amministratore' && ruolo !== 'impiegata');
                return d.inRegistroPresenze !== undefined ? d.inRegistroPresenze : fallbackPresenze;
            });
            
            if (typeof window.renderAutisti === 'function') window.renderAutisti();
            if (typeof window.renderAutistiDropdown === 'function') window.renderAutistiDropdown();
        });
        activeListeners.push(unsubUsers);
    }

    // Listener per Mezzi (mezzi)
    const unsubMezzi = onSnapshot(collection(db, "mezzi"), { includeMetadataChanges: true }, (snapshot) => {
        const mezzi = [];
        snapshot.forEach((d) => {
            if (!d.id.startsWith('_')) {
                mezzi.push({ id: d.id, ...d.data() });
            }
        });
        window.appData.lista_mezzi = mezzi;
        if (typeof window.renderLista === 'function') window.renderLista();
        if (typeof window.renderMezziInserimento === 'function') window.renderMezziInserimento();
        if (typeof window.renderMezzi === 'function') window.renderMezzi();
    });
    activeListeners.push(unsubMezzi);

    // Listener per Clienti Fatturazione (Nuova Rubrica V2, usato per presenze operative e registrazioni turno)
    const unsubClientiFatturazione = onSnapshot(collection(db, "clienti_fatturazione"), { includeMetadataChanges: true }, (snapshot) => {
        const clientiFat = [];
        const progettiMapped = [];
        snapshot.forEach((d) => {
            const data = d.data();
            clientiFat.push({ id: d.id, ...data, isProgetto: true });
            
            // Mappatura per retrocompatibilità con la Registrazione Turno (script.js)
            progettiMapped.push({
                id: d.id,
                nome: data.nome,
                viaggi: (data.zone_fatturazione || []).map(z => z.nome_zona || ''),
                isProgetto: true
            });
        });
        window.appData.lista_clienti_fatturazione = clientiFat;
        window.appData.lista_progetti = progettiMapped;
        
        if (typeof window.renderProgetti === 'function') window.renderProgetti();
        if (typeof window.renderProgettiInserimento === 'function') window.renderProgettiInserimento();
        if (typeof window.renderProgettiImpostazioni === 'function') window.renderProgettiImpostazioni();
    });
    activeListeners.push(unsubClientiFatturazione);

    // Listeners per le 4 liste delle Scalette Navette e Navette Pure (unificate con doppio flag)
    const setupUnifiedNavettaListener = (tipo, collectionPath, listPropName, legacyAutistiProp, legacyPuraProp) => {
        const unsub = onSnapshot(collection(db, "clienti/DNR/" + collectionPath), { includeMetadataChanges: true }, (snapshot) => {
            const fullList = [];
            snapshot.forEach((d) => {
                fullList.push({ id: d.id, ...d.data() });
            });
            
            // Ordina alfabeticamente
            fullList.sort((a, b) => (a.nome || "").localeCompare(b.nome || ""));
            
            // 1. Salva la lista unificata completa per la schermata impostazioni
            window.appData[listPropName] = fullList;
            
            // 2. Filtra per la retrocompatibilità (Navetta Autisti)
            window.appData[legacyAutistiProp] = fullList.filter(item => item.is_navetta_autisti === true);
            
            // 3. Filtra per la retrocompatibilità (Navetta Pura)
            window.appData[legacyPuraProp] = fullList.filter(item => item.is_navetta === true);
            
            // 4. Aggiorna l'interfaccia se le funzioni di rendering sono presenti
            if (typeof window.renderUnifiedNavetteList === 'function') {
                window.renderUnifiedNavetteList(tipo);
            }
        });
        activeListeners.push(unsub);
    };

    setupUnifiedNavettaListener('partenze', 'fatturazione_navette_partenze', 'anagrafica_partenze', 'lista_scaletta_partenze', 'lista_navetta_partenze');
    setupUnifiedNavettaListener('carichi', 'fatturazione_navette_carichi', 'anagrafica_carichi', 'lista_scaletta_carico', 'lista_navetta_carico');
    setupUnifiedNavettaListener('clienti', 'fatturazione_navette_clienti', 'anagrafica_clienti', 'lista_scaletta_clienti', 'lista_navetta_clienti');
    setupUnifiedNavettaListener('destinazioni', 'fatturazione_navette_destinazioni', 'anagrafica_destinazioni', 'lista_scaletta_destinazioni_merce', 'lista_navetta_destinazioni_merce');

    // Listener per la lista delle Sedi Magazzino (lasciata separata)
    const setupScalettaListener = (tipo, globalProp) => {
        const unsub = onSnapshot(collection(db, "clienti/DNR/" + tipo), { includeMetadataChanges: true }, (snapshot) => {
            const dataList = [];
            snapshot.forEach((d) => dataList.push({ id: d.id, ...d.data() }));
            window.appData[globalProp] = dataList;
            if (typeof window.renderScaletteItems === 'function') window.renderScaletteItems(tipo);
        });
        activeListeners.push(unsub);
    };
    setupScalettaListener('fatturazione_magazzini_sedi', 'lista_magazzini_sedi');

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
        const { id: _, ruolo, canElevate, email, createdAt, uid, ...updateData } = data;
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
window.registerNewUserCloud = async function(email, password, nome, cognome, ruolo, turno, canElevate, inRegistroPresenze = false, inPianificazioneViaggi = false) {
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
            inRegistroPresenze: inRegistroPresenze,
            inPianificazioneViaggi: inPianificazioneViaggi,
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
        if (collectionName === 'dipendenti') {
            const { getFunctions, httpsCallable } = await import("https://www.gstatic.com/firebasejs/10.8.0/firebase-functions.js");
            const functions = getFunctions(app, 'europe-west1');
            const adminUpdateRole = httpsCallable(functions, 'admin_update_role');
            await adminUpdateRole({ action: 'DELETE_USER', targetUid: id });
            return true;
        }
        const docRef = doc(db, collectionName, id);
        await deleteDoc(docRef);
        return true;
    } catch (e) {
        console.error("Errore eliminazione Firebase:", e);
        throw e;
    }
}



window.startRealtimeSync = startRealtimeSync;
