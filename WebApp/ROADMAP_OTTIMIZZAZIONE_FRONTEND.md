# Roadmap Ottimizzazione Frontend e Firebase

Questo documento cristallizza lo stato dell'architettura dell'applicazione dopo l'implementazione della Fase 1 e Fase 2, e definisce i prossimi passi (Fase 2.5 e Fase 3) da valutare dopo un periodo di monitoraggio sul campo (circa 5-6 giorni).

---

## STATO ATTUALE: BASELINE v6.039

La transizione dal vecchio monolite (`firebase-auth-sync.js`) a un sistema modulare isolato è stata completata con successo, ottenendo enormi vantaggi prestazionali in fase di Login senza rompere le vecchie dipendenze.

### Architettura Corrente
```text
Frontend
│
├── Pagine pubbliche (es. login.html)
│      │
│      ├── core/firebase-init.js
│      └── core/auth-service.js (Carica Firestore SOLO post-login)
│
├── Pagine operative legacy (es. impostazioni, presenze)
│      │
│      └── firebase-auth-sync.js (Bridge di compatibilità legacy)
│              │
│              ├── core/firebase-init.js
│              ├── core/auth-service.js
│              ├── services/realtime-sync.js (Tutti i listener isolati qui)
│              └── services/crud-service.js (Tutte le funzioni CRUD isolate qui)
```

### Obiettivi Raggiunti
- [x] **Firebase Init Separato**
- [x] **Auth Separato**
- [x] **Firestore Lazy Loading su Login**: `login.html` non scarica più centinaia di KB di SDK Firestore e non apre websocket inutili se l'utente non è autenticato.
- [x] **Sync Realtime Isolato**: Unico punto di avvio (`startRealtimeSync`), eliminando i doppi listener.
- [x] **Compatibilità Assoluta**: Il contratto globale (`window.appData`, `window.currentUser`, ecc.) è stato preservato al 100%. Nessuna rottura sulle interfacce HTML esistenti.
- [x] **Cache Busting (`?v=6.039`)**: Per forzare i Service Worker e i browser a caricare i nuovi moduli.

---

## PROSSIME FASI (DA VALUTARE FRA 5-6 GIORNI)

L'obiettivo di questo periodo di pausa è raccogliere dati reali su:
1. Tempi effettivi di apertura da mobile (First Contentful Paint).
2. Segnalazioni di errori o anomalie dagli autisti.
3. Consumo e fatturazione delle letture Firestore.

Se i dati confermeranno la necessità di spingersi oltre, queste sono le prossime fasi pianificate:

### FASE 2.5-A: Ottimizzazione Pagine Isolate
Sostituire il bridge globale in pagine che non necessitano dell'intero `appData`.
*   **Target**: `visualizzazione.html`, `fatturazione.html`, pagine di puro report.
*   **Azione**: Rimuovere `firebase-auth-sync.js` e caricare solo i moduli necessari per evitare il download pesante della lista mezzi/autisti/scalette.

### FASE 2.5-B: Riduzione dei Dati Sincronizzati
Oggi `realtime-sync.js` scarica l'intero ecosistema aziendale in ogni pagina.
Domani potremmo dividere il flusso:
*   `dashboard.html` -> solo dati aggregati.
*   `mappa.html` -> solo coordinate clienti.
*   `presenze.html` -> solo lista autisti e giustificativi.
*   **Vantaggio**: Riduzione drastica delle letture Firestore (Billing) e della RAM usata sul dispositivo.

### FASE 3: Refactoring Rendering Asincrono (ALTO RISCHIO)
Attualmente le pagine disegnano le UI assumendo che `window.appData` sia già popolato e bloccando la pagina finché Firebase non risponde.
*   **Il nuovo modello**: La pagina si disegna immediatamente vuota (o con skeleton loaders) -> Aspetta l'evento `dataReady` da Firebase -> Chiama un `render()` per popolare i dati.
*   **Perché è rimandata**: Richiede una riscrittura strutturale dell'HTML e dei componenti UI di tutte le 14 pagine.

---
**Promemoria per lo Sviluppatore:** Consultare le metriche di Lighthouse e Firebase Usage prima di avviare le Fasi 2.5 o 3. I file di dettaglio pre-Fase 2.5 si trovano in `frontend/report-post-fase2/`.
