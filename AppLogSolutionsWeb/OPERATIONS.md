# ⚙️ Manuale delle Procedure Operative — OPERATIONS.md

> **Procedure Operative, Deploy, Backup e Disaster Recovery per AppLogSolutionsWeb**  
> **Inquadramento**: LIVELLO 1 — CORE DOCUMENTATION SYSTEM  
> **Proprietà**: Loge Solution  
> **Ultimo Aggiornamento**: Luglio 2026 (Versione 1.0)

---

## 📑 INDICE DELLE OPERAZIONI

1. [Governance dei Deploy e Ambienti](#1-governance-dei-deploy-e-ambienti)
2. [Procedura Sicura di Versionamento (Bump Versione)](#2-procedura-sicura-di-versionamento-bump-versione)
3. [Procedure di Backup e Salvaguardia Dati](#3-procedure-di-backup-e-salvaguardia-dati)
4. [Procedure di Disaster Recovery (DR)](#4-procedure-di-disaster-recovery-dr)
5. [Strategie di Rollback per Componente](#5-strategie-di-rollback-per-componente)
6. [Gestione dei Log e Monitoraggio](#6-gestione-dei-log-e-monitoraggio)

---

## 1. GOVERNANCE DEI DEPLOY E AMBIENTI

### 1.1 Ambienti Firebase
* **SVILUPPO**: Project ID `log-solutions-cantiere`
* **PRODUZIONE**: Project ID `log-solution-60007`

### 1.2 Regola Inviolabile dei Deploy Selettivi
È **TASSATIVAMENTE VIETATO** eseguire deploy completi (`firebase deploy`) o deploy senza il flag esplicito `--project <PROJECT_ID>`.

#### Deploy Sviluppo:
```bash
firebase deploy --only hosting --project log-solutions-cantiere
firebase deploy --only functions --project log-solutions-cantiere
firebase deploy --only firestore:rules --project log-solutions-cantiere
firebase deploy --only storage --project log-solutions-cantiere
```

#### Deploy Produzione (Solo previa autorizzazione contenente "Produzione" e Project ID):
```bash
firebase deploy --only hosting --project log-solution-60007
firebase deploy --only functions --project log-solution-60007
firebase deploy --only firestore:rules --project log-solution-60007
firebase deploy --only storage --project log-solution-60007
```

---

## 2. PROCEDURA SICURA DI VERSIONAMENTO (BUMP VERSIONE)

I concetti di **bump versione**, **commit**, **push** e **deploy** sono **4 AZIONI SEPARATE**.

```text
Fase A: Bump Versione ──► python bump_version.py ──► Test locali ──► git status/diff ──► STOP
Fase B: Commit         ──► git commit (Previa autorizzazione separata)
Fase C: Push           ──► git push (Previa verifica branch e workflow attivati)
Fase D: Deploy         ──► firebase deploy --only ... --project ... (Previa autorizzazione esplicita)
```

---

## 3. PROCEDURE DI BACKUP E SALVAGUARDIA DATI

1. **Backup Codice**: Working tree pulito, branch dedicato e tag Git pre-refactoring.
2. **Backup Firestore**: Export completo via Console GCP / CLI Firebase prima di modifiche allo schema.
3. **Backup Cloud Storage**: Protezione tramite snapshot immutabili con timestamp nella directory `caches_backup/` gestita da `functions/infrastructure/firebase_setup.py`.
4. **Guardia Anti-Troncamento Cache**: La funzione `min_bytes_guard` (100 KB) rifiuta automaticamente la sovrascrittura delle cache distanze se il nuovo file è inferiore al precedente.

---

## 4. PROCEDURE DI DISASTER RECOVERY (DR)

In caso di guasto catastrofico o corruzione dati:
1. Consultare la documentazione specialistica [`dr_system/MANUALE_GESTIONE_UMANA_DR.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/dr_system/MANUALE_GESTIONE_UMANA_DR.md).
2. Verificare l'auto-certificazione di salute del DR System (`dr_system/README_DR_AUTONOMO.md`).
3. Eseguire il ripristino delle collezioni Firestore dai backup JSON più recenti conservati in storage locale/GCP.

---

## 5. STRATEGIE DI ROLLBACK PER COMPONENTE

* **Rollback Frontend**: Ripristino file dal commit stabile (`git checkout <commit_sha> -- frontend/`), nuovo commit di rollback e deploy `firebase deploy --only hosting --project <PROJECT_ID>`.
* **Rollback Cloud Functions**: Ripristino dell'intera directory `functions/` dal commit stabile, nuovo commit e deploy `firebase deploy --only functions --project <PROJECT_ID>`.
* **Rollback Rules**: Deploy separato `firebase deploy --only firestore:rules --project <PROJECT_ID>` o `storage`.



## PROCEDURE DI FREEZE E CUTOVER (PRODUZIONE E CANTIERE)

### PRODUCTION FREEZE
È attivo il **PRODUCTION_FREEZE**: non sono permesse modifiche strutturali o nuove funzionalità sull'app di Produzione (`log-solution-60007`). Sono concessi unicamente hotfix operativi urgenti, etichettati come `PRODUCTION_HOTFIX`. Tutte le nuove evoluzioni architetturali sono destinate a CANTIERE.

### REQUISITO DI AUTONOMIA
Prima del rilascio, il CANTIERE deve dimostrare la completa autonomia (CANTIERE MUST WORK STANDALONE). Tutte le 30 macro-funzionalità logistico-operative (auth, ingestion, routing, or-tools, distinte, mappe, ecc.) devono funzionare senza alcuna dipendenza (né di API, né di dati real-time) dalla Produzione.

### CUTOVER PLAN
Il passaggio finale non sarà un aggiornamento del codice di Produzione, bensì un Cutover architetturale. Il piano di cutover dovrà prevedere: data freeze, migrazione delta dati anagrafici, validazione di integrità, allineamento di dominio/DNS ed un robusto piano di rollback. Fino all'esecuzione del Cutover, Produzione e Cantiere procedono come entità separate.

