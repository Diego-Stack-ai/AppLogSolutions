// firebase-config.js
// Gestione Multi-Ambiente: Produzione e Sviluppo

const firebaseConfigProd = {
  apiKey: "AIzaSyDLnhP2Q4bz2ubYwcMLiD3-qq4c220eVKw",
  authDomain: "log-solution-60007.web.app",
  projectId: "log-solution-60007",
  storageBucket: "log-solution-60007.firebasestorage.app",
  messagingSenderId: "74169420428",
  appId: "1:74169420428:web:630250640b42d4a49049a9"
};

const firebaseConfigDev = {
  apiKey: "AIzaSyD6kcBZyrPi9Pe_NZenbQzhP1Q6otYh8Ew",
  authDomain: "log-solutions-cantiere.firebaseapp.com",
  projectId: "log-solutions-cantiere",
  storageBucket: "log-solutions-cantiere.firebasestorage.app",
  messagingSenderId: "646843725221",
  appId: "1:646843725221:web:e56143098e6e6dcfb8e44c",
  measurementId: "G-BQWBPK7HZM"
};

// Riconosciamo l'ambiente dall'URL o se stiamo girando in locale
const isDevEnvironment = window.location.hostname.includes('log-solutions-cantiere') || 
                         window.location.hostname.includes('--cantiere') ||
                         window.location.hostname === 'localhost' || 
                         window.location.hostname === '127.0.0.1';

export const firebaseConfig = isDevEnvironment ? firebaseConfigDev : firebaseConfigProd;

if (isDevEnvironment) {
    console.log("[Firebase Config] ATTENZIONE: Connesso all'AMBIENTE CANTIERE (log-solutions-cantiere)");
} else {
    console.log("[Firebase Config] Connesso alla PRODUZIONE PRINCIPALE (log-solution-60007)");
}
