import { 
    collection, 
    doc, 
    addDoc, 
    setDoc, 
    updateDoc, 
    getDoc, 
    getDocs, 
    query, 
    where, 
    orderBy, 
    serverTimestamp,
    deleteDoc
} from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";
import { getStorage, ref as sRef, getDownloadURL } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-storage.js";
import { app, db, auth } from "./core/firebase-init.js";

/**
 * Helper to parse time string (HH:MM or decimal) into decimal hours.
 */
export function parseTimeToDecimal(val) {
    if (!val || val.trim() === "") return 0.0;
    const cleanVal = val.trim().replace(',', '.');
    if (cleanVal.includes(':')) {
        const parts = cleanVal.split(':');
        const h = parseInt(parts[0]) || 0;
        const m = parseInt(parts[1]) || 0;
        return h + m / 60.0;
    }
    const f = parseFloat(cleanVal);
    return isNaN(f) ? 0.0 : f;
}

/**
 * Centralized calculation of hours based on the four time points.
 * Standard contract limit is always 8.0 hours.
 */
export function calculateHours(oraInizioM, oraFineM, oraInizioP, oraFineP) {
    const valInizioM = (oraInizioM || "").trim();
    const valFineM = (oraFineM || "").trim();
    const valInizioP = (oraInizioP || "").trim();
    const valFineP = (oraFineP || "").trim();

    const decInizioM = parseTimeToDecimal(valInizioM);
    const decFineM = parseTimeToDecimal(valFineM);
    const decInizioP = parseTimeToDecimal(valInizioP);
    const decFineP = parseTimeToDecimal(valFineP);

    let totalHours = 0.0;

    // Turno unico lungo da InizioM a FineP
    if (valInizioM && !valFineM && !valInizioP && valFineP) {
        let diff = decFineP >= decInizioM ? decFineP - decInizioM : (24 - decInizioM) + decFineP;
        if (decFineP === 0 && decInizioM === 0) diff = 0;
        totalHours = diff;
    } else {
        // Turni separati
        let mornHours = 0.0;
        if (valInizioM && valFineM) {
            mornHours = decFineM >= decInizioM ? decFineM - decInizioM : (24 - decInizioM) + decFineM;
            if (decFineM === 0 && decInizioM === 0) mornHours = 0;
        }
        
        let aftHours = 0.0;
        if (valInizioP && valFineP) {
            aftHours = decFineP >= decInizioP ? decFineP - decInizioP : (24 - decInizioP) + decFineP;
            if (decFineP === 0 && decInizioP === 0) aftHours = 0;
        }
        
        totalHours = mornHours + aftHours;
    }

    const standardHours = 8.0; // Ore ordinarie sempre a 8.0 per tutti
    const ordinarie = Math.min(totalHours, standardHours);
    const straordinarie = Math.max(0.0, totalHours - standardHours);

    return {
        oreTotali: Number(totalHours.toFixed(2)),
        oreOrdinarie: Number(ordinarie.toFixed(2)),
        oreStraordinarie: Number(straordinarie.toFixed(2))
    };
}

// ─── SALVA VIAGGIO ────────────────────────────────────────────────────────────
/**
 * Crea o aggiorna un viaggio nella collezione "viaggi".
 * @param {Object} tripData - Dati del viaggio (deve includere 'id' se è un aggiornamento)
 * @returns {string} tripId
 */
export async function saveTrip(tripData) {
    const user = auth.currentUser;
    if (!user) throw new Error("Utente non autenticato");

    console.log("[Firestore] saveTrip chiamato:", tripData);

    const tripId = tripData.id || tripData.tripId || null;
    
    // Pulisce i campi id/tripId dal payload per non duplicarli nel documento
    const { id: _id, tripId: _tripId, ...cleanData } = tripData;

    const payload = {
        ...cleanData,
        autistaId: user.uid,
        updatedAt: serverTimestamp()
    };

    if (tripId) {
        const tripRef = doc(db, "viaggi", tripId);
        await updateDoc(tripRef, payload);
        console.log(`[Firestore] Viaggio aggiornato [ID: ${tripId}]`);
    } else {
        const docRef = await addDoc(collection(db, "viaggi"), {
            ...payload,
            createdAt: serverTimestamp()
        });
        console.log(`[Firestore] Nuovo viaggio creato [ID: ${docRef.id}]`);
        // We set tripId so we can return it correctly below
        tripData.id = docRef.id;
    }

    // --- SINCRO AUTOMATICA CON PRESENZE ---
    try {
        if (tripData.data && tripData.autista) {
            const presenzeDocId = `${user.uid}_${tripData.data}`;
            const presenzeRef = doc(db, "presenze", presenzeDocId);
            
            const finalKmPartenza = Number(tripData.kmPartenza) || 0;
            const finalKmArrivo = Number(tripData.kmArrivo) || 0;
            const finalKmDelta = Math.max(0, finalKmArrivo - finalKmPartenza);

            const finalInizioM = tripData.mattinaInizio || "";
            const finalFineM = tripData.mattinaFine || "";
            const finalInizioP = tripData.pomeriggioInizio || "";
            const finalFineP = tripData.pomeriggioFine || "";

            const calcolo = calculateHours(
                finalInizioM,
                finalFineM,
                finalInizioP,
                finalFineP
            );

            // Calcolo del giorno della settimana e del mese in locale per evitare bug di fuso orario
            const dateVal = tripData.data; // Formato "YYYY-MM-DD"
            const parts = dateVal.split('-');
            const year = parseInt(parts[0]);
            const month = parseInt(parts[1]);
            const day = parseInt(parts[2]);
            const dt = new Date(year, month - 1, day);
            
            const giorniSettimana = ['Domenica', 'Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato'];
            const giornoSettimana = giorniSettimana[dt.getDay()];
            const mese = `${year}-${month.toString().padStart(2, '0')}`;

            const presenzaPayload = {
                autistaId: user.uid,
                nomeAutista: tripData.autista,
                data: tripData.data,
                mese: mese,
                giornoSettimana: giornoSettimana,
                cliente: tripData.cliente || "",
                viaggio: tripData.viaggio || "",
                targa: tripData.automezzo || "",
                kmPartenza: finalKmPartenza,
                kmArrivo: finalKmArrivo,
                kmDelta: finalKmDelta,
                oraInizioM: finalInizioM,
                oraFineM: finalFineM,
                oraInizioP: finalInizioP,
                oraFineP: finalFineP,
                oreOrdinarie: calcolo.oreOrdinarie,
                oreStraordinarie: calcolo.oreStraordinarie,
                oreTotali: calcolo.oreTotali,
                note: tripData.nota || "",
                importo: Number(tripData.importo) || 0,
                isMagazzino: tripData.isMagazzino || false,
                attivitaAggiuntive: tripData.attivitaAggiuntive || [],
                // Campi "congelati" originari del viaggio per il confronto discrepanze
                viaggioOraInizioM: finalInizioM,
                viaggioOraFineM: finalFineM,
                viaggioOraInizioP: finalInizioP,
                viaggioOraFineP: finalFineP,
                viaggioKmPartenza: finalKmPartenza,
                viaggioKmArrivo: finalKmArrivo
            };
            
            // Usiamo merge: true per non rischiare di cancellare eventuali campi specifici di amministrazione
            // ma tutti i campi logistici, orari e calcolo ore sono completamente sovrascritti dai dati aggiornati del viaggio.
            await setDoc(presenzeRef, presenzaPayload, { merge: true });
            console.log(`[Firestore] Sincronizzato con presenze (sovrascrittura) [ID: ${presenzeDocId}]`);
        }
    } catch (err) {
        console.error("Errore sincro presenze:", err);
    }

    return tripData.id || tripId;
}

// ─── LISTA VIAGGI ─────────────────────────────────────────────────────────────
/**
 * Recupera tutti i viaggi, opzionalmente filtrati per autista.
 * @param {string} autistaNome - Nome autista o 'tutti'
 */
export async function getAllTrips(autistaNome = 'tutti') {
    console.log(`[Firestore] getAllTrips: filtro autista = "${autistaNome}"`);

    let q;
    if (autistaNome !== 'tutti') {
        q = query(
            collection(db, "viaggi"),
            where("autista", "==", autistaNome),
            orderBy("data", "desc")
        );
    } else {
        q = query(collection(db, "viaggi"), orderBy("data", "desc"));
    }

    const snapshot = await getDocs(q);
    const trips = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
    console.log(`[Firestore] ${trips.length} viaggi recuperati.`);
    return trips;
}

// ─── LOG GPS ──────────────────────────────────────────────────────────────────
/**
 * Recupera i log GPS di un viaggio, filtrati e ordinati.
 * Scarta log senza coordinate valide o con accuratezza scarsa.
 * @param {string} tripId
 */
export async function getTripLogs(tripId) {
    if (!tripId) return [];

    const logsRef = collection(db, "viaggi", tripId, "logs");
    const q = query(logsRef, orderBy("timestamp", "asc"));
    const snapshot = await getDocs(q);

    const allLogs = snapshot.docs.map(d => d.data());
    const validLogs = allLogs.filter(log =>
        log.lat && log.lng &&
        !isNaN(log.lat) && !isNaN(log.lng) &&
        (!log.accuracy || log.accuracy <= 50)
    );

    console.log(`[Firestore] getTripLogs: ${allLogs.length} totali, ${validLogs.length} validi.`);
    return validLogs;
}

// ─── ELIMINA VIAGGIO ──────────────────────────────────────────────────────────
/**
 * Elimina un viaggio e tutti i suoi log GPS.
 * @param {string} tripId
 */
export async function deleteTrip(tripId) {
    console.log(`[Firestore] Eliminazione viaggio [ID: ${tripId}]...`);

    const logsRef = collection(db, "viaggi", tripId, "logs");
    const snapshot = await getDocs(logsRef);
    const deletePromises = snapshot.docs.map(d => deleteDoc(d.ref));

    await Promise.all(deletePromises);
    await deleteDoc(doc(db, "viaggi", tripId));

    console.log(`[Firestore] Viaggio ${tripId} eliminato con ${snapshot.docs.length} log.`);
}

const storage = getStorage(app);

window.firebaseStorage = storage;
window.sRef = sRef;
window.getDownloadURL = getDownloadURL;

// ─── GESTIONE TURNI IN SOSPESO ───────────────────────────────────────────────

/**
 * Controlla se c'è un turno "in corso" per l'autista corrente
 */
export async function checkPendingTrip() {
    const user = auth.currentUser;
    if (!user) return null;

    try {
        const q = query(
            collection(db, "viaggi"),
            where("autistaId", "==", user.uid),
            where("stato", "==", "in corso")
        );
        const snap = await getDocs(q);
        if (!snap.empty) {
            // Prende il primo trovato (dovrebbe essercene uno solo in corso)
            const docSnap = snap.docs[0];
            return { id: docSnap.id, ...docSnap.data() };
        }
    } catch (err) {
        console.error("[Firestore] Errore checkPendingTrip:", err);
    }
    return null;
}

/**
 * Chiude il turno in "anomalia" e segna la riga delle presenze come errata
 */
export async function closeTripWithAnomaly(tripData) {
    const user = auth.currentUser;
    if (!user || !tripData || !tripData.id) return;

    try {
        // 1. Marca il viaggio come anomalia
        const tripRef = doc(db, "viaggi", tripData.id);
        await updateDoc(tripRef, { 
            stato: "anomalia", 
            note: (tripData.nota ? tripData.nota + " | " : "") + "Turno annullato per dimenticanza chiusura",
            updatedAt: serverTimestamp() 
        });

        // 2. Segna le presenze come "hasError"
        if (tripData.data) {
            const presenzeDocId = `${user.uid}_${tripData.data}`;
            const presenzeRef = doc(db, "presenze", presenzeDocId);
            
            await setDoc(presenzeRef, {
                hasError: true,
                note: "Dimenticanza chiusura. Gestione manuale richiesta.",
                autistaId: user.uid,
                nomeAutista: tripData.autista || "",
                data: tripData.data
            }, { merge: true });
        }
        
        console.log(`[Firestore] Viaggio ${tripData.id} chiuso in anomalia.`);
    } catch (err) {
        console.error("[Firestore] Errore closeTripWithAnomaly:", err);
    }
}

export { db, auth, storage, sRef, getDownloadURL };
