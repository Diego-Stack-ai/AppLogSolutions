import os
import json
import logging
import firebase_admin
from firebase_admin import initialize_app, firestore, storage

# --- Inizializzazione Firebase ---
if not firebase_admin._apps:
    initialize_app()

def get_dynamic_project_id():
    pid = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCLOUD_PROJECT")
    if not pid:
        try:
            pid = firebase_admin.get_app().project_id
        except Exception:
            pass
    if not pid:
        try:
            import google.auth
            _, pid = google.auth.default()
        except Exception:
            pass
    return pid or "log-solution-60007"

PROJECT_ID = get_dynamic_project_id()

BUCKET_NAME = f"{PROJECT_ID}.firebasestorage.app"

def get_db():
    return firestore.client()

def get_bucket():
    return storage.bucket(name=BUCKET_NAME)

# --- STORAGE CACHES ---
_LOCAL_STORAGE_CACHES = {
    "distanze_reali_cache.json": None,
    "directions_cache.json": None,
    "directions_cache_v2.json": None,
    "distanze_traffico_cache.json": None
}
_INITIAL_CACHE_COUNTS = {}

def load_storage_cache(filename):
    global _LOCAL_STORAGE_CACHES, _INITIAL_CACHE_COUNTS
    if _LOCAL_STORAGE_CACHES[filename] is not None:
        return _LOCAL_STORAGE_CACHES[filename]
        
    try:
        bucket = get_bucket()
        blob = bucket.blob(f"caches/{filename}")
        loaded_data = None
        if blob.exists():
            try:
                data_str = blob.download_as_string().decode("utf-8")
                loaded_data = json.loads(data_str)
                if not isinstance(loaded_data, dict):
                    loaded_data = None
            except Exception as e_parse:
                print(f"[CACHE-GUARD] Errore parsing JSON su {filename}: {e_parse}. Tentativo di recupero da backup...")
                loaded_data = None
        
        # Fallback 1: Recupero dal backup cloud più recente se il primario è corrotto o mancante
        if loaded_data is None:
            backup_latest = bucket.blob(f"caches_backup/{filename.replace('.json', '')}_latest.json")
            if backup_latest.exists():
                try:
                    b_str = backup_latest.download_as_string().decode("utf-8")
                    loaded_data = json.loads(b_str)
                    print(f"[CACHE-GUARD] Ripristino automatico da backup riuscito per {filename} ({len(loaded_data)} chiavi).")
                except Exception as e_bkp:
                    print(f"[CACHE-GUARD] Errore caricamento backup latest per {filename}: {e_bkp}")
                    loaded_data = None
        
        # Fallback 2: Recupero dal file locale di seeding
        if loaded_data is None:
            import os
            # Calcoliamo il path rispetto a main.py (che è il parent dir di infrastructure)
            local_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "caches", filename)
            if os.path.exists(local_path):
                with open(local_path, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                blob.upload_from_filename(local_path, content_type="application/json")
                print(f"[CACHE-GUARD] Seeding iniziale da file locale per {filename} ({len(loaded_data)} chiavi).")
            else:
                loaded_data = {}
                
        _LOCAL_STORAGE_CACHES[filename] = loaded_data
        _INITIAL_CACHE_COUNTS[filename] = len(loaded_data)
    except Exception as e:
        print(f"[CACHE] Errore load {filename}: {e}")
        _LOCAL_STORAGE_CACHES[filename] = {}
        _INITIAL_CACHE_COUNTS[filename] = 0
        
    return _LOCAL_STORAGE_CACHES[filename]

def save_storage_cache(filename):
    global _LOCAL_STORAGE_CACHES, _INITIAL_CACHE_COUNTS
    try:
        current_count = len(_LOCAL_STORAGE_CACHES[filename])
        initial_count = _INITIAL_CACHE_COUNTS.get(filename, 0)
        
        # GUARDIA ANTI-REGRESSIONE E CORRUZIONE
        if current_count < initial_count:
            err_msg = f"[CACHE-GUARD] ANOMALIA GRAVE: regressione chiavi per {filename} ({current_count} < {initial_count}). Sincronizzazione bloccata per proteggere la cache cloud."
            print(err_msg)
            raise RuntimeError(err_msg)
            
        bucket = get_bucket()
        json_str = json.dumps(_LOCAL_STORAGE_CACHES[filename], ensure_ascii=False)
        blob = bucket.blob(f"caches/{filename}")
        blob.upload_from_string(json_str, content_type="application/json")
        
        # Aggiornamento iniziale chiavi al nuovo valore di successo
        _INITIAL_CACHE_COUNTS[filename] = current_count
        
        # SALVATAGGIO BACKUP SNAPSHOT GIORNALIERO E LATEST
        import datetime
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        base_name = filename.replace('.json', '')
        backup_daily = bucket.blob(f"caches_backup/{base_name}_{today_str}.json")
        if not backup_daily.exists():
            backup_daily.upload_from_string(json_str, content_type="application/json")
            backup_latest = bucket.blob(f"caches_backup/{base_name}_latest.json")
            backup_latest.upload_from_string(json_str, content_type="application/json")
            print(f"[CACHE-GUARD] Creato snapshot di backup giornaliero per {filename} ({today_str}).")
            
    except Exception as e:
        print(f"[CACHE] Errore save {filename}: {e}")

