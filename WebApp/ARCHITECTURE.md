# Blueprint Architetturale Ufficiale - AppLogSolutions Produzione

Questa documentazione descrive **esclusivamente** l'architettura di Produzione.
Non esiste alcun multi-ambiente operativo all'interno di questo repository.

## Componenti Architetturali
- **Frontend Produzione**: HTML/JS/CSS puro, no-build, erogato da Firebase Hosting.
- **Backend Monolitico**: Firebase Cloud Functions basate sul file storico monolitico `functions/main.py`.
- **Firebase Prod (`log-solution-60007`)**:
  - **Firestore**: Database NoSQL per tutti i dati logistici (viaggi, consegne).
  - **Storage**: Archiviazione per PDF, export e cache.
  - **Auth**: Gestione autenticazione utenti.
  - **Hosting**: Erogazione del frontend.
  - **Functions**: Esecuzione del backend Python.
