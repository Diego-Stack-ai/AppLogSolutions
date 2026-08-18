# 📦 Modello di Dominio e Linguaggio Ubiquo — DOMAIN_MODEL.md

> **Single Source of Truth del Dominio Logistico per AppLogSolutionsWeb**  
> **Inquadramento**: LIVELLO 1 — CORE DOCUMENTATION SYSTEM  
> **Proprietà**: Loge Solution  
> **Ultimo Aggiornamento**: Luglio 2026 (Versione 1.0)

---

## 📑 INDICE DEL MODELLO DI DOMINIO

1. [Inquadramento DDD e Bounded Contexts](#1-inquadramento-ddd-e-bounded-contexts)
2. [Linguaggio Ubiquo Ufficiale](#2-linguaggio-ubiquo-ufficiale)
3. [Modello dei Committenti (Tenants)](#3-modello-dei-committenti-tenants)
4. [Tassonomia Documenti e Consegne](#4-tassonomia-documenti-e-consegne)
5. [Tassonomia dei Viaggi](#5-tassonomia-dei-viaggi)
6. [Regole di Business Inviolabili](#6-regole-di-business-inviolabili)

---

## 1. INQUADRAMENTO DDD E BOUNDED CONTEXTS

In accordo con i principi di Domain-Driven Design (DDD), il sistema distingue due Bounded Contexts fondamentali:

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             BOUNDED CONTEXTS SYSTEM                              │
├──────────────────────────────────────────────────────────────────────────────────┤
│ 1. BOUNDED CONTEXT VETTORE (Loge Solution Core):                                 │
│    - Governance della flotta veicoli (automezzi, targhe, capienze)               │
│    - Gestione del personale autisti (presenze, turni, straordinari)              │
│    - Gestione dei Viaggi Operativi Finali ed assegnazione risorse                │
│    - Calcolo dei corrispettivi contabili (Fatturazione Trasporti)                │
│                                                                                  │
│ 2. BOUNDED CONTEXT COMMITTENTI (Tenants):                                        │
│    - Ingestione DDT, bolle, ordini (PDF, Excel, TXT)                             │
│    - Anagrafica clienti commerciali dei committenti                              │
│    - Articoli, colli, peso (kg), note di consegna e vincoli orari                │
│    - Listini e regole tariffarie commerciali                                     │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. LINGUAGGIO UBIQUO UFFICIALE

Per evitare qualsiasi malinteso tra sviluppatori, architetti ed agenti AI, i seguenti termini hanno una definizione **unica ed ufficiale**:

| Termine Ufficiale | Definizione Vincolante di Dominio | Appartenenza Dominio |
| --- | --- | --- |
| **Loge Solution** | Società proprietaria dell'applicazione web ed esecutrice del servizio distributivo come Vettore Operativo. | Core Vettore |
| **Committente / Tenant** | Cliente aziendale (es. DNR, Cattel, GranChef, Bauer) che affida le merci ed i punti di consegna a Loge Solution. | Client Tenant |
| **tenantId** | Identificativo stringa univoco del committente (`"DNR"`, `"CATTEL"`, `"GRAN CHEF"`). | Client Tenant |
| **sourceChannel** | Canale documentale sorgente del committente (`"FRUTTA"`, `"LATTE"`, `"EXCEL_CATTEL"`). | Client Tenant |
| **parserType** | Adattatore di parsing specifico utilizzato per estrarre i dati dal file (`"PDF_DNR"`, `"XLS_CATTEL"`). | System Ingestion |
| **Cliente Commerciale** | Il destinatario finale della merce (es. bar, scuola, ristorante) appartenente all'anagrafica del committente. | Client Tenant |
| **Punto di Consegna** | Indirizzo fisico geografico e coordinate GPS di destinazione raggiunti dai veicoli. | Territorio |
| **Fermata** | Arresto fisico del veicolo in un Punto di Consegna per scaricare la merce di uno o più committenti. | Operatività Vettore |
| **pointUUID** | Identificativo univoco immutabile assegnato a ciascuna fermata per garantirne il Data Lineage. | Data Lineage |
| **Zona Logistica** | Area distributiva o raggruppamento logico iniziale di consegne (es. `"ZONA 1"`, `"CATTEL MESTRE"`). | Pianificazione |
| **Viaggio Iniziale** | Giro o proposta di carico fornito originariamente dal committente (es. foglio Excel Cattel). | Sorgente Importata |
| **Viaggio Operativo Finale** | Itinerario reale deciso ed ottimizzato da Loge Solution ed assegnato al veicolo. | Operatività Vettore |
| **ORIGINAL_DDT** | Documento digitale originale di trasporto estratto dai file sorgente PDF. | Documentale |
| **DELIVERY_PLACEHOLDER** | Segnaposto A4 generato dal sistema quando il committente usa bolle cartacee fisiche. | Documentale |
| **Distinta di Viaggio** | Documento riepilogativo PDF generato per l'autista contenente la sequenza ufficiale delle tappe. | Output Operativo |
| **Navetta** | Spostamento secondario o collegamento di merce tra magazzini o depositi. | Operatività Vettore |
| **Presenza HR** | Registro dell'attività lavorativa dell'autista (entrata, uscita, pausa, straordinario). | HR Vettore |

---

## 3. MODELLO DEI COMMITTENTI (TENANTS)

1. **Pariteticità dei Tenant**: DNR non è il tenant radice o proprietario dell'app, ma un committente cliente come gli altri.
2. **Canali DNR**: `DNR_FRUTTA` e `DNR_LATTE` non sono due tenant distinti, ma rappresentano `tenantId = "DNR"` con `sourceChannel = "FRUTTA"` o `sourceChannel = "LATTE"`.
3. **Isolamento Anagrafico**: Ciascun committente possiede il proprio sotto-albero anagrafico in Firestore (`clienti/{tenantId}/raccolta clienti`).

---

## 4. TASSONOMIA DOCUMENTI E CONSEGNE

```text
[File Sorgente: PDF / Excel / TXT]
              │
              ▼
    [Processing Job Parsing]
              │
              ├──► ORIGINAL_DDT (PDF Estratto memorizzato in split_ddt/)
              │
              └──► DELIVERY_PLACEHOLDER (Segnaposto A4 generato dal sistema)
```

* **DNR**: Genera `ORIGINAL_DDT` estratti dai PDF cumulativi.
* **Cattel / GranChef**: Generano `DELIVERY_PLACEHOLDER` per l'autista mentre le bolle cartacee originali viaggiano fisicamente.

---

## 5. TASSONOMIA DEI VIAGGI

Distinzione vincolante tra i 4 livelli del Viaggio:
1. **Viaggio Iniziale (Sorgente)**: Il giro o la zona proposta dal committente in fase di importazione.
2. **Viaggio Operativo Finale (Aziendale)**: L'itinerario reale deciso da Loge Solution ed assegnato alla targa del mezzo. Può contenere consegne di più committenti (viaggi misti).
3. **Viaggio Commerciale**: L'insieme delle consegne attribuite ad uno specifico committente per rendicontazione.
4. **Viaggio Fatturabile**: La base di calcolo per l'emissione della fattura contabile verso il committente.

---

## 6. REGOLE DI BUSINESS INVIOLABILI

1. **Data Lineage Immutabile**: Nessuna operazione di ottimizzazione o spostamento fermata può cancellare il `tenantId` originario o i riferimenti al DDT sorgente.
2. **Preservazione del Valore Commerciale**: La riorganizzazione dei viaggi operativi da parte di Loge Solution non deve mai alterare il calcolo contabile delle tariffe pattuite con ciascun committente.
3. **Divieto Fallback DNR**: Se un dato arriva senza `tenantId`, non deve mai essere assegnato automaticamente a DNR, ma bloccato o posto in quarantena (`processing_jobs_quarantine`).



## TARGET_APPLOGSOLUTIONSWEB: Modello Target dei Punti di Consegna

La vecchia struttura `clienti/{tenant}/raccolta clienti/{documento}` è considerata LEGACY.

Il nuovo percorso target in Firestore è:
`tenants/{tenant}/punti_consegna/{id_punto}`

### Identità e Anagrafica
- **id_punto**: ID interno, univoco, immutabile, indipendente dal nome o codice committente (es. DP00123).
- **Identità esterna**: `tenant`, `canale` (es. FRUTTA/LATTE, o null), `codice_esterno`.
- **Dati anagrafici**: `cliente`, `indirizzo`, `citta`, `cap` (string), `provincia` (2 caratteri), `lat` (float), `lon` (float).
- **Note**: Divise in `nota_anagrafica` (stabile) e `nota_consegna` (per singola importazione).
- *Superamento codici legacy*: `codice_frutta` e `codice_latte` non definiscono l'identità. Un punto FRUTTA e un punto LATTE DNR diventano due schede distinte se hanno logiche/canali separati (anche alla stessa destinazione fisica). P00000 non rappresenta un punto reale.

### Relazioni e Regole Operative
- **Associazione Punti (`consegna_presso_punto_id`)**: Definisce la consegna fisica presso un'altra entità anagrafica distinta. (Previene cicli o autorelazioni).
- **Vincolo Associazione (`vincolo_associazione`)**: Se `null`, segue i vincoli del punto fisico; se `RESTRITTIVO`, i vincoli temporali concorrono a determinare la finestra (es. intersezione 08:00-15:00 e 07:30-10:00 -> 08:00-10:00).
- **Orari**: `orario_min_mattina`, `orario_max_mattina`, `orario_min_pomeriggio`, `orario_max_pomeriggio` (formato HH:MM o null). Sostituiscono gli alias om_frutta/latte.
- **Configurazione Routing (`modalita_creazione_viaggi`)**: ZONA vs IMPORTAZIONE a livello di tenant (es. DNR -> ZONA).
- **Geocoding (`stato_geocoding`)**: Auto-geocodificato ma 'da verificare' fino a supervisione umana.

