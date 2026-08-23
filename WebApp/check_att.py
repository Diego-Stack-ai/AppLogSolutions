import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('prod_key.json')
app = firebase_admin.initialize_app(cred)
db = firestore.client(app=app)
docs = db.collection('presenze').where('mese', '==', '2026-07').limit(500).stream()
for doc in docs:
    d = doc.to_dict()
    if d.get('attivitaAggiuntive'):
        print(d.get('attivitaAggiuntive'))
        break
