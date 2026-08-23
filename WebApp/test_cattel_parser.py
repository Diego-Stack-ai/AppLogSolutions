import os
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'dev_key.json'

import sys
sys.path.append('functions')
import main as backend
import firebase_admin
from firebase_admin import credentials, firestore, storage
import pandas as pd

if not firebase_admin._apps:
    app = firebase_admin.initialize_app()
else:
    app = firebase_admin.get_app()

db = firestore.client(app=app)
bucket = storage.bucket('log-solutions-sviluppo.appspot.com')

with open('CATTEL_25-07-2026_ReportPianificazione.xlsx', 'rb') as f:
    excel_bytes = f.read()

# Get some db_mappati
db_mappati = {}
for doc in db.collection('clienti').document('CATTEL').collection('raccolta clienti').limit(500).stream():
    db_mappati[doc.id.lower()] = doc.to_dict()

res = backend._processa_excel_cattel_core_logic(excel_bytes, db_mappati, "25-07-2026", "TEST_JOB")

deliveries = res['deliveries']
print(f"Deliveries trovate: {len(deliveries)}")

# Test parser outputs
fl142gn_found = False
log01_found = False
log02_found = False

print("\nTabella Verifica Parser (prime righe per giro):")
print(f"{'Codice':<15} | {'Targa':<10} | {'Autista':<15} | {'zona_cod calcolato':<25}")

test_delivs = []
for d in deliveries:
    targa = d.get('cattel_zona_viaggio', '')
    if targa == 'FL142GN' and not fl142gn_found:
        test_delivs.append(d)
        fl142gn_found = True
    elif targa == 'LOG01' and not log01_found:
        test_delivs.append(d)
        log01_found = True
    elif targa == 'LOG02' and not log02_found:
        test_delivs.append(d)
        log02_found = True
        
for d in test_delivs:
    print(f"{d['codice_consegna']:<15} | {d['cattel_zona_viaggio']:<10} | {d['autista']:<15} | {d.get('zona', 'MANCANTE'):<25}")

# Now build punti_map logic
print("\n--- Test Punti Map / Master JSON ---")
punti_map = {}
for ddt in test_delivs:
    # mock of what main.py does:
    cod = ddt.get('codice_consegna')
    cod_l = str(cod).strip().lower()
    cliente_info = db_mappati.get(cod_l)
    chiave = cod
    
    # We expect `ddt.get('zona')` to have the value
    z = ddt.get('zona') or ((cliente_info.get('codice_zona') or cliente_info.get('zona') or '0000') if cliente_info else '0000')
    
    punti_map[chiave] = {
        "zona": z,
        "codice_consegna": cod
    }
    print(f"Punto map {cod}: zona assegnata = {z}")

# Zone grouping
from collections import defaultdict
zone_dict = defaultdict(list)
for p in punti_map.values():
    z_id = p.get("zona", "0000")
    if not z_id: z_id = "0000"
    zone_dict[z_id].append(p)

cattel_keys = sorted([k for k in zone_dict.keys() if k.startswith("CATTEL_")])
print("\n--- Zone Create ---")
for idx, zid in enumerate(cattel_keys, start=1):
    parts = zid.split('_')
    targa_label = parts[1] if len(parts) > 2 else f"Viaggio {idx}"
    print(f"id_zona finale: {zid} -> nome_giro: Cattel {targa_label}, punti: {len(zone_dict[zid])}")
