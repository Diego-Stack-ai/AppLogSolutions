import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('dev_key.json')
app = firebase_admin.initialize_app(cred)
db = firestore.client()

viaggi = db.collection('clienti').document('DNR').collection('viaggi ddt').stream()
for i, doc in enumerate(viaggi):
    if i > 5: break
    print(f"--- Doc {i} ---")
    d = doc.to_dict()
    for k, v in d.items():
        if k not in ['punti', 'punti_ottimizzati']:
            print(f"{k}: {v}")
