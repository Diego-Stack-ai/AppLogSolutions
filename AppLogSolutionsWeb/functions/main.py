import io
import re
import json
import time
import math
import gc
import typing
import uuid
from datetime import datetime, date
from collections import defaultdict
import firebase_admin
from firebase_admin import initialize_app, firestore, storage
from firebase_functions import https_fn, options
# pypdf e pdfplumber importati localmente per timeout

from infrastructure.firebase_setup import (
    get_dynamic_project_id, PROJECT_ID, BUCKET_NAME, get_db, get_bucket,
    load_storage_cache, save_storage_cache
)
from core.utils import (
    normalize_code, _build_tripla_chiave, _extract_phone, clean_client_code, _safe_float
)

import os
_project_id = os.environ.get("GCP_PROJECT", "log-solution-60007")
ALLOWED_ORIGINS = [
    f"https://{_project_id}.web.app",
    f"https://{_project_id}.firebaseapp.com",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:3000"
]

def get_tenant_from_viaggio_id(viaggio_id):
    if not viaggio_id:
        return "DNR"
        
    db = get_db()
    
    # 1. Cerca il viaggio in modo dinamico tramite Collection Group Query
    try:
        docs = db.collection_group('viaggi ddt').where(firestore.FieldPath.document_id(), '==', viaggio_id).limit(1).get()
        if docs:
            path_parts = docs[0].reference.path.split('/')
            if len(path_parts) >= 2:
                return path_parts[1]
    except Exception as e:
        print(f"[get_tenant_from_viaggio_id] Errore Collection Group Query: {e}")
        
    # 2. Fallback dinamico basato sui tenant registrati su Firestore
    try:
        viaggio_id_upper = str(viaggio_id).upper()
        tenants = [doc.id for doc in db.collection('clienti').list_documents()]
        for t in tenants:
            t_upper = t.upper()
            if t_upper == "GRAN CHEF":
                if "GRAN_CHEF" in viaggio_id_upper or "GRAND_CHEF" in viaggio_id_upper or "_GC_" in viaggio_id_upper or "GRANCHEF" in viaggio_id_upper:
                    return t
            if t_upper in viaggio_id_upper.replace("_", " "):
                return t
    except Exception as e:
        print(f"[get_tenant_from_viaggio_id] Errore caricamento tenant da Firestore: {e}")
        
    # 3. Fallback assoluto storicamente tollerato
    return "DNR"

from infrastructure.google_maps_api import (
    GOOGLE_MAPS_API_KEY, AVG_SPEED_KMH,
    _haversine, _cache_key, _leggi_cache_firestore, _scrivi_cache_firestore,
    _crea_matrice_distanze_cloud, _get_directions_data, _get_depot_for_points_cloud,
    _get_directions_and_simulate_cloud, _get_directions_sec_with_traffic
)
try:
    import requests
except ImportError:
    requests = None

# --- CHIAVE API GOOGLE (da impostare nelle variabili d'ambiente della Cloud Function) ---
import os
import logging
import sentry_sdk

# Configurazione logging strutturato nativo GCP e Sentry SDK
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger("AppLogSolutions")

sentry_sdk.init(
    dsn="https://8e3e071e1609300da167c7815f0c76bd@o4511642916618240.ingest.de.sentry.io/4511642970357840",
    traces_sample_rate=1.0,
    environment="production"
)



# --- CONFIGURAZIONI ---
# Riconoscimento automatico dell'ambiente per il Bucket



DATA_DDT_RE = re.compile(r'del\s+(\d{2})/(\d{2})/(\d{4})', re.I)
LUOGO_RE = re.compile(r'(?:[Ll]uogo [Dd]i [Dd]estinazione|[Cc]odice [Dd]estinazione):\s*([pP]\d{4,5})')
CAP_RE = re.compile(r"\b(\d{5})\b")
PROVINCIA_RE = re.compile(r"\(([A-Z]{2})\)")
CAUSALE_RE = re.compile(r'(?:conto di|ordine e conto di)\s+([A-Z]\d{4})(?:\s+H(\d{2}))?(?:\s+(\d{3}))?', re.I)
NUM_DDT_RE = re.compile(r'DDT\s*[Nn][°º\.\s]*([A-Za-z0-9/-]+)', re.I)


# --- STORAGE CACHES ---



# --- GESTIONE CONFIGURAZIONI CACHE ---
_CACHED_ARTICOLI_NOTI = None
_CACHED_CONSOLIDAMENTO = None
_CACHE_TIMESTAMP = 0
CACHE_TTL = 300 # 5 minuti










# --- CORE LOGIC FUNCTIONS ---



@https_fn.on_call()
def admin_reset_password(req: https_fn.CallableRequest) -> dict:
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )
    from services.admin_service import handle_admin_reset_password
    return handle_admin_reset_password(req)


# ─── PUNTO #4: PROTEZIONE TRIPLA CHIAVE ────────────────────────────────────────




def _cerca_cliente_cloud(codice: str):
    """
    Cerca un cliente in Firestore per codice (frutta o latte).
    Restituisce (doc_dict, doc_id) o (None, None).
    Il codice viene cercato in modo case-insensitive.
    IMPORTANTE: se il codice e' p00000 NON restituiamo mai un match univoco
    perche' p00000 e' un codice fittizio usato per clienti multipli.
    """
    codice_l = codice.strip().lower()

    # p00000 e' un codice fittizio: non usare come chiave di ricerca singola
    if codice_l == "p00000":
        return None, None

    db = get_db()
    col = db.collection('clienti').document('DNR').collection('raccolta clienti')

    # Cerca per codice_frutta
    for val in [codice_l, codice_l.upper()]:
        docs = list(col.where('codice_frutta', '==', val).limit(1).stream())
        if docs:
            return docs[0].to_dict(), docs[0].id

    # Cerca per codice_latte
    for val in [codice_l, codice_l.upper()]:
        docs = list(col.where('codice_latte', '==', val).limit(1).stream())
        if docs:
            return docs[0].to_dict(), docs[0].id

    return None, None


def _salva_nuovo_cliente_tripla_chiave(cod_f: str, cod_l: str, nome: str, extra: dict = None):
    """
    Crea un nuovo cliente in Firestore usando la TRIPLA CHIAVE come ID documento.
    In questo modo due clienti diversi con lo stesso p00000 NON si sovrascrivono.
    """
    chiave = _build_tripla_chiave(cod_f, cod_l, nome)
    doc_id = chiave.replace("/", "_").replace(".", "_").replace(" ", "_")[:500]
    doc_data = {
        "codice_frutta": str(cod_f).strip().lower(),
        "codice_latte":  str(cod_l).strip().lower(),
        "nome_consegna": nome,
        "cliente": nome,
        "tripla_chiave": chiave,
        "stato": "da_mappare"
    }
    if extra:
        doc_data.update(extra)
    get_db().collection('clienti').document('DNR').collection('raccolta clienti').document(doc_id).set(doc_data, merge=True)
    return doc_id









# ─── PUNTO #3: MAPPE AUTISTI CON STRADE CURVE (GOOGLE DIRECTIONS) ─────────────

DEPOT_CLOUD = {"lat": 45.442805, "lon": 11.714498, "nome": "DEPOSITO VEGGIANO"}
AVG_SPEED_KMH = 45
TIME_PER_STOP_MIN = 8












# ─── PUNTO #6: RIEPILOGO FATTURAZIONE MENSILE ────────────────────────────────

# Costanti fatturazione
VALORE_DDT_STANDARD = 16.50   # € per DDT standard (Frutta e Latte)
VALORE_DDT_SPECIALE = 16.50   # € per DDT aree speciali (stessa tariffa, separati per contabilità)















import re



def _ordina_job_ids_gc(job_ids, tenant="GRAN CHEF"):
    db = get_db()
    jobs_info = []
    for jid in job_ids:
        try:
            doc = db.collection('clienti').document(tenant).collection('processing_jobs').document(jid).get()
            if doc.exists:
                d = doc.to_dict()
                created = d.get('created_at') or 0
                if hasattr(created, 'timestamp'):
                    created = created.timestamp()
                elif isinstance(created, (int, float)):
                    pass
                else:
                    created = 0
                jobs_info.append((jid, created))
            else:
                jobs_info.append((jid, 0))
        except Exception:
            jobs_info.append((jid, 0))
    jobs_info.sort(key=lambda x: x[1])
    return [x[0] for x in jobs_info]

def core_genera_report_giornaliero(uid, data_consegna, tipologie_da_elaborare=None):
    """
    Implementa gli step 2, 3 e 4 del workflow locale con logica a blocchi:
    - Identifica fornitori da sovrascrivere (quelli presenti in split_ddt)
    - Elimina vecchi viaggi DB per quei fornitori
    - Mantiene intatti (cassaforte) i viaggi che non contengono fornitori da sovrascrivere
    - Genera nuovi giri di default per i nuovi dati
    """
    start_time = time.time()
    db = get_db()
    bucket = storage.bucket(name=BUCKET_NAME)
    if not data_consegna:
        return {"status": "errore", "message": "Data mancante"}

    print(f"[INFO] Generazione report per il {data_consegna}")
    
    # 1. Recupera i DDT scansionando la cartella dello Storage
    ddt_list = []
    if tipologie_da_elaborare:
        prefixes_search = [f"split_ddt/{data_consegna}/{t.upper()}/" for t in tipologie_da_elaborare]
    else:
        prefixes_search = [f"split_ddt/{data_consegna}/"]
    print(f"[INFO] Scansione Storage per data {data_consegna}...")
    
    tenant_con_ddt = set()
    
    try:
        # Caricamento bulk clienti da tutti i tenant dinamici
        db_mappati = {}
        try:
            tenants = [doc.id for doc in db.collection('clienti').list_documents()]
        except Exception as e:
            print(f"[genera_completo_giornata] Errore lookup tenant: {e}")
            tenants = ['DNR', 'GRAN CHEF', 'CATTEL', 'DAC']
            
        for current_tenant in tenants:
            clienti_ref = db.collection('clienti').document(current_tenant).collection('raccolta clienti')
            for doc in clienti_ref.stream():
                d = doc.to_dict()
                cf = str(d.get('codice_frutta') or '').strip().lower()
                cl = str(d.get('codice_latte') or '').strip().lower()
                if cf and cf != 'p00000' and cf != 'nan': db_mappati[cf] = d
                if cl and cl != 'p00000' and cl != 'nan': db_mappati[cl] = d

        for pref in prefixes_search:
            blobs = bucket.list_blobs(prefix=pref)
            for blob in blobs:
                if "ddt_estratti" in blob.name and blob.name.endswith(".json"):
                    print(f"[INFO] Leggo file: {blob.name}")
                    
                    # Identifica tenant dal path
                    if "/CATTEL/" in blob.name: tenant_con_ddt.add("CATTEL")
                    elif "/GRAND_CHEF/" in blob.name: tenant_con_ddt.add("GRAN_CHEF")
                    elif "/DAC/" in blob.name: tenant_con_ddt.add("DAC")
                    elif "/FRUTTA/" in blob.name or "/LATTE/" in blob.name: tenant_con_ddt.add("DNR")
                    
                    try:
                        import json
                        meta_data = json.loads(blob.download_as_string())
                        job_competenza = meta_data.get("competenza") or meta_data.get("tipo", "FRUTTA").upper()
                        if job_competenza in ("GRAND_CHEF", "GRAND CHEF", "GRAN CHEF"):
                            job_competenza = "GRAN_CHEF"
                        if job_competenza == "DAC":
                            job_competenza = "DAC"
                        for ddt in meta_data.get("deliveries", []):
                            cod = ddt.get("codice_consegna")
                            cod_l = str(cod).strip().lower()
                            cliente_info = db_mappati.get(cod_l)
                            
                            if cliente_info:
                                ddt["nome"] = cliente_info.get('cliente') or cliente_info.get('nome_consegna') or cod
                            else:
                                ddt["nome"] = cod
                            ddt["competenza"] = ddt.get("competenza") or job_competenza
                            ddt_list.append(ddt)
                    except Exception as e_read:
                        print(f"[ERROR] Impossibile leggere {blob.name}: {e_read}")
    except Exception as e_list:
        print(f"[ERROR] Errore scansione storage: {e_list}")

    if not ddt_list:
        # Debug Radar
        cercati = [f"split_ddt/{data_consegna}/**/ddt_estratti_*.json"]
        try:
            prefix_check = f"split_ddt/{data_consegna}/"
            blobs_esistenti = list(bucket.list_blobs(prefix=prefix_check))
            files_trovati = [b.name for b in blobs_esistenti]
            msg = f"Nessun dato trovato per il {data_consegna}. Percorsi attesi: {', '.join(cercati)}. Nello Storage vedo: {', '.join(files_trovati) if files_trovati else 'NULLA'}"
        except Exception as e_debug:
            msg = f"Nessun dato trovato per il {data_consegna} e errore durante il radar: {e_debug}"
            
        print(f"[ERROR] {msg}")
        return {"status": "errore", "message": msg}

    print(f"[INFO] Tenant con nuovi dati (da sovrascrivere): {tenant_con_ddt}")

    # 0.5. Sovrascrittura Selettiva (Elimina i viaggi Firestore per i tenant che vogliamo sovrascrivere)
    if tenant_con_ddt:
        try:
            for t_sov in tenant_con_ddt:
                tenant = "GRAN CHEF" if t_sov == "GRAN_CHEF" else t_sov
                if t_sov == "DAC": tenant = "DAC"
                viaggi_ref = db.collection('clienti').document(tenant).collection('viaggi ddt')
                viaggi = viaggi_ref.where("data_lavoro", "==", data_consegna).stream()
                for v in viaggi:
                    v.reference.delete()
        except Exception as e:
            print(f"[ERROR] Eliminazione vecchi viaggi fallita: {e}")

    # PRE-SALVATAGGIO: Leggi i viaggi esistenti prima di cancellarli per logica Cassaforte
    import json
    mappa_zone_esistenti = {}
    try:
        blob_old_json = bucket.blob(f"REPORTS/{data_consegna}/viaggi_giornalieri_Johnson.json")
        if blob_old_json.exists():
            old_data = json.loads(blob_old_json.download_as_string().decode('utf-8'))
            old_zones = old_data.get("zone", []) if isinstance(old_data, dict) else old_data
            for z in old_zones:
                mappa_zone_esistenti[z.get("id_zona")] = z
    except Exception as e_old:
        print(f"[WARN] Impossibile leggere il vecchio viaggi_giornalieri_Johnson.json: {e_old}")

    # Aggiorna con i file tenant-specifici (che sono la vera 'fonte di verità' per i viaggi svuotati/cancellati)
    try:
        tenants = [doc.id for doc in db.collection('clienti').list_documents()]
    except Exception as e:
        print(f"[genera_completo_giornata] Errore lookup tenant per file JSON: {e}")
        tenants = ["CATTEL", "GRAN CHEF", "DNR", "DAC"]
        
    for t in tenants:
        t_folder = t.upper().replace(" ", "_")
        try:
            blob_t = bucket.blob(f"{t_folder}/REPORTS/{data_consegna}/viaggi_giornalieri_Johnson.json")
            if blob_t.exists():
                t_data = json.loads(blob_t.download_as_string().decode('utf-8'))
                t_zones = t_data.get("zone", []) if isinstance(t_data, dict) else t_data
                
                # Rimuovi dal globale tutti i viaggi che sembrano appartenere a questo tenant.
                # Se sono stati svuotati dall'utente, non ci saranno nel JSON del tenant, e così evitiamo di resuscitarli!
                keys_to_remove = []
                for k, v in mappa_zone_esistenti.items():
                    cz = str(v.get("cliente_zona", "")).upper()
                    if t_folder == "CATTEL" and "CATTEL" in cz:
                        keys_to_remove.append(k)
                    elif t_folder == "GRAN_CHEF" and ("GRAN CHEF" in cz or "GRAND CHEF" in cz):
                        keys_to_remove.append(k)
                    elif t_folder == "DAC" and "DAC" in cz:
                        keys_to_remove.append(k)
                    elif t_folder == "DNR" and ("CATTEL" not in cz and "GRAN" not in cz and "DAC" not in cz):
                        keys_to_remove.append(k)
                
                for k in keys_to_remove:
                    mappa_zone_esistenti.pop(k, None)
                    
                # Aggiungi i viaggi reali e aggiornati di questo tenant
                for z in t_zones:
                    mappa_zone_esistenti[z.get("id_zona")] = z
        except Exception as e_t:
            print(f"[WARN] Impossibile leggere il JSON del tenant {t_folder}: {e_t}")

    # 0. Svuota le vecchie cartelle nello Storage per evitare doppioni
    try:
        data_f = data_consegna.replace('/', '-')
        prefixes_to_clean = [
            f"REPORTS/{data_consegna}/",
            f"CONSEGNE/CONSEGNE_{data_f}/"
        ]
        for pref in prefixes_to_clean:
            blobs_old = bucket.list_blobs(prefix=pref)
            for b_old in blobs_old:
                try: b_old.delete()
                except: pass
        print(f"[INFO] Pulizia cartelle completata per {data_consegna}")
    except Exception as e_clean:
        print(f"[WARN] Impossibile pulire cartelle storage: {e_clean}")

    # 2. Aggrega per cliente (Step 2 locale)
    punti_map = {} # chiave: tripla_chiave o codice_cliente
    for ddt in ddt_list:
        cod = ddt.get('codice_consegna')
        cod_l = str(cod).strip().lower()
        tipo = ddt.get('tipo', 'FRUTTA')
        competenza = ddt.get('competenza') or tipo
        
        cliente_info = db_mappati.get(cod_l)
        nome = ddt.get('nome', cod)
        
        if cliente_info:
            cf_key = str(cliente_info.get('codice_frutta') or 'p00000').strip().lower()
            cl_key = str(cliente_info.get('codice_latte') or 'p00000').strip().lower()
            nome_key = cliente_info.get('cliente') or cliente_info.get('nome_consegna') or nome
            chiave = _build_tripla_chiave(cf_key, cl_key, nome_key)
        else:
            chiave = ddt.get('tripla_chiave') or cod
        
        cf_val = (cliente_info.get('codice_frutta') or 'p00000') if cliente_info else (cod if tipo == 'FRUTTA' else 'p00000')
        cl_val = (cliente_info.get('codice_latte') or 'p00000') if cliente_info else (cod if tipo == 'LATTE' else 'p00000')
        
        prov_code = ""
        full_ind = ""
        citta_val = ""
        
        if cliente_info:
            prov_raw = str(cliente_info.get('provincia') or cliente_info.get('prov') or '').upper().strip()
            prov_map = {
                "BRESCIA": "BS", "VERONA": "VR", "MANTOVA": "MN", "PADOVA": "PD",
                "VICENZA": "VI", "BELLUNO": "BL", "UDINE": "UD", "TREVISO": "TV",
                "VENEZIA": "VE", "ROVIGO": "RO"
            }
            prov_code = prov_map.get(prov_raw, prov_raw)
            if len(prov_code) > 2:
                prov_code = prov_code[:2]
                
            citta_val = str(cliente_info.get('citta') or '').strip()
            ind_val = str(cliente_info.get('indirizzo') or '').strip()
            
            ind_parts = [ind_val]
            if citta_val:
                ind_parts.append(citta_val)
            full_ind = ", ".join([p for p in ind_parts if p])
            if prov_code:
                full_ind += f" ({prov_code})"
        else:
            full_ind = ddt.get('indirizzo', '')
            
        note_val = ""
        tel_val = ""
        om_frutta = ""
        oM_frutta = ""
        om_latte = ""
        oM_latte = ""
        om_val = ""
        oM_val = ""
        
        if cliente_info:
            note_val = str(cliente_info.get("note", cliente_info.get("nota_integrativa", cliente_info.get("Note", ""))) or "").strip()
            tel_val = str(cliente_info.get("telefono", cliente_info.get("tel", cliente_info.get("phone", ""))) or "").strip()
            om_frutta = str(cliente_info.get("orario_min_frutta") or "").strip()
            oM_frutta = str(cliente_info.get("orario_max_frutta") or "").strip()
            om_latte = str(cliente_info.get("orario_min_latte") or "").strip()
            oM_latte = str(cliente_info.get("orario_max_latte") or "").strip()
            
            if note_val.lower() == "nan": note_val = ""
            if tel_val.lower() == "nan": tel_val = ""
            if om_frutta.lower() == "nan": om_frutta = ""
            if oM_frutta.lower() == "nan": oM_frutta = ""
            if om_latte.lower() == "nan": om_latte = ""
            if oM_latte.lower() == "nan": oM_latte = ""
            
            if tipo == "FRUTTA":
                om_val = om_frutta if om_frutta else (str(cliente_info.get("orario_min") or "").strip())
                oM_val = oM_frutta if oM_frutta else (str(cliente_info.get("orario_max") or "").strip())
            else:
                om_val = om_latte if om_latte else (str(cliente_info.get("orario_min") or "").strip())
                oM_val = oM_latte if oM_latte else (str(cliente_info.get("orario_max") or "").strip())
                
            if om_val.lower() == "nan": om_val = ""
            if oM_val.lower() == "nan": oM_val = ""
            
        if ddt.get("orario_min"): om_val = str(ddt["orario_min"]).strip()
        if ddt.get("orario_max"): oM_val = str(ddt["orario_max"]).strip()
        if ddt.get("note"): note_val = str(ddt["note"]).strip()

        # Usa la zona assegnata dal ddt (se proveniente da un Excel che l'ha già generata)
        raw_zona = str(ddt.get('zona') or '').strip()
        if not raw_zona:
            # Fallback per PDF (DNR) che usano l'Anagrafica Clienti
            raw_zona = str((cliente_info.get('codice_zona') or cliente_info.get('zona') or '0000') if cliente_info else '0000').strip()

        if chiave not in punti_map:
            punti_map[chiave] = {
                "nome": nome,
                "indirizzo": full_ind,
                "provincia": prov_code,
                "prov": prov_code,
                "citta": citta_val,
                "codice_frutta": cf_val,
                "codice_latte": cl_val,
                "codici_ddt_frutta": [],
                "codici_ddt_latte": [],
                "zona": raw_zona,
                "lat": float(cliente_info.get('lat', 0)) if cliente_info and cliente_info.get('lat') else 0,
                "lon": float(cliente_info.get('lon', 0)) if cliente_info and cliente_info.get('lon') else 0,
                "rientri_alert": [],
                "tipologia_grado": cliente_info.get('tipologia_grado', '') if cliente_info else ('GRAND CHEF' if tipo == 'GRAND_CHEF' else ''),
                "tipo": tipo,
                "competenze": [],
                "gc_colli": ddt.get("gc_colli", ""),
                "gc_peso_kg": ddt.get("gc_peso_kg", ""),
                "gc_num_cartone": ddt.get("gc_num_cartone", ""),
                "orario_min_frutta": om_frutta,
                "orario_max_frutta": oM_frutta,
                "orario_min_latte": om_latte,
                "orario_max_latte": oM_latte,
                "orario_min": om_val,
                "orario_max": oM_val,
                "note": note_val,
                "telefono": tel_val
            }
        else:
            esistente = punti_map[chiave]
            if cf_val != 'p00000' and esistente["codice_frutta"] == 'p00000':
                esistente["codice_frutta"] = cf_val
            if cl_val != 'p00000' and esistente["codice_latte"] == 'p00000':
                esistente["codice_latte"] = cl_val
            if ddt.get("gc_colli"): esistente["gc_colli"] = ddt.get("gc_colli")
            if ddt.get("gc_peso_kg"): esistente["gc_peso_kg"] = ddt.get("gc_peso_kg")
            if ddt.get("gc_num_cartone"): esistente["gc_num_cartone"] = ddt.get("gc_num_cartone")
            if tipo == 'GRAND_CHEF':
                esistente["tipo"] = 'GRAND_CHEF'
                if not esistente.get("tipologia_grado"):
                    esistente["tipologia_grado"] = 'GRAND CHEF'
            
            if not esistente.get("orario_min") and om_val: esistente["orario_min"] = om_val
            if not esistente.get("orario_max") and oM_val: esistente["orario_max"] = oM_val
            if not esistente.get("note") and note_val: esistente["note"] = note_val
            if not esistente.get("telefono") and tel_val: esistente["telefono"] = tel_val
        
        if tipo == 'FRUTTA':
            punti_map[chiave]["codici_ddt_frutta"].append(ddt.get('num_ddt', 'UNK'))
        else:
            punti_map[chiave]["codici_ddt_latte"].append(ddt.get('num_ddt', 'UNK'))
            
        if "competenze" not in punti_map[chiave]:
            punti_map[chiave]["competenze"] = []
        if competenza not in punti_map[chiave]["competenze"]:
            punti_map[chiave]["competenze"].append(competenza)

    # --- INTEGRAZIONE RIENTRI DDT ---
    # Esegui esclusivamente quando è coinvolto il tenant DNR
    is_dnr = True
    if tipologie_da_elaborare:
        non_dnr_tenants = ['DAC', 'CATTEL', 'GRAN CHEF', 'GRAND_CHEF']
        is_dnr = any(str(t).upper().strip() not in non_dnr_tenants for t in tipologie_da_elaborare)
        
    if is_dnr:
        try:
            rientri_ref = db.collection('clienti').document('DNR').collection('rientri ddt')
            for r_doc in rientri_ref.stream():
                r_data = r_doc.to_dict() or {}
                stato = str(r_data.get('stato') or r_data.get('Stato') or '').strip().lower()
                if 'allegato' in stato and data_consegna not in stato: continue
                    
                r_cod = str(r_data.get('codice_consegna') or r_data.get('Codice consegna') or '').strip()
                if not r_cod: continue
                r_data_ddt = r_data.get('data_ddt') or r_data.get('Data e Num DDT') or ''
                r_cod_l = r_cod.lower()
                
                chiave_esistente = None
                for k in punti_map.keys():
                    if str(k).strip().lower() == r_cod_l:
                        chiave_esistente = k
                        break
                        
                stato_attuale = str(r_data.get('stato') or r_data.get('Stato') or '')
                nuovo_stato = ""
                tipo_val = str(r_data.get('Tipo') or r_data.get('tipo') or '').lower().strip()
                is_parz = bool(r_data.get('is_parziale') or False) or (tipo_val == 'parziale')
                note_val = str(r_data.get('note') or r_data.get('Note') or r_data.get('nota_integrativa') or '').strip()
                
                rientro_obj = {
                    "codice": r_cod,
                    "status": "red",
                    "data_ddt": r_data_ddt,
                    "is_parziale": is_parz,
                    "nota_integrativa": note_val
                }
                
                if chiave_esistente:
                    punti_map[chiave_esistente]['rientri_alert'].append(rientro_obj)
                    nuovo_stato = f"allegato DDT {data_consegna}"
                else:
                    cliente_info = db_mappati.get(r_cod_l)
                    if r_cod not in punti_map:
                        punti_map[r_cod] = {
                            "nome": (cliente_info.get('cliente') or cliente_info.get('nome_consegna') or r_cod) if cliente_info else r_cod,
                            "indirizzo": cliente_info.get('indirizzo', '') if cliente_info else '',
                            "codice_frutta": cliente_info.get('codice_frutta', 'p00000') if cliente_info else 'p00000',
                            "codice_latte": cliente_info.get('codice_latte', 'p00000') if cliente_info else 'p00000',
                            "codici_ddt_frutta": [],
                            "codici_ddt_latte": [],
                            "zona": "PUNTI_DI_CONSEGNA",
                            "lat": float(cliente_info.get('lat', 0)) if cliente_info and cliente_info.get('lat') else 0,
                            "lon": float(cliente_info.get('lon', 0)) if cliente_info and cliente_info.get('lon') else 0,
                            "rientri_alert": [],
                            "_is_rientro_speciale": True
                        }
                    punti_map[r_cod]['rientri_alert'].append(rientro_obj)
                    nuovo_stato = "In lavorazione"
                    
                if stato_attuale != nuovo_stato:
                    try:
                        db.collection('clienti').document('DNR').collection('rientri ddt').document(r_doc.id).update({
                            'Stato': nuovo_stato,
                            'stato': firestore.DELETE_FIELD
                        })
                    except Exception as e_up:
                        print(f"[WARN] Impossibile aggiornare stato rientro {r_doc.id}: {e_up}")
        except Exception as e_r:
            print(f"[ERROR] Errore integrazione rientri: {e_r}")

    # 3. Organizza per Zone (Step 4 locale)
    zone_finali = []
    color_index = 0
    palette = ["#4f46e5", "#10b981", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1", "#a855f7", "#3b82f6", "#22c55e", "#d946ef", "#84cc16"]

    # --- LOGICA A BLOCCHI (CASSAFORTE) ---
    def get_tenant_from_cz(cz):
        if not cz: return "DNR"
        cz = cz.upper().strip()
        if cz == "CATTEL": return "CATTEL"
        if cz in ("GRAN CHEF", "GRAND_CHEF", "GRAN_CHEF", "GRAND CHEF"): return "GRAN_CHEF"
        if cz == "DAC": return "DAC"
        return "DNR"

    for zid, old_z in mappa_zone_esistenti.items():
        # Verifichiamo se il vecchio viaggio contiene ALMENO UN cliente dei tenant da sovrascrivere
        da_scartare = False
        stops = old_z.get("lista_punti", [])
        if not stops: stops = old_z.get("stops", [])
        
        for stop in stops:
            stop_comp = stop.get("competenze", [])
            if stop_comp:
                stop_tenants = [get_tenant_from_cz(comp) for comp in stop_comp]
            else:
                stop_tenants = [get_tenant_from_cz(old_z.get("cliente_zona", ""))]
                
            if any(t in tenant_con_ddt for t in stop_tenants):
                da_scartare = True
                break
                
        if not da_scartare:
            # Il viaggio è sicuro, non contiene clienti sovrascritti -> CASSAFORTE
            old_z_copy = dict(old_z)
            # Riassegna la palette per mantenere uniformità
            old_z_copy["color"] = palette[color_index % len(palette)]
            zone_finali.append(old_z_copy)
            color_index += 1

    # Raggruppa i NUOVI punti da elaborare
    zone_dict = defaultdict(list)
    for p in punti_map.values():
        z_id = p.get("zona", "0000")
        if not z_id: z_id = "0000"
        zone_dict[z_id].append(p)

    # Costruisci Zone Normali senza usare i prefissi hardcoded
    normal_keys = [k for k in zone_dict.keys() if k not in ("DDT_DA_INSERIRE", "PUNTI_DI_CONSEGNA", "0000", "SENZA_ZONA")]
    
    # Ordiniamo le zone per nome in modo deterministico
    normal_keys = sorted(normal_keys)
    
    tenant_counters = {}
    
    for zid in normal_keys:
        punti = zone_dict[zid]
        if not punti:
            continue
            
        # Determina la competenza/tenant del giro prendendola nativamente dal primo punto
        primo_punto = punti[0]
        comp_lista = primo_punto.get("competenze", [])
        tenant = comp_lista[0] if comp_lista else (primo_punto.get("tipo") or "DNR")
        
        # Normalizzazione estetica per la UI (Card dei Viaggi)
        if tenant in ("GRAND_CHEF", "GRAND CHEF", "GRAN_CHEF"):
            tenant = "GRAN CHEF"
        elif tenant in ("FRUTTA", "LATTE"):
            tenant = "DNR"
            
        if tenant not in tenant_counters:
            tenant_counters[tenant] = 1
        else:
            tenant_counters[tenant] += 1
            
        idx = tenant_counters[tenant]
        
        # (La logica fine di rinomina sarà affidata all'AI futura, per ora manteniamo retro-compatibilità
        # pulendo i vecchi prefissi se l'estrattore li ha inseriti)
        # Logica di rinomina dinamica per QUALSIASI tenant basato su file (es. DAC, GRAND CHEF, PINCO PALLO)
        # Se la zona creata nel parser inizia col nome del tenant (es. "Pinco Pallo_8xY3b..."), rinominiamo il giro in modo pulito.
        nome_giro = zid
        if tenant == "DNR":
            # DNR usa zone geografiche reali, non prefissi file
            nome_giro = zid if zid != "0000" else f"V{idx:02d}"
            tenant = "PROGETTO SCUOLE" # Fallback visivo richiesto storicamente per DNR
        elif zid.startswith(f"{tenant}_"):
            parts = zid.split('_', 1)
            label = parts[1] if len(parts) > 1 and parts[1] != "0000" else f"{idx:02d}"
            nome_giro = f"{tenant} {label}"
        elif tenant == "GRAN CHEF" and zid.startswith("GC_"):
            # Gestione dei vecchi job GRAN CHEF (retrocompatibilità)
            nome_giro = f"Gran Chef {idx:02d}"
            
        zone_finali.append({
            "id_zona": zid,
            "nome_giro": nome_giro,
            "color": palette[color_index % len(palette)],
            "lista_punti": punti,
            "cliente_zona": tenant
        })
        color_index += 1
        
    for sp_key, label, c_z in [
        ("0000", "0000 - Non Assegnato", ""), 
        ("PUNTI_DI_CONSEGNA", "PUNTI_DI_CONSEGNA - Anomalia", ""),
        ("DDT_DA_INSERIRE", "DDT DA INSERIRE - Inserimento Rapido", "")
    ]:
        if sp_key in zone_dict and zone_dict[sp_key]:
            zone_finali.append({
                "id_zona": sp_key, "nome_giro": label, "color": "#cbd5e1",
                "lista_punti": zone_dict[sp_key], "cliente_zona": c_z
            })

    # Ordina e formatta
    master_json = []
    zone_finali_ordinate = sorted(zone_finali, key=lambda x: (
        x["id_zona"] in ["0000", "PUNTI_DI_CONSEGNA", "DDT_DA_INSERIRE"],
        x["id_zona"]
    ))
    
    for z in zone_finali_ordinate:
        if not z.get('lista_punti'):
            if z.get('stops'):
                z['lista_punti'] = z['stops']
            else:
                z['lista_punti'] = []
            
        # Pulisce codici nan nei punti originali
        for p in z["lista_punti"]:
            if str(p.get("codice_frutta", "")).lower() == "nan": p["codice_frutta"] = "p00000"
            if str(p.get("codice_latte", "")).lower() == "nan": p["codice_latte"] = "p00000"
            
        z_dict = {
            "id_zona": z["id_zona"],
            "nome_giro": z["nome_giro"],
            "color": z["color"],
            "cliente_zona": z.get("cliente_zona", ""),
            "stops": z["lista_punti"]
        }
        master_json.append(z_dict)

    # Scrittura JSON Master nello Storage (Globale per retrocompatibilità + Specifico per ciascun Tenant attivo)
    output_str = json.dumps({"data_consegna": data_consegna, "zone": master_json}, indent=2)
    bucket.blob(f"REPORTS/{data_consegna}/viaggi_giornalieri_Johnson.json").upload_from_string(
        output_str, content_type='application/json'
    )
    
    tenants_con_viaggi = set()
    for z in master_json:
        doc_id_z = f"{data_consegna}_{z['id_zona']}"
        tenant_v = get_tenant_from_viaggio_id(doc_id_z)
        tenants_con_viaggi.add(tenant_v)
        
    for t_v in tenants_con_viaggi:
        # Filtriamo le zone di competenza di questo tenant
        master_json_t = []
        for z in master_json:
            doc_id_z = f"{data_consegna}_{z['id_zona']}"
            t_z = get_tenant_from_viaggio_id(doc_id_z)
            if t_z == t_v:
                master_json_t.append(z)
                
        output_str_t = json.dumps({"data_consegna": data_consegna, "zone": master_json_t, "tenant": t_v}, indent=2)
        bucket.blob(f"{t_v}/REPORTS/{data_consegna}/viaggi_giornalieri_Johnson.json").upload_from_string(
            output_str_t, content_type='application/json'
        )
    
    # Scrittura su Firestore (Salvataggio Viaggi divisi per Tenant)
    for z in master_json:
        doc_id = f"{data_consegna}_{z['id_zona']}"
        tenant_viaggio = get_tenant_from_viaggio_id(doc_id)
        viaggio_ref = db.collection('clienti').document(tenant_viaggio).collection('viaggi ddt').document(doc_id)
        
        # Manteniamo t_guida_min, t_tot_min, km_reali, autista se erano presenti nella cassaforte
        old_viaggio_data = {}
        if z["id_zona"] in mappa_zone_esistenti:
            old_viaggio_data = mappa_zone_esistenti[z["id_zona"]]
            
        viaggio_data = {
            'data_lavoro': data_consegna,
            'id_zona': z['id_zona'],
            'nome_giro': z['nome_giro'],
            'cliente_zona': z['cliente_zona'],
            'colore': z['color'],
            'stops': z['stops'],
            'autista': old_viaggio_data.get('autista', ''),
            't_guida_min': old_viaggio_data.get('t_guida_min', 0),
            't_tot_min': old_viaggio_data.get('t_tot_min', 0),
            'km_reali': old_viaggio_data.get('km_reali', 0),
            'traffico_aggiornato_at': old_viaggio_data.get('traffico_aggiornato_at', ''),
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        try:
            viaggio_ref.set(viaggio_data, merge=True)
        except Exception as e_s:
            print(f"[ERROR] Salvataggio {doc_id} in Firestore fallito: {e_s}")

    # Generazione report delegata al frontend
    res_links = {}
    
    elapsed = time.time() - start_time
    print(f"[INFO] Report giornaliero generato in {elapsed:.2f}s")
    
    return {
        "status": "ok",
        "message": "Report generato con successo",
        "data_consegna": data_consegna,
        "zone_generate": len(master_json),
        "links": res_links,
    }





# --- CODICE MIGRAZIONE MAPPE INTERATTIVE 3B E PIPELINE 5, 6, 7B SU WEB ---


import hashlib
import uuid
from urllib.parse import quote
from decimal import Decimal

DEPOT_VEGGIANO = {"lat": 45.442805, "lon": 11.714498, "nome": "DEPOSITO VEGGIANO", "indirizzo": "Via Alessandro Volta 25/a, 35030 Veggiano (PD)"}
DEPOT_CASTENEDOLO = {"lat": 45.471591, "lon": 10.298200, "nome": "DEPOSITO CASTENEDOLO", "indirizzo": "Via Vulcania snc, 25014 Castenedolo (BS)"}
DEPOT_SOMMACAMPAGNA = {"lat": 45.414500, "lon": 10.898500, "nome": "DEPOSITO SOMMACAMPAGNA", "indirizzo": "Via Caselle 90/b, 37066 Sommacampagna (VR)"}

CODICE_VUOTO = "p00000"

CONSOLIDAMENTO = {
    "LT-ES-04-LS":   ("Fardelli",  "Bottiglie", 10),
    "LT-AQ-04-LB":   ("Fardelli",  "Bottiglie", 12),
    "LT-AQ-04-LS":   ("Fardelli",  "Bottiglie", 10),
    "LT-AQ-04-LV":   ("Fardelli",  "Bottiglie",  6),
    "LT-ESL-IN-LB":  ("Fardelli",  "Bottiglie",  6),
    "YO-BI-MN-04-LB":("Cartoni",   "Cluster",   10),
    "YO-DL-02-LC":   ("Cartoni",   "Porzioni",   6),
    "AP-SU-PC":      ("Cartoni",   "Porzioni",  24),
    "FO-DI-GP-01-NI":("Colli",     "Buste",     16),
    "FO-DI-PV-04-LB":("Colli",     "Fette",     20),
    "AL-M-BI-L3-NI": ("Colli",     "Porzioni",  10),
    "SUCCO-REC":     ("Cartoni",   "Porzioni",  24),
    "PF-T-LI-L3-NA": ("Cartoni",   "Porzioni",   8),
    "SU-M-BI-L3-NI": ("Cartoni",   "Porzioni",  18),
    "YO-CN-MN-04-":  ("Cartoni",   "Cluster",   10),
    "YO-CN-MN-04-LB":("Cartoni",   "Cluster",   10),
    "AL-T-LI-NA":    ("Cartoni",   "Porzioni",  12),
    "NE-M-BI-L3-NI": ("Colli",     "Porzioni",  10),
}

UNITA_QTY = r"(Confezioni|Confezione|confezioni|confezione|Colli|Collo|colli|collo|Brick|brick|Fardelli|Fardello|fardelli|fardello|Bottiglie|Bottiglia|bottiglie|bottiglia|Cartoni|Cartone|cartoni|cartone|Cluster|cluster|Porzioni|Porzione|porzioni|porzione|Fascette|Fascetta|fascette|fascetta|Manifesti|Manifesto|manifesti|manifesto|Fette|Fetta|fette|fetta|Buste|Busta|buste|busta|pz)"
SCAD_RE = re.compile(r"Scad\.\s*min\.\s*(\d{2}/\d{2}/\d{4})", re.I)














def _genera_url_storage_token(blob):
    import uuid
    from urllib.parse import quote
    
    # Prova a recuperare il token esistente dai metadati per evitare di invalidare vecchi link
    try:
        blob.reload()
        if blob.metadata and "firebaseStorageDownloadTokens" in blob.metadata:
            token = blob.metadata["firebaseStorageDownloadTokens"]
            return f"https://firebasestorage.googleapis.com/v0/b/{BUCKET_NAME}/o/{quote(blob.name, safe='')}?alt=media&token={token}"
    except Exception as e_meta:
        print(f"[WARN] Impossibile leggere metadati esistenti per token: {e_meta}")
        
    token = str(uuid.uuid4())
    blob.metadata = {"firebaseStorageDownloadTokens": token}
    blob.patch()
    return f"https://firebasestorage.googleapis.com/v0/b/{BUCKET_NAME}/o/{quote(blob.name, safe='')}?alt=media&token={token}"





@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_256, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]),
    invoker="public")
def risolvi_tenant_consegna(req: https_fn.CallableRequest):
    """
    Risolve il tenant logistico in base al codice consegna cercando
    dinamicamente su tutte le anagrafiche.
    """
    from services.tenant_service import handle_risolvi_tenant_consegna

    codice = str(req.data.get("codice_consegna", "")).strip() if req.data else ""
    db = get_db()
    
    return handle_risolvi_tenant_consegna(codice, db)

# --- ENDPOINTS HTTP ---
@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=540,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def web_calcola_percorsi(req: https_fn.CallableRequest):
    if not req.auth or not req.auth.uid: raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    caller_doc = get_db().collection("dipendenti").document(req.auth.uid).get()
    if not caller_doc.exists or caller_doc.to_dict().get("ruolo") not in {"amministratore", "impiegata"}: raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.PERMISSION_DENIED, message="Negato.")
    from services.routing_service import handle_web_calcola_percorsi
    return handle_web_calcola_percorsi(req)

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_2, timeout_sec=540,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def genera_completo_giornata(req: https_fn.CallableRequest):
    if not req.auth: raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    from services.routing_service import handle_genera_completo_giornata
    return handle_genera_completo_giornata(req)

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=540,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def processa_job_pdf(req: https_fn.CallableRequest):
    if not req.auth or not req.auth.uid: raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    caller_doc = get_db().collection("dipendenti").document(req.auth.uid).get()
    if not caller_doc.exists or caller_doc.to_dict().get("ruolo") not in {"amministratore", "impiegata"}: raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.PERMISSION_DENIED, message="Negato.")
    from services.pdf_service import handle_processa_job_pdf
    return handle_processa_job_pdf(req)

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=300,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def genera_distinta_viaggio(req: https_fn.CallableRequest):
    if not req.auth: raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    from services.routing_service import handle_genera_distinta_viaggio
    return handle_genera_distinta_viaggio(req)

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=300,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def ottimizza_viaggio(req: https_fn.CallableRequest):
    if not req.auth: raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    from services.routing_service import handle_ottimizza_viaggio
    return handle_ottimizza_viaggio(req)

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=300,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def genera_mappa_autista(req: https_fn.CallableRequest):
    if not req.auth or not req.auth.uid:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )

    caller_uid = req.auth.uid
    caller_doc = get_db().collection("dipendenti").document(caller_uid).get()
    if not caller_doc.exists or caller_doc.to_dict().get("ruolo") not in ["amministratore", "impiegata"]:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permessi insufficienti."
        )
    
    from services.map_service import handle_genera_mappa_autista
    
    return handle_genera_mappa_autista(
        viaggio_id=req.data.get("viaggio_id"),
        distinta_url=req.data.get("distinta_url"),
        tenant=req.data.get("tenant"),
        get_viaggio_doc_fn=_get_viaggio_doc_self_healing,
        get_depot_fn=_get_depot_for_points_cloud,
        get_directions_data_fn=_get_directions_data,
        genera_html_fn=_genera_html_mappa,
        bucket=storage.bucket(name=BUCKET_NAME),
        genera_url_token_fn=_genera_url_storage_token,
        registra_statistica_fn=_registra_statistica,
        time_per_stop_min=TIME_PER_STOP_MIN
    )

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=300,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def ricalcola_percorso(req: https_fn.CallableRequest):
    if not req.auth: raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    from services.routing_service import handle_ricalcola_percorso
    return handle_ricalcola_percorso(req)

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=540,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def riepilogo_fatturazione(req: https_fn.CallableRequest):
    from services.billing_service import handle_riepilogo_fatturazione
    
    mese = req.data.get("mese", "") if req.data else ""
    anno = req.data.get("anno", "2026") if req.data else "2026"
    
    return handle_riepilogo_fatturazione(
        mese=mese,
        anno=anno,
        bucket_name=BUCKET_NAME,
        stats_callback=_registra_statistica,
        auth_context=req.auth
    )

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=120,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def pulisci_cartelle_elaborazione(req: https_fn.CallableRequest):
    """Pulisce le cartelle di storage e i job Firestore per la giornata selezionata prima di caricare i nuovi file."""
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )

    try:
        data_consegna = req.data.get("data_consegna")
        tipologie = req.data.get("tipologie", ["FRUTTA", "LATTE", "GRAND_CHEF", "DAC"])
        bucket = storage.bucket(name=BUCKET_NAME)
        db = get_db()
        
        from services.cleanup_service import handle_pulisci_cartelle_elaborazione
        return handle_pulisci_cartelle_elaborazione(data_consegna, tipologie, bucket, db)
    except Exception as e:
        return {"status": "errore", "message": str(e)}

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def check_giornaliero(req: https_fn.CallableRequest):
    from services.monitoring_service import handle_check_giornaliero
    return handle_check_giornaliero(req)

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def stats_giornaliere(req: https_fn.CallableRequest):
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )
    print(f"[DEPRECATION] LEGACY_ENDPOINT_INVOKED endpoint=stats_giornaliere uid={req.auth.uid}")
    from services.monitoring_service import handle_stats_giornaliere
    return handle_stats_giornaliere(req)

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def chiudi_giornata(req: https_fn.CallableRequest):
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message='Non autorizzato.'
        )
    from services.operations_service import handle_chiudi_giornata
    return handle_chiudi_giornata(get_db())

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=300,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def genera_report_giornaliero(req: https_fn.CallableRequest):
    if not req.auth or not req.auth.uid:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )
    
    caller_uid = req.auth.uid
    dipendente_doc = get_db().collection("dipendenti").document(caller_uid).get()
    if not dipendente_doc.exists:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permessi insufficienti."
        )
    
    ruolo = dipendente_doc.to_dict().get("ruolo", "").lower()
    if ruolo not in ["amministratore", "impiegata"]:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permessi insufficienti."
        )

    try:
        data_consegna = req.data.get("data_consegna") if isinstance(req.data, dict) else None
        tipologie_da_elaborare = req.data.get("tipologie_da_elaborare", []) if isinstance(req.data, dict) else []
        azioni = req.data.get("azioni", {}) if isinstance(req.data, dict) else {}
        return core_genera_report_giornaliero(
            req.auth.uid if req.auth else None,
            data_consegna,
            tipologie_da_elaborare
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Global exception: {str(e)}"}


@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_256, timeout_sec=120,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def elimina_giornata_logistica(req: https_fn.CallableRequest):
    """
    Funzione di Tabula Rasa o Soft Delete:
    - Se soft_delete == True: imposta solo archiviato_ui: True (mantenendo intatti i dati nel Cloud per i primi 2 mesi).
    - Se passate tipologie_da_eliminare / tenant_da_eliminare: elimina solo quelle tipologie e tenant specifici (Sovrascrittura Parziale).
    - Altrimenti: elimina completamente una giornata (split_ddt, REPORTS, CONSEGNE e record Firestore).
    """
    if not req.auth or not req.auth.uid:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )

    caller_uid = req.auth.uid
    caller_doc = (
        get_db()
        .collection("dipendenti")
        .document(caller_uid)
        .get()
    )
    if not caller_doc.exists or caller_doc.to_dict().get("ruolo") != "amministratore":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permessi insufficienti."
        )

    data_consegna = req.data.get("data_consegna")
    soft_delete = req.data.get("soft_delete", False)
    
    # Parametri per eliminazione selettiva
    tipologie_da_eliminare = req.data.get("tipologie_da_eliminare", [])
    tenant_da_eliminare = req.data.get("tenant_da_eliminare", [])
    cliente_zona_da_eliminare = req.data.get("cliente_zona_da_eliminare", [])
    
    if not data_consegna:
        return {"status": "errore", "message": "data_consegna mancante"}

    db = get_db()
    
    if soft_delete:
        print(f"[INFO] Richiesta Soft Delete (pulizia UI) per la giornata {data_consegna}")
        try:
            try:
                tenants = [doc.id for doc in db.collection('clienti').list_documents() if doc.id != "report_logistici"]
            except:
                tenants = ["DNR", "CATTEL", "GRAN CHEF", "BAUER", "DAC"]
            
            # Aggiorna il report logistico globale
            doc_ref = db.collection('clienti').document('report_logistici').collection('giornate').document(data_consegna)
            if doc_ref.get().exists:
                doc_ref.update({"archiviato_ui": True, "archiviato_at": datetime.now().isoformat()})
                
            for tenant in tenants:
                # Aggiorna anche i viaggi ddt per coerenza
                viaggi_ref = db.collection('clienti').document(tenant).collection('viaggi ddt')
                viaggi = viaggi_ref.where("data_lavoro", "==", data_consegna).stream()
                for v in viaggi:
                    viaggi_ref.document(v.id).update({"archiviato_ui": True})
                
            print(f"[INFO] Soft Delete completato con successo per {data_consegna}")
            return {"status": "ok", "message": "Giornata rimossa dalla schermata attiva (dati conservati su Cloud)"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "errore", "message": f"Errore Soft Delete: {str(e)}"}

    print(f"[INFO] Inizio eliminazione per la giornata {data_consegna}. Parziale: {bool(tipologie_da_eliminare)}")
    bucket = storage.bucket(name=BUCKET_NAME)
    
    try:
        # 1. Elimina cartelle su Storage
        data_f = data_consegna.replace('/', '-')
        
        if tipologie_da_eliminare:
            prefixes_to_clean = []
            for t in tipologie_da_eliminare:
                prefixes_to_clean.append(f"split_ddt/{data_consegna}/{t.upper()}/")
        else:
            prefixes_to_clean = [
                f"split_ddt/{data_consegna}/",
                f"REPORTS/{data_consegna}/",
                f"CONSEGNE/CONSEGNE_{data_f}/"
            ]
            try:
                tenants = [doc.id for doc in db.collection('clienti').list_documents()]
            except Exception as e:
                print(f"[elimina_giornata] Errore lookup tenant per storage: {e}")
                tenants = ["CATTEL", "GRAN CHEF", "BAUER", "DAC"]
                
            for tenant in tenants:
                if tenant == "DNR":
                    continue # Già pulito nella root REPORTS/
                tenant_folder = tenant.upper().replace(" ", "_")
                prefixes_to_clean.append(f"{tenant_folder}/REPORTS/{data_consegna}/")
                prefixes_to_clean.append(f"{tenant_folder}/CONSEGNE/CONSEGNE_{data_f}/")
        
        for pref in prefixes_to_clean:
            blobs = bucket.list_blobs(prefix=pref)
            for b in blobs:
                try:
                    b.delete()
                except Exception as ex:
                    print(f"[WARN] Errore cancellazione {b.name}: {ex}")
                    
        # 2. Elimina record da Firestore (SOLO se eliminiamo tutta la giornata)
        if not tipologie_da_eliminare:
            print(f"[INFO] Eliminazione report logistico principale per {data_consegna}")
            db.collection('clienti').document('report_logistici').collection('giornate').document(data_consegna).delete()
        
        # 3. Elimina i viaggi ddt
        print(f"[INFO] Eliminazione viaggi ddt per la giornata {data_consegna}")
        try:
            tenants = [doc.id for doc in db.collection('clienti').list_documents()]
        except:
            tenants = ["DNR", "CATTEL", "GRAN CHEF", "BAUER", "DAC"]
        for tenant in tenants:
            viaggi_ref = db.collection('clienti').document(tenant).collection('viaggi ddt')
            viaggi_da_eliminare = viaggi_ref.where("data_lavoro", "==", data_consegna).stream()
            for v in viaggi_da_eliminare:
                v_data = v.to_dict()
                v_cliente_zona = v_data.get("cliente_zona", "")
                
                # Se siamo in modalità selettiva, controlla se questo viaggio appartiene al cliente da eliminare
                should_delete = False
                if not tipologie_da_eliminare:
                    should_delete = True
                else:
                    if v_cliente_zona in cliente_zona_da_eliminare:
                        should_delete = True
                    elif ("PROGETTO SCUOLE" in cliente_zona_da_eliminare or "" in cliente_zona_da_eliminare) and (not v_cliente_zona or v_cliente_zona == "PROGETTO SCUOLE"):
                        # Fallback logico per Frutta/Latte che spesso non hanno cliente_zona o hanno PROGETTO SCUOLE
                        should_delete = True
                        
                if should_delete:
                    try:
                        v.reference.delete()
                    except Exception as e:
                        print(f"[ERROR] Impossibile eliminare viaggio {v.id}: {str(e)}")
                        pass
                
        # 3.1 Elimina pianificazione viaggi (se esiste)
        print(f"[INFO] Eliminazione pianificazione viaggi per la giornata {data_consegna}")
        try:
            tenants = [doc.id for doc in db.collection('clienti').list_documents()]
        except:
            tenants = ["DNR", "CATTEL", "GRAN CHEF", "BAUER", "DAC"]
        for tenant in tenants:
            pian_ref = db.collection('clienti').document(tenant).collection('pianificazione_viaggi')
            # Cancellazione document based per data_lavoro o id
            for p in pian_ref.stream():
                data = p.to_dict()
                should_delete = False
                if not tipologie_da_eliminare:
                    if data.get("data_lavoro") == data_consegna or p.id.startswith(f"{data_consegna}_"):
                        should_delete = True
                else:
                    v_cliente_zona = data.get("cliente_zona", "")
                    if data.get("data_lavoro") == data_consegna or p.id.startswith(f"{data_consegna}_"):
                        if v_cliente_zona in cliente_zona_da_eliminare:
                            should_delete = True
                        elif ("PROGETTO SCUOLE" in cliente_zona_da_eliminare or "" in cliente_zona_da_eliminare) and (not v_cliente_zona or v_cliente_zona == "PROGETTO SCUOLE"):
                            should_delete = True
                
                if should_delete:
                    try:
                        p.reference.delete()
                    except Exception as e:
                        pass

                
        # 4. Elimina eventuali processing_jobs rimasti
        print(f"[INFO] Eliminazione processing_jobs per la giornata {data_consegna}")
        tenants_to_clean = tenant_da_eliminare if tenant_da_eliminare else ["GRAND_CHEF", "CATTEL", "DNR", "DAC"]
        for t in tenants_to_clean:
            tenant = "GRAN CHEF" if t == "GRAND_CHEF" else t
            jobs_ref = db.collection('clienti').document(tenant).collection('processing_jobs')
            old_jobs = jobs_ref.where('data_lavoro', '==', data_consegna).stream()
            for oj in old_jobs:
                try:
                    oj.reference.delete()
                except Exception:
                    pass
        
        print(f"[INFO] Eliminazione completata con successo per {data_consegna}")
        return {"status": "ok", "message": "Giornata eliminata con successo"}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Errore interno: {str(e)}"}


# ─── CLOUD FUNCTION ALIAS PER CALCOLA PERCORSI ────────────────────────────────

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=540,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def calcola_percorsi_zone(req: https_fn.CallableRequest):
    if not req.auth: raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    from services.routing_service import handle_calcola_percorsi_zone
    return handle_calcola_percorsi_zone(req)






@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=300,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def aggiorna_traffico_serale(req: https_fn.CallableRequest):
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )

    try:
        from services.traffic_service import handle_aggiorna_traffico_serale
        data_consegna = req.data.get("data_consegna")
        db = get_db()
        return handle_aggiorna_traffico_serale(
            data_consegna=data_consegna,
            db=db,
            get_directions_with_traffic_fn=_get_directions_sec_with_traffic,
            haversine_fn=_haversine,
            registra_statistica_fn=_registra_statistica,
            depot_cloud=DEPOT_CLOUD,
            time_per_stop_min=TIME_PER_STOP_MIN
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Global exception: {str(e)}"}

def get_tenant_from_cz(cz):
    if not cz: return "DNR"
    cz = str(cz).strip().upper()
    if cz in ("GRAN CHEF", "GRAND_CHEF", "GRAN_CHEF", "GRAND CHEF"): return "GRAN_CHEF"
    if cz == "DAC": return "DAC"
    if "CATTEL" in cz: return "CATTEL"
    return "DNR"

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_256, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def preflight_elaborazione_mappe(req: https_fn.CallableRequest):
    """
    Pre-flight check per l'elaborazione mappe.
    Rileva quali blocchi hanno nuovi dati in split_ddt e se i vecchi viaggi 
    hanno contaminazioni (fornitori misti).
    Restituisce un dizionario con i dati necessari al frontend per decidere lo scenario (A, B o C).
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )

    data_consegna = req.data.get("data_consegna")
    if not data_consegna:
        return {"status": "errore", "message": "data_consegna mancante"}

    bucket = storage.bucket(name=BUCKET_NAME)

    from services.operations_service import handle_preflight_elaborazione_mappe
    return handle_preflight_elaborazione_mappe(data_consegna, bucket, get_tenant_from_cz)
@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_256, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def ripristina_cache_backup(req: https_fn.CallableRequest):
    if not req.auth or not req.auth.uid:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )

    caller_uid = req.auth.uid
    caller_doc = get_db().collection("dipendenti").document(caller_uid).get()
    if not caller_doc.exists or caller_doc.to_dict().get("ruolo") != "amministratore":
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permessi insufficienti."
        )
    """
    Gestione backup cache:
    - azione == 'lista': restituisce l'elenco dei backup disponibili in caches_backup/
    - azione == 'ripristina': copia il backup selezionato in caches/distanze_reali_cache.json
    """
    azione = req.data.get("azione", "lista")
    target_backup = req.data.get("target_backup")
    
    bucket = storage.bucket(name=BUCKET_NAME)
    global _LOCAL_STORAGE_CACHES, _INITIAL_CACHE_COUNTS
    
    if azione == "lista":
        blobs = bucket.list_blobs(prefix="caches_backup/")
        backup_list = []
        for b in blobs:
            if b.name.endswith(".json"):
                backup_list.append({
                    "name": b.name.replace("caches_backup/", ""),
                    "path": b.name,
                    "size": b.size,
                    "updated": b.updated.strftime("%Y-%m-%d %H:%M:%S") if b.updated else ""
                })
        # Ordina per nome/data decrescente
        backup_list.sort(key=lambda x: x["name"], reverse=True)
        return {"status": "ok", "backups": backup_list}
        
    elif azione == "ripristina":
        if not target_backup:
            return {"status": "errore", "message": "Nessun backup specificato per il ripristino"}
            
        print(f"[CACHE-GUARD] Richiesta ripristino manuale da {target_backup}")
        try:
            source_blob = bucket.blob(f"caches_backup/{target_backup}")
            if not source_blob.exists():
                return {"status": "errore", "message": f"Il backup {target_backup} non esiste su Storage"}
                
            dest_blob = bucket.blob("caches/distanze_reali_cache.json")
            
            # Effettua la copia lato storage
            bucket.copy_blob(source_blob, bucket, dest_blob.name)
            
            # Ricarica in memoria il backup ripristinato
            data_str = dest_blob.download_as_string().decode("utf-8")
            loaded_data = json.loads(data_str)
            _LOCAL_STORAGE_CACHES["distanze_reali_cache.json"] = loaded_data
            _INITIAL_CACHE_COUNTS["distanze_reali_cache.json"] = len(loaded_data)
            
            print(f"[CACHE-GUARD] Ripristino completato con successo da {target_backup} ({len(loaded_data)} chiavi)")
            return {"status": "ok", "message": f"Backup {target_backup} ripristinato con successo ({len(loaded_data)} distanze attive)"}
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "errore", "message": f"Errore durante il ripristino: {str(e)}"}
            
    return {"status": "errore", "message": "Azione non riconosciuta"}


# ─── ARCHIVIAZIONE A FREDDO E RECUPERO R&D (PUNTO 2) ───────────────────────────

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=540,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def gestisci_archiviazione_mensile(req: https_fn.CallableRequest):
    if not req.auth or not req.auth.uid:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )

    caller_uid = req.auth.uid
    caller_doc = get_db().collection("dipendenti").document(caller_uid).get()
    allowed_roles = {"amministratore", "impiegata"}
    
    if not caller_doc.exists or caller_doc.to_dict().get("ruolo") not in allowed_roles:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permessi insufficienti."
        )

    """
    Esegue il backup automatico a inizio del 3° mese.
    Sposta i dati operativi in ARCHIVIO_STORICO_RD/[YYYY-MM]/[data_consegna]/
    eseguendo un controllo ferreo di residenza prima di cancellare l'originale.
    """
    print("[ARCHIVIO-RD] Avvio procedura di archiviazione mensile automatica (3° mese)...")
    db = get_db()
    bucket = storage.bucket(name=BUCKET_NAME)
    
    giornate_archiviate = []
    errori = []
    
    try:
        now = datetime.now()
        reports_ref = db.collection('clienti').document('report_logistici').collection('giornate')
        
        reports = list(reports_ref.stream())
        
        try:
            tenants = [doc.id for doc in db.collection('clienti').list_documents() if doc.id != "report_logistici"]
        except:
            tenants = ["DNR", "CATTEL", "GRAN CHEF", "BAUER", "DAC"]
        
        for rep in reports:
            data_consegna = rep.id
            rep_data = rep.to_dict()
            
            # Calcola l'età della giornata
            try:
                # data_consegna è nel formato DD-MM-YYYY
                dt_obj = datetime.strptime(data_consegna, "%d-%m-%Y")
                giorni_trascorsi = (now - dt_obj).days
            except Exception as e_dt:
                print(f"[WARN] Impossibile calcolare data per {data_consegna}: {e_dt}")
                continue
                
            # Verifica se appartiene al 3° mese (più di 60 giorni fa) e non è già archiviato a freddo
            if giorni_trascorsi > 60 and not rep_data.get("archiviato_storico_rd", False):
                print(f"[ARCHIVIO-RD] Giornata {data_consegna} idonea per archiviazione a freddo ({giorni_trascorsi} giorni fa).")
                mese_anno = dt_obj.strftime("%Y-%m")
                pref_dest = f"ARCHIVIO_STORICO_RD/{mese_anno}/{data_consegna}"
                
                # 1. Salvataggio record Firestore su Storage
                blob_rep = bucket.blob(f"{pref_dest}/firestore_report.json")
                blob_rep.upload_from_string(json.dumps(rep_data, default=str), content_type="application/json")
                
                # Salvataggio di tutti i viaggi ddt associati da tutti i tenant
                viaggi_snap = []
                viaggi_tenants = {}
                for t in tenants:
                    t_viaggi = list(db.collection('clienti').document(t).collection('viaggi ddt').where("data_lavoro", "==", data_consegna).stream())
                    for v in t_viaggi:
                        viaggi_snap.append(v)
                        viaggi_tenants[v.id] = t
                        
                viaggi_count = 0
                for v in viaggi_snap:
                    v_blob = bucket.blob(f"{pref_dest}/viaggi_ddt/{v.id}.json")
                    v_blob.upload_from_string(json.dumps(v.to_dict(), default=str), content_type="application/json")
                    viaggi_count += 1
                    
                # 2. Copia cartelle Storage
                data_f = data_consegna.replace('/', '-')
                prefixes_to_copy = [
                    f"split_ddt/{data_consegna}/",
                    f"REPORTS/{data_consegna}/",
                    f"CONSEGNE/CONSEGNE_{data_f}/"
                ]
                
                file_copiati_verificati = True
                for pref in prefixes_to_copy:
                    blobs = bucket.list_blobs(prefix=pref)
                    for b in blobs:
                        dest_name = f"{pref_dest}/{b.name}"
                        try:
                            new_blob = bucket.copy_blob(b, bucket, dest_name)
                            # Controllo ferreo di Residenza e Integrità
                            if not new_blob.exists():
                                print(f"[FATAL] Fallita verifica residenza per {dest_name}")
                                file_copiati_verificati = False
                        except Exception as ex_copy:
                            print(f"[WARN] Errore copia {b.name}: {ex_copy}")
                            file_copiati_verificati = False
                            
                # 3. Filiera di controllo pre-cancellazione
                if file_copiati_verificati and blob_rep.exists():
                    print(f"[ARCHIVIO-RD] ✓ Verifica di residenza superata per {data_consegna}. Pulizia dati originali...")
                    # Elimina blob originali
                    for pref in prefixes_to_copy:
                        blobs = bucket.list_blobs(prefix=pref)
                        for b in blobs:
                            try:
                                b.delete()
                            except Exception as ex_del:
                                print(f"[WARN] Errore pulizia {b.name}: {ex_del}")
                                
                    # Aggiorna report logistico con il marcatore di archiviazione a freddo
                    reports_ref.document(data_consegna).update({
                        "archiviato_storico_rd": True,
                        "archiviato_storico_at": datetime.now().isoformat(),
                        "archiviato_ui": True
                    })
                    
                    # Rimuovi record attivi di viaggi ddt per liberare spazio
                    for v in viaggi_snap:
                        t_competenza = viaggi_tenants.get(v.id, "DNR")
                        db.collection('clienti').document(t_competenza).collection('viaggi ddt').document(v.id).delete()
                        
                    giornate_archiviate.append(data_consegna)
                else:
                    errori.append(f"Fallita verifica residenza per {data_consegna}")
                    print(f"[ARCHIVIO-RD] ⚠️ Verifica fallita per {data_consegna}. Dati attivi preservati.")
                    
        return {
            "status": "ok",
            "message": f"Archiviazione completata. {len(giornate_archiviate)} giornate trasferite in R&D.",
            "giornate_archiviate": giornate_archiviate,
            "errori": errori
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Errore procedura di archiviazione: {str(e)}"}


@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_512, timeout_sec=120,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def recupera_viaggio_storico(req: https_fn.CallableRequest):
    """
    Gestisce il pannello R&D in Link Viaggi:
    - azione == 'lista_mesi': elenca le directory mensili in ARCHIVIO_STORICO_RD/
    - azione == 'lista_giornate': elenca le date in ARCHIVIO_STORICO_RD/[mese]/
    - azione == 'recupera': ripristina i dati in viaggi ddt con flag is_recupero_rd: True
    """
    if not req.auth or not req.auth.uid:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )
    
    caller_uid = req.auth.uid
    dipendente_doc = get_db().collection("dipendenti").document(caller_uid).get()
    if not dipendente_doc.exists:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permessi insufficienti."
        )
    
    ruolo = dipendente_doc.to_dict().get("ruolo", "").lower()
    if ruolo not in ["amministratore", "impiegata"]:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permessi insufficienti."
        )

    from services.history_service import handle_recupera_viaggio_storico
    return handle_recupera_viaggio_storico(
        req,
        tenant_resolver=get_tenant_from_viaggio_id,
        bucket_name=BUCKET_NAME
    )

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_256, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def rilascia_recupero_storico(req: https_fn.CallableRequest):
    if not req.auth or not req.auth.uid:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )
    
    caller_uid = req.auth.uid
    dipendente_doc = get_db().collection("dipendenti").document(caller_uid).get()
    if not dipendente_doc.exists:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permessi insufficienti."
        )
    
    ruolo = dipendente_doc.to_dict().get("ruolo", "").lower()
    if ruolo not in ["amministratore", "impiegata"]:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permessi insufficienti."
        )

    from services.history_service import handle_rilascia_recupero_storico
    return handle_rilascia_recupero_storico(req)

# ─── SERVIZIO SPEDIZIONE EMAIL SMTP/IMAP CON ALLEGATI ───────────────────────
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import imaplib
import base64

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_512, timeout_sec=120,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def invia_email_fattura(req: https_fn.CallableRequest):
    """
    Spedisce l'email con allegati e la inserisce nella cartella Posta Inviata IMAP.
    """
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )

    from services.email_service import handle_invia_email_fattura
    return handle_invia_email_fattura(req.data, get_db())

    azione = req.data.get("azione")
    
    if azione == "test_smtp":
        test_config = req.data.get("test_config", {})
        smtp_host = test_config.get("smtp_host")
        smtp_port = test_config.get("smtp_port")
        imap_host = test_config.get("imap_host")
        imap_port = test_config.get("imap_port")
        email_user = test_config.get("email_user")
        email_password = test_config.get("email_password")
        sender_name = test_config.get("sender_name", "")
        smtp_security = test_config.get("smtp_security", "auto")
        
        if not all([smtp_host, smtp_port, imap_host, imap_port, email_user, email_password]):
            return {"status": "errore", "message": "Configurazione email per il test incompleta."}
            
        try:
            subject = "Log Solution - Test Connessione Servizio Email"
            body = "Messaggio di test autogenerato per collaudo SMTP e IMAP."
            
            res_imap = send_and_save_email(
                smtp_host, int(smtp_port), imap_host, int(imap_port),
                email_user, email_password, email_user, subject, body
            )
            
            msg_res = "Connessione SMTP riuscita ed email di test inviata!"
            if not res_imap:
                msg_res += " Nota: Invio riuscito, ma impossibile salvare nella cartella 'Posta Inviata' via IMAP (verifica indirizzo IMAP)."
                
            return {"status": "ok", "message": msg_res}
        except Exception as e:
            return {"status": "errore", "message": str(e)}
            
    elif azione == "invia_fattura":
        destinatario = req.data.get("destinatario")
        oggetto = req.data.get("oggetto")
        corpo = req.data.get("corpo")
        cliente = req.data.get("cliente")
        periodo = req.data.get("periodo")
        allegato_pdf = req.data.get("allegato_pdf")
        allegato_excel = req.data.get("allegato_excel")
        
        if not destinatario or not oggetto or not corpo:
            return {"status": "errore", "message": "I campi destinatario, oggetto e corpo sono obbligatori."}
            
        db = get_db()
        try:
            settings_doc = db.collection("config").document("email_settings").get()
            if not settings_doc.exists:
                return {"status": "errore", "message": "Configura prima le credenziali email in Impostazioni."}
                
            d = settings_doc.to_dict()
            smtp_host = d.get("smtp_host")
            smtp_port = d.get("smtp_port")
            imap_host = d.get("imap_host")
            imap_port = d.get("imap_port")
            email_user = d.get("email_user")
            email_password = d.get("email_password")
            sender_name = d.get("sender_name", "")
            smtp_security = d.get("smtp_security", "auto")
            
            if not all([smtp_host, smtp_port, imap_host, imap_port, email_user, email_password]):
                return {"status": "errore", "message": "Configurazione email su Firestore incompleta."}
                
            attachments = []
            if allegato_pdf:
                filename_pdf = f"Fatturazione_{cliente.replace(' ', '_')}_{periodo.replace(' ', '_')}.pdf"
                attachments.append((filename_pdf, allegato_pdf))
            if allegato_excel:
                filename_xls = f"Fatturazione_{cliente.replace(' ', '_')}_{periodo.replace(' ', '_')}.xlsx"
                attachments.append((filename_xls, allegato_excel))
                
            res_imap = send_and_save_email(
                smtp_host, int(smtp_port), imap_host, int(imap_port),
                email_user, email_password, destinatario, oggetto, corpo, attachments
            )
            
            # Scrive registro storico in Firestore
            log_ref = db.collection("clienti").document("DNR").collection("emails_inviate")
            log_ref.add({
                "cliente": cliente,
                "periodo": periodo,
                "destinatario": destinatario,
                "oggetto": oggetto,
                "inviato_da": email_user,
                "ha_pdf": bool(allegato_pdf),
                "ha_excel": bool(allegato_excel),
                "timestamp": datetime.now(),
                "status": "inviato",
                "imap_saved": res_imap
            })
            
            msg_res = "Email inviata con successo!"
            if not res_imap:
                msg_res += " Nota: Invio riuscito, ma impossibile inserire la copia in Posta Inviata del server."
                
            return {"status": "ok", "message": msg_res}
        except Exception as e:
            return {"status": "errore", "message": str(e)}
            
    return {"status": "errore", "message": "Azione non riconosciuta"}

@https_fn.on_request(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post", "options"]))
def autista_aggiorna_sequenza(req: https_fn.Request) -> https_fn.Response:
    from services.driver_service import handle_autista_aggiorna_sequenza
    return handle_autista_aggiorna_sequenza(req)

@https_fn.on_request(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post", "options"]))
def autista_salva_reso(req: https_fn.Request) -> https_fn.Response:
    from services.driver_service import handle_autista_salva_reso
    return handle_autista_salva_reso(req)

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=120)
def genera_riepiloghi_aziendali_light(req: https_fn.CallableRequest) -> typing.Any:
    try:
        # Verifica auth
        if not req.auth or not req.auth.uid:
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
                message="Non autorizzato."
            )

        caller_uid = req.auth.uid
        caller_doc = get_db().collection("dipendenti").document(caller_uid).get()
        if not caller_doc.exists or caller_doc.to_dict().get("ruolo") not in ["amministratore", "impiegata"]:
            raise https_fn.HttpsError(
                code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
                message="Permessi insufficienti."
            )
            
        data_consegna = req.data.get("data_consegna")
        if not data_consegna:
            return {"status": "errore", "message": "Data consegna mancante"}
            
        tenant = req.data.get("tenant", "DNR")
        db = get_db()
        bucket = storage.bucket(name=BUCKET_NAME)
        
        # Recupera viaggi di tutti i tenant registrati per avere una visione globale unificata
        try:
            tenants = [doc.id for doc in db.collection('clienti').list_documents()]
        except Exception as e_tenants:
            print(f"[genera_riepiloghi_aziendali_light] Errore lookup tenant: {e_tenants}")
            tenants = ["DNR", "CATTEL", "GRAN CHEF", "BAUER", "DAC"]
            
        docs = []
        for t in tenants:
            try:
                t_docs = db.collection("clienti").document(t).collection("viaggi ddt").where("data_lavoro", "==", data_consegna).get()
                docs.extend(t_docs)
            except Exception as e_query:
                print(f"[genera_riepiloghi_aziendali_light] Errore query tenant {t}: {e_query}")
                
        if not docs:
            return {"status": "errore", "message": f"Nessun viaggio trovato per il {data_consegna}"}
            
        # De-duplicazione dando priorità assoluta ai viaggi salvati nel proprio tenant di competenza
        viaggi_mappati = {}
        for doc in docs:
            v_id = doc.id
            path_parts = doc.reference.path.split('/')
            if len(path_parts) >= 2:
                tenant_di_salvataggio = path_parts[1]
                real_tenant = get_tenant_from_viaggio_id(v_id)
                is_correct_path = (tenant_di_salvataggio == real_tenant)
                
                if v_id not in viaggi_mappati or is_correct_path:
                    viaggi_mappati[v_id] = (doc, is_correct_path)
                    
        docs = [item[0] for item in viaggi_mappati.values()]
            
        # Per unire i PDF, usiamo pypdf (già presente in requirements.txt)
        from pypdf import PdfReader, PdfWriter
        import requests
        import io
        
        # Ordiniamo i documenti per id viaggio
        docs = sorted(docs, key=lambda d: d.id)
        
        # Gruppi per azienda (Dinamico)
        gruppi = {}
        
        for doc in docs:
            v_data = doc.to_dict()
            url_light = v_data.get("distinta_light")
            if not url_light:
                continue
                
            cz = (v_data.get("cliente_zona") or "").upper().strip()
            
            # Determina l'azienda/tenant del viaggio
            if v_data.get("is_cattel") or "CATTEL" in cz:
                azienda = "CATTEL"
            elif v_data.get("is_gc") or cz in ("GRAN CHEF", "GRAN_CHEF", "GRANCHEF") or "GRAN CHEF" in cz or "GRANCHEF" in cz:
                azienda = "GRANCHEF"
            elif v_data.get("is_bauer") or "BAUER" in cz:
                azienda = "BAUER"
            elif v_data.get("is_dac") or "DAC" in cz:
                azienda = "DAC"
            elif cz:
                # Se c'è un altro cliente_zona (es. nuovo tenant dinamico), lo usiamo come nome azienda
                azienda = cz
            else:
                # Default a DNR
                azienda = "DNR"
                
            if azienda not in gruppi:
                gruppi[azienda] = []
            gruppi[azienda].append(url_light)
                
        risultati_urls = {}
        tot_uniti = 0
        
        for azienda, urls in gruppi.items():
            if not urls:
                continue
                
            writer = PdfWriter()
            pdfs_trovati_az = 0
            
            for url_light in urls:
                try:
                    resp = requests.get(url_light, timeout=15)
                    if resp.status_code == 200:
                        reader = PdfReader(io.BytesIO(resp.content))
                        for page in reader.pages:
                            writer.add_page(page)
                        pdfs_trovati_az += 1
                except Exception as e:
                    print(f"Errore download {url_light} per {azienda}: {e}")
                    
            if pdfs_trovati_az > 0:
                master_stream = io.BytesIO()
                writer.write(master_stream)
                master_stream.seek(0)
                
                file_name = f"REPORTS/{data_consegna}/Riepilogo_Generale_{azienda}_{data_consegna}.pdf"
                master_blob = bucket.blob(file_name)
                master_blob.upload_from_file(master_stream, content_type="application/pdf")
                
                master_url = _genera_url_storage_token(master_blob)
                risultati_urls[azienda] = master_url
                tot_uniti += pdfs_trovati_az
                
        if not risultati_urls:
            return {"status": "errore", "message": "Nessuna distinta light trovata da unire per le aziende."}
            
        # Salva le URL generate nel documento generale della giornata
        report_ref = db.collection("clienti").document("report_logistici").collection("giornate").document(data_consegna)
        if report_ref.get().exists:
            report_ref.update({"riepiloghi_urls": risultati_urls})
        else:
            report_ref.set({
                "data_consegna": data_consegna,
                "riepiloghi_urls": risultati_urls,
                "tipo": "REPORT_GENERALE",
                "created_at": firestore.SERVER_TIMESTAMP
            })
            
        return {
            "status": "ok", 
            "urls": risultati_urls, 
            "messaggio": f"Unite {tot_uniti} distinte light divise per {len(risultati_urls)} aziende."
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": str(e)}


# ---------------------------------------------------------
# GOVERNANCE AMMINISTRATORI E GESTIONE ACCOUNT
# ---------------------------------------------------------

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_256, timeout_sec=60)
def admin_update_role(req: https_fn.CallableRequest) -> typing.Any:
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )
    from services.admin_service import handle_admin_update_role
    return handle_admin_update_role(req)

def core_elabora_centro_costi(req_data: dict, uid: str) -> typing.Any:
    if not req.auth:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    
    file_path = req_data.get("filePath")
    mese_riferimento = req_data.get("meseRiferimento")
    
    if not file_path or not mese_riferimento:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="Parametri mancanti.")

    try:
        anno, mese_str = mese_riferimento.split("-")
        mese_index = int(mese_str) - 1
    except Exception:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="Formato mese non valido (atteso YYYY-MM).")

    def estrai_valore_pdf(linea, mese_idx):
        matches = re.findall(r'-?\d{1,3}(?:\.\d{3})*,\d{2}', linea)
        if matches and mese_idx < len(matches):
            try:
                return float(matches[mese_idx].replace('.', '').replace(',', '.'))
            except Exception:
                pass
        return 0.0

    try:
        from pypdf import PdfReader
        import tempfile
        import os
        import traceback

        bucket = get_bucket()
        blob = bucket.blob(file_path)
        if not blob.exists():
            raise Exception(f"File PDF non trovato nello Storage: {file_path}")

        _, tmp_path = tempfile.mkstemp(suffix=".pdf")
        blob.download_to_filename(tmp_path)

        db = get_db()
        batch = db.batch()
        importati = 0
        pagine_totali = 0

        reader = PdfReader(tmp_path)
        pagine_totali = len(reader.pages)
        
        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text: continue
            if "* Totale azienda *" in text: continue

            cf = None
            nome = None
            for line in text.split('\n'):
                m = re.search(r"([A-Z][A-Z\s']+?)\s+([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])\b", line)
                if m:
                    nome = m.group(1).strip()
                    cf = m.group(2)
                    break

            if not cf:
                for line in text.split('\n'):
                    m = re.search(r'\b([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])\b', line)
                    if m:
                        cf = m.group(1)
                        nome = line[:line.find(cf)].strip() or cf
                        break

            if not cf: continue

            costo_totale = 0.0
            costo_ordinario = 0.0
            costo_straordinario = 0.0
            ore_ordinarie = 0.0
            ore_straordinarie = 0.0

            for line in text.split('\n'):
                lu = line.upper()
                if 'C O S T O' in lu and 'T O T A L E' in lu:
                    costo_totale = estrai_valore_pdf(line, mese_index)
                elif 'COSTO TOTALE' in lu:
                    costo_totale = estrai_valore_pdf(line, mese_index)
                elif 'COSTO ORARIO ORDINARIO' in lu:
                    costo_ordinario = estrai_valore_pdf(line, mese_index)
                elif 'COSTO ORARIO STRAORDIN' in lu:
                    costo_straordinario = estrai_valore_pdf(line, mese_index)
                elif 'STRAORDINARI' in lu:
                    ore_straordinarie = estrai_valore_pdf(line, mese_index)
                elif 'ORDINARI' in lu:
                    ore_ordinarie = estrai_valore_pdf(line, mese_index)

            doc_ref = (
                db.collection('clienti').document('DNR')
                .collection('costi_personale').document(mese_riferimento)
                .collection('dipendenti').document(cf)
            )
            batch.set(doc_ref, {
                'nome': nome,
                'codice_fiscale': cf,
                'costo_totale': costo_totale,
                'costo_orario_ordinario': costo_ordinario,
                'costo_orario_straordinario': costo_straordinario,
                'ore_ordinarie': ore_ordinarie,
                'ore_straordinarie': ore_straordinarie,
                'aggiornato_il': firestore.SERVER_TIMESTAMP
            }, merge=True)
            importati += 1

        if importati > 0:
            batch.commit()

        try:
            os.remove(tmp_path)
        except Exception:
            pass
        try:
            blob.delete()
        except Exception:
            pass

        return {"importati": importati, "status": "success", "pagine": pagine_totali}
    
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        print(f"[CC] ERRORE: {type(e).__name__}: {e}\n{trace}")
        return {
            "status": "error",
            "message": f"Errore Python: {type(e).__name__} - {str(e)}"
        }

@https_fn.on_call(region="europe-west1")
def get_backend_version(req: https_fn.CallableRequest) -> typing.Any:
    return {"version": "1.1.0"}

# Import AI Agents - SPOSTATI NELLA NUOVA CODEBASE 'ai' PER EVITARE TIMEOUT
# from ai_agents import agent_extractor, agent_chat_assistant


@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=60)
def elabora_centro_costi(req: https_fn.CallableRequest) -> typing.Any:
    if not req.auth: raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    from services.cost_service import handle_elabora_centro_costi
    return handle_elabora_centro_costi(req)

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_512, timeout_sec=120, secrets=["GEMINI_API_KEY"])
def agent_extractor(req: https_fn.CallableRequest) -> typing.Any:
    if not req.auth:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    
    uid = req.auth.uid
    db = firestore.client()
    doc = db.collection("dipendenti").document(uid).get()
    if not doc.exists or doc.to_dict().get("ruolo") != "amministratore":
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.PERMISSION_DENIED, message="Operazione non consentita.")
        
    import ai_agents
    return ai_agents.agent_extractor(req)

@https_fn.on_call(region="europe-west1", timeout_sec=120, secrets=["GEMINI_API_KEY"])
def agent_chat_assistant(req: https_fn.CallableRequest) -> typing.Any:
    if not req.auth:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
        
    uid = req.auth.uid
    db = firestore.client()
    doc = db.collection("dipendenti").document(uid).get()
    if not doc.exists or doc.to_dict().get("ruolo") != "amministratore":
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.PERMISSION_DENIED, message="Operazione non consentita.")
        
    import ai_agents
    return ai_agents.agent_chat_assistant(req)
