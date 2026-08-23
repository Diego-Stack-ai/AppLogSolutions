const admin = require('firebase-admin');
const serviceAccount = require('./cantiere_key.json');

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount)
});

const db = admin.firestore();

async function run() {
    try {
        const uid = "Ws6G1rYXMpPPHEydxa3VkgJ4Weg2";
        const dipendenteRef = db.collection('clienti').doc('DNR').collection('dipendenti').doc(uid);
        
        await dipendenteRef.set({
            id_dipendente: uid,
            nome: "Diego",
            cognome: "Boschetto",
            ruolo: "admin",
            mansione: "Amministrazione",
            email: "boschetto.diego@logsolution.app",
            attivo: true,
            createdAt: admin.firestore.FieldValue.serverTimestamp()
        });

        console.log("Documento utente creato con successo nel Cantiere!");
    } catch (e) {
        console.error("Errore:", e);
    }
}

run();
