import os
import firebase_admin
from firebase_admin import credentials, firestore

def copia_collezione(db, source_col, dest_col):
    docs = db.collection('clienti').document('DNR').collection(source_col).get(timeout=60)
    count = 0
    for doc in docs:
        db.collection('clienti').document('DNR').collection(dest_col).document(doc.id).set(doc.to_dict() or {})
        count += 1
    print(f"Copiati {count} documenti da '{source_col}' a '{dest_col}'")

def main():
    if not os.path.exists("prod_key.json"):
        print("ERRORE: Manca prod_key.json per connettersi al database.")
        return

    print("Inizializzazione connessione a Firebase...\n")
    cred = credentials.Certificate("prod_key.json")
    app = firebase_admin.initialize_app(cred, name='migrazione_navette')
    db = firestore.client(app=app)

    mappatura = {
        'magazzini_sedi': 'fatturazione_magazzini_sedi',
        'navette_anagrafica_partenze': 'fatturazione_navette_partenze',
        'navette_anagrafica_carichi': 'fatturazione_navette_carichi',
        'navette_anagrafica_clienti': 'fatturazione_navette_clienti',
        'navette_anagrafica_destinazioni': 'fatturazione_navette_destinazioni'
    }

    print("--- INIZIO MIGRAZIONE DATI ANAGRAFICI NAVETTE/MAGAZZINI ---")
    
    for src, dest in mappatura.items():
        print(f"\nSto copiando la collezione: {src} -> {dest}")
        copia_collezione(db, src, dest)

    print("\n--- MIGRAZIONE COMPLETATA ---")
    print("I vecchi dati sono stati riversati nelle nuove collezioni di fatturazione.")

if __name__ == "__main__":
    main()
