import argparse
import os
import sys

# DEVE ESSERE IN DRY RUN a meno che non passiamo --execute
parser = argparse.ArgumentParser()
parser.add_argument('--execute', action='store_true', help='Execute deletion')
args = parser.parse_args()

os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'dev_key.json'
import firebase_admin
from firebase_admin import firestore, storage

# 1. Verifica ambiente e project id
try:
    app = firebase_admin.initialize_app(None, {'storageBucket': 'log-solutions-sviluppo.firebasestorage.app'})
    pid = app.project_id
except Exception:
    app = firebase_admin.get_app()
    pid = app.project_id

if pid == "log-solution-60007":
    print("ERRORE: Project ID è Produzione! Arresto.")
    sys.exit(1)

if "sviluppo" not in str(app.project_id) and "sviluppo" not in app.options.get('storageBucket', ''):
    # Se per qualche motivo non siamo in dev
    print("ERRORE: Non siamo in ambiente di sviluppo (log-solutions-sviluppo).")
    sys.exit(1)

print(f"VERIFICA AMBIENTE SUPERATA: {app.options.get('storageBucket')}")

db = firestore.client(app=app)
bucket = storage.bucket(app=app)

FIRESTORE_DELETE_ALLOWLIST = [
    "clienti/CATTEL/viaggi ddt/25-07-2026_CATTEL_0000_01_bda95be14aaa",
    "clienti/CATTEL/trip_title_locks/65c48b90050d571b38947b8f",
    "clienti/CATTEL/processing_jobs/jgsbJytUKVtXWx0nKwRd"
]

STORAGE_DELETE_ALLOWLIST = [
    ("split_ddt/25-07-2026/CATTEL/1701002166-1791002678_25-07-2026.pdf", 1785091167790938),
    ("split_ddt/25-07-2026/CATTEL/1701002166-1791002775_25-07-2026.pdf", 1785091168399077),
    ("split_ddt/25-07-2026/CATTEL/1701006035-1791002895_25-07-2026.pdf", 1785091161665773),
    ("split_ddt/25-07-2026/CATTEL/1701006224-1791003002_25-07-2026.pdf", 1785091158623274),
    ("split_ddt/25-07-2026/CATTEL/1701009992-0_25-07-2026.pdf", 1785091160457987),
    ("split_ddt/25-07-2026/CATTEL/1701010117-1791006103_25-07-2026.pdf", 1785091167190148),
    ("split_ddt/25-07-2026/CATTEL/1701010720-0_25-07-2026.pdf", 1785091163506742),
    ("split_ddt/25-07-2026/CATTEL/1701011001-0_25-07-2026.pdf", 1785091165375817),
    ("split_ddt/25-07-2026/CATTEL/1701011323-0_25-07-2026.pdf", 1785091162272307),
    ("split_ddt/25-07-2026/CATTEL/1701012821-0_25-07-2026.pdf", 1785091161057526),
    ("split_ddt/25-07-2026/CATTEL/1701012866-1791007265_25-07-2026.pdf", 1785091162880820),
    ("split_ddt/25-07-2026/CATTEL/1701013049-1791006800_25-07-2026.pdf", 1785091159236572),
    ("split_ddt/25-07-2026/CATTEL/1701078754-0_25-07-2026.pdf", 1785091165978803),
    ("split_ddt/25-07-2026/CATTEL/1701078766-0_25-07-2026.pdf", 1785091166584952),
    ("split_ddt/25-07-2026/CATTEL/1701081272-0_25-07-2026.pdf", 1785091164117202),
    ("split_ddt/25-07-2026/CATTEL/1701081272-1791001159_25-07-2026.pdf", 1785091164753144),
    ("split_ddt/25-07-2026/CATTEL/1701081397-0_25-07-2026.pdf", 1785091169612392),
    ("split_ddt/25-07-2026/CATTEL/1701082502-0_25-07-2026.pdf", 1785091159851505),
    ("split_ddt/25-07-2026/CATTEL/1701084326-0_25-07-2026.pdf", 1785091170249923),
    ("split_ddt/25-07-2026/CATTEL/1701088880-0_25-07-2026.pdf", 1785091169001565),
    ("split_ddt/25-07-2026/CATTEL/ddt_estratti_jgsbJytUKVtXWx0nKwRd.json", 1785091170405308)
]

print("\n--- INIZIO SCRIPT PULIZIA ---\n")

if not args.execute:
    print("MODALITA DRY-RUN ATTIVA (Nessuna cancellazione verra' eseguita)\n")
else:
    print("MODALITA EXECUTE ATTIVA (Cancellazione in corso...)\n")

# Process Firestore
for path in FIRESTORE_DELETE_ALLOWLIST:
    doc_ref = db.document(path)
    doc = doc_ref.get()
    if doc.exists:
        if args.execute:
            doc_ref.delete()
            print(f"[ELIMINATO] Firestore: {path}")
        else:
            print(f"[TROVATO - PRONTO PER ELIMINAZIONE] Firestore: {path}")
    else:
        print(f"[NON TROVATO] Firestore: {path}")

# Process Storage
for name, gen in STORAGE_DELETE_ALLOWLIST:
    blob = bucket.blob(name, generation=gen)
    if blob.exists():
        if args.execute:
            blob.delete()
            print(f"[ELIMINATO] Storage: {name} (gen {gen})")
        else:
            print(f"[TROVATO - PRONTO PER ELIMINAZIONE] Storage: {name} (gen {gen})")
    else:
        print(f"[NON TROVATO] Storage: {name} (gen {gen})")

print("\n--- FINE SCRIPT PULIZIA ---")
