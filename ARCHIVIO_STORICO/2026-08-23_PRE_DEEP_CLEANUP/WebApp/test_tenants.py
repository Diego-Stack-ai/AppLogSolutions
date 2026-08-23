import os
import sys

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'dev_key.json'
import firebase_admin
from firebase_admin import firestore

app = firebase_admin.initialize_app()
db = firestore.client(app=app)
clienti = db.collection('clienti').stream()
print([c.id for c in clienti])
