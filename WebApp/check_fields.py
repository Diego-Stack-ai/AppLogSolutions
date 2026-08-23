import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('dev_key.json')
app = firebase_admin.initialize_app(cred)
db = firestore.client()

doc = next(db.collection('clienti').document('DNR').collection('viaggi ddt').limit(1).stream())
print("Keys del documento:")
for k, v in doc.to_dict().items():
    print(f"{k}: {type(v)}")
