# AppLogSolutionsWeb — Security Cantiere

## 1. Scope
Questo documento fotografa il CURRENT VERIFIED SECURITY STATE del progetto `log-solutions-cantiere`. Non è una proiezione teorica né un target implementato; espone lo stato effettivo della sicurezza emerso dagli audit sul codice sorgente.

## 2. Security Principles
- Distinguere sempre tra CURRENT (stato attuale), KNOWN VULNERABILITY (vulnerabilità nota), HARDENING (rafforzamento), TARGET (stato desiderato) e REMEDIATION PLAN.
- **AUTHENTICATED NON equivale a AUTHORIZED FOR EVERY TENANT.**
- Il principio del least privilege guida il TARGET, ma deve essere mappato sulle reali necessità operative per evitare rotture (regressioni).
- Nessun artefatto viene promosso in Produzione prima della validazione del Security Gate.

## 3. Current Verified Status
L'architettura attuale (CURRENT) è prevalentemente "Authentication-centric". Questo significa che per molte operazioni il controllo si ferma a `isAuthenticated()`, delegando il filtraggio dati al client (o non effettuandolo). Il modello TARGET prevede invece: Authentication + RBAC + Tenant boundary + Least privilege.

## 4. Firebase Auth
Il meccanismo di autenticazione Firebase gestisce l'accesso al sistema. Allo stato attuale, gran parte della sicurezza si affida alla validità del token JWT (presenza di `req.auth`). Esistono controlli parziali basati sui campi del documento utente (ruolo), ma non applicati in modo sistematico a tutte le chiamate sensibili.

## 5. Firestore Rules
- **CURRENT MODEL**: Prevalentemente Authentication-centric.
- **TARGET MODEL**: Authentication + RBAC + Tenant boundary.
*(La correzione richiederà una matrice di accesso preventiva per evitare rotture).*

## 6. Storage Rules
- **CURRENT**: Path ad accesso autenticato troppo ampi (es. `imports/`, `REPORTS/`, `cedolini/`) senza segregazione tenant. Esistenza di path pubblici per la scrittura (es. `RESI/`).
- **TARGET**: Autenticazione obbligatoria per write (salvo casi speciali giustificati in cui si valida fortemente input/tipo/dimensione), role check, tenant boundary, validazione mimetype/dimensione, e minimizzazione dei path pubblici di lettura.

## 7. Cloud Functions / RBAC
- **CURRENT**: Mancanza di un RBAC uniforme. Alcune funzioni verificano che il chiamante sia amministratore/impiegata (es. `elimina_giornata_logistica`, `processa_job_pdf`), mentre molte altre funzioni critiche richiedono solo `req.auth` (es. `genera_distinta_viaggio`, `ottimizza_viaggio`, `genera_completo_giornata`, `pulisci_cartelle_elaborazione`).
- **TARGET MODEL**: `Callable -> req.auth -> UID -> role -> tenant authorization -> input validation -> App Check -> business operation`. Le policy esatte dipenderanno dalla funzione.

## 8. Tenant Isolation
- **CURRENT**: Il backend contiene meccanismi di fallback legacy. In particolare, helpers come `get_tenant_from_viaggio_id` o `get_tenant_from_cz` possiedono fallback statici (es. `"DNR"`). Questo crea un rischio (P3) in quanto eventuali record o file salvati con tenant "DNR" risultano fuori dal recinto di isolamento desiderato. Firestore Rules NON isolano il path `clienti/{tenant}`.
- **TARGET**: Nessun fallback implicito a DNR. L'isolamento deve essere garantito per UID, ROLE e TENANT MEMBERSHIP sia a livello rule che backend.

## 9. App Check
- **CURRENT**: Inizializzato lato frontend. Enforcement lato backend / Firebase Console assente nel repository (Cloud Console state: NOT_VERIFIABLE_FROM_REPOSITORY).
- **TARGET**: Server-side enforcement. *(Importante: Prima di attivarlo, verificare la compatibilità offline, i test e l'impatto sugli autisti)*.

## 10. CORS
- **CURRENT**: La configurazione CORS espone origini multiple per facilitare lo sviluppo (es. `localhost:5000`, `127.0.0.1:5000`, `localhost:3000`).
- **TARGET**: Hardening. Mantenere le origini strettamente necessarie all'ambiente Cantiere.

## 11. Secrets
- Le scansioni del repository non hanno individuato secret critici in grado di compromettere database o infrastruttura. Alcuni identificatori pubblici (es. Sentry DSN) sono cablati, ma non costituiscono rischio diretto di lettura dati.

## 12. Offline Security
- **CURRENT**: NOT FULLY VERIFIED. Richiede un audit dedicato sulle tecnologie usate (localStorage, IndexedDB, Firebase persistence, service workers). Occorre verificare la pulizia dei dati sensibili dopo il logout e nei dispositivi condivisi.

## 13. AI Security
- **CURRENT**: NO CRITICAL EVIDENCE FOUND, ma NEEDS DEDICATED SECURITY REVIEW (analisi di `agent_extractor` e `agent_chat_assistant` su authorization, tenant scope, e rischio prompt injection).

## 14. Email Security
- **CURRENT**: `invia_email_fattura` è esposta, ma manca di RBAC rigoroso (Wave 2).

## 15. Maps/API Security
- **CURRENT**: GOOGLE_MAPS_CLOUD_RESTRICTIONS = NOT_VERIFIABLE_FROM_REPOSITORY. Verifica delle restrizioni API rimandata a un check sulla Google Cloud Console.

## 16. Verified Findings

- **VERIFIED P0 — FIRESTORE TENANT ISOLATION MISSING**
  I path `customers/{tenant}/{collection=**}` e `clienti/{tenant}/{collection=**}` non verificano l'appartenenza al tenant. Qualunque utente autenticato può accedere.

- **VERIFIED P1 — FIRESTORE AUTH-ONLY WRITE**
  I path come `mezzi/`, `progetti/`, `viaggi/`, ecc. permettono `write` a qualunque utente autenticato, senza RBAC o isolamento dati.

- **VERIFIED P1 — STORAGE PUBLIC WRITE RESI**
  Il path `RESI/{allPaths=**}` ha scrittura pubblica non autenticata, esponendo potenziale caricamento di file non tracciati.

- **VERIFIED P1/P2 — STORAGE AUTH-ONLY**
  Path come `imports/`, `REPORTS/`, `cedolini/`, `DDT_NAVETTE/` sono scrivibili e leggibili da qualunque utente autenticato senza segregazione tenant. 

- **VERIFIED P2 — MISSING RBAC ON CALLABLES**
  Molteplici Cloud Functions modificano lo stato dell'app (es. `aggiorna_traffico_serale`, `ricalcola_percorso`) verificando solo l'esistenza dell'autenticazione.

- **VERIFIED P2 — APP CHECK**
  Enforcement backend (Cloud Functions, Firestore, Storage) non visibile nel repository. 

- **VERIFIED P3 — DNR FALLBACK**
  Fallback legacy in helper logistici (es. `get_tenant_from_viaggio_id`).

- **VERIFIED P3 — LOCALHOST CORS**
  Origins `localhost` permessi nel middleware callable. Hardening opportunity.

## 17. False Positives (Disproven/Reclassified Findings)
1. **PRODUCTION_ORIGIN_IN_CORS**: FALSE POSITIVE. In runtime, `GCLOUD_PROJECT=log-solutions-cantiere`, pertanto il dominio `log-solution-60007.web.app` non rientra automaticamente negli origin autorizzati.
2. **SENTRY DSN SECRET**: FALSE POSITIVE come secret critico (Classificato come: PUBLIC_IDENTIFIER / SENSITIVE_CONFIGURATION, impatto LOW).

## 18. Security Waves (Remediation Plan)
*NON APPLICARE IN QUESTA FASE. Piano di esecuzione documentale.*

- **SECURITY WAVE 1 — DATA BOUNDARIES (Priorità massima)**
  - Hardening di Firestore Rules e Storage Rules, introducendo isolamento Tenant.
  - Creazione e validazione dell'ACCESS MATRIX (pre-requisito).
- **SECURITY WAVE 2 — BACKEND AUTHORIZATION**
  - Implementazione RBAC su Cloud Functions (es. `invia_email_fattura`, `genera_completo_giornata`).
  - Rimozione sicura dei fallback `DNR`.
- **SECURITY WAVE 3 — PLATFORM HARDENING**
  - App Check server enforcement.
  - CORS hardening (rimozione localhost in env non-local).
  - Revisione restrizioni Maps API e offline caching.

## 19. Importantissima Regola Anti-Regressione
**NON restringere Firestore/Storage Rules senza prima mappare le letture/scritture reali del frontend.**
Una rule più restrittiva può causare rotture incontrollate. Il flusso operativo DEVE essere:
`DISCOVERY CLIENT ACCESS → ACCESS MATRIX → RULE DESIGN → EMULATOR TEST → CANTIERE DEPLOY → FUNCTIONAL TEST → LOG REVIEW`

## 20. Security Release Gate
- **CANTIERE_SECURITY_READY_FOR_PRODUCTION = FALSE**
L'innalzamento in Produzione sarà possibile solo quando: P0=0, P1(access-control)=0, isolamento tenant dimostrato, regole testate e approvate.
