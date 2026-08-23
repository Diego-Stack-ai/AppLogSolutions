import json
import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('dev_key.json')
app = firebase_admin.initialize_app(cred)
db = firestore.client()

print('=== PRESENZE LUGLIO ===')
presenze = db.collection('presenze').where('mese', '==', '2026-07').stream()
c_p = 0
for doc in presenze:
    d = doc.to_dict()
    print(f"Data: {d.get('data')}, Autista: {d.get('autistaNome')}, Targa: {d.get('targa')}, Viaggio: {d.get('viaggio')}, Cliente: {d.get('cliente')}")
    c_p += 1
print(f"Totale presenze luglio: {c_p}\n")

print('=== VIAGGI LUGLIO (DNR) ===')
viaggi = db.collection('clienti').document('DNR').collection('viaggi ddt').stream()
c_v = 0
for doc in viaggi:
    d = doc.to_dict()
    dDate = d.get('data_lavoro', d.get('data_consegna', d.get('data', '')))
    if '-07-2026' in dDate or dDate.startswith('2026-07'):
        print(f"Data: {dDate}, ClienteFatt: {d.get('cliente_fatturazione', d.get('cliente'))}, Autista: {d.get('autista')}, Colli: {d.get('colli')}, Mezzo: {d.get('mezzo')}")
        c_v += 1
print(f"Totale viaggi luglio: {c_v}")
