# DATA PIPELINE HARDENING PLAN

Questo documento funge da roadmap tecnica ufficiale per il consolidamento e la tracciabilità del dato attraverso l'intera pipeline logistica.

## PRINCIPIO ARCHITETTURALE

- **NORMALIZZARE UNA VOLTA A MONTE**: Il parsing e la pulizia del dato avvengono esclusivamente nel momento dell'estrazione.
- **VALIDARE PRIMA DI PROSEGUIRE**: I dati devono essere validati in punti di controllo rigidi. Se un requisito fondamentale manca, il processo si arresta.
- **PROPAGARE SENZA REINTERPRETARE**: I consumer (reporting, mappa, routing) leggono il dato canonico; non esistono fallback silenti o deduzioni a valle. 
- **IL ROUTING NON DEVE RIPARARE DATI SPORCHI**.
- **REPORTING NON DEVE INVENTARE DATI MANCANTI**.
- **I CONSUMER DOWNSTREAM DEVONO LEGGERE LO STESSO DATO CANONICO SENZA REINTERPRETARLO**.

---

## FASE 1 — PDF / EXCEL INGESTION HARDENING

### 1. DATA_LAVORO AUTOREVOLE
La data selezionata manualmente nella pagina Elaborazione è la data operativa ufficiale della giornata.
Serve per:
- giornata logistica
- generazione viaggi
- mappa
- routing
- persistenza
- reporting operativo
- fatturazione

Le date interne a PDF/Excel (data DDT, stampa, estrazione, ecc.) sono **metadata** e NON devono sovrascrivere automaticamente la `data_lavoro`.

### 2. MULTI-FILE
Una stessa lavorazione può contenere:
- più PDF FRUTTA
- più PDF LATTE
- più file Excel
- file con date interne differenti

Non deve esistere la regola legacy: 1 file = 1 giornata.

### 3. DDT MULTIPAGINA
Per i nuovi PDF FRUTTA/LATTE:
- viene fornita una sola copia del DDT;
- stesso numero DDT ripetuto N volte nello stesso PDF significa UN DDT composto da N pagine (es. FNS36593, FNS36593 -> 2 pagine).

NON devono esistere logiche attive tipo pari/dispari, dimezzamento, prima copia/seconda copia, eliminazione automatica di pagine con stesso DDT.
*(Nota: in passato esistevano PDF a doppia copia; eventuali residui legacy dovranno essere auditati).*

### 4. NUMERO DDT
Il numero DDT è l'identificatore documentale.
Deve essere usato per raggruppare rigorosamente le pagine dello stesso DDT.

### 5. CONTROLLO DOPPIO UPLOAD
In audit successivo si verificherà che il sistema impedisca il caricamento/elaborazione dello stesso file o dello stesso DDT più volte. Questa meccanica è separata dalla logica multipagina.

### 6. CODICE ZONA FRUTTA/LATTE
Valori come C3108, A3108, G3108, Q3108 letti dal PDF indicano la zona "3108". La lettera iniziale NON appartiene all'identità della zona.
Il valore canonico è `id_zona = "3108"`.
La rimozione del prefisso è business-correct, tuttavia occorre evitare slice rigidi come `[1:5]` se questi possono troncare codici futuri inaspettatamente più lunghi.

### 7. ID_ZONA
`id_zona` è un IDENTIFICATORE TESTUALE.
Target contract: `id_zona = str`.
Non deve essere trattato come quantità numerica (es. mai operare conversioni int(), float() o arrotondamenti per dedurne il comportamento).
Eventuali float integralizzati da pandas ("3108.0") non devono subire trasformazioni semantiche distruttive o automatiche in assenza di chiare regole di business.

### 8. TIPI CANONICI
Definire come target almeno:
- `tenant` = str
- `id_zona` = str
- `numero_ddt` = str
- `data_lavoro` = tipo/formato canonico
- `data_documento` = metadata
- `codice_cliente` = str
- `colli` = int
- `peso_kg` = float
- `lat` = float
- `lng` = float

### 9. PAGINE / DDT PERSI
La pipeline target NON deve poter saltare silenziosamente una pagina o un DDT fallendo il parsing dichiarando comunque SUCCESS.
Audit futuro su: pagine ricevute, riconosciute, associate, DDT prodotti, non riconosciuti, anomalie.

### 10. FALLBACK ANAGRAFICA
I fallback downstream (es. `cliente_info.get("codice_zona")`) devono essere classificati e verificati. Un errore del parser non deve essere nascosto silenziosamente da un'anagrafica disallineata.

### 11. RAW VS CANONICAL
Raw utile per: audit, debugging, AI futura, nuovi formati sorgente (es. `raw_zone_code = "C3108"`).
Canonical usato dal software (`id_zona = "3108"`).

### 12. PARSER CONTRACT
- **Parser**: estrae.
- **Normalizer**: normalizza tecnicamente.
- **Validator**: controlla.
- **Reporting**: aggrega.
- **Routing**: calcola.

---

## FASE 2 — DATA PROCESSING

Audit futuro su:
- reporting_service.py
- aggregazione dati
- merge con dati precedenti
- costruzione viaggi (tenant, id_zona, nome_giro, data_lavoro, metadata)
- JSON
- Firestore
- type drift
- fallback legacy

**Target**: i dati canonici della FASE 1 devono rimanere canonici. Nessuna distorsione semantica in FASE 2.

---

## FASE 3 — MAPPA OPERATIVA

Audit futuro su:
- caricamento viaggi, split, merge
- spostamento consegne
- rinomina
- proprietà tenant, metadata, origine consegne

**Regole**:
- Tenant esplicito.
- `id_zona` preservato.
- `nome_giro` separato da `id_zona`.
- Lo split non perde tenant/origine.
- Il merge non perde source metadata delle consegne.

**Associazione**:
tenant + zona → nome_giro
Una zona già assegnata a un viaggio dello stesso tenant non deve essere disponibile per un secondo viaggio incompatibile.

---

## FASE 4 — PRE-ROUTING VALIDATION

Prima del routing occorre contare i viaggi effettivi nello stato finale della mappa.
Ogni viaggio deve avere: `tenant`, `id_zona`, `nome_giro`, `consegne`.

Verificare:
- tutti i viaggi rinominati
- tenant valido
- zona valida
- nome_giro valido
- tenant + nome_giro univoco
- nessun viaggio incompleto

Se qualcosa fallisce: **STOP. Niente routing. Nessun SUCCESS con zero viaggi.**

---

## FASE 5 — ROUTING

Routing deve occuparsi solo di:
- selezione viaggi validi
- Distance Matrix
- OR-Tools
- Directions
- sequenza
- km, traffico
- persistenza
- stato elaborato

Routing NON deve:
- inventare tenant
- dedurre tenant da ID
- riparare id_zona
- rinominare viaggi
- applicare fallback DNR
- correggere dati provenienti dalle fasi precedenti

---

## FASE 6 — DOWNSTREAM

Seguire i dati fino a:
- Pianificazione, mappe autisti
- distinte, link_viaggi
- presenze, fatturazione

Verificare preservazione di:
`data_lavoro`, `tenant`, `id_zona`, `nome_giro`, source consegna, numero DDT, metadata necessari, km, stato viaggio.
Particolare attenzione: `data_lavoro` resta la data operativa autorevole anche per fatturazione.

---

## STATO PROGETTO

- **FASE 1 — IN CORSO**
  - 1A PDF FRUTTA/LATTE = PROSSIMA
  - 1B EXCEL / ALTRI PARSER = NON INIZIATA
  - 1C CANONICAL CONTRACT = NON INIZIATA
- **FASE 2** = NON INIZIATA
- **FASE 3** = NON INIZIATA
- **FASE 4** = NON INIZIATA
- **FASE 5** = NON INIZIATA
- **FASE 6** = NON INIZIATA

---

## METODO DI LAVORO

Ogni fase deve seguire il ciclo:
**AUDIT → REPORT → STOP → APPROVAZIONE → PATCH MINIMA → TEST → COMMIT → CANTIERE → TEST REALE**.

Solo al completamento di una fase e relativo test si passa alla successiva.
Produzione e Muletto: NO TOUCH senza autorizzazione esplicita.



## GATES AGGIUNTIVI OBBLIGATORI E RICONCILIAZIONE

### RICONCILIAZIONE PRODUZIONE-CANTIERE
Lo stato della riconciliazione tra PRODUZIONE e CANTIERE è attualmente **SUSPENDED**.
Sebbene i punti storici (865 vs 866) coincidano, la presunta presenza del tenant `DAC` in PRODUZIONE non è stata confermata da un audit approfondito (DAC FOUND: False nelle collection standard, ma serve ulteriore verifica sui flussi di ingestion/excel). Nessuna promozione può avvenire prima della riconciliazione totale, inclusi i nuovi tenant.

### GATE: GIT_SEPARATION_AUDIT
Prima di separare i repository, deve essere eseguito un audit Git per mappare remote, branch, GitHub Actions, script di deploy, secrets e riferimenti ai project ID.

### GATE: FIREBASE_DATA_STRUCTURE_REVIEW
Prima di finalizzare la nuova entità CANTIERE, è obbligatorio rivedere l'intera struttura Firebase attuale.
- FIRESTORE: root collections, documenti, subcollections, struttura tenant, duplicazioni, legacy vs target.
- STORAGE: REPORTS, split_ddt, processing, CONSEGNE, backup, ecc.
- AUTH/RULES/CONFIG: utenti, ruoli, tenant, Firestore Rules, App Check, configurazioni.
Stato revisione: PENDING.

### PIANO DI CUTOVER
CANTIERE non verrà rilasciato tramite upgrade in-place. La sostituzione di PRODUZIONE sarà un **CUTOVER TRA DUE APPLICAZIONI** indipendenti. 
Richiederà un piano contenente data freeze, backup, delta dati, validazione, rollback, smoke test, e reindirizzamento dominio/DNS.

