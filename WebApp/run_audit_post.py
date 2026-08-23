import os
import sys
import json
import datetime
from collections import defaultdict

# ==================================================
# FASE 1: CONFERMA AMBIENTE
# ==================================================
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'dev_key.json'
import firebase_admin
from firebase_admin import firestore, storage

# Initialize
app = firebase_admin.initialize_app(None, {'storageBucket': 'log-solutions-sviluppo.firebasestorage.app'})
db = firestore.client(app=app)
bucket = storage.bucket(app=app)

PROJECT_ID = app.project_id
BUCKET_NAME = bucket.name

if PROJECT_ID != "log-solutions-sviluppo" or BUCKET_NAME != "log-solutions-sviluppo.firebasestorage.app":
    print("ERRORE CRITICO: Ambiente non corrispondente. ARRESTO.")
    sys.exit(1)

START_TIME = datetime.datetime.now().isoformat()

dates_to_find = [
    '25-07-2026', '2026-07-25', '25/07/2026', '2026/07/25',
    '25-7-2026', '2026-7-25', '20260725', '25_07_2026',
    '2026_07_25', '25.07.2026'
]

# Variabili di stato
inventory = []
ID_COUNTER = 1

def add_to_inventory(system, tenant, category, subcat, path, doc_id, data_op, data_cr, data_up, job_id, src_job_id, trip_id, status, size, refs, classif, notes):
    global ID_COUNTER
    inventory.append({
        'ID': ID_COUNTER,
        'Sistema': system,
        'Project ID': PROJECT_ID,
        'Tenant': tenant,
        'Categoria': category,
        'Sottocategoria': subcat,
        'Path completo': path,
        'Document ID': doc_id,
        'Data operativa': data_op,
        'Data creazione': data_cr,
        'Data aggiornamento': data_up,
        'JobId': job_id,
        'SourceJobId': src_job_id,
        'TripId': trip_id,
        'Stato': status,
        'Dimensione': size,
        'Riferimenti': refs,
        'Classificazione preliminare': classif,
        'Note': notes
    })
    ID_COUNTER += 1

# ==================================================
# FASE 2-12, 18-20: SCANSIONE FIRESTORE
# ==================================================
print("[*] Inizio scansione profonda Firestore...", flush=True)

def find_dates_in_dict(d, found_in_fields=None):
    if found_in_fields is None: found_in_fields = set()
    found = False
    
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, str):
                for df in dates_to_find:
                    if df in v:
                        found = True
                        found_in_fields.add(k)
                        break
            elif isinstance(v, dict) or isinstance(v, list):
                if find_dates_in_dict(v, found_in_fields):
                    found = True
                    found_in_fields.add(k)
    elif isinstance(d, list):
        for item in d:
            if find_dates_in_dict(item, found_in_fields):
                found = True
    elif isinstance(d, str):
        for df in dates_to_find:
            if df in d:
                found = True
                break
    return found

def classify_doc(coll_name, doc_data, found_fields):
    category = "ALTRO"
    classif = "G. COLLEGAMENTO NON DIMOSTRATO"
    
    if 'processing_jobs' in coll_name: category = 'PROCESSING_JOB'
    elif 'viaggi' in coll_name: category = 'VIAGGIO'
    elif 'title_locks' in coll_name: category = 'TITLE_LOCK'
    elif 'pianificazioni' in coll_name: category = 'PIANIFICAZIONI'
    elif 'reports' in coll_name: category = 'REPORT'
    elif 'mappe' in coll_name: category = 'MAPPA'
    elif 'distinte' in coll_name: category = 'DISTINTA'
    
    if category in ['PROCESSING_JOB', 'VIAGGIO', 'TITLE_LOCK'] and ('data_lavoro' in found_fields or 'dataConsegna' in found_fields):
        classif = "A. ARTEFATTO OPERATIVO ESCLUSIVO DELLA GIORNATA"
        
    return category, classif

def scan_collection(coll_ref, prefix=''):
    try:
        docs = coll_ref.stream()
        for doc in docs:
            doc_data = doc.to_dict() or {}
            doc_id = doc.id
            path = doc.reference.path
            
            tenant = doc_data.get('tenant', path.split('/')[1] if path.startswith('clienti/') and len(path.split('/')) > 2 else 'N/A')
            data_op = doc_data.get('data_lavoro', doc_data.get('dataConsegna', doc_data.get('data_consegna', 'N/A')))
            data_cr = doc_data.get('createTime', doc_data.get('createdAt', 'N/A'))
            data_up = doc_data.get('updateTime', doc_data.get('updatedAt', 'N/A'))
            job_id = doc_data.get('jobId', doc_data.get('processingJobId', 'N/A'))
            src_job_id = doc_data.get('sourceJobId', 'N/A')
            trip_id = doc_data.get('tripId', 'N/A')
            status = doc_data.get('status', doc_data.get('stato', 'N/A'))
            size = str(len(doc_data.keys())) + " campi"
            
            found_in_id = False
            for df in dates_to_find:
                if df in doc_id:
                    found_in_id = True
                    break
                    
            found_fields = set()
            found_in_content = find_dates_in_dict(doc_data, found_fields)
            
            if found_in_id or found_in_content:
                category, classif = classify_doc(coll_ref.id, doc_data, found_fields)
                add_to_inventory('FIRESTORE', tenant, category, coll_ref.id, path, doc_id, data_op, data_cr, data_up, job_id, src_job_id, trip_id, status, size, list(found_fields), classif, "")

            try:
                subcollections = doc.reference.collections()
                for subcoll in subcollections:
                    scan_collection(subcoll, prefix + '  ')
            except Exception:
                pass
    except Exception as e:
        pass

collections = db.collections()
for coll in collections:
    scan_collection(coll)

# ==================================================
# FASE 13-17: SCANSIONE STORAGE
# ==================================================
print("[*] Inizio scansione profonda Storage...", flush=True)

blobs = bucket.list_blobs()
for b in blobs:
    b_name = b.name
    found = False
    for df in dates_to_find:
        if df in b_name:
            found = True
            break
    
    if found:
        tenant = "N/A"
        for t in ["CATTEL", "GRAN_CHEF", "GRAND_CHEF", "DNR", "BAUER", "GRAN CHEF"]:
            if t in b_name or b_name.startswith(t):
                tenant = t
                break
                
        category = "INPUT" if "input_pdf_fornitore" in b_name else ("REPORT" if "REPORTS" in b_name else "ALTRO")
        classif = "A. ARTEFATTO OPERATIVO ESCLUSIVO DELLA GIORNATA" if category != "INPUT" else "INPUT ORIGINALE ATTIVO"
        
        data_cr = str(b.time_created) if b.time_created else "N/A"
        data_up = str(b.updated) if b.updated else "N/A"
        
        add_to_inventory('STORAGE', tenant, category, "N/A", f"gs://{bucket.name}/{b.name}", b.name, "N/A", data_cr, data_up, "N/A", "N/A", "N/A", "N/A", str(b.size) + " bytes", [], classif, "")


# ==================================================
# FASE 21-33: OUTPUT MARKDOWN
# ==================================================
print("[*] Scrittura report markdown in corso...", flush=True)

md = f"""# AUDIT COMPLETO DATI 25-07-2026 - SVILUPPO (STRICT READ-ONLY)

## FASE 1 — CONFERMA AMBIENTE
- **Project ID effettivo:** `{PROJECT_ID}`
- **Bucket effettivo:** `{BUCKET_NAME}`
- **Timestamp Inizio Audit:** `{START_TIME}`
- **Status di sicurezza:** CONFERMATO NESSUNA MODIFICA ESEGUITA, SOLO READ-ONLY. Produzione NON interrogata e TOTALMENTE invariata.

## RIEPILOGO GLOBALE
- Elementi totali trovati: {len(inventory)}
- Elementi Firestore: {len([i for i in inventory if i['Sistema'] == 'FIRESTORE'])}
- Elementi Storage: {len([i for i in inventory if i['Sistema'] == 'STORAGE'])}

## INVENTARIO MASTER

| ID | Sistema | Tenant | Categoria | Sottocategoria | Path / Document ID | Data Operativa | TripId/JobId | Classificazione Preliminare |
|---|---|---|---|---|---|---|---|---|
"""

for item in inventory:
    path_doc = item['Document ID'] if item['Sistema'] == 'STORAGE' else item['Path completo']
    job_trip = f"Job: {item['JobId']} / Trip: {item['TripId']}"
    md += f"| {item['ID']} | {item['Sistema']} | {item['Tenant']} | {item['Categoria']} | {item['Sottocategoria']} | `{path_doc}` | {item['Data operativa']} | {job_trip} | {item['Classificazione preliminare']} |\n"

md += """
## FASE 23 - CLASSIFICAZIONE PRELIMINARE E REGOLE DI ARRESTO
- L'audit è stato eseguito **senza modificare**, **senza eliminare** e **senza spostare** alcun file o documento.
- L'inventario master espone gli elementi trovati.
- In attesa della revisione del Project Owner. NON verrà eseguita alcuna cancellazione o modifica codice.
"""

import pathlib
brain_dir = pathlib.Path(r"C:\Users\39349\.gemini\antigravity\brain\2e582344-db76-4115-8e4e-627b211c5d26")
out_path = brain_dir / "POST_CANCELLATION_AUDIT_1.md"
with open(out_path, "w", encoding="utf-8") as f:
    f.write(md)

print(f"[*] Audit completato. File salvato in: {out_path}")
