import firebase_admin
from firebase_admin import credentials, firestore
try:
    firebase_admin.initialize_app()
except ValueError:
    pass
db = firestore.client()
docs = db.collection('dipendenti').stream()
for d in docs:
    data = d.to_dict()
    print(f"{data.get('nome', '')} {data.get('cognome', '')}: email={data.get('email', '')}")
