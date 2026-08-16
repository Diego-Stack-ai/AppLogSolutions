# AppLogSolutionsWeb — Versioning Cantiere

## 1. Scope
Questo documento regola ESCLUSIVAMENTE le operazioni di versionamento del `cantiere` (`log-solutions-cantiere`). Definisce le procedure per incrementare le versioni frontend e backend in modo indipendente, senza impattare la Produzione e senza forzare deploy automatici.

## 2. Versioning Principles (Governance Rule)
- **VERSION BUMP != GIT COMMIT**
- **VERSION BUMP != GIT PUSH**
- **VERSION BUMP != FIREBASE DEPLOY**
- **VERSION BUMP != PRODUCTION RELEASE**
- **TARGET_BRANCH = cantiere**
- **PRODUCTION = READ ONLY**
- **MULETTO = NO TOUCH**

## 3. Frontend Version
La versione del frontend è indipendente dal backend. Serve per il cache busting dei browser e per tracciare lo stato dell'UI.

## 4. Backend Version
La versione del backend è indipendente dal frontend. Serve per tracciare l'evoluzione delle API e della business logic (`functions/`).

## 5. bump_version.py (Verified Script Behavior)
- **SOURCE**: Legge da `frontend/script.js`.
- **PATTERN**: Cerca `APP_VERSION = "x.y.z"`.
- **INCREMENT LOGIC**: Se inizia con 5, forza 6.000. Altrimenti incrementa la minor (es. 6.001). Se minor >= 1000, incrementa major.
- **EFFECT**:
  - Sovrascrive `APP_VERSION` in `frontend/script.js`.
  - Aggiorna il nome cache `log-solution-vX` in `frontend/sw.js`.
  - Aggiorna le query string di cache busting (`?v=X`) in tutti i file HTML e JS (eccetto script.js e sw.js).
- **ENCODING / FALLBACK**: Prova utf-8, usa fallback cp1252 in caso di UnicodeDecodeError.
- **FAILURE BEHAVIOR**: Se regex fallisce, default a 6.000. Nessun rollback automatico.

## 6. bump_backend_version.py (Verified Script Behavior)
- **SOURCE**: Legge da `functions/main.py`.
- **PATTERN**: Cerca `return {"version": "x.y.z"}` (tipicamente nel getter di versione).
- **INCREMENT LOGIC**: Incrementa la patch (es. 1.0.0 -> 1.0.1). Se patch >= 100, incrementa minor.
- **EFFECT**: Sovrascrive la stringa di versione in `functions/main.py`.
- **FAILURE BEHAVIOR**: Se non trova il pattern, usa fallback a 1.0.1. Stampa un avviso in console.

## 7. File Impact
- **FRONTEND_BUMP_POTENTIAL_FILES**: `frontend/script.js`, `frontend/sw.js`, `frontend/*.html`, `frontend/*.js` (esclusi script.js e sw.js). Scritture basate su ricerca (DISCOVERED_FILE_WRITE).
- **BACKEND_BUMP_POTENTIAL_FILES**: `functions/main.py` (DIRECT_WRITE).

## 8. Side Effects
Entrambi gli script sono verificati essere PRIVI di side effect impliciti:
- Nessuna operazione git (add, commit, push).
- Nessuna operazione di deploy (firebase, gcloud).
- Nessuna modifica a Firestore/Storage.
- Nessun accesso di rete a Produzione o Muletto.

## 9. When frontend bump is required
- FRONTEND_CHANGE: TRUE
- SERVICE_WORKER_CHANGE: TRUE
- CACHE_RELEVANT_CHANGE: TRUE
- BACKEND_ONLY_CHANGE: FALSE
- DOCUMENTATION_ONLY_CHANGE: FALSE
- CONFIG_CHANGE: FALSE

## 10. When backend bump is required
- Cloud Function modificata: TRUE
- service modificato: TRUE
- core modificato: TRUE
- infrastructure modificato: TRUE
- solo frontend modificato: FALSE
- solo documentazione modificata: FALSE

## 11. Pre-bump guard (Governance Rule)
Prima di eseguire qualsiasi bump, verificare:
1. Repository corretto.
2. Branch = cantiere.
3. HEAD noto.
4. Git status pulito e controllato per modifiche note.
5. Scope Cantiere confermato.

## 12. Post-bump guard (Governance Rule)
Dopo il bump, eseguire:
- `git status --short` e `git diff`
Confrontare `EXPECTED_FILES_CHANGED` vs `ACTUAL_FILES_CHANGED`. Se un file inatteso è modificato, **STOP** e non committare.

## 13. Git relationship (Governance Rule)
Il versionamento è isolato e propedeutico al deploy. Il bump NON è un'autorizzazione implicita ai passaggi successivi.
Flusso: CODE CHANGE -> TEST -> VERSION DECISION -> BUMP (se richiesto) -> DIFF GUARD -> COMMIT AUTORIZZATO -> PUSH AUTORIZZATO -> DEPLOY CANTIERE AUTORIZZATO -> POST-DEPLOY VALIDATION.

## 14. Deploy relationship
Vedi sopra. Il deploy non avviene mai all'interno degli script di versionamento.

## 15. Cantiere vs Produzione
Il versionamento eseguito sul branch `cantiere` riguarda solo il Cantiere.
NON implica che Produzione abbia la stessa versione. NON modificare mai i file della Produzione per "riallineare" forzatamente le versioni. La promozione Cantiere -> Produzione avverrà con procedura separata e controllata.

## 16. Failure policy (Governance Rule)
Se uno qualsiasi degli script fallisce parzialmente o produce output inattesi: **STOP**.
Prima di rilanciare, ispezionare il `git diff`. NON rilanciare lo script ciecamente. NON correggere i numeri di versione a mano senza aver compreso lo stato dei file.

## 17. Standard report
Ogni bump deve riportare:
- BUMP_TYPE
- SCRIPT
- BRANCH
- HEAD_BEFORE
- VERSION_BEFORE
- VERSION_AFTER
- EXPECTED_FILES_CHANGED vs ACTUAL_FILES_CHANGED
- UNEXPECTED_FILES_CHANGED
- SCRIPT_SUCCESS
- DIFF_VALIDATED
- COMMIT_EXECUTED
- PUSH_EXECUTED
- DEPLOY_EXECUTED
- PRODUCTION_CHANGED
- MULETTO_CHANGED
- SAFE_TO_PROCEED

## 18. Stop conditions
Violazione dell'Identity Guard, side effect inattesi nei diff, fallimento degli script, mutazioni non attese su file fuori perimetro, coinvolgimento di Produzione/Muletto o documentazione storica.
