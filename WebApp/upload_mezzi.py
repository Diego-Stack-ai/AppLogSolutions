import os
import urllib.parse
from uuid import uuid4
import firebase_admin
from firebase_admin import credentials, firestore, storage
import mimetypes
import time

cred = credentials.Certificate(r"G:\Il mio Drive\App\AppLogSolutionsWeb\dev_key.json")
try:
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'log-solutions-sviluppo.firebasestorage.app'
    })
except Exception as e:
    print("Initialization err:", e)
    
db = firestore.client()
bucket = storage.bucket()

base_dirs = [
    r"G:\Il mio Drive\App\AUTOMEZZI LEASING ESGrent",
    r"G:\Il mio Drive\App\AUTOMEZZI LOG. SOLUTIONS"
]

targhe = [
    'FJ638LN', 'FD788RT', 'GB969FN', 'GF929KT', 'EK832AW', 'EN201DB', 
    'EN364DB', 'DS224AD', 'EN155RJ', 'FF809PM', 'FL142GN', 'GH876XK', 
    'GH877XK', 'GH878XK', 'GJ328KZ', 'HB712NN', 'HB713NN', 'HB714NN', 
    'HB954TE', 'XA673WH', 'FN481YL'
]

def get_targa(folder_name):
    for t in targhe:
        if t in folder_name:
            return t
    return None

for b_dir in base_dirs:
    if not os.path.exists(b_dir):
        print(f"Skipping {b_dir}, doesn't exist.")
        continue
        
    for folder in os.listdir(b_dir):
        folder_path = os.path.join(b_dir, folder)
        if not os.path.isdir(folder_path):
            continue
            
        targa = get_targa(folder)
        if not targa:
            print(f"Skipping folder (no targa matched): {folder}")
            continue
            
        print(f"\nProcessing {targa} in {folder}")
        
        foto_urls = []
        documenti_urls = []
        
        for file in os.listdir(folder_path):
            file_path = os.path.join(folder_path, file)
            if not os.path.isfile(file_path):
                continue
                
            safe_name = file.replace(' ', '_')
            ext = os.path.splitext(file)[1].lower()
            is_foto = ext in ['.jpg', '.jpeg', '.png']
            
            subfolder = 'foto' if is_foto else 'documenti'
            timestamp = int(time.time() * 1000)
            storage_path = f"MEZZI/{targa}/{subfolder}/{timestamp}_{safe_name}"
            
            blob = bucket.blob(storage_path)
            
            new_token = str(uuid4())
            metadata = {"firebaseStorageDownloadTokens": new_token}
            blob.metadata = metadata
            
            content_type, _ = mimetypes.guess_type(file_path)
            if not content_type:
                content_type = 'application/octet-stream'
                
            print(f"  Uploading {file} to {storage_path}...")
            blob.upload_from_filename(file_path, content_type=content_type)
            
            encoded_path = urllib.parse.quote(storage_path, safe='')
            download_url = f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/{encoded_path}?alt=media&token={new_token}"
            
            file_data = {
                "name": file,
                "url": download_url,
                "path": storage_path
            }
            
            if is_foto:
                foto_urls.append(file_data)
            else:
                documenti_urls.append(file_data)
                
        if not foto_urls and not documenti_urls:
            print("  No files to process.")
            continue
            
        doc_ref = db.collection('mezzi').document(targa)
        doc_snap = doc_ref.get()
        
        if doc_snap.exists:
            update_data = {}
            if foto_urls:
                existing = doc_snap.to_dict().get('fotoUrls', [])
                # Avoid duplicates by checking names
                existing_names = [e.get('name') for e in existing]
                new_foto = [f for f in foto_urls if f['name'] not in existing_names]
                if new_foto:
                    update_data['fotoUrls'] = existing + new_foto
            if documenti_urls:
                existing = doc_snap.to_dict().get('documentiUrls', [])
                existing_names = [e.get('name') for e in existing]
                new_docs = [f for f in documenti_urls if f['name'] not in existing_names]
                if new_docs:
                    update_data['documentiUrls'] = existing + new_docs
                    
            if update_data:
                doc_ref.set(update_data, merge=True)
                print(f"  -> Updated Firestore document for {targa}")
            else:
                print(f"  -> Files already exist in Firestore for {targa}")
        else:
            new_doc = {
                "targa": targa,
                "modello": "",
                "patente": "B",
                "fotoUrls": foto_urls,
                "documentiUrls": documenti_urls
            }
            doc_ref.set(new_doc)
            print(f"  -> Created Firestore document for {targa}")

print("\nImport completato!")
