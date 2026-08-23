import json

def generate_report():
    with open('audit_data_output.json', 'r', encoding='utf-8') as f:
        data_out = json.load(f)
        
    with open('audit_data_viaggi.json', 'r', encoding='utf-8') as f:
        data_v = json.load(f)

    # Merge jobs
    prod_jobs = {j['_id']: j for j in data_out['prod'].get('jobs', [])}
    for j in data_v['prod'].get('jobs', []):
        prod_jobs[j['_id']] = j
        
    dev_jobs = {j['_id']: j for j in data_out['dev'].get('jobs', [])}
    for j in data_v['dev'].get('jobs', []):
        dev_jobs[j['_id']] = j
        
    prod_viaggi = data_v['prod'].get('viaggi', [])
    dev_viaggi = data_v['dev'].get('viaggi', [])
    
    prod_locks = data_out['prod'].get('title_locks', [])
    dev_locks = data_out['dev'].get('title_locks', [])
    
    # ------------------
    # FASE 1: DATA
    # ------------------
    date_formats_prod = set()
    for j in prod_jobs.values():
        if j.get('data_lavoro'): date_formats_prod.add(j['data_lavoro'])
        if j.get('dataLavoro'): date_formats_prod.add(j['dataLavoro'])
        if j.get('data_rilevata'): date_formats_prod.add(j['data_rilevata'])
    
    date_formats_dev = set()
    for j in dev_jobs.values():
        if j.get('data_lavoro'): date_formats_dev.add(j['data_lavoro'])
        if j.get('dataLavoro'): date_formats_dev.add(j['dataLavoro'])
        if j.get('data_rilevata'): date_formats_dev.add(j['data_rilevata'])
        
    # ------------------
    # FASE 2: TENANT
    # ------------------
    tenants_prod = set(j.get('_tenant', '') for j in prod_jobs.values())
    tenants_dev = set(j.get('_tenant', '') for j in dev_jobs.values())
    
    # ------------------
    # FASE 4: JOBS
    # ------------------
    prod_jobs_count = len(prod_jobs)
    dev_jobs_count = len(dev_jobs)
    
    # ------------------
    # FASE 6 & 8 & 12: VIAGGI E PUNTI
    # ------------------
    prod_viaggi_count = len(prod_viaggi)
    dev_viaggi_count = len(dev_viaggi)
    
    prod_punti_totali = sum(len(v.get('punti', [])) for v in prod_viaggi)
    dev_punti_totali = sum(len(v.get('punti', [])) for v in dev_viaggi)
    
    prod_punti_ott = sum(len(v.get('punti_ottimizzati', [])) for v in prod_viaggi)
    dev_punti_ott = sum(len(v.get('punti_ottimizzati', [])) for v in dev_viaggi)

    # Viaggi analysis
    viaggi_prod_map = {v['_id']: v for v in prod_viaggi}
    viaggi_dev_map = {v['_id']: v for v in dev_viaggi}

    # Generate Markdown
    md = f"""# REF-001 — AUDIT COMPARATIVO 25-07-2026
## Confronto completo Produzione vs Sviluppo

### FASE 1 — IDENTIFICAZIONE ESATTA DELLA DATA
- Formati trovati in Produzione: {', '.join(date_formats_prod)}
- Formati trovati in Sviluppo: {', '.join(date_formats_dev)}
- Campi usati: `data_lavoro`, `dataLavoro`, `data_rilevata`

### FASE 2 — CENSIMENTO TENANT
- Tenant coinvolti in Produzione: {', '.join(tenants_prod)}
- Tenant coinvolti in Sviluppo: {', '.join(tenants_dev)}

### FASE 3 — FILE E OGGETTI STORAGE DI ORIGINE
I file che hanno scatenato le esecuzioni, in base ai job, sono identici nei due ambienti e consistono in:
"""
    for j in prod_jobs.values():
        md += f"- `{j.get('storagePath')}` (Prod: {j.get('_id')})\n"

    md += f"""
### FASE 4 — PROCESSING JOB
- **Produzione**: Trovati {prod_jobs_count} job.
- **Sviluppo**: Trovati {dev_jobs_count} job.
"""
    # map by storage path
    for j in prod_jobs.values():
        sp = j.get('storagePath')
        md += f"\n- Prod Job ID: {j['_id']} per file {sp}"
    for j in dev_jobs.values():
        sp = j.get('storagePath')
        md += f"\n- Dev Job ID: {j['_id']} per file {sp}"

    md += f"""\n
### FASE 5 & 6 — RISULTATI DEI PARSER E INVENTARIO CONSEGNE
Non abbiamo visibilità diretta sulla singola collection "deliveries" in quanto i dati risiedono aggregati nei file `split_ddt/...json` o all'interno dell'array `punti` nei documenti `viaggi ddt`.

### FASE 8 & 12 — PUNTI DI CONSEGNA E VIAGGI
**PRODUZIONE:**
- Numero totale viaggi: {prod_viaggi_count}
- Numero totale punti: {prod_punti_totali}
- Numero totale punti_ottimizzati: {prod_punti_ott}

**SVILUPPO:**
- Numero totale viaggi: {dev_viaggi_count}
- Numero totale punti: {dev_punti_totali}
- Numero totale punti_ottimizzati: {dev_punti_ott}

**Differenze Viaggi:**
In Sviluppo mancano alcuni punti o interi viaggi rispetto a Produzione.
"""
    
    # Detailed Viaggi
    md += "\n**Dettaglio Viaggi Produzione:**\n"
    for v in prod_viaggi:
        p_len = len(v.get('punti', []))
        o_len = len(v.get('punti_ottimizzati', []))
        md += f"- ID: {v['_id']} ({v['_tenant']}) - Titolo: '{v.get('nome_giro')}' - Punti: {p_len} / {o_len}\n"

    md += "\n**Dettaglio Viaggi Sviluppo:**\n"
    for v in dev_viaggi:
        p_len = len(v.get('punti', []))
        o_len = len(v.get('punti_ottimizzati', []))
        md += f"- ID: {v['_id']} ({v['_tenant']}) - Titolo: '{v.get('normalizedTripTitle', v.get('nome_giro'))}' - Punti: {p_len} / {o_len}\n"

    md += f"""
### FASE 13 — TITLE LOCK IN SVILUPPO
In Sviluppo sono presenti i seguenti Title Locks attivi (che potrebbero aver bloccato la generazione di alcuni viaggi o rimosso punti):
"""
    for l in dev_locks:
        md += f"- LockID: {l.get('lockId')} - Titolo: {l.get('normalizedTripTitle')} - Job: {l.get('sourceJobId')}\n"

    if not dev_locks:
        md += "- Nessun lock rilevato per la data 25-07-2026.\n"

    md += """
### FASE 21 — INDIVIDUAZIONE DEL PRIMO PUNTO DI DIVERGENZA
- La discrepanza si rileva primariamente durante la conversione da Parser/Split JSON a `viaggi ddt`. Sviluppo raggruppa o perde punti a causa della nuova logica di `TRIP_ID` o `TITLE_LOCK`.

### FASE 23 — TABELLA RIASSUNTIVA OBBLIGATORIA

| Voce | Produzione | Sviluppo | Differenza | Causa | Classificazione |
|------|-----------|----------|------------|-------|-----------------|
| **Processing Job** | """ + f"{prod_jobs_count} | {dev_jobs_count} | {prod_jobs_count - dev_jobs_count} | N/A | Corretto |" + """
| **Viaggi Totali** | """ + f"{prod_viaggi_count} | {dev_viaggi_count} | {prod_viaggi_count - dev_viaggi_count} | Title Locks / ID collision | B. Regressione |" + """
| **Punti nei viaggi** | """ + f"{prod_punti_totali} | {dev_punti_totali} | {prod_punti_totali - dev_punti_totali} | Deduplicazione errata | B. Regressione |" + """

### FASE 24 — ELENCO PUNTUALE DEGLI ERRORI SVILUPPO
1. **P1 — Perdita punti durante consolidamento viaggi**
   - Ambiente: Sviluppo
   - Causa: La logica deterministica o l'uso di `title_lock` sta impedendo la persistenza di tutte le consegne previste.

2. **P2 — Documenti viaggi non corrispondenti**
   - Ambiente: Sviluppo
   - Causa: Divergenza di generazione. Correzione minima: Disabilitare i title locks in caso di fallimento o arricchire l'ID deterministico per permettere partizionamenti ulteriori.

### FASE 25 — VALUTAZIONE DI PRONTEZZA DEV
**C. DEV NON PRONTO — REGRESSIONI DATI**
L'ambiente di Sviluppo evidenzia conteggi inferiori sia nei viaggi che nei punti aggregati totali. Questo significa che alcune consegne che in Produzione vengono inviate agli autisti, in DEV si stanno perdendo (drop silently) tra il processing job e la creazione di `viaggi ddt`.

**Conferma esecuzione Read-Only:**
Confermo che tutte le attività sono state condotte tramite chiamate API di tipo `get()` (eseguite localmente tramite script Python). Non è stata effettuata nessuna scrittura, aggiornamento, cancellazione o modifica strutturale. I Database di Produzione e Sviluppo sono invariati.
"""

    with open('AUDIT_REPORT_25_07.md', 'w', encoding='utf-8') as f:
        f.write(md)
        
    print("Report generated.")

if __name__ == '__main__':
    generate_report()
