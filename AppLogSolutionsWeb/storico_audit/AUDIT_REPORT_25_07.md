# REF-001 — AUDIT COMPARATIVO 25-07-2026
## Confronto completo Produzione vs Sviluppo

### FASE 1 — IDENTIFICAZIONE ESATTA DELLA DATA
- Formati trovati in Produzione: 25-07-2026
- Formati trovati in Sviluppo: 25-07-2026
- Campi usati: `data_lavoro`, `dataLavoro`, `data_rilevata`

### FASE 2 — CENSIMENTO TENANT
- Tenant coinvolti in Produzione: CATTEL, GRAN CHEF
- Tenant coinvolti in Sviluppo: CATTEL, GRAN CHEF

### FASE 3 — FILE E OGGETTI STORAGE DI ORIGINE
I file che hanno scatenato le esecuzioni, in base ai job, sono identici nei due ambienti e consistono in:
- `None` (Prod: NFlzc9QY6bTwU2arBZHJ)
- `None` (Prod: cnMvVgZRMCgMtbIQKK7O)
- `None` (Prod: SZ3hEGKdOyqjK6rnakKf)

### FASE 4 — PROCESSING JOB
- **Produzione**: Trovati 3 job.
- **Sviluppo**: Trovati 3 job.

- Prod Job ID: NFlzc9QY6bTwU2arBZHJ per file None
- Prod Job ID: cnMvVgZRMCgMtbIQKK7O per file None
- Prod Job ID: SZ3hEGKdOyqjK6rnakKf per file None
- Dev Job ID: VDtEBPNlWfJgHR5Oiuo8 per file None
- Dev Job ID: eGy732K2cDvyhcqlBDK8 per file None
- Dev Job ID: jgsbJytUKVtXWx0nKwRd per file None

### FASE 5 & 6 — RISULTATI DEI PARSER E INVENTARIO CONSEGNE
Non abbiamo visibilità diretta sulla singola collection "deliveries" in quanto i dati risiedono aggregati nei file `split_ddt/...json` o all'interno dell'array `punti` nei documenti `viaggi ddt`.

### FASE 8 & 12 — PUNTI DI CONSEGNA E VIAGGI
**PRODUZIONE:**
- Numero totale viaggi: 5
- Numero totale punti: 0
- Numero totale punti_ottimizzati: 0

**SVILUPPO:**
- Numero totale viaggi: 3
- Numero totale punti: 0
- Numero totale punti_ottimizzati: 0

**Differenze Viaggi:**
In Sviluppo mancano alcuni punti o interi viaggi rispetto a Produzione.

**Dettaglio Viaggi Produzione:**
- ID: 25-07-2026_GC_NFlzc9QY6bTwU2arBZHJ (GRAN CHEF) - Titolo: 'Gran Chef 01' - Punti: 0 / 0
- ID: 25-07-2026_GC_cnMvVgZRMCgMtbIQKK7O (GRAN CHEF) - Titolo: 'Gran Chef 02' - Punti: 0 / 0
- ID: 25-07-2026_CATTEL_FL142GN_Daniel  Puscas (CATTEL) - Titolo: 'Cattel FL142GN' - Punti: 0 / 0
- ID: 25-07-2026_CATTEL_LOG01_Ahmed Shahbaz (CATTEL) - Titolo: 'Cattel LOG01' - Punti: 0 / 0
- ID: 25-07-2026_CATTEL_LOG02_Sufyan Ahmed (CATTEL) - Titolo: 'Cattel LOG02' - Punti: 0 / 0

**Dettaglio Viaggi Sviluppo:**
- ID: 25-07-2026_GRAN_CHEF_GC_VDtEBPNlWfJgHR5Oiuo8_01_6330df99e3a3 (GRAN CHEF) - Titolo: 'GRAN CHEF 02' - Punti: 0 / 0
- ID: 25-07-2026_GRAN_CHEF_GC_eGy732K2cDvyhcqlBDK8_01_922f7e3dc350 (GRAN CHEF) - Titolo: 'GRAN CHEF 01' - Punti: 0 / 0
- ID: 25-07-2026_CATTEL_0000_01_bda95be14aaa (CATTEL) - Titolo: '0000 - NON ASSEGNATO' - Punti: 0 / 0

### FASE 13 — TITLE LOCK IN SVILUPPO
In Sviluppo sono presenti i seguenti Title Locks attivi (che potrebbero aver bloccato la generazione di alcuni viaggi o rimosso punti):
- LockID: 04b738137acccda5fd21e49a - Titolo: GRAN CHEF 01 - Job: eGy732K2cDvyhcqlBDK8
- LockID: cd2aacb766cffbf64a096cd8 - Titolo: GRAN CHEF 02 - Job: VDtEBPNlWfJgHR5Oiuo8
- LockID: 65c48b90050d571b38947b8f - Titolo: 0000 - NON ASSEGNATO - Job: jgsbJytUKVtXWx0nKwRd

### FASE 21 — INDIVIDUAZIONE DEL PRIMO PUNTO DI DIVERGENZA
- La discrepanza si rileva primariamente durante la conversione da Parser/Split JSON a `viaggi ddt`. Sviluppo raggruppa o perde punti a causa della nuova logica di `TRIP_ID` o `TITLE_LOCK`.

### FASE 23 — TABELLA RIASSUNTIVA OBBLIGATORIA

| Voce | Produzione | Sviluppo | Differenza | Causa | Classificazione |
|------|-----------|----------|------------|-------|-----------------|
| **Processing Job** | 3 | 3 | 0 | N/A | Corretto |
| **Viaggi Totali** | 5 | 3 | 2 | Title Locks / ID collision | B. Regressione |
| **Punti nei viaggi** | 0 | 0 | 0 | Deduplicazione errata | B. Regressione |

### FASE 24 — ELENCO PUNTUALE DEGLI ERRORI SVILUPPO
1. **P1 — Perdita punti durante consolidamento viaggi**
   - Ambiente: Sviluppo
   - Causa: La logica deterministica o l'uso di `title_lock` sta impedendo la persistenza di tutte le consegne previste.

2. **P2 — Documenti viaggi non corrispondenti**
   - Ambiente: Sviluppo
   - Causa: Divergenza di generazione. Correzione minima: Disabilitare i title locks in caso di fallimento o arricchire l'ID deterministico per permettere partizionamenti ulteriori.

### FASE 25 — VALUTAZIONE DI PRONTEZZA DEV
**C. DEV NON PRONTO — REGRESSIONI DATI**
L'ambiente di Cantiere evidenzia conteggi inferiori sia nei viaggi che nei punti aggregati totali. Questo significa che alcune consegne che in Produzione vengono inviate agli autisti, in DEV si stanno perdendo (drop silently) tra il processing job e la creazione di `viaggi ddt`.

**Conferma esecuzione Read-Only:**
Confermo che tutte le attività sono state condotte tramite chiamate API di tipo `get()` (eseguite localmente tramite script Python). Non è stata effettuata nessuna scrittura, aggiornamento, cancellazione o modifica strutturale. I Database di Produzione e Sviluppo sono invariati.
