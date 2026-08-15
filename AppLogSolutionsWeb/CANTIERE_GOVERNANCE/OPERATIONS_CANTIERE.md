# AppLogSolutionsWeb — Operations Cantiere

## 1. Scope
Questo documento regola ESCLUSIVAMENTE le operazioni del `cantiere` (`log-solutions-cantiere`). Definisce le procedure operative per garantire un ambiente di sviluppo/collaudo sicuro, isolato e controllato, derivando dai principi generali senza alterare la documentazione di Produzione.

## 2. Ambienti
- **Cantiere (`log-solutions-cantiere`)**: Ambiente di sviluppo e validazione. TARGET ESCLUSIVO di questo documento.
- **Produzione (`log-solution-60007`)**: READ ONLY. Divieto assoluto di modifica.
- **Muletto (`log-solution-muletto`)**: NO TOUCH ASSOLUTO. Riserva di emergenza.
- **Sviluppo Legacy (`log-solutions-sviluppo`)**: DISMESSO.

## 3. Git Guard
Ogni operazione deve essere preceduta da un controllo di identità (Identity Guard):
- Verificare la root del repository (`git rev-parse --show-toplevel`).
- Verificare il branch corrente (`git branch --show-current`). DEVE ESSERE `cantiere`.
- Verificare l'HEAD corrente (`git rev-parse HEAD`).
- Verificare lo stato del repository (`git status --short`).

## 4. Versionamento
Regola fondamentale: **VERSION BUMP != COMMIT != PUSH != DEPLOY**
- **`bump_version.py`**: Incrementa la versione del frontend. Legge `APP_VERSION` da `frontend/script.js`, aggiorna la versione (logica 6.xxx), e aggiorna `sw.js` (`log-solution-vX`) e tutti i file HTML/JS (aggiungendo `?v=X` per il cache busting, usando fallback encoding cp1252 se utf-8 fallisce). NON fa commit, push o deploy.
- **`bump_backend_version.py`**: Incrementa la versione del backend. Legge `return {"version": "X"}` da `functions/main.py`, calcola il bump patch/minor e lo sovrascrive. NON fa commit, push o deploy.

## 5. Pre-deploy
Prima di effettuare un deploy sul Cantiere, eseguire:
1. Identity Guard
2. Branch check (`cantiere`)
3. HEAD check
4. `git status` check
5. Target project check (`log-solutions-cantiere`)
6. Static compile (es. `python -m py_compile`)
7. Import test locale
8. Dependency audit (es. verifica `unresolved globals`)
9. Function discovery (elenco di cosa sta per cambiare)
10. Diff scope
11. Eventuale backup/snapshot
12. GO/NO-GO

*Nota: per le Functions Python, il `py_compile` è necessario ma NON sufficiente. Se un modulo viene refactorizzato, sono obbligatori import test, controllo globals, dependency audit, smoke test e regressione specifica.*

## 6. Deploy selettivo
**PREFERIRE DEPLOY SELETTIVO** durante il collaudo.
Esempio:
`firebase deploy --project log-solutions-cantiere --only functions:NOME_FUNZIONE`
Deploy multiplo selettivo ammesso solo dichiarando esplicitamente le funzioni modificate.

## 7. Full deploy
Il deploy completo delle funzioni (`firebase deploy --project log-solutions-cantiere --only functions`) è classificato come **HIGH IMPACT**.
Richiede esplicita autorizzazione prima dell'esecuzione.

## 8. GitHub workflow
Il workflow `deploy-cantiere.yml` è impostato su `workflow_dispatch` (MANUAL FULL DEPLOY).
- **PUSH_BRANCH_CANTIERE != DEPLOY**
- Non deve essere usato durante test selettivi, salvo esplicita autorizzazione.

## 9. Cloud Shell
Prima di usare i tool CLI:
- Eseguire: `gcloud config set project log-solutions-cantiere`
- Verificare: `gcloud config get-value project`
Se l'output è diverso da `log-solutions-cantiere`, **STOP**.

## 10. CORS
Il test CORS standard per il Cantiere si esegue via curl, puntando agli URL Cantiere e all'Origin del Cantiere:
```bash
curl -i -X OPTIONS \
  'https://europe-west1-log-solutions-cantiere.cloudfunctions.net/FUNCTION_NAME' \
  -H 'Origin: https://log-solutions-cantiere.web.app' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type,authorization,x-firebase-appcheck'
```
Esito corretto deve contenere: `access-control-allow-origin: https://log-solutions-cantiere.web.app`

## 11. Logging
La lettura dei log via gcloud va effettuata filtrando specificamente per servizio.
Esempio:
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="SERVICE_NAME"' \
  --project log-solutions-cantiere
```
- Filtrare per timestamp
- Cercare "ERROR" e leggere lo `stderr`
- Correlare richieste POST e OPTIONS
- Non fermarsi solo all'HTTP status.

## 12. Post-deploy
Dopo ogni deploy, verificare la stabilità tramite i seguenti passi standard:
1. Verificare l'esito: "Successful update operation"
2. Controllare la revisione Cloud Run
3. Verificare `latestReadyRevision == latestCreatedRevision`
4. Traffico = 100% sulla nuova revisione
5. Controllo log di startup
6. Test OPTIONS/CORS (se callable web)
7. Test reale frontend
8. Console F12 per errori JS
9. Tab Network per status code HTTP
10. Cloud Logging backend
11. Functional smoke test
12. Esito finale: GO/ROLLBACK

## 13. Rollback
Sono definiti due livelli di rollback, nessuno dei quali deve mai toccare l'ambiente di Produzione:
- **A. SELECTIVE ROLLBACK (Preferito)**: se il problema riguarda singole funzioni.
- **B. FULL BACKEND ROLLBACK**: solo per guasti sistemici.
Ogni rollback necessita di: baseline nota, hash/commit, target `log-solutions-cantiere` esplicito e test post-rollback.

## 14. Backup
Prima di operazioni ad alto impatto (migrazioni, cancellazioni massive, import, refactoring critici, modifica regole o full deploy), valutare un backup strategico.
Tipi di backup:
- CODE BACKUP
- DATA BACKUP
- FIRESTORE EXPORT
- STORAGE BACKUP
- CONFIG SNAPSHOT

## 15. Operazioni distruttive
Operazioni quali `elimina_giornata_logistica`, archiviazioni mensili, pulizia massiva, cancellazione dati Firestore o Storage richiedono:
- Esplicita autorizzazione
- Target Cantiere verificato preventivamente
- Esecuzione in modalità dry-run (ove possibile)
- Backup preventivo (se necessario)
- Scope d'azione ben delimitato
- Produzione log/report finale

## 16. Legacy sviluppo
L'ambiente `log-solutions-sviluppo` è dismesso.
Script come `deploy_dev.ps1` e `sincronizza_sviluppo.py` sono classificati come **LEGACY / TO BE REMOVED FROM CANTIERE**.
NON usarli. NON eliminarli in questa fase.

## 17. Produzione/Muletto
Come da Scope, **Produzione** (`log-solution-60007`) è **READ ONLY** e **Muletto** (`log-solution-muletto`) è **NO TOUCH**.
Qualsiasi comando operativo che includa questi project ID deve causare lo **STOP** immediato del processo, salvo autorizzazione esplicita futura da parte del Project Owner.

## 18. Standard reporting
Ogni operazione rilevante deve includere un report con:
- REPO_ROOT
- BRANCH
- HEAD_BEFORE
- HEAD_AFTER
- TARGET_PROJECT
- FILES_CHANGED
- TESTS_EXECUTED
- TEST_RESULTS
- FUNCTIONS_DEPLOYED
- REVISION_BEFORE
- REVISION_AFTER
- CORS_STATUS
- LOG_STATUS
- FRONTEND_TEST_STATUS
- COMMIT_EXECUTED
- PUSH_EXECUTED
- DEPLOY_EXECUTED
- PRODUCTION_CHANGED
- MULETTO_CHANGED
- SAFE_TO_PROCEED

## 19. Stop conditions
Qualsiasi discrepanza in: Branch, HEAD, Project ID, o errori nel Pre/Post Deploy check, causa l'interruzione immediata dell'operatività (STOP) finché non viene diagnosticata e autorizzata la ripresa.

## 20. Promotion toward Production
Nessun artefatto dal Cantiere verrà promosso alla Produzione senza aver soddisfatto la validazione end-to-end, i test completi dei refactoring architetturali, l'assenza di proxy helper residui (nei limiti del target design) e l'approvazione esplicita al deployment formale.
