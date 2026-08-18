# 📜 Costituzione Operativa degli Agenti AI per AppLogSolutionsWeb (AGENTS.md)

---

## 🛡️ 0.1 BOOTSTRAP VERIFICABILE E GERARCHIA ASSOLUTA DELLE FONTI

La documentazione del progetto è governata dal principio del **BOOTSTRAP VERIFICABILE**. La lettura dei 5 documenti Core non è soltanto obbligatoria, ma deve essere **DIMOSTRABILE** prima di qualsiasi attività (analisi, modifica, review, test o deploy).

### 🏆 Gerarchia Assoluta delle Fonti
Se due documenti risultano in conflitto, prevale tassativamente la fonte di livello superiore:
1. **[`README.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/README.md)** (Livello 1 — Core)
2. **[`AGENTS.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/AGENTS.md)** (Livello 1 — Core)
3. **[`DOMAIN_MODEL.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/DOMAIN_MODEL.md)** (Livello 1 — Core)
4. **[`ARCHITECTURE.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/ARCHITECTURE.md)** (Livello 1 — Core)
5. **[`OPERATIONS.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/OPERATIONS.md)** (Livello 1 — Core)
6. **Documentazione Specialistica** (Livello 2 — Consultabile solo all'occorrenza)

---

## 📋 0.2 SCHEDA DI BOOTSTRAP REPORT (OBBLIGATORIA PRE-ATTIVITÀ)

Prima di svolgere qualsiasi attività sul codice o sulla documentazione, l'Agente AI DEVE produrre in output il seguente report:

```text
==================================================
BOOTSTRAP REPORT
==================================================
README.md:               [ LETTO ]
AGENTS.md:               [ LETTO ]
DOMAIN_MODEL.md:         [ LETTO ]
ARCHITECTURE.md:         [ LETTO ]
OPERATIONS.md:           [ LETTO ]

Contesto Core costruito:  [ SI ]

Attività richiesta:
[ descrizione sintetica ]

Documentazione specialistica necessaria:
[ elenco documenti ]

Motivazione della consultazione:
[ spiegazione ]
==================================================
```

---

## 🚨 0.3 PRINCIPIO DI PROMOZIONE DELLA CONOSCENZA

Se durante un'attività l'Agente scopre che una conoscenza fondamentale esiste soltanto in un documento specialistico oppure non è documentata, **DEVE INTERROMPERE L'ATTIVITÀ** e produrre il seguente avviso:

```text
==================================================
ATTENZIONE — PROMOZIONE CONOSCENZA RICHIESTA
==================================================
È stata individuata una conoscenza fondamentale non presente nella Documentazione Core.

Documento sorgente:
[...]

Si propone di aggiornare:
[ README.md | AGENTS.md | DOMAIN_MODEL.md | ARCHITECTURE.md | OPERATIONS.md ]
prima di proseguire con l'implementazione.
==================================================
```

---

## 📊 0.4 DOCUMENTATION GOVERNANCE CHECK (OBBLIGATORIO POST-ATTIVITÀ)

Al termine di ogni attività documentale o di codice, l'Agente DEVE produrre automaticamente il seguente riepilogo:

```text
==================================================
DOCUMENTATION GOVERNANCE CHECK
==================================================
Bootstrap eseguito:                     [ SI / NO ]
Documenti Core letti:                   [ elenco ]
Documentazione specialistica consultata: [ elenco ]
Nuove conoscenze individuate:           [ elenco ]
Conoscenze da promuovere nei Core:      [ elenco ]
Conflitti documentali rilevati:         [ elenco ]
Documentazione aggiornata:              [ elenco ]
Codice modificato:                      [ SI / NO ]
Deploy:                                 NO
Commit:                                 NO
Push:                                   NO
==================================================
```

---

## ⚖️ 0.5 PRINCIPIO DI PROPORZIONALITÀ E LIVELLI DI INTERVENTO

La profondità della procedura documentale deve essere sempre **proporzionata al rischio dell'intervento**. La Governance garantisce la massima qualità e coerenza, ma **non deve trasformarsi in burocrazia né rallentare inutilmente attività semplici**.

### 🚥 Tabella dei Livelli di Intervento

```text
┌───────────┬──────────────────────────────────────────┬────────────────────────────────────────────────────────┐
│ LIVELLO   │ TIPOLOGIA INTERVENTO                    │ PROCEDURA DOCUMENTALE RICHIESTA                       │
├───────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ LIVELLO A │ Interventi Minimi                       │ ✓ Bootstrap Core                                       │
│           │ (CSS, testi, icone, piccoli bug UI)      │ ✓ Lettura specialistica solo se necessaria             │
│           │                                          │ ✓ Governance Check sintetico                          │
├───────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ LIVELLO B │ Interventi Applicativi                   │ ✓ Bootstrap Core                                       │
│           │ (Nuove pagine, JS significativo,         │ ✓ Documentazione specialistica pertinente              │
│           │  query Firestore, nuove schermate)       │ ✓ Bootstrap Report + Governance Check completo         │
├───────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ LIVELLO C │ Interventi Architetturali                │ ✓ Bootstrap Core + Tutta la specialistica pertinente  │
│           │ (Cloud Functions, Storage, Offline,      │ ✓ Bootstrap Report completo + Governance Check         │
│           │  Multi-Tenant, Routing, Parser, Refactor)│ ✓ Verifica coerenza con ARCHITECTURE.md & DOMAIN_MODEL │
├───────────┼──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ LIVELLO D │ Interventi Strategici                    │ ✓ Bootstrap Completo + Consultazione totale            │
│           │ (Modifica Architettura, Modello Dominio, │ ✓ Analisi d'Impatto + Aggiornamento Documenti Core     │
│           │  Governance, DDD, Pipeline Dati)        │ ✓ Nuova ADR (Architectural Decision Record) PRIMA      │
└───────────┴──────────────────────────────────────────┴────────────────────────────────────────────────────────┘
```

### 💡 Principio di Semplicità
L'Agente AI deve sempre scegliere il **livello minimo necessario** in base alla natura dell'attività.  
È espressamente **VIETATO** applicare la burocrazia di Livello C o D ad attività semplici che rientrano nel Livello A.



> **Fonte Autorevole Primaria e Vincolante del Progetto `AppLogSolutionsWeb v3.00`**  
> **Ultimo Aggiornamento**: Luglio 2026 (Versione 4.1 - Costituzione 21 Sezioni)


---

## 🔒 0.6 POLITICA DI STABILITÀ DELLA GOVERNANCE ED STATO UFFICIALE

La Governance Documentale rappresenta la **Costituzione Operativa del progetto AppLogSolutionsWeb**. Una volta approvata, **NON DEVE ESSERE MODIFICATA** durante le normali attività di sviluppo quotidiano.

### 📌 Stato Ufficiale della Governance
```text
==================================================
STATO DELLA GOVERNANCE: STABILE
==================================================
```

I 3 stati possibili per la Governance sono:
1. `IN COSTRUZIONE`: Fase iniziale di stesura delle regole.
2. `STABILE`: Fase attiva di produzione e sviluppo normale (**STATO ATTUALE**).
3. `IN REVISIONE STRAORDINARIA`: Modifica concordata per cause eccezionali.

### 🚨 Le 5 Condizioni Tassative per Modificare la Governance
Qualsiasi proposta di modifica alla Governance è considerata **Revisione Straordinaria** ed è consentita **ESCLUSIVAMENTE** al verificarsi di almeno una delle seguenti 5 condizioni:
1. **Nuova Famiglia di Funzionalità**: Introduzione di moduli che alterano il modello operativo del progetto.
2. **Cambio Architetturale Generale**: Modifiche profonde alla struttura dell'applicazione o dei servizi cloud.
3. **Nuovo Principio DDD**: Introduzione di un nuovo Bounded Context o principio di Domain-Driven Design.
4. **Nuovo Paradigma Tecnologico**: Adozione di una nuova piattaforma, orchestratore o architettura AI.
5. **Lacuna Bloccante**: Individuazione di una falla normativa che rende impossibile svolgere le attività future.

In tutti gli altri casi, la Governance è **STABILE** e gli Agenti AI devono utilizzarla senza proporre continuamente nuove regole o burocrazia.

---

## 🛑 0. GOVERNANCE DOCUMENTALE E PROTOCOLLO DI BOOTSTRAP OBBLIGATORIO

La documentazione del progetto è strutturata su due livelli trasparenti:

### 🔴 LIVELLO 1: DOCUMENTAZIONE CORE (OBBLIGATORIA)
Prima di svolgere qualsiasi attività, ogni Agente AI DEVE leggere integralmente i 5 documenti Core nel seguente ordine sequenziale:
1. **[`README.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/README.md)**: Porta d'ingresso e Mappa di Bootstrap.
2. **[`AGENTS.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/AGENTS.md)**: Costituzione Operativa, Governance, Deploy e Git.
3. **[`DOMAIN_MODEL.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/DOMAIN_MODEL.md)**: Linguaggio Ubiquo (DDD), Definizioni di Dominio e Modello Dati.
4. **[`ARCHITECTURE.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/ARCHITECTURE.md)**: Blueprint Architetturale Tecnico.
5. **[`OPERATIONS.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/OPERATIONS.md)**: Procedure Operative, Workflow, Backup e Disaster Recovery.

### 🟡 LIVELLO 2: DOCUMENTAZIONE SPECIALISTICA (CONSULTABILE ALL'OCCORRENZA)
La documentazione specialistica (`frontend/docs/`, `.agent/workflows/`, `dr_system/`) deve essere consultata **esclusivamente DOPO** aver letto la documentazione Core e solo per le aree pertinenti alla richiesta dell'utente.

> [!CAUTION]
> **DIVIETO DI ASSUNZIONE E LETTURA PARZIALE**:  
> È vietato iniziare modifiche al codice dopo aver letto solo documentazione specialistica.  
> È vietato considerare come "fonte autorevole" un documento specialistico se la documentazione Core stabilisce diversamente.

---

## 📑 INDICE GENERALE

1. [Autorità e scopo](#1-autorità-e-scopo)
2. [Identità del progetto e proprietà dei dati](#2-identità-del-progetto-e-proprietà-dei-dati)
3. [Separazione Dev/Produzione](#3-separazione-devproduzione)
4. [Modalità operative](#4-modalità-operative)
5. [Autorizzazioni separate](#5-autorizzazioni-separate)
6. [Lavoro obbligatorio per fasi](#6-lavoro-obbligatorio-per-fasi)
7. [Divieto di decisioni architetturali autonome](#7-divieto-di-decisioni-architetturali-autonome)
8. [Classificazione delle attività ad alto rischio](#8-classificazione-delle-attività-ad-alto-rischio)
9. [Backup obbligatori](#9-backup-obbligatori)
10. [Git e branch](#10-git-e-branch)
11. [Bump versione](#11-bump-versione)
12. [Deploy selettivo Dev](#12-deploy-selettivo-dev)
13. [Deploy selettivo Produzione](#13-deploy-selettivo-produzione)
14. [Firebase e target espliciti](#14-firebase-e-target-espliciti)
15. [Script con accesso alla produzione](#15-script-con-accesso-alla-produzione)
16. [Governance multi-tenant](#16-governance-multi-tenant)
17. [Test](#17-test)
18. [Rollback](#18-rollback)
19. [Scheda operativa](#19-scheda-operativa)
20. [Report conclusivo](#20-report-conclusivo)
21. [Allegato comandi autorizzati](#21-allegato-comandi-autorizzati)

---

## 1. AUTORITÀ E SCOPO

```text
AGENTS.md è la fonte autorevole primaria per qualsiasi agente AI,
strumento automatico o operatore tecnico che lavori sul progetto AppLogSolutionsWeb.

In caso di conflitto con altri documenti Markdown, istruzioni locali,
workflow o commenti nel codice, prevale AGENTS.md fino a revisione
esplicita approvata dall'utente.
```

Tutti gli altri documenti operativi presenti nel repository (inclusi quelli nelle cartelle `.agent/` e `docs/`) devono rinviare ad `AGENTS.md` e non possono contenere o mantenere procedure contraddittorie o prive di vincoli di sicurezza.

---

## 2. IDENTITÀ DEL PROGETTO E PROPRIETÀ DEI DATI

### 2.1 Azienda Proprietaria e Ruolo del Vettore
**Loge Solution** è la società proprietaria dell'applicazione web e gestisce il servizio logistico come vettore operativo. Loge Solution è:
* Proprietaria dei mezzi di trasporto e delle targhe;
* Datore di lavoro degli autisti e responsabile del personale;
* Responsabile di presenze, giustificativi, ferie, malattie e ruoli utente;
* Gestore di magazzini, sedi aziendali, cassa e amministrazione;
* Proprietaria della pianificazione dei viaggi operativi finali.

### 2.2 Committenti (Tenants)
I committenti (es. **DNR, CATTEL, GRAN CHEF, BAUER, HOTEL**) sono i clienti aziendali che affidano a Loge Solution la merce ed i punti di consegna. I committenti forniscono:
* DDT, punti di consegna, codici cliente, articoli, colli, peso, note e orari;
* File sorgente PDF, Excel (XLSX), TXT o altri formati;
* Dati commerciali e regole di listino specifiche.

### 2.3 Distinzione Obbligatoria del Modello Dati

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         TASSONOMIA DEL CONTESTO OPERATIVO                        │
├──────────────────────────────────────────────────────────────────────────────────┤
│ 1. tenantId              : "DNR" | "CATTEL" | "GRAN CHEF" | "BAUER"               │
│ 2. sourceChannel         : "FRUTTA" | "LATTE" | "EXCEL_CATTEL" | "EXCEL_GRAN_CHEF"  │
│ 3. zonaLogistica         : "ZONA 1" | "ZONA 2" | "CATTEL MESTRE" | "PADOVA CENTRO"│
│ 4. puntoDiConsegna       : Destinazione fisica (Indirizzo/GPS)                   │
│ 5. viaggioIniziale       : Raggruppamento o giro proposto dal committente        │
│ 6. viaggioOperativoFinale: Itinerario reale ottimizzato ed assegnato al mezzo    │
│ 7. documento             : DDT originale o foglio segnaposto (Placeholder)       │
│ 8. servizioFatturabile   : Corrispettivo calcolato per committente/viaggio       │
└──────────────────────────────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **Modellazione DNR**: `DNR_LATTE` e `DNR_FRUTTA` **non sono tenant distinti**.
> Il modello atteso è `tenantId = "DNR"` con `sourceChannel = "LATTE"` o `sourceChannel = "FRUTTA"`.

Un viaggio operativo finale potrà in futuro contenere consegne di committenti diversi (viaggi misti), ma ogni singola fermata dovrà mantenere la propria provenienza originaria (`tenantId` per fermata).

---

## 3. SEPARAZIONE DEV/PRODUZIONE

```text
SVILUPPO  : log-solutions-cantiere   (Database, Storage, Auth, Functions, Hosting)
PRODUZIONE: log-solution-60007       (Database, Storage, Auth, Functions, Hosting)
```

1. **Separazione Dati**: Firestore e Cloud Storage sono su istanze GCP fisicamente distinte.
2. **Codice Sorgente Comune**: Il codice locale e `functions/main.py` sono comuni a entrambi gli ambienti.
3. **Principio di Impatto**:
   * Modificare il codice locale non modifica nessun ambiente.
   * Il deploy Dev modifica solo Dev (`log-solutions-cantiere`).
   * Il deploy Prod modifica solo Prod (`log-solution-60007`).

> [!CAUTION]
> **AVVISO RISCHIO PROJECT DEFAULT (`.firebaserc`)**:  
> In `.firebaserc`, il progetto `"default"` è impostato su **`log-solution-60007` (PRODUZIONE)**.  
> Un comando `firebase deploy` lanciato senza `--project` colpirà di default la PRODUZIONE!

---

## 4. MODALITÀ OPERATIVE

L'agente AI deve operare selezionando esplicitamente una delle 5 modalità seguenti:

### 4.1 MODALITÀ 1 — ANALISI (Read-Only)
* **Consentito**: Leggere file, cercare riferimenti, produrre audit, individuare rischi, creare diagrammi e piani.
* **Vietato**: Modificare file, eseguire script di scrittura, fare commit, push o deploy.
* **Output Obbligatorio**:
  ```text
  Analisi conclusa | File coinvolti | Problemi individuati | Rischi | Decisioni richieste | Nessuna modifica eseguita
  ```

### 4.2 MODALITÀ 2 — PIANIFICAZIONE (Design & Docs)
* **Consentito**: Produrre piani esecutivi, definire fasi, proporre test e rollback, classificare rischi in artefatti.
* **Vietato**: Modificare codice sorgente, eseguire deploy o migrazioni dati.
* **Output Obbligatorio**: Artefatto `implementation_plan.md` con criteri di ingresso/uscita, perimetro e approvazione richiesta.

### 4.3 MODALITÀ 3 — IMPLEMENTAZIONE (Local Code Editing)
* **Consentito**: Modificare esclusivamente i file approvati, eseguire test locali, mostrare diff.
* **Vietato**: Bump versione, commit, push, deploy, modifiche in produzione o migrazioni dati senza autorizzazione separata.
* **Output Obbligatorio**:
  ```text
  File modificati | Diff sintetico | Test eseguiti | Rischi residui | Rollback | Attendo autorizzazione per fase successiva
  ```

### 4.4 MODALITÀ 4 — COLLAUDO DEV (Dev Deploy & Testing)
* **Consentito**: Deploy selettivo **esclusivamente su Sviluppo** (`log-solutions-cantiere`), test su Firebase Dev, collaudo Hosting e Functions Dev.
* **Vietato**: Operazioni su Produzione, push su `main`, script con credenziali Prod.

### 4.5 MODALITÀ 5 — RILASCIO PRODUZIONE (Prod Deploy)
* **Consentito soltanto dopo**: Richiesta inequivocabile dell'utente contenente le parole "Produzione", collaudo Dev completato, branch idoneo, versione approvata, riepilogo diff, backup confermato e conferma finale del `PROJECT ID: log-solution-60007`.

---

## 5. AUTORIZZAZIONI SEPARATE

```text
Analisi, modifica codice, bump, commit, push e deploy
sono azioni distinte e richiedono autorizzazioni distinte.
```

* *"Analizza"* ➔ **NON autorizza** modifiche al codice.
* *"Modifica"* ➔ **NON autorizza** commit.
* *"Aggiorna la versione"* ➔ **NON autorizza** commit, push o deploy.
* *"Commit"* ➔ **NON autorizza** push.
* *"Push"* ➔ **NON autorizza** deploy.
* *"Deploy Dev"* ➔ **NON autorizza** Produzione.
* *"Deploy Hosting"* ➔ **NON autorizza** Cloud Functions.
* *"Deploy Functions"* ➔ **NON autorizza** Rules.
* *"Procedi"* o *"Vai avanti"* ➔ **NON autorizza** la Produzione.

Dopo il completamento di ciascun passaggio, l'agente DEVE FERMARSI ed attendere indicazioni.

---

## 6. LAVORO OBBLIGATORIO PER FASI

```text
L'AGENTE È OBBLIGATO A LAVORARE PER FASI SUCCESSIVE.
```

Una fase non può iniziare finché:
1. La fase precedente non è conclusa e documentata;
2. Il risultato ed i diff non sono stati mostrati;
3. I rischi residui non sono stati esplicitati;
4. L'utente non ha approvato l'avvio della fase successiva.

Per attività complesse si applica la sequenza:  
`Analisi ➔ Piano ➔ Approvazione ➔ Implementazione ➔ Test ➔ Collaudo Dev ➔ Approvazione ➔ Rilascio Prod`.

---

## 7. DIVIETO DI DECISIONI ARCHITETTURALI AUTONOME

```text
UN AGENTE NON PUÒ PRENDERE AUTONOMAMENTE
DECISIONI ARCHITETTURALI IRREVERSIBILI.
```

L'agente **può**: Proporre soluzioni, confrontare alternative, evidenziare rischi, preparare piani dettagliati.  
L'agente **NON può senza approvazione esplicita**:
* Modificare la struttura del database Firestore o spostare collezioni;
* Cambiare i path di Cloud Storage o la struttura delle cartelle;
* Alterare il modello dei tenant o rimuovere fallback esistenti;
* Trasformare dati globali in tenant-specifici (o viceversa);
* Modificare il modello dati dei viaggi o delle fermate;
* Eliminare o migrare dati di produzione;
* Modificare Security Rules, Authentication o workflow CI/CD.

---

## 8. CLASSIFICAZIONE DELLE ATTIVITÀ AD ALTO RISCHIO

Le seguenti attività sono classificate ad **ALTO RISCHIO**:
* Modifiche a `functions/main.py` o architettura Cloud Functions;
* Modifiche a Firestore, Storage, Security Rules o Auth;
* Modifiche a `.firebaserc`, `firebase.json` o GitHub Actions;
* Migrazioni dati, script di sincronizzazione o cancellazioni massive;
* Modifiche al motore dei viaggi o della fatturazione.

---

## 9. BACKUP OBBLIGATORI

Requisiti di backup obbligatori per tipo di risorsa:
* **Modifiche Codice**: Working tree pulito, commit stabile di riferimento e strategia `git revert`.
* **Modifiche Firestore**: Backup/export verificato, conteggio documenti e procedura di ripristino.
* **Modifiche Storage**: Inventario oggetti (path, dimensioni, hash SHA-256) e conservazione degli originali.
* **Modifiche Rules**: Versione precedente salvata e test su Firebase Emulator.
* **Modifiche Functions**: Backup dell'intera directory `functions/` (main, moduli, requirements).

L'agente non può mai dichiarare *"rischio zero"* o *"rollback garantito"* senza evidenza verificabile.

---

## 10. GIT E BRANCH

```text
Durante sviluppo, refactoring e collaudo
non lavorare direttamente sul branch main.
```

### Regole di Branching:
1. Usare sempre un branch dedicato (es. `dev` o `feature/nome-task`).
2. Mostrare `git status` e `git diff` prima di ogni commit.

### Avviso Critico Push su Main:
> [!CAUTION]
> **AVVISO CRITICO GITHUB ACTIONS**:  
> Un `git push` sul branch `main` attiva il workflow `.github/workflows/deploy.yml` che **distribuisce automaticamente l'Hosting di PRODUZIONE (`log-solution-60007`)**.

Prima di qualsiasi push su `main`, l'agente deve mostrare:
```text
ATTENZIONE: Il push sul branch main distribuirà l'Hosting di PRODUZIONE (log-solution-60007).
Branch: main | Commit: [SHA] | Workflow: deploy.yml | Progetto Target: log-solution-60007
```
Ed attendere conferma esplicita dopo aver mostrato questo avviso.

---

## 11. BUMP VERSIONE

I concetti di **bump versione**, **commit**, **push** e **deploy** sono **QUATTRO AZIONI SEPARATE**.

> [!WARNING]
> La frase dell'utente *"aggiorna la versione"* autorizza **ESCLUSIVAMENTE la Fase A (Bump locale e test)**, NON autorizza commit, push o deploy.

### Fase A — Bump (Autorizzato da "aggiorna la versione"):
1. Dichiarare versione attuale, nuova versione, branch, ambiente target e project ID.
2. Eseguire `python bump_version.py`.
3. Eseguire i test locali.
4. Mostrare `git status`.
5. Mostrare il riepilogo `git diff`.
6. **🛑 STOP (Fermarsi ed attendere autorizzazioni esplicite separate per la Fase B)**.

### Fase B — Commit:
* Eseguibile solo dopo autorizzazione esplicita al commit.

### Fase C — Push:
* Eseguibile solo dopo autorizzazione al push e verifica dei workflow attivati.

### Fase D — Deploy:
* Eseguibile solo dopo autorizzazione separata ed esplicita sul progetto target.

---

## 12. DEPLOY SELETTIVO DEV

Il deploy completo `firebase deploy --project log-solutions-cantiere` è classificato come **OPERAZIONE ECCEZIONALE AD ALTO RISCHIO**.

La procedura standard per lo sviluppo utilizza **esclusivamente deploy selettivi**:

```bash
# Frontend Sviluppo
firebase deploy --only hosting --project log-solutions-cantiere

# Backend Cloud Functions Sviluppo
firebase deploy --only functions --project log-solutions-cantiere

# Firestore Rules Sviluppo
firebase deploy --only firestore:rules --project log-solutions-cantiere

# Storage Rules Sviluppo
firebase deploy --only storage --project log-solutions-cantiere
```

---

## 13. DEPLOY SELETTIVO PRODUZIONE

La produzione non deve MAI essere aggiornata automaticamente. La procedura standard per la Produzione utilizza **esclusivamente deploy selettivi**:

```bash
# Frontend Produzione
firebase deploy --only hosting --project log-solution-60007

# Backend Cloud Functions Produzione
firebase deploy --only functions --project log-solution-60007

# Firestore Rules Produzione
firebase deploy --only firestore:rules --project log-solution-60007

# Storage Rules Produzione
firebase deploy --only storage --project log-solution-60007
```

---

## 14. FIREBASE E TARGET ESPLICITI

Ogni comando Firebase CLI DEVE contenere il flag esplicito `--project <PROJECT_ID>`.

```text
OPERAZIONE ECCEZIONALE AD ALTO RISCHIO: Deploy Completo
```

Il comando `firebase deploy --project <PROJECT_ID>` senza `--only` è consentito soltanto previa autorizzazione contenente le parole "deploy completo", il `PROJECT_ID` esplicito e l'elenco dei componenti coinvolti.

```text
Riconfigurazione Motore Cloud Functions:
firebase deploy --only functions --project log-solutions-cantiere
firebase deploy --only functions --project log-solution-60007
```

---

## 15. SCRIPT CON ACCESSO ALLA PRODUZIONE

Durante qualsiasi lavoro sull'ambiente di Cantiere è **TASSATIVAMENTE VIETATO** eseguire:
* Script che caricano `prod_key.json`;
* Script che inizializzano Sviluppo e Produzione contemporaneamente;
* Script di sincronizzazione (`sincronizza_sviluppo.py`, `sincronizza_totale.py`, `sincronizza_cache_distanze.py`);
* Script diagnostici con capacità di scrittura (`indaga_mezzo.py`, `investiga_distinta.py`);
* Endpoint HTTP assoluti di produzione (`https://europe-west1-log-solution-60007.cloudfunctions.net/...`);
* Comandi `gcloud` o `firebase` rivolti alla produzione.

---

## 16. GOVERNANCE MULTI-TENANT

* **DNR non è il tenant radice** o il committente proprietario dell'app;
* **Nessun fallback automatico a DNR** (`|| 'DNR'` o `req.data.get("tenant", "DNR")`) deve essere introdotto in nuovo codice;
* **`tenantId`**, **`sourceChannel`** e **`zonaLogistica`** sono tre concetti distinti;
* **DNR Latte e Frutta** sono canali dello stesso tenant (`tenantId = "DNR"`);
* **I dati globali aziendali** (autisti, mezzi, presenze) non vanno salvati sotto la sottocollezione `clienti/DNR/`;
* **Nessuna sostituzione massiva** di stringhe DNR senza preventiva classificazione;
* **I viaggi operativi multi-committente** richiedono un progetto approvato prima di qualsiasi modifica al codice.

---

## 17. TEST

* Prima di distribuire modifiche a Security Rules o funzioni di backend complesse, testare il comportamento locali tramite Firebase Emulator (`firebase emulators:start`).
* Verificare esplicitamente che i tentativi di lettura o scrittura cross-tenant restituiscano `PERMISSION_DENIED`.

---

## 18. ROLLBACK

* **Rollback Codice Frontend**: Ripristino controllato dei file dal commit stabile (`git checkout <commit_sha> -- frontend/`), creazione di un nuovo commit di rollback (`git commit -m "rollback: frontend..."`) ed esecuzione di `firebase deploy --only hosting --project <PROJECT_ID>`. *(Evitare `git checkout <commit_sha>` isolato per non generare uno stato detached HEAD)*.
* **Rollback Cloud Functions**: Ripristino controllato di **tutti i file backend** del commit stabile (inclusi `functions/main.py`, moduli in `infrastructure/`, dipendenze e configurazioni), creazione di un commit di rollback e deploy `firebase deploy --only functions --project <PROJECT_ID>`.
* **Rollback Firestore Rules**: Ripristino separato del file `firestore.rules` ed esecuzione di `firebase deploy --only firestore:rules --project <PROJECT_ID>`.
* **Rollback Storage Rules**: Ripristino separato del file `storage.rules` ed esecuzione di `firebase deploy --only storage --project <PROJECT_ID>`.
* **Rollback Dati**: Il rollback Git **NON ripristina Firestore o Storage**. Per i dati occorre utilizzare gli script di ripristino dai backup JSON/GCP.

---

## 19. SCHEDA OPERATIVA

Prima di qualsiasi operazione di modifica, deploy o rilascio, l'agente deve generare la **Scheda Operativa**:

```text
==================================================
SCHEDA OPERATIVA
==================================================
MODALITÀ:               [ ANALISI / PIANIFICAZIONE / IMPLEMENTAZIONE / COLLAUDO / RILASCIO ]
OBIETTIVO:              [ Descrizione sintetica task ]
AMBIENTE:               [ Cantiere / Produzione ]
PROJECT ID:             [ log-solutions-cantiere / log-solution-60007 ]
BRANCH:                 [ dev / feature-... / main ]
VERSIONE:               [ vX.XXX ]
FILE COINVOLTI:         [ elenco file ]
COMPONENTI FIREBASE:    [ hosting / functions / firestore:rules / storage ]
DATABASE:               [ Firestore Cantiere / Firestore Produzione ]
STORAGE BUCKET:         [ valore letto dalla configurazione effettiva ]
RULES:                  [ Invariate / Modificate ]
SCRIPT:                 [ Elenco script eseguiti ]
TARGET PROD RILEVATI:   [ SÌ / NO ]
CREDENZIALI PROD:       [ CARICATE / ASSENTI ]
BACKUP DISPONIBILE:     [ SÌ / NO / N/A ]
ROLLBACK:               [ Procedura specifica ]
RISCHIO:                [ BASSO / MEDIO / ALTO / CRITICO ]
AUTORIZZAZIONE:         [ In attesa / Ricevuta ]
==================================================
```

---

## 20. REPORT CONCLUSIVO

Ogni risposta di chiusura attività deve contenere il riepilogo:

```text
==================================================
REPORT FINALE ATTIVITÀ
==================================================
MODALITÀ OPERATIVA USATA: [ ANALISI / PIANIFICAZIONE / IMPLEMENTAZIONE / COLLAUDO / RILASCIO ]
FILE LETTI:              [ elenco o conteggio ]
FILE MODIFICATI:         [ elenco file ]
FILE NON MODIFICATI:     [ conferma ]
TEST ESEGUITI:           [ elenco test ]
TEST NON ESEGUITI:       [ elenco ]
COMMIT ESEGUITO:         [ SÌ / NO ]
PUSH ESEGUITO:           [ SÌ / NO ]
DEPLOY ESEGUITO:         [ SÌ / NO ]
AMBIENTE TOCCATO:        [ Sviluppo / Nessuno ]
PRODUZIONE TOCCATA:      [ NO ]
RISCHI RESIDUI:          [ elenco ]
PROSSIMA FASE PROPOSTA:  [ descrizione ]
AUTORIZZAZIONE RICHESTA: [ descrivere autorizzazione necessaria ]
==================================================
```

---

## 21. ALLEGATO COMANDI AUTORIZZATI

### Sviluppo (`log-solutions-cantiere`):
* `firebase deploy --only hosting --project log-solutions-cantiere`
* `firebase deploy --only functions --project log-solutions-cantiere`
* `firebase deploy --only firestore:rules --project log-solutions-cantiere`
* `firebase deploy --only storage --project log-solutions-cantiere`

### Produzione (`log-solution-60007`):
* `firebase deploy --only hosting --project log-solution-60007`
* `firebase deploy --only functions --project log-solution-60007`
* `firebase deploy --only firestore:rules --project log-solution-60007`
* `firebase deploy --only storage --project log-solution-60007`


## REGOLA OBBLIGATORIA: DISTINZIONE AMBIENTI E BRANCH

Tutti gli agenti operativi e di refactoring DEVONO distinguere rigorosamente i concetti di Branch Git dai Progetti Firebase. 

1. **PRODUZIONE (log-solution-60007)**: È l'ambiente di produzione legacy. Read-only. Congelato.
2. **CANTIERE (log-solutions-cantiere)**: È la nuova entità applicativa in costruzione, totalmente indipendente.
3. **SVILUPPO**: Altro ambiente separato, non sinonimo di Cantiere.
4. **TARGET_LOGIDESK**: Il modello di architettura definitiva documentato.
5. **Git Branch (`cantiere` vs `main` ecc.)**: Non implica automaticamente il progetto Firebase sottostante. L'agente deve sempre validare separatamente `GIT_BRANCH` e `FIREBASE_PROJECT` prima di intraprendere operazioni tecniche o modifiche di codice. 

