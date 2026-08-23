import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate(r"G:\Il mio Drive\App\AppLogSolutionsWeb\dev_key.json")
try:
    firebase_admin.initialize_app(cred)
except ValueError:
    pass # App already initialized

db = firestore.client()

def migrate_pair(legacy_autisti, legacy_pura, new_collection):
    print(f"Migrating {legacy_autisti} + {legacy_pura} -> {new_collection}...")
    
    # Read autisti items
    autisti_items = {}
    autisti_ref = db.collection("clienti").document("DNR").collection(legacy_autisti)
    for d in autisti_ref.stream():
        name = d.to_dict().get("nome", "").strip().upper()
        if name:
            autisti_items[name] = d.id

    # Read pura items
    pura_items = {}
    pura_ref = db.collection("clienti").document("DNR").collection(legacy_pura)
    for d in pura_ref.stream():
        name = d.to_dict().get("nome", "").strip().upper()
        if name:
            pura_items[name] = d.id

    # Merge names
    all_names = set(list(autisti_items.keys()) + list(pura_items.keys()))
    
    new_ref = db.collection("clienti").document("DNR").collection(new_collection)
    
    # First, clear new collection to make it clean
    existing_docs = new_ref.stream()
    deleted = 0
    for d in existing_docs:
        d.reference.delete()
        deleted += 1
    if deleted > 0:
        print(f"  Cleaned {deleted} existing documents from {new_collection}")

    # Write merged items
    written = 0
    for name in sorted(all_names):
        is_autisti = name in autisti_items
        is_pura = name in pura_items
        
        # Write to firestore
        new_ref.add({
            "nome": name,
            "is_navetta_autisti": is_autisti,
            "is_navetta": is_pura
        })
        written += 1
        
    print(f"  Successfully wrote {written} items into {new_collection}")

# Run migration for all 4 groups
migrate_pair("scaletta_partenze", "navetta_partenze", "navette_anagrafica_partenze")
migrate_pair("scaletta_carico", "navetta_carico", "navette_anagrafica_carichi")
migrate_pair("scaletta_clienti", "navetta_clienti", "navette_anagrafica_clienti")
migrate_pair("scaletta_destinazioni_merce", "navetta_destinazioni_merce", "navette_anagrafica_destinazioni")

print("Migration completed successfully!")
