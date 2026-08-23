import firebase_admin
from firebase_admin import credentials, firestore
import json
import sys

cred = credentials.Certificate('prod_key.json')
firebase_admin.initialize_app(cred)

db = firestore.client()

data = '2026-07-22'
print(f"Indagando la data {data} su log-solution-60007 (Produzione)...")

# Cerchiamo in clienti/DNR/reports_logistici/2026-07-22/viaggi
viaggi_ref = db.collection('clienti').document('DNR').collection('reports_logistici').document(data).collection('viaggi')
viaggi = viaggi_ref.stream()

found = False
for v in viaggi:
    v_dict = v.to_dict()
    print(f"Viaggio ID: {v.id}")
    if 'mezzo' in v_dict:
        print(f"  Mezzo associato: {v_dict.get('mezzo')}")
    if 'targa' in v_dict:
        print(f"  Targa: {v_dict.get('targa')}")
    
    # Check if FL142GN is anywhere in the dict
    v_str = json.dumps(v_dict).lower()
    if 'fl142gn' in v_str:
        print("  *** TROVATO FL142GN NEL VIAGGIO ***")
        found = True

# Also check document itself
doc_ref = db.collection('clienti').document('DNR').collection('reports_logistici').document(data)
doc_snap = doc_ref.get()
if doc_snap.exists:
    d_dict = doc_snap.to_dict()
    print(f"\nDocumento principale per {data} esiste.")
    d_str = json.dumps(d_dict).lower()
    if 'fl142gn' in d_str:
        print("  *** TROVATO FL142GN NEL DOCUMENTO PRINCIPALE ***")
        found = True
else:
    print(f"\nNessun documento principale per {data}.")

if not found:
    print("\nIl mezzo FL142GN non e' presente nei viaggi o nel documento di questa data.")
