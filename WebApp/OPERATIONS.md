# Manuale delle Procedure Operative - PRODUZIONE

Queste procedure sono valide **esclusivamente** per l'ambiente di Produzione (`log-solution-60007`).

## Procedure di Deploy
I deploy devono essere eseguiti all'interno della directory `WebApp/`.

- **Hosting**:
  `firebase deploy --only hosting --project log-solution-60007`

- **Functions (Singola)**:
  `firebase deploy --only functions:NOME_FUNZIONE --project log-solution-60007`

- **Rules (SOLO SE esplicitamente autorizzate)**:
  `firebase deploy --only firestore:rules --project log-solution-60007`
  `firebase deploy --only storage --project log-solution-60007`

## 🚫 AZIONI VIETATE
È **TASSATIVAMENTE VIETATO** eseguire i seguenti comandi senza specifica necessità o autorizzazione:
- `firebase deploy`
- `firebase deploy --only functions`
