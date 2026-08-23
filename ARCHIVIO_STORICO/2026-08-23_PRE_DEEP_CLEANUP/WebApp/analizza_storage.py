import os
import firebase_admin
from firebase_admin import credentials, storage

def main():
    if not os.path.exists("prod_key.json"):
        print("ERRORE: Manca prod_key.json")
        return

    print("Connessione a Firebase Storage in corso...\n")
    cred = credentials.Certificate("prod_key.json")
    app = firebase_admin.initialize_app(cred, {
        'storageBucket': 'log-solution-60007.firebasestorage.app'
    })

    bucket = storage.bucket()
    blobs = bucket.list_blobs()

    total_size = 0
    file_count = 0
    folders = {}

    for blob in blobs:
        file_count += 1
        total_size += blob.size

        # Raggruppa per cartella principale (es. split_ddt, REPORTS, ecc)
        folder = blob.name.split('/')[0] if '/' in blob.name else 'Root'
        
        if folder not in folders:
            folders[folder] = {'count': 0, 'size': 0}
        
        folders[folder]['count'] += 1
        folders[folder]['size'] += blob.size

    # Converti in Megabyte
    total_mb = total_size / (1024 * 1024)

    print("=========================================")
    print("   ANALISI SPAZIO FIREBASE STORAGE       ")
    print("=========================================")
    print(f"Totale File presenti: {file_count}")
    print(f"Spazio Totale Occupato: {total_mb:.2f} MB")
    print("\n--- DETTAGLIO PER CARTELLA ---")
    
    for f_name, f_data in sorted(folders.items(), key=lambda x: x[1]['size'], reverse=True):
        f_mb = f_data['size'] / (1024 * 1024)
        print(f"📁 {f_name.ljust(20)} : {f_mb:>7.2f} MB  ({f_data['count']} file)")
    
    print("=========================================")

if __name__ == "__main__":
    main()
