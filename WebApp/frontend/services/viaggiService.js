import { collection, query, orderBy, limit, onSnapshot, doc, getDoc, setDoc } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";
import { app, db } from "../core/firebase-init.js";

// Inizializzazione sicura di Firebase (evita l'errore "app already exists")

/**
 * Ascolta in tempo reale la lista degli ultimi 15 Reports Logistici (DDT) del tenant.
 * @param {string|function} tenantId - L'ID del tenant (es. 'DNR', 'GRAN CHEF', 'CATTEL') o callback se omesso.
 * @param {function} [callback] - Funzione eseguita ogni volta che i dati cambiano.
 * @returns {function} unsubscribe - Funzione per fermare l'ascolto.
 */
export function subscribeToReportsLogistici(tenantId, callback) {
    let finalCallback = callback;
    if (typeof tenantId === 'function') {
        finalCallback = tenantId;
    }
    const reportsRef = collection(db, 'clienti', 'report_logistici', 'giornate');
    const q = query(reportsRef, orderBy('created_at', 'desc'), limit(15));
    return onSnapshot(q, { includeMetadataChanges: true }, finalCallback);
}

/**
 * Ascolta in tempo reale la coda dei job di elaborazione per un tenant specifico.
 * @param {string} tenantId - L'ID del tenant (es. 'DNR', 'GRAN CHEF', 'CATTEL')
 * @param {number} limitCount - Numero massimo di job da caricare
 * @param {function} callback - Funzione eseguita ogni volta che i dati cambiano.
 * @returns {function} unsubscribe
 */
export function subscribeToProcessingJobs(tenantId, limitCount = 10, callback) {
    const jobsRef = collection(db, 'clienti', tenantId, 'processing_jobs');
    const q = query(jobsRef, orderBy('created_at', 'desc'), limit(limitCount));
    return onSnapshot(q, { includeMetadataChanges: true }, callback);
}

/**
 * Carica la pianificazione giornaliera dei viaggi.
 * @param {string} tenantId - L'ID del tenant.
 * @param {string} dataIso - Data in formato YYYY-MM-DD.
 * @returns {Promise<Object|null>} I dati della pianificazione o null se non esiste.
 */
export async function getPianificazioneGiorno(tenantId, dataIso) {
    const docRef = doc(db, "clienti", tenantId, "pianificazione_viaggi", dataIso);
    const docSnap = await getDoc(docRef);
    return docSnap.exists() ? docSnap.data() : null;
}

/**
 * Salva la pianificazione giornaliera dei viaggi (assegnazioni autisti).
 * @param {string} tenantId - L'ID del tenant.
 * @param {string} dataIso - Data in formato YYYY-MM-DD.
 * @param {Array} assegnazioni - Array delle assegnazioni.
 * @returns {Promise<void>}
 */
export async function salvaPianificazione(tenantId, dataIso, assegnazioni) {
    const docRef = doc(db, "clienti", tenantId, "pianificazione_viaggi", dataIso);
    return await setDoc(docRef, {
        dataPianificazione: dataIso,
        ultimaModifica: new Date().toISOString(),
        assegnazioni: assegnazioni
    }, { merge: true });
}

/**
 * Blocca o sblocca la giornata di pianificazione.
 * @param {string} tenantId - L'ID del tenant.
 * @param {string} dataIso - Data in formato YYYY-MM-DD.
 * @param {boolean} isBloccato - true per bloccare, false per sbloccare.
 * @returns {Promise<void>}
 */
export async function bloccaGiornataPianificazione(tenantId, dataIso, isBloccato) {
    const docRef = doc(db, "clienti", tenantId, "pianificazione_viaggi", dataIso);
    return await setDoc(docRef, { isBloccato: isBloccato }, { merge: true });
}
