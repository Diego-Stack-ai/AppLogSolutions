import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('dev_key.json')
app = firebase_admin.initialize_app(cred)
db = firestore.client()

presenze = db.collection('presenze').where('data', '==', '19-07-2026').stream()
c = 0
for doc in presenze:
    d = doc.to_dict()
    print(f"Data: {d.get('data')}, Autista: {d.get('autistaNome')}, Targa: {d.get('targa')}, Viaggio: {d.get('viaggio')}, Cliente: {d.get('cliente')}")
    c += 1
if c == 0:
    print("Nessun record trovato per il 19-07-2026.")
