import firebase_admin
from firebase_admin import credentials, firestore
import os

def check_env(env_name, key_path):
    if not os.path.exists(key_path):
        print(f"Key not found: {key_path}")
        return

    if not firebase_admin._apps:
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)
    else:
        firebase_admin.delete_app(firebase_admin.get_app())
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    print(f"\n--- Checking {env_name} ---")
    
    docs = list(db.collection_group('nuovi codici consegna').stream())
    print(f"Total nuovi codici consegna (anywhere): {len(docs)}")
    for doc in docs[:10]:
        print(f" - ID: {doc.id}, Parent: {doc.reference.parent.parent.id if doc.reference.parent.parent else 'root'}, Tipo: {doc.to_dict().get('tipo')}")
        
    rc_docs = list(db.collection_group('raccolta clienti').stream())
    print(f"Total raccolta clienti (anywhere): {len(rc_docs)}")
    rosso = [d for d in rc_docs if d.to_dict().get('stato_suggerito') == 'rosso' or d.to_dict().get('stato') == 'rosso']
    missing_gps = [d for d in rc_docs if not d.to_dict().get('lat') or not d.to_dict().get('lon')]
    print(f"raccolta clienti (rosso): {len(rosso)}")
    print(f"raccolta clienti (missing gps): {len(missing_gps)}")

if __name__ == "__main__":
    check_env("SVILUPPO", "G:/Il mio Drive/App/AppLogSolutionsWeb/dev_key.json")
    check_env("PROD", r"C:\Users\Diego\Documents\antigravity\elegant-goodall\log-solution-60007-firebase-adminsdk-h4g9o-c46fa673eb.json")
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--execute", action="store_true", help="Actually delete the documents")
    args = parser.parse_args()
    
    delete_anomalies(args.project_id, dry_run=not args.execute)
