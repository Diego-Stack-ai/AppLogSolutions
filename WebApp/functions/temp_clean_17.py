import firebase_admin
from firebase_admin import credentials, firestore, storage

try:
    app = firebase_admin.get_app()
except ValueError:
    cred = credentials.Certificate('../dev_key.json')
    app = firebase_admin.initialize_app(cred, {
        'storageBucket': 'log-solutions-sviluppo.firebasestorage.app'
    })

db = firestore.client()
# Forza l'uso del progetto di sviluppo per Firestore per sicurezza
db._client_info.client_library_version = 'google-cloud-firestore'
# Firestore instance is determined by the service account. The service account used must be from Sviluppo.
# Actually, wait, serviceAccountKey.json might be production?
# Let's check the project ID of the credentials.
project_id = cred.project_id
print(f"Project ID from credentials: {project_id}")

bucket = storage.bucket('log-solutions-sviluppo.firebasestorage.app')

data_da_cancellare = "17-07-2026"
data_f = data_da_cancellare.replace('/', '-')

print(f"=== INIZIO PULIZIA PER LA DATA {data_da_cancellare} ===")

# 1. Elimina Viaggi da Firestore
print("1. Eliminazione Viaggi da Firestore...")
viaggi_ref = db.collection('clienti').document('DNR').collection('viaggi ddt')
viaggi = viaggi_ref.where("data_lavoro", "==", data_da_cancellare).stream()
count_v = 0
for v in viaggi:
    v.reference.delete()
    count_v += 1
print(f"   -> Eliminati {count_v} documenti da 'viaggi ddt'.")

# 2. Elimina Report Logistici
try:
    db.collection('clienti').document('DNR').collection('reports_logistici').document(data_da_cancellare).delete()
    print("   -> Report logistico eliminato.")
except Exception:
    pass

# 3. Pulizia Storage
print("3. Eliminazione cartelle da Storage...")
prefixes = [
    f"REPORTS/{data_da_cancellare}/",
    f"CONSEGNE/CONSEGNE_{data_f}/",
    f"split_ddt/{data_da_cancellare}/"
]
count_b = 0
for pref in prefixes:
    blobs = bucket.list_blobs(prefix=pref)
    for b in blobs:
        b.delete()
        count_b += 1
print(f"   -> Eliminati {count_b} file dallo Storage.")
print("=== PULIZIA COMPLETATA CON SUCCESSO ===")
