# AppLogSolutionsWeb — Governance Cantiere

## Stato

SCOPE = CANTIERE ONLY

TARGET_FIREBASE_PROJECT = log-solutions-cantiere

TARGET_GIT_BRANCH = cantiere


## Principio di separazione

Questa directory governa esclusivamente l'ambiente Cantiere
di AppLogSolutionsWeb.

Le regole presenti qui NON modificano automaticamente
la governance della Produzione.


## Ambienti

### CANTIERE

Firebase Project:

log-solutions-cantiere

Stato:

AMBIENTE ATTIVO DI SVILUPPO, REFACTORING E COLLAUDO.

È l'unico ambiente modificabile durante l'attuale programma
di evoluzione architetturale.


### PRODUZIONE

Firebase Project:

log-solution-60007

Stato:

BASELINE STABILE E PROTETTA.

DIVIETO DI MODIFICA salvo ordine esplicito del Project Owner.

Le modifiche sperimentali del Cantiere NON devono essere propagate
automaticamente in Produzione.


### MULETTO

Firebase Project:

log-solution-muletto

Stato:

RISERVA DI EMERGENZA.

DIVIETO ASSOLUTO DI MODIFICA, DEPLOY, TEST O SINCRONIZZAZIONE.


### SVILUPPO LEGACY

Firebase Project storico:

log-solutions-sviluppo

Stato:

DISMESSO.

I riferimenti legacy saranno rimossi progressivamente
dal ramo Cantiere.


## Deploy Cantiere

Un push sul branch cantiere NON deve causare automaticamente deploy.

Il workflow GitHub del Cantiere è manual-only.

Ogni deploy deve essere:

- esplicito;
- indirizzato a log-solutions-cantiere;
- preferibilmente selettivo;
- preceduto da controlli;
- seguito da validazione.


## Produzione protetta

Qualsiasi comando Cantiere che utilizzi:

log-solution-60007

deve essere considerato un errore critico e causare STOP,
salvo ordine esplicito del Project Owner.


## Muletto protetto

Qualsiasi comando che utilizzi:

log-solution-muletto

deve causare STOP.


## Architettura Cantiere

Il backend Cantiere è in fase di modularizzazione.

Il modello corrente comprende:

main.py come Firebase gateway / entrypoint

e service specializzati:

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

oltre a:

core/
infrastructure/
ai_agents.py

Questa architettura è ancora in collaudo e NON deve essere considerata
automaticamente equivalente alla Produzione.


## Versionamento

Sono presenti due sistemi distinti:

bump_version.py
→ versione Frontend/PWA

bump_backend_version.py
→ versione Backend

Le procedure esistenti devono essere preservate salvo correzioni
esplicitamente approvate.


## Documentazione futura Cantiere

Questa directory ospiterà progressivamente:

AGENTS_CANTIERE.md
ARCHITECTURE_CANTIERE.md
OPERATIONS_CANTIERE.md
VERSIONING_CANTIERE.md
SECURITY_CANTIERE.md
UI_CANTIERE.md

e:

AI_BRIDGE/

Questi documenti NON devono essere creati automaticamente
in questa fase.


## Regola di promozione

Solo quando Cantiere sarà completamente collaudato:

CANTIERE
    ↓
AUDIT COMPLETO
    ↓
APPROVAZIONE PROJECT OWNER
    ↓
PROMOZIONE CONTROLLATA
    ↓
PRODUZIONE

La promozione potrà comprendere:

- codice;
- main.py;
- service/motori;
- frontend;
- Firebase configuration;
- documentazione;
- skill;
- procedure operative.

Prima di tale momento Produzione e Cantiere restano separati.


## AI Bridge

È prevista una futura directory:

CANTIERE_GOVERNANCE/AI_BRIDGE/

per la comunicazione controllata:

ChatGPT
↔ GitHub
↔ Antigravity

Non crearla ancora.

Prima devono essere definite e approvate
le regole di governance Cantiere.
