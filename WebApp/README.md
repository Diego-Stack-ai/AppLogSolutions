# 🚀 AppLogSolutionsWeb v3.00 — Piattaforma Logistica Modulare Dual Mode

> **Proprietà**: Loge Solution (Vettore Operativo)  
> **Repository Root**: `AppLogSolutionsWeb`  
> **Stato Governance**: LIVELLO 1 CORE DOCUMENTATION SYSTEM (v5.0)

---

## 🛑 PROTOCOLLO DI BOOTSTRAP OBBLIGATORIO PER AGENTI AI

```text
====================================================================================
                        BOOTSTRAP OBBLIGATORIO AGENTI AI
====================================================================================
Prima di svolgere qualsiasi attività (Analisi, Modifica Codice, Refactoring, Deploy),
qualsiasi Agente AI DEVE leggere integralmente i 5 Documenti Core nel seguente ordine:

1. README.md       ──► Porta d'ingresso e Mappa di Bootstrap
2. AGENTS.md       ──► Costituzione Operativa, Governance, Deploy e Git
3. DOMAIN_MODEL.md ──► Linguaggio Ubiquo (DDD), Definizioni di Dominio e Modello Dati
4. ARCHITECTURE.md ──► Blueprint Architetturale Tecnico (Firestore, Storage, Functions)
5. OPERATIONS.md   ──► Procedure Operative, Workflow, Backup e Disaster Recovery
====================================================================================
```

> [!CAUTION]
> **DIVIETO ASSOLUTO**:  
> È tassativamente vietato saltare la lettura di uno qualsiasi dei 5 documenti Core.  
> Nessun agente può consultare direttamente la documentazione specialistica (Livello 2) prima di aver costruito l'intero contesto leggendo la documentazione Core (Livello 1).

---

## 📑 STRUTTURA DELLA DOCUMENTAZIONE SUL PROGETTO

### 🔴 LIVELLO 1: DOCUMENTAZIONE CORE (OBBLIGATORIA)
1. **[`README.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/README.md)**: Porta d'ingresso e guida al Bootstrap.
2. **[`AGENTS.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/AGENTS.md)**: Costituzione Operativa Vincolante (Governance, Deploy, Git, Regole di Sicurezza).
3. **[`DOMAIN_MODEL.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/DOMAIN_MODEL.md)**: Modello di Dominio DDD e Linguaggio Ubiquo (Tenant, Vettore, Punto, Fermata, Viaggio, DDT).
4. **[`ARCHITECTURE.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/ARCHITECTURE.md)**: Blueprint Architetturale Tecnico (Firestore, Storage, Backend Python, Multi-Tenant, Target AI).
5. **[`OPERATIONS.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/OPERATIONS.md)**: Procedure Operative, Backup, Disaster Recovery e Manuale di Rilascio.

### 🟡 LIVELLO 2: DOCUMENTAZIONE SPECIALISTICA (CONSULTABILE ALL'OCCORRENZA)
Da consultare **SOLO DOPO** la lettura completa dei 5 documenti Core:
* **Frontend & UI/UX**:
  * [`frontend/docs/design-system.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/frontend/docs/design-system.md) (Design Tokens, Glassmorphism, CSS)
  * [`frontend/docs/differenze_modali.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/frontend/docs/differenze_modali.md) (Componenti Modali Operatore vs Autista)
* **Workflows & Backend Cloud**:
  * [`.agent/workflows/workflow_automazione.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/.agent/workflows/workflow_automazione.md) (Motore Python, Cache & Soft Delete)
  * [`.agent/workflows/Gestione CONSEGNE.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/.agent/workflows/Gestione%20CONSEGNE.md) (Integrazione Web App vs Standalone Locale)
* **Disaster Recovery Dettagliato**:
  * [`dr_system/README_DR_AUTONOMO.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/dr_system/README_DR_AUTONOMO.md) (Infrastruttura DR automatica)
  * [`dr_system/MANUALE_GESTIONE_UMANA_DR.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/dr_system/MANUALE_GESTIONE_UMANA_DR.md) (Guida di ripristino umano d'emergenza)

---

## ⚡ GUIDA RAPIDA DI DEPLOY E AMBIENTI

* **SVILUPPO**: `log-solutions-sviluppo`
  * Frontend: `firebase deploy --only hosting --project log-solutions-sviluppo`
  * Backend: `firebase deploy --only functions --project log-solutions-sviluppo`
* **PRODUZIONE**: `log-solution-60007` (Consultare la sezione 13 di [`AGENTS.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/AGENTS.md)).


---

## 🛡️ GERARCHIA ASSOLUTA DELLE FONTI E BOOTSTRAP VERIFICABILE

Prima di accedere al codice o alla documentazione specialistica, ogni Agente AI DEVE produrre il **`BOOTSTRAP REPORT`** attestando la lettura sequenziale dei 5 documenti Core:

1. **[`README.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/README.md)** (Porta d'ingresso & Bootstrap Roadmap)
2. **[`AGENTS.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/AGENTS.md)** (Costituzione Operativa, Safety & Deploy)
3. **[`DOMAIN_MODEL.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/DOMAIN_MODEL.md)** (Linguaggio Ubiquo DDD & Modello Dati)
4. **[`ARCHITECTURE.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/ARCHITECTURE.md)** (Blueprint Architetturale Tecnico)
5. **[`OPERATIONS.md`](file:///H:/Il%20mio%20Drive/App/AppLogSolutionsWeb/OPERATIONS.md)** (Procedure Operative & DR)
6. **Documentazione Specialistica** (Consultabile solo previa motivazione dichiarata nel report)

In caso di conflitto tra documenti, prevale la fonte di livello superiore secondo la gerarchia sopra indicata.


---

## ⚖️ LIVELLI DI INTERVENTO E PROPORZIONALITÀ

Per garantire sostenibilità ed efficienza, gli interventi sono classificati in 4 livelli:
* **LIVELLO A (Minimi)**: CSS, testi, piccole fix UI ➔ *Governance Check sintetico*.
* **LIVELLO B (Applicativi)**: Nuove pagine, JS, query Firestore ➔ *Bootstrap Report + Governance Check*.
* **LIVELLO C (Architetturali)**: Cloud Functions, Storage, Multi-Tenant, Refactoring ➔ *Bootstrap Report + Coerenza ARCHITECTURE.md*.
* **LIVELLO D (Strategici)**: Modello Dominio, Architettura, Governance ➔ *ADR + Aggiornamento Documenti Core PRIMA di codificare*.


---

## 🔒 STATO DELLA GOVERNANCE: STABILE

> **STATO ATTUALE**: `STABILE`  
> La Governance Documentale del progetto è ufficialmente sigillata e stabile. Gli Agenti AI utilizzano le regole esistenti senza apportare modifiche normative salvo l'apertura di una **Revisione Straordinaria** autorizzata.
