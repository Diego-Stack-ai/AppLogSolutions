# AGENTS_CANTIERE.md

## 1. Identità e Scope

SCOPE = CANTIERE ONLY

TARGET_BRANCH = cantiere

TARGET_FIREBASE_PROJECT = log-solutions-cantiere


## 2. Gerarchia Documentale Cantiere

Il documento deve dichiarare che:

PROJECT_MANIFEST.md
rimane la Source of Truth superiore di dominio.

La governance operativa specifica del Cantiere è definita da:

CANTIERE_GOVERNANCE/README_CANTIERE.md
CANTIERE_GOVERNANCE/AGENTS_CANTIERE.md

I documenti Produzione non devono essere riscritti per riflettere
lo stato sperimentale del Cantiere.


## 3. Protezione Ambienti

PRODUZIONE:
log-solution-60007

Regola:
READ ONLY salvo ordine esplicito del Project Owner.

MULETTO:
log-solution-muletto

Regola:
NO TOUCH ASSOLUTO.

SVILUPPO LEGACY:
log-solutions-sviluppo

Regola:
DISMESSO.


## 4. Identity Guard Obbligatorio

Prima di ogni operazione che modifica file:

verificare:

- repository root
- branch
- HEAD
- git status
- target Firebase se rilevante

Se branch != cantiere:
STOP.

Se target Firebase != log-solutions-cantiere:
STOP.


## 5. Scope Guard

Ogni comando deve dichiarare:

FILES_ALLOWED
FILES_FORBIDDEN
TARGET_PROJECT
TARGET_BRANCH

Ogni modifica fuori scope:
STOP.


## 6. No Implicit Actions

Vietato eseguire implicitamente:

git add
git commit
git push
firebase deploy
gcloud deploy
cancellazioni
migrazioni
modifiche dati cloud

Ogni azione deve essere autorizzata dalla fase corrente.


## 7. Diff Guard

Prima di ogni commit:

git diff
git diff --cached
git status --short

Devono risultare esclusivamente i file ammessi.


## 8. Test Guard

Una modifica non è valida solo perché compila.

Per Python backend:

py_compile è necessario ma NON sufficiente.

Quando pertinente eseguire anche:

- import test
- unresolved global symbol audit
- dependency audit
- smoke test
- parser-specific test
- regression test
- function discovery

Per frontend:

- syntax check
- console error check
- network error check
- auth flow
- PWA/service worker
- mobile behavior quando pertinente


## 9. Regola Refactoring / Modularizzazione

Durante estrazioni da main.py verso services/:

verificare SEMPRE:

- import persi
- costanti globali
- regex
- helper
- standard library imports
- Firebase globals
- Storage globals
- Firestore globals
- dipendenze service-to-service
- security checks
- exception namespaces

Un refactoring non è completato finché il nuovo modulo non è
staticamente e funzionalmente autosufficiente.


## 10. Architettura Backend Cantiere

Modello attuale:

main.py
= gateway / Firebase entrypoint / composition root

services/
= motori di business

core/
= helper e logica condivisa

infrastructure/
= Firebase e servizi infrastrutturali

ai_agents.py
= entrypoint/logica AI dedicata

Motori attuali:

admin_service.py
billing_service.py
cleanup_service.py
cost_service.py
driver_service.py
email_service.py
history_service.py
map_service.py
monitoring_service.py
operations_service.py
pdf_service.py
reporting_service.py
routing_service.py
tenant_service.py
traffic_service.py

La lista riflette la "current Cantiere architecture" (verificata su codice reale) e non è una verità eterna.


## 11. Cloud Functions

Le Cloud Functions rappresentano porte di ingresso.

Le Functions non sono equivalenti ai motori.

Relazione:

Frontend
-> Cloud Function
-> main.py wrapper
-> service
-> core/infrastructure
-> Firestore/Storage/API


## 12. Deploy Governance

Ogni deploy deve essere:

- manuale
- esplicito
- target:
  log-solutions-cantiere
- preferibilmente selettivo
- preceduto da test
- seguito da verifica post-deploy

Vietato usare implicitamente il Firebase project "default".

Usare sempre:

--project log-solutions-cantiere

Deploy completo Functions:

firebase deploy --only functions

NON deve essere usato durante fasi di collaudo selettivo
senza esplicita autorizzazione.


## 13. GitHub Workflow

Il workflow Cantiere deve rimanere manual-only.

Un push sul branch cantiere:

NON DEVE CAUSARE DEPLOY AUTOMATICO.


## 14. Versionamento

Preservare:

bump_version.py
bump_backend_version.py

Non modificare questi script senza fase dedicata.

Frontend e backend hanno versionamenti separati.

Bump:
NON implica commit.
NON implica push.
NON implica deploy.


## 15. Sicurezza

Preservare e verificare quando pertinente:

- Firebase Auth
- req.auth
- UID
- RBAC
- tenant isolation
- App Check
- CORS
- Firestore Rules
- Storage Rules
- operazioni distruttive
- input validation

Un refactoring non può ridurre i controlli di sicurezza.


## 16. Multi-Tenant

Nessun tenant deve diventare fallback implicito.

DNR non deve diventare tenant root automatico.

Preservare isolamento tenant e data lineage.


## 17. Produzione

Le modifiche Cantiere NON devono essere propagate automaticamente
alla Produzione.

La Produzione può essere analizzata in READ ONLY per confronto,
ma non modificata.


## 18. Muletto

Muletto = riserva di emergenza.

Qualunque comando che punti a:

log-solution-muletto

deve causare STOP.


## 19. Legacy Sviluppo

log-solutions-sviluppo è dismesso.

File e riferimenti legacy potranno essere rimossi in fasi dedicate.

Non deve essere usato per nuovi test o deploy.


## 20. Reporting Obbligatorio

Ogni fase tecnica deve terminare con report strutturato contenente almeno:

REPO_ROOT
BRANCH
HEAD_BEFORE
HEAD_AFTER se applicabile
FILES_CHANGED
TESTS_EXECUTED
TEST_RESULTS
COMMIT_EXECUTED
PUSH_EXECUTED
DEPLOY_EXECUTED
TARGET_PROJECT
PRODUCTION_CHANGED
MULETTO_CHANGED
SAFE_TO_PROCEED


## 21. Stop Gate

Se:

- branch errato
- progetto Firebase errato
- file inattesi
- test falliti
- diff inatteso
- produzione coinvolta
- muletto coinvolto
- dipendenza non compresa
- requisito ambiguo

=> STOP.

Non tentare correzioni autonome fuori scope.


## 22. AI_BRIDGE

AI_BRIDGE sarà creato in una fase successiva.

Quando esisterà:

- opererà solo su Cantiere
- COMMAND.md non potrà autorizzare Produzione o Muletto
- REPORT.md dovrà riportare le guardie
- nessun comando AI_BRIDGE potrà bypassare AGENTS_CANTIERE.md
