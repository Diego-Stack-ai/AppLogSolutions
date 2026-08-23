const admin = require('firebase-admin');
const fs = require('fs');
const path = require('path');

// Initialize Firebase Admin (assuming run from functions folder)
const serviceAccountPath = path.join(__dirname, 'serviceAccountKey.json');
let serviceAccount;
try {
    serviceAccount = require(serviceAccountPath);
} catch (e) {
    console.error("No serviceAccountKey.json found in functions folder.");
    process.exit(1);
}

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount)
});

const db = admin.firestore();

async function runAnalysis() {
    console.log("=== ANALISI NAVETTE LUGLIO 2026 ===\n");
    
    // 1. Fetch Anagrafica (Carichi e Clienti)
    const anagraficaCarichi = {};
    const anagraficaClienti = {};
    
    const carichiSnap = await db.collection('clienti/DNR/navette_anagrafica_carichi').get();
    carichiSnap.forEach(doc => {
        const d = doc.data();
        anagraficaCarichi[(d.nome || '').trim().toUpperCase()] = d;
    });
    
    const clientiSnap = await db.collection('clienti/DNR/navette_anagrafica_clienti').get();
    clientiSnap.forEach(doc => {
        const d = doc.data();
        anagraficaClienti[(d.nome || '').trim().toUpperCase()] = d;
    });

    // 2. Fetch Presenze for July 2026
    const presenzeSnap = await db.collection('presenze')
        .where('mese', '==', '2026-07')
        .get();

    let navetteCount = 0;
    
    presenzeSnap.forEach(doc => {
        const pres = doc.data();
        const dataStr = pres.data;
        const autista = pres.autistaNome || pres.autista;
        
        if (pres.attivitaAggiuntive && Array.isArray(pres.attivitaAggiuntive)) {
            pres.attivitaAggiuntive.forEach(att => {
                if (att.tipo === 'navetta' || att.tipo === 'navettaMissione') {
                    const tipoNavetta = att.tipo === 'navetta' ? 'PURA' : 'AUTISTI';
                    const partenza = att.partenza || '-';
                    
                    if (att.tappe && Array.isArray(att.tappe)) {
                        att.tappe.forEach((t, i) => {
                            navetteCount++;
                            const carico = (t.carico || t.luogo || '').trim();
                            const cMerce = (t.cliente_merce || '').trim();
                            const destinazione = (t.destinazione_merce || t.scarico || '').trim();
                            
                            // Lookup prices
                            let valCarico = 'NON TROVATO IN ANAGRAFICA';
                            let valMerce = 'NON TROVATO IN ANAGRAFICA';
                            
                            if (carico && carico !== '-') {
                                const conf = anagraficaCarichi[carico.toUpperCase()];
                                if (conf) {
                                    valCarico = conf.prezzo !== undefined ? String(conf.prezzo) : 'CAMPO PREZZO VUOTO/ASSENTE';
                                }
                            } else {
                                valCarico = 'N/A';
                            }
                            
                            if (cMerce && cMerce !== '-') {
                                const conf = anagraficaClienti[cMerce.toUpperCase()];
                                if (conf) {
                                    valMerce = conf.prezzo !== undefined ? String(conf.prezzo) : 'CAMPO PREZZO VUOTO/ASSENTE';
                                }
                            } else {
                                valMerce = 'N/A';
                            }

                            console.log(`[${dataStr}] - Autista: ${autista} - Tipo: ${tipoNavetta}`);
                            console.log(`  Partenza Iniziale: ${partenza}`);
                            console.log(`  Tappa ${i+1}:`);
                            console.log(`    - Luogo di Carico: ${carico || '-'} -> Valore in Tabella: ${valCarico}`);
                            console.log(`    - Cliente/Merce  : ${cMerce || '-'} -> Valore in Tabella: ${valMerce}`);
                            console.log(`    - Destinazione   : ${destinazione || '-'}`);
                            console.log('----------------------------------------------------');
                        });
                    }
                }
            });
        }
    });
    
    console.log(`Totale tappe navette analizzate nel mese: ${navetteCount}`);
}

runAnalysis().catch(console.error).finally(() => process.exit(0));
