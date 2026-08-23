import os
import sys

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'dev_key.json'
import firebase_admin
from firebase_admin import firestore, storage

app = firebase_admin.initialize_app(None, {'storageBucket': 'log-solutions-sviluppo.firebasestorage.app'})
db = firestore.client(app=app)
bucket = storage.bucket(app=app)

dates_to_find = ['25-07-2026', '2026-07-25']

print("--- INIZIO SCANSIONE GLOBALE 25 LUGLIO ---", flush=True)

# 1. Scansione Storage
print("\n[STORAGE]", flush=True)
blobs = bucket.list_blobs()
storage_count = 0
for b in blobs:
    for d in dates_to_find:
        if d in b.name:
            print(f"  Trovato in Storage: {b.name}", flush=True)
            storage_count += 1
            break
if storage_count == 0:
    print("  Nessun file trovato in Storage.", flush=True)

# 2. Scansione Firestore
print("\n[FIRESTORE - CERCO SOLO IN CLIENTI E ROOT]", flush=True)

# We will just list all collections and check documents.
# For a faster scan, we only check the main collections
main_collections = ["clienti", "utenti", "configs"]
for coll_name in main_collections:
    print(f"Scansione collezione: {coll_name}", flush=True)
    coll_ref = db.collection(coll_name)
    docs = coll_ref.stream()
    for doc in docs:
        doc_str = str(doc.to_dict())
        for d in dates_to_find:
            if d in doc.id or d in doc_str:
                print(f"  Trovato in Firestore: {doc.reference.path}", flush=True)
        # subcollections
        try:
            for subcoll in doc.reference.collections():
                subdocs = subcoll.stream()
                for sdoc in subdocs:
                    sdoc_str = str(sdoc.to_dict())
                    for d in dates_to_find:
                        if d in sdoc.id or d in sdoc_str:
                            print(f"  Trovato in Firestore Subcoll: {sdoc.reference.path}", flush=True)
        except Exception:
            pass

print("\n--- FINE SCANSIONE ---", flush=True)
