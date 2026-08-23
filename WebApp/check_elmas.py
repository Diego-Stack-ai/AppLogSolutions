import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('dev_key.json')
app = firebase_admin.initialize_app(cred)
db = firestore.client()

presenze = db.collection('presenze').where('data', '==', '2026-07-04').where('autistaNome', '==', 'Shehu Elmas').stream()
for doc in presenze:
    print(f"ID Doc: {doc.id}")
    d = doc.to_dict()
    for k, v in d.items():
        print(f"  {k}: {repr(v)}")
