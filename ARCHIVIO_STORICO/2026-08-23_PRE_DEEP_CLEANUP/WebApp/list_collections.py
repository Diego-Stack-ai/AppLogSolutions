import firebase_admin
from firebase_admin import credentials, firestore

cred_prod = credentials.Certificate('prod_key.json')
app_prod = firebase_admin.initialize_app(cred_prod, name='prod3')
db = firestore.client(app=app_prod)

collections = db.collection('clienti').document('GRAN CHEF').collections()
for c in collections:
    print(c.id)
