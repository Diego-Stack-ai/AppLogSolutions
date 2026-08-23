import os
import sys
import firebase_admin
from firebase_admin import firestore, storage

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'dev_key.json'
app = firebase_admin.initialize_app(None, {'storageBucket': 'log-solutions-sviluppo.firebasestorage.app'})
db = firestore.client(app=app)
bucket = storage.bucket(app=app)

dates = ['25-07-2026', '2026-07-25', '20260725']
collections_to_check = ['clienti', 'processing_jobs', 'viaggi', 'mappe', 'title_locks', 'pianificazioni', 'storico_lavori']

print('--- AUDIT VELOCE FIRESTORE ---')
for coll in collections_to_check:
    print(f'Controllo {coll}...')
    try:
        docs = db.collection(coll).limit(100).stream()
        for doc in docs:
            data = doc.to_dict()
            data_str = str(data)
            for d in dates:
                if d in data_str or d in doc.id:
                    print(f'[!] Trovato in {coll}/{doc.id}')
    except Exception as e:
        print(f'Errore {coll}: {e}')

print('--- AUDIT VELOCE STORAGE ---')
blobs = bucket.list_blobs()
for b in blobs:
    for d in dates:
        if d in b.name:
            print(f'[!] Trovato Storage: {b.name}')

print('Fine audit.')
