import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('dev_key.json')
app = firebase_admin.initialize_app(cred)
db = firestore.client()

clienti = db.collection('clienti').stream()

for cliente in clienti:
    viaggi = db.collection('clienti').document(cliente.id).collection('viaggi ddt').stream()
    c = 0
    gc_count = 0
    for doc in viaggi:
        d = doc.to_dict()
        dDate = d.get('data_lavoro', d.get('data_consegna', d.get('data', '')))
        if '-07-2026' in dDate or dDate.startswith('2026-07'):
            c += 1
            if 'GC' in str(d.get('id_zona', '')) or 'GRAN CHEF' in str(d.get('nome_giro', '')).upper():
                gc_count += 1
    if c > 0:
        print(f"Tenant '{cliente.id}': {c} viaggi a Luglio (di cui {gc_count} sembrano associati a GRAN CHEF tramite id_zona/nome_giro)")

