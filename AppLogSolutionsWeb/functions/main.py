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
        from services.reporting_service import handle_genera_report_giornaliero
        return handle_genera_report_giornaliero(req)
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
    """
    from services.history_service import handle_ripristina_cache_backup
    return handle_ripristina_cache_backup(req)
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
    Esegue il backup automatico a inizio del 3o mese.
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
            
        from services.reporting_service import handle_genera_riepiloghi_aziendali_light
        return handle_genera_riepiloghi_aziendali_light(req)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Global exception: {str(e)}"}



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
