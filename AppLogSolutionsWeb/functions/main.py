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

def get_config_app():
    global _CACHED_ARTICOLI_NOTI, _CACHED_CONSOLIDAMENTO, _CACHE_TIMESTAMP
    now = time.time()
    
    if _CACHED_ARTICOLI_NOTI is None or _CACHED_CONSOLIDAMENTO is None or (now - _CACHE_TIMESTAMP) > CACHE_TTL:
        print("[INFO] Fetching config da Firestore (customers/DNR/anagrafica_articoli)")
        
        docs = get_db().collection('clienti').document('DNR').collection('codici articoli').stream()
        _CACHED_CONSOLIDAMENTO = {d.id: d.to_dict() for d in docs}
        
        # Merge ARTICOLI_NOTI dall'anagrafica
        noti_da_anagrafica = [d_id.upper() for d_id, data in _CACHED_CONSOLIDAMENTO.items() if data.get('is_articolo_noto') or data.get('is_wildcard_prefix')]
        _CACHED_ARTICOLI_NOTI = frozenset(noti_da_anagrafica)
            
        _CACHE_TIMESTAMP = now
        
    return _CACHED_ARTICOLI_NOTI, _CACHED_CONSOLIDAMENTO

def _estrai_data_luogo(text):
    data = None
    m = DATA_DDT_RE.search(text)
    if m:
        data = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    luogo_m = LUOGO_RE.search(text)
    luogo = luogo_m.group(1).lower() if luogo_m else None
    
    num_m = NUM_DDT_RE.search(text)
    num_ddt = num_m.group(1).replace("/", "-") if num_m else "UNK"
    
    # Estrazione dinamica della zona
    idx_c = text.upper().find("CAUSALE DEL TRASPORTO")
    zona = ""
    if idx_c >= 0:
        sezione = text[idx_c:idx_c+200]
        m_z = CAUSALE_RE.search(sezione)
        if m_z:
            zona = m_z.group(1)[1:5]
            
    return data, luogo, num_ddt, zona

def _estrai_dati_consegna_completi(text: str, codice: str, da_frutta: bool) -> dict:
    """Estrae indirizzo, cap, citta, prov e orari per nuovi clienti."""
    res = {"dest": "", "ind": "", "cap": "", "cit": "", "prov": "", "om": "", "oM": "14:00"}
    if codice.lower() not in text.lower(): return res
    
    idx_l = text.find("Luogo di destinazione")
    if idx_l < 0: return res

    if da_frutta:
        blocco = text[idx_l : idx_l + 650]
        lines = [ln.strip() for ln in blocco.split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            if LUOGO_RE.search(ln):
                if i + 1 < len(lines): res["dest"] = lines[i + 1].strip().title()
                if i + 2 < len(lines): res["ind"] = lines[i + 2].strip().title()
                break
    else:
        idx_causale = text.upper().find("CAUSALE DEL TRASPORTO")
        blocco = text[:idx_causale] if idx_causale > 0 else text[idx_l : idx_l + 900]
        for ln in blocco.split("\n"):
            ln = ln.strip()
            cf_m = re.match(r"^[Cc]\.?[Ff]\.?\s+", ln)
            if cf_m: res["dest"] = ln[cf_m.end():].strip().title()
            else:
                albo_m = re.match(r"^[Aa]lbo\s+", ln, re.I)
                if albo_m: res["ind"] = ln[albo_m.end():].strip().title()

    idx_resp = text.upper().find("RESPONSABILE DEL TRASPORTO")
    blocco_prov = text[idx_resp:] if idx_resp >= 0 else text
    for prov_m in PROVINCIA_RE.finditer(blocco_prov):
        sigla = prov_m.group(1)
        if sigla == "MN" and ("Pomponesco" in blocco_prov[max(0, prov_m.start()-40):prov_m.start()] or "46030" in blocco_prov): continue
        res["prov"] = sigla
        caps = list(CAP_RE.finditer(blocco_prov[:prov_m.start()]))
        if caps:
            res["cap"] = caps[-1].group(1)
            pre = blocco_prov[caps[-1].end() : caps[-1].end() + 60]
            citta_m = re.search(r"\s*[-]?\s*([A-Za-zÀ-ÿ\s'.]+?)\s*\([A-Z]{2}\)", pre)
            if citta_m: res["cit"] = citta_m.group(1).strip().title()
        break
        
    idx_c = text.upper().find("CAUSALE DEL TRASPORTO")
    if idx_c >= 0:
        sezione = text[idx_c:idx_c+150]
        m = CAUSALE_RE.search(sezione)
        if m:
            if m.group(2): res["oM"] = f"{int(m.group(2)):02d}:00"
            if m.group(3):
                s = m.group(3)
                if len(s) == 3: res["om"] = f"{int(s[0]):02d}:{int(s[1:3]):02d}"
    return res

def _normalizza_cella_codice_base(raw: str) -> str:
    righe = [l.strip() for l in str(raw).split('\n') if l.strip() and not l.strip().startswith("Codice:")]
    if not righe: return ""
    codice_base = righe[0]
    if len(righe) > 1 and codice_base.endswith('-'):
        pezzi = righe[1].split()
        if pezzi: codice_base += pezzi[0]
    return codice_base

def _processa_pdf_core_logic(pdf_bytes: bytes, etichetta: str, db_mappati: dict, db_articoli: dict) -> dict:
    from pypdf import PdfReader, PdfWriter
    import pdfplumber
    nuovi_dati = {}
    nuovi_orari = {}
    nuovi_articoli = {}
    deliveries_list = []
    split_files = {}
    visti = {}
    blocchi = {}
    chiave_zona = {}
    
    reader = PdfReader(io.BytesIO(pdf_bytes))
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i in range(len(pdf.pages)):
            pg = pdf.pages[i]
            text = pg.extract_text() or ""
            d, l, num_ddt, zona = _estrai_data_luogo(text)
            if not d or not l:
                print(f"[WARN] Pagina {i+1} saltata. Data estratta: {d or 'MANCANTE'}, Codice estratto: {l or 'MANCANTE'}. Motivo: Elementi identificativi assenti.")
                continue
            
            chiave = (l, d, num_ddt)
            if chiave not in chiave_zona and zona:
                chiave_zona[chiave] = zona
            
            if l not in db_mappati and l not in nuovi_dati:
                info = _estrai_dati_consegna_completi(text, l, etichetta == "FRUTTA")
                info["tipo"] = etichetta
                nuovi_dati[l] = info
            elif l in db_mappati and l not in nuovi_orari:
                # Confronto Orari
                om_mappa = db_mappati[l].get(f"orario_min_{etichetta.lower()}") or ""
                oM_mappa = db_mappati[l].get(f"orario_max_{etichetta.lower()}") or ""
                idx_c = text.upper().find("CAUSALE DEL TRASPORTO")
                if idx_c >= 0:
                    m_c = CAUSALE_RE.search(text[idx_c:idx_c+150])
                    if m_c:
                        oM_ddt = f"{int(m_c.group(2)):02d}:00" if m_c.group(2) else ""
                        om_ddt = ""
                        if m_c.group(3):
                            s = m_c.group(3)
                            if len(s) == 3: om_ddt = f"{int(s[0]):02d}:{int(s[1:3]):02d}"
                            elif len(s) == 4: om_ddt = f"{int(s[:2]):02d}:{int(s[2:]):02d}"
                        
                        if (oM_ddt and oM_ddt != oM_mappa) or (om_ddt and om_ddt != om_mappa):
                            nuovi_orari[l] = {
                                "cliente": db_mappati[l].get("cliente", ""),
                                "citta": db_mappati[l].get("citta", ""),
                                "orario_min_mappa": om_mappa,
                                "orario_max_mappa": oM_mappa,
                                "orario_min_ddt": om_ddt,
                                "orario_max_ddt": oM_ddt,
                                "data_rilevazione": d,
                                "tipo": etichetta
                            }

            # Estrazione Articoli
            try:
                tables = pg.extract_tables()
                if tables:
                    tab = next((t for t in tables if t and len(t) > 1 and "Cod. Articolo" in " ".join(str(c or "") for c in t[0])), None)
                    if tab:
                        for row in tab[1:]:
                            if row and row[0]:
                                cod_base = _normalizza_cella_codice_base(str(row[0]))
                                if cod_base and cod_base not in nuovi_articoli:
                                    if not _is_primary_code(cod_base, db_articoli):
                                        nuovi_articoli[cod_base] = {
                                            "codice_rilevato": cod_base,
                                            "rilevato_il": d,
                                            "ddt_rif": num_ddt,
                                            "cliente_rif": l,
                                            "tipo": etichetta
                                        }
            except Exception as e:
                print(f"[WARN] Errore estrazione articoli pagina {i}: {e}")
                
            chiave = (l, d, num_ddt)
            if chiave not in blocchi: blocchi[chiave] = []
            blocchi[chiave].append((text, reader.pages[i]))
            
            # --- PROTEZIONE RAM (Chunking) ---
            pg.flush_cache()
            if i > 0 and i % 50 == 0:
                gc.collect()
            

    for chiave, lista_pagine in blocchi.items():
        writer = PdfWriter()
        l, d, num_ddt = chiave
        pagine_da_salvare = [p[1] for p in lista_pagine]
        for pg in pagine_da_salvare: writer.add_page(pg)
            
        cnt = visti.get(chiave, 0) + 1
        visti[chiave] = cnt
        fname = f"{l}_{d}_{num_ddt}_{cnt}.pdf" if cnt > 1 else f"{l}_{d}_{num_ddt}.pdf"
        
        out_stream = io.BytesIO()
        writer.write(out_stream)
        out_stream.seek(0)
        split_files[fname] = out_stream
        
        deliveries_list.append({
            "codice_consegna": l,
            "data": d,
            "num_ddt": num_ddt,
            "pdf_name": fname,
            "tipo": etichetta,
            "zona": chiave_zona.get(chiave, "")
        })

    return {
        "split_files": split_files,
        "nuovi_dati": nuovi_dati,
        "nuovi_orari": nuovi_orari,
        "nuovi_articoli": nuovi_articoli,
        "deliveries": deliveries_list
    }



def consolidate_qty(codice, lista_qty, config):
    c = config.get(codice.lower()) or config.get(codice.upper()) or config.get(codice)
    if not c:
        by_unit = defaultdict(int)
        for q, u in lista_qty: by_unit[u] += q
        return " e ".join([f"{v} {k}" for k, v in sorted(by_unit.items())])
    
    u_princ = str(c.get('unita_principale') or c.get('Unita principale') or c.get('unita_princ') or '').strip()
    u_sec = str(c.get('unita_secondaria') or c.get('Unita secondaria') or c.get('unita_sec') or '').strip()
    ratio_raw = c.get('ratio') or c.get('Ratio') or 0
    try:
        ratio = int(ratio_raw)
    except:
        ratio = 0
        
    tot_sec = 0
    tot_princ = 0
    
    # Manteniamo le etichette originali per fallback
    primary_labels_found = []
    secondary_labels_found = []
    
    for q, u in lista_qty:
        ul = u.lower()
        if (u_princ and u_princ.lower() in ul) or ul in ("fardello", "fardelli", "cartoni", "cartone", "brick", "colli", "confezioni", "manifesti", "fascette"):
            tot_princ += q
            primary_labels_found.append(u)
        else:
            tot_sec += q
            secondary_labels_found.append(u)

    if ratio > 0:
        tot_princ += tot_sec // ratio
        resto_sec = tot_sec % ratio
    else:
        resto_sec = tot_sec
        
    res = []
    if tot_princ > 0:
        label_p = u_princ if u_princ else (primary_labels_found[0].capitalize() if primary_labels_found else "Unita'")
        res.append(f"{tot_princ} {label_p}")
    if resto_sec > 0:
        label_s = u_sec if u_sec else (secondary_labels_found[0].capitalize() if secondary_labels_found else "Pezzi")
        res.append(f"{resto_sec} {label_s}")
        
    if not res:
        return "0"
    return " e ".join(res)

def _registra_statistica(tipo_operazione, tempo_sec, errori=0):
    oggi = str(date.today())
    stats_ref = get_db().collection('stats_monitoring').document(oggi)
    
    try:
        doc = stats_ref.get()
        if doc.exists:
            d = doc.to_dict()
            tot_tempo = d.get('tempo_totale_sec', 0) + tempo_sec
            tot_ops = d.get('operazioni_totali', 0) + 1
            tot_err = d.get('errori_totali', 0) + errori
            
            # Specifiche per tipo API
            tipo_count = d.get(f'count_{tipo_operazione}', 0) + 1
            tipo_tempo = d.get(f'tempo_{tipo_operazione}', 0) + tempo_sec
            
            stats_ref.update({
                'tempo_totale_sec': tot_tempo,
                'operazioni_totali': tot_ops,
                'tempo_medio_globale': tot_tempo / tot_ops,
                'errori_totali': tot_err,
                f'count_{tipo_operazione}': tipo_count,
                f'tempo_medio_{tipo_operazione}': tipo_tempo / tipo_count,
                f'tempo_{tipo_operazione}': tipo_tempo
            })
        else:
            stats_ref.set({
                'data': oggi,
                'tempo_totale_sec': tempo_sec,
                'operazioni_totali': 1,
                'tempo_medio_globale': tempo_sec,
                'errori_totali': errori,
                f'count_{tipo_operazione}': 1,
                f'tempo_medio_{tipo_operazione}': tempo_sec,
                f'tempo_{tipo_operazione}': tempo_sec
            })
    except Exception as e:
        print(f"[ERROR] Registrazione statistiche fallita: {e}")

# --- CORE LOGIC FUNCTIONS ---



@https_fn.on_call()
def admin_reset_password(req: https_fn.CallableRequest) -> dict:
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





def _get_viaggio_doc_self_healing(viaggio_id, tenant=None):
    db = get_db()
    tenant_viaggio = get_tenant_from_viaggio_id(viaggio_id) or tenant or "DNR"
    doc_ref = db.collection('clienti').document(tenant_viaggio).collection('viaggi ddt').document(viaggio_id)
    doc_viaggio = doc_ref.get()
    
    if tenant_viaggio != "DNR" and (not doc_viaggio.exists or not doc_viaggio.to_dict().get('punti')):
        # Cerca se esiste la versione completa in DNR
        doc_dnr_ref = db.collection('clienti').document('DNR').collection('viaggi ddt').document(viaggio_id)
        doc_dnr = doc_dnr_ref.get()
        if doc_dnr.exists and doc_dnr.to_dict().get('punti'):
            print(f"[MIGRAZIONE AUTO-RISANANTE] Migrazione viaggio {viaggio_id} da DNR a {tenant_viaggio}")
            dnr_data = doc_dnr.to_dict()
            target_data = doc_viaggio.to_dict() if doc_viaggio.exists else {}
            merged_data = {**dnr_data, **target_data}
            doc_ref.set(merged_data)
            doc_viaggio = doc_ref.get()
            try:
                doc_dnr_ref.delete()
            except Exception as e_del:
                print(f"[WARN] Impossibile eliminare duplicato in DNR: {e_del}")
                
    return doc_ref, doc_viaggio, tenant_viaggio

def core_ottimizza_viaggio(viaggio_id):
    start_time = time.time()
    print("[INFO] Start ottimizza_viaggio")

    if not viaggio_id:
        return {"status": "errore", "message": "viaggio_id mancante", "errori": ["viaggio_id mancante"], "data": {}}
        
        
    doc_ref, doc_viaggio, tenant_viaggio = _get_viaggio_doc_self_healing(viaggio_id)
    if not doc_viaggio.exists:
        return {"status": "errore", "message": "Viaggio non trovato", "errori": ["Viaggio non trovato"], "data": {}}
    viaggio = doc_viaggio.to_dict()
    
    punti = viaggio.get('punti', [])
    if not punti:
        return {"status": "errore", "message": "Viaggio vuoto (nessun punto)", "errori": ["Punti vuoti"], "data": {}}
    
    # BLOCCO ERRORI LOGICI: Impossibile ottimizzare se i DDT sono < 2
    if len(punti) < 2:
        return {
            "status": "errore", 
            "message": "Impossibile ottimizzare: servono almeno 2 DDT nel viaggio.", 
            "errori": ["Meno di 2 DDT"], 
            "data": {}
        }
        
    errori_lista = []

    # Costruisci punti come lista di dict con lat/lon
    punti_norm = []
    for i, p in enumerate(punti):
        try:
            punti_norm.append({'lat': float(p['lat']), 'lon': float(p.get('lon', p.get('lng', 0)))})
        except:
            punti_norm.append({'lat': 0.0, 'lon': 0.0})
            errori_lista.append(f"Coordinate invalide punto {i}")

    distance_matrix = _crea_matrice_distanze_cloud(punti_norm, errori_lista)

    try:
        from ortools.constraint_solver import routing_enums_pb2
        from ortools.constraint_solver import pywrapcp

        manager = pywrapcp.RoutingIndexManager(len(distance_matrix), 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return distance_matrix[from_node][to_node]

        transit_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
        
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_parameters.time_limit.seconds = 10 
        
        solution = routing.SolveWithParameters(search_parameters)
        
        if solution:
            ordine_visita = []
            index = routing.Start(0)
            while not routing.IsEnd(index):
                ordine_visita.append(manager.IndexToNode(index))
                index = solution.Value(routing.NextVar(index))
                
            punti_ottimizzati = [punti[i] for i in ordine_visita]
            
            # Update stato viaggio a "ottimizzato"
            doc_ref.update({
                "punti_ottimizzati": punti_ottimizzati,
                "ordine_visita": ordine_visita,
                "status": "ottimizzato"
            })
            
            end_time = time.time()
            elapsed = end_time - start_time
            _registra_statistica('ottimizza_viaggio', elapsed, len(errori_lista))

            return {
                "status": "ok" if not errori_lista else "parziale",
                "message": f"Ottimizzazione in {elapsed:.2f}s",
                "errori": errori_lista,
                "data": {
                    "viaggio_id": viaggio_id,
                    "ordine_visita": ordine_visita,
                    "tempo_sec": elapsed
                }
            }
        else:
            return {"status": "errore", "message": "Nessuna soluzione trovata da OR-Tools", "errori": errori_lista + ["Nessuna route"], "data": {}}
            
    except Exception as e_opt:
        err_msg = f"Errore runtime OR-Tools: {e_opt}"
        return {"status": "errore", "message": "Eccezione OR-Tools", "errori": errori_lista + [err_msg], "data": {}}

def core_genera_distinta_viaggio(viaggio_id):
    start_time = time.time()
    print("[INFO] Start genera_distinta_viaggio")
    
    if not viaggio_id:
        return {"status": "errore", "message": "viaggio_id mancante", "errori": ["viaggio_id mancante"], "data": {}}

    doc_ref, doc_viaggio, tenant_viaggio = _get_viaggio_doc_self_healing(viaggio_id)
    if not doc_viaggio.exists:
        return {"status": "errore", "message": "Viaggio non trovato", "errori": ["Viaggio non trovato"], "data": {}}
    viaggio = doc_viaggio.to_dict()
    
    # BLOCCO ERRORI LOGICI: Impedire distinta se non ottimizzato
    if viaggio.get('status', 'bozza') != 'ottimizzato':
        return {
            "status": "errore", 
            "message": "Operazione respinta. Il viaggio deve essere ottimizzato prima di generare la distinta.",
            "errori": ["Stato viaggio non ottimizzato"], 
            "data": {}
        }
    
    ddt_ids = viaggio.get('ddt_ids', [])
    if not ddt_ids:
        return {"status": "errore", "message": "Viaggio vuoto (nessun ddt_ids)", "errori": ["Viaggio senza ddt_ids"], "data": {}}

    articoli_noti, config_cons = get_config_app()
    bucket = storage.bucket(name=BUCKET_NAME)
    accumulatore = defaultdict(lambda: {"qty": [], "desc": ""})
    errori_lista = []
    
    for ddt_id in ddt_ids:
        try:
            ddt_doc = get_db().collection('clienti').document('DNR').collection('ddt').document(ddt_id).get()
            if not ddt_doc.exists: continue
            ddt = ddt_doc.to_dict()
            blob = bucket.blob(ddt['storage_path'])
            if not blob.exists(): continue
            
            pdf_bytes = blob.download_as_bytes()
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    if not tables: continue
                    tab = next((t for t in tables if t and "Cod. Articolo" in str(t[0])), None)
                    if not tab: continue
                    for row in tab[1:]:
                        if not row or not row[0]: continue
                        base, var = normalize_code(row[0], articoli_noti)
                        desc = str(row[1] or "").replace('\n', ' ').strip()
                        qty_raw = str(row[3] or "")
                        qty_parsed = [(int(m.group(1)), m.group(2).title()) 
                                      for m in re.finditer(r"(\d+)\s+([A-Za-z]+)", qty_raw)]
                        if qty_parsed:
                            key = (base, var)
                            accumulatore[key]["qty"].extend(qty_parsed)
                            if not accumulatore[key]["desc"]:
                                accumulatore[key]["desc"] = desc
        except Exception as e_ddt:
            err_msg = f"Errore su DDT {ddt_id}: {e_ddt}"
            errori_lista.append(err_msg)

    if not accumulatore:
        return {"status": "errore", "message": "Nessun articolo estratto dai DDT", "errori": errori_lista, "data": {}}

    report_items = []
    for (codice, variante), dati in sorted(accumulatore.items()):
        report_items.append({
            "codice": codice,
            "variante": variante,
            "descrizione": dati["desc"],
            "display_qty": consolidate_qty(codice, dati["qty"], config_cons)
        })

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm

    try:
        out_pdf = io.BytesIO()
        c = canvas.Canvas(out_pdf, pagesize=A4)
        width, height = A4
        c.setFont("Helvetica-Bold", 16)
        
        data_viaggio = viaggio.get('data', 'Sconosciuta')
        nome_giro = viaggio.get('nome_giro', 'Sconosciuto')
        c.drawString(2*cm, height - 2*cm, f"DISTINTA DI CARICO - {nome_giro} del {data_viaggio}")
        
        c.setFont("Helvetica-Bold", 10)
        y = height - 3.5*cm
        
        c.drawString(2*cm, y, "Codice")
        c.drawString(6*cm, y, "Descrizione / Variante")
        c.drawString(14*cm, y, "Quantità")
        c.line(2*cm, y-0.2*cm, 19*cm, y-0.2*cm)
        y -= 0.8*cm

        c.setFont("Helvetica", 10)
        for item in report_items:
            if y < 2*cm:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = height - 2*cm
            c.drawString(2*cm, y, item['codice'])
            
            desc_var = item['descrizione']
            if item['variante']:
                desc_var += f" ({item['variante']})"
            if len(desc_var) > 45: desc_var = desc_var[:42] + "..."
            c.drawString(6*cm, y, desc_var)
            
            c.drawString(14*cm, y, item['display_qty'])
            y -= 0.6*cm

        c.save()
        out_pdf.seek(0)
        
        data_formattata = data_viaggio.replace('/', '-')
        pdf_path = f"CONSEGNE/CONSEGNE_{data_formattata}/DISTINTE_VIAGGIO/{viaggio_id}.pdf"
        distinta_blob = bucket.blob(pdf_path)
        if distinta_blob.exists():
            distinta_blob.delete()
        distinta_blob.upload_from_file(out_pdf, content_type="application/pdf")
        pdf_url = f"gs://{BUCKET_NAME}/{pdf_path}"
        
        # AGGIORNA STATO A COMPLETATO E AGGIORNA STATO DDT AD ASSEGNATO
        doc_ref.update({"status": "completato"})
        for ddt_id in ddt_ids:
            get_db().collection('clienti').document('DNR').collection('ddt').document(ddt_id).update({"stato": "assegnato"})
            
    except Exception as e_pdf:
        err_msg = f"Errore generazione PDF: {e_pdf}"
        return {"status": "errore", "message": "Fallita generazione PDF", "errori": errori_lista + [err_msg], "data": {}}
    
    end_time = time.time()
    elapsed = end_time - start_time
    _registra_statistica('genera_distinta', elapsed, len(errori_lista))

    return {
        "status": "ok" if not errori_lista else "parziale",
        "message": f"Distinta generata in {elapsed:.2f}s",
        "errori": errori_lista,
        "data": {
            "viaggio_id": viaggio_id,
            "articoli_totali": len(report_items),
            "pdf_url": pdf_url,
            "tempo_sec": elapsed
        }
    }


# ─── PUNTO #3: MAPPE AUTISTI CON STRADE CURVE (GOOGLE DIRECTIONS) ─────────────

DEPOT_CLOUD = {"lat": 45.442805, "lon": 11.714498, "nome": "DEPOSITO VEGGIANO"}
AVG_SPEED_KMH = 45
TIME_PER_STOP_MIN = 8







def _genera_html_mappa(viaggio_id, punti, km, sec_guida, polylines, depot=None, distinta_url=None, ora_partenza_dep="07:00", actual_viaggio_id=None):
    """Genera HTML mappa mobile-first con polyline strade vere."""
    if depot is None:
        depot = _get_depot_for_points_cloud(punti)
    t_guida_min = sec_guida // 60
    t_sosta_min = len(punti) * TIME_PER_STOP_MIN
    t_tot_min   = t_guida_min + t_sosta_min

    def fmt_min(m):
        hh, mm = divmod(m, 60)
        return f"{hh}h {mm}m" if hh > 0 else f"{mm}m"

    depot_nome = depot.get("nome", "Deposito").title() if depot else "Deposito"
    
    fermate_html = ""
    
    # 1. Card di Partenza
    if distinta_url:
        fermate_html += f'''
            <div class="card" style="background:#f1f5f9; border-color:#94a3b8; grid-template-columns: 42px 1.4fr 1fr; padding: 10px; gap: 8px; align-items: stretch; cursor: default;">
                <div class="stop-num" style="background:#475569; align-self: center;"><span class="material-icons-round">home</span></div>
                <div class="stop-info" style="justify-content: center;">
                    <b class="name" style="font-size: 0.8rem;">PARTENZA</b>
                    <span class="addr" style="font-size: 0.7rem;">{depot_nome}</span>
                    <span class="orario-badge" style="background:#1e293b; color:white; margin-top:2px; font-size: 0.6rem;"><span class="material-icons-round" style="font-size: 10px !important;">schedule</span>Partenza: {ora_partenza_dep}</span>
                </div>
                <div style="border-left: 2px solid #bae6fd; background: #f0f9ff; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 4px; border-radius: 8px; gap: 4px;">
                    <div style="font-size: 0.52rem; font-weight: 800; text-transform: uppercase; letter-spacing: .06em; color: #0369a1;">📋 Distinta</div>
                    <a href="{distinta_url}" target="_blank" onclick="event.stopPropagation()" style="background: #0284c7; color: white; border: none; border-radius: 6px; padding: 5px 6px; font-size: 0.62rem; font-weight: 800; text-decoration: none; display: flex; align-items: center; gap: 3px; width: 100%; justify-content: center;">🔗 Apri PDF</a>
                </div>
            </div>'''
    else:
        fermate_html += f'''
            <div class="card" style="background:#f1f5f9; border-color:#94a3b8; grid-template-columns: 42px 1fr; cursor: default;">
                <div class="stop-num" style="background:#475569;"><span class="material-icons-round">home</span></div>
                <div class="stop-info">
                    <b class="name">PARTENZA</b>
                    <span class="addr">{depot_nome}</span>
                    <span class="orario-badge" style="background:#1e293b; color:white; margin-top:4px;"><span class="material-icons-round">schedule</span>Partenza: {ora_partenza_dep}</span>
                </div>
            </div>'''

    for idx, p in enumerate(punti):
        nome = p.get("nome", p.get("codice_cliente", f"Tappa {idx+1}"))
        rag_sociale = p.get("ragione_sociale", p.get("nome_cliente", ""))
        ind  = p.get("indirizzo", "")
        lat  = p.get("lat", "")
        lon  = p.get("lon", p.get("lng", ""))
        nav  = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}&travelmode=driving"
        
        is_parz = any(r.get("is_parziale") for r in p.get("rientri_alert", []) if isinstance(r, dict))
        warn_class = " warning" if is_parz else ""
        
        # Note
        note_txt = str(p.get("note", p.get("nota_integrativa", p.get("Note", ""))) or "").strip()
        note_html = ""
        if note_txt and note_txt.lower() != "nan":
            note_safe = note_txt.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
            note_html = f'<div class="note-chip"><span class="material-icons-round">sticky_note_2</span>Note: {note_safe}</div>'
            
        # Orari
        om_val = str(p.get("orario_min") or p.get("orario_min_frutta", p.get("orario_min_latte", ""))).strip()
        oM_val = str(p.get("orario_max") or p.get("orario_max_frutta", p.get("orario_max_latte", ""))).strip()
        
        orario_html = ""
        if (om_val and om_val.lower() != "nan") or (oM_val and oM_val.lower() != "nan"):
            if om_val and oM_val:
                orario_txt = f"{om_val} - {oM_val}"
            elif om_val:
                orario_txt = f"Dalle {om_val}"
            else:
                orario_txt = f"Entro le {oM_val}"
            orario_html = f'<span class="orario-badge"><span class="material-icons-round">schedule</span>Fascia: {orario_txt}</span>'
            
        # Orario stimato arrivo / ripartenza
        ora_arr = str(p.get("ora_arrivo") or "").strip()
        ora_rip = str(p.get("ora_ripartenza") or "").strip()
        eta_html = ""
        if ora_arr and ora_rip:
            eta_html = f'<span class="eta-badge"><span class="material-icons-round">timer</span>Arrivo {ora_arr} &mdash; Ripart. {ora_rip}</span>'
        elif ora_arr:
            eta_html = f'<span class="eta-badge"><span class="material-icons-round">timer</span>Arrivo stimato {ora_arr}</span>'
            
        # Chiamata
        phone_num = _extract_phone(p)
        if phone_num:
            action_col = (
                f'<div class="nav-col">'
                f'<a href="{nav}" target="_blank" class="btn-nav" onclick="event.stopPropagation()"><span class="material-icons-round">navigation</span></a>'
                f'<a href="tel:{phone_num}" class="btn-call" onclick="event.stopPropagation()"><span class="material-icons-round">call</span></a>'
                f'<button class="btn-ok" onclick="toggleConsegnato(event, {idx})"><span class="material-icons-round">check</span></button>'
                f'<button class="btn-cam" onclick="openCamera(event, {idx})"><span class="material-icons-round">photo_camera</span></button>'
                f'</div>'
            )
            card_style = 'grid-template-columns: 42px 1fr auto;'
        else:
            action_col = (
                f'<div class="nav-col">'
                f'<a href="{nav}" target="_blank" class="btn-nav" style="grid-column:span 2; width:100%;" onclick="event.stopPropagation()"><span class="material-icons-round">navigation</span></a>'
                f'<button class="btn-ok" onclick="toggleConsegnato(event, {idx})"><span class="material-icons-round">check</span></button>'
                f'<button class="btn-cam" onclick="openCamera(event, {idx})"><span class="material-icons-round">photo_camera</span></button>'
                f'</div>'
            )
            card_style = 'grid-template-columns: 42px 1fr auto;'
            
        fermate_html += (
            f'<div class="card" id="card-{idx}" onclick="selectCard({idx})" style="{card_style}">'
            f'<div class="stop-num{warn_class}">{idx+1}</div>'
            f'<div class="stop-info">'
            f'<span class="name">{nome}</span>'
            f'<span class="addr">{ind}</span>'
            f'{orario_html}'
            f'{eta_html}'
            f'{note_html}'
            f'</div>'
            f'{action_col}</div>'
        )

    # 3. Card di Arrivo
    ora_rientro_dep = ""
    try:
        part_m = re.match(r"(\d{2}):(\d{2})", str(ora_partenza_dep).strip())
        start_min = int(part_m.group(1)) * 60 + int(part_m.group(2)) if part_m else 420
        
        t_tot_min = (sec_guida // 60) + len(punti) * TIME_PER_STOP_MIN
        hh_ret, mm_ret = divmod(start_min + int(t_tot_min), 60)
        hh_ret = hh_ret % 24
        ora_rientro_dep = f"{hh_ret:02d}:{mm_ret:02d}"
    except Exception as e_time:
        print(f"[WARN] Impossibile calcolare ora rientro: {e_time}")

    rientro_badge = f'<span class="orario-badge" style="background:#1e293b; color:white; margin-top:4px;"><span class="material-icons-round">schedule</span>Rientro stimato: {ora_rientro_dep}</span>' if ora_rientro_dep else ''
    
    fermate_html += f'''
        <div class="card" id="arrivo-card" style="background:#f1f5f9; border-color:#94a3b8; grid-template-columns: 42px 1fr; cursor: default;">
            <div class="stop-num" style="background:#475569;"><span class="material-icons-round">flag</span></div>
            <div class="stop-info">
                <b class="name">ARRIVO</b>
                <span class="addr">{depot_nome}</span>
                {rientro_badge}
            </div>
        </div>'''

    punti_js_list = []
    for p in punti:
        is_parz = any(r.get("is_parziale") for r in p.get("rientri_alert", []) if isinstance(r, dict))
        punti_js_list.append({
            "lat": float(p.get("lat", 0)),
            "lng": float(p.get("lon", p.get("lng", 0))),
            "nome": p.get("nome", ""),
            "codice_cliente": p.get("codice_cliente", ""),
            "ragione_sociale": p.get("ragione_sociale", p.get("nome_cliente", "")),
            "indirizzo": p.get("indirizzo", ""),
            "is_parziale": is_parz
        })
    punti_js     = json.dumps(punti_js_list)
    polylines_js = json.dumps(polylines)

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>Mappa {viaggio_id}</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/icon?family=Material+Icons+Round" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/sortablejs@latest/Sortable.min.js"></script>
<script src="https://maps.googleapis.com/maps/api/js?key={GOOGLE_MAPS_API_KEY}&libraries=geometry&callback=initMap" async defer></script>
<style>
:root{{--p:#4f46e5;--accent:#10b981;--call:#16a34a}}
body,html{{margin:0;padding:0;height:100%;font-family:'Outfit',sans-serif;overflow:hidden}}
.main-container{{display:flex;flex-direction:column;height:100vh}}
#map-wrapper{{position:relative;width:100%;height:42vh;transition:height 0.3s ease;flex-shrink:0}}
#map-wrapper.collapsed{{height:12vh}}
#map{{height:100%;width:100%;background:#dfe5eb}}
#sidebar{{flex:1;display:flex;flex-direction:column;background:white;border-top:2px solid #cbd5e1;overflow:hidden}}
.header{{padding:8px 12px;background:#1e293b;color:white;border-bottom:2px solid var(--accent)}}
.trip-title{{margin:0;font-size:.65rem;font-weight:800;text-transform:uppercase;color:var(--accent)}}
.stats-row{{display:flex;gap:10px;flex-wrap:wrap;margin-top:4px}}
.stat-val{{font-size:.85rem;font-weight:800;color:white}}
.stat-lbl{{font-size:.52rem;color:#94a3b8;text-transform:uppercase}}
#delivery-list{{flex:1;overflow-y:auto;padding:8px;background:#f1f5f9;padding-bottom:60px}}
.card{{background:white;border-radius:12px;padding:10px;margin-bottom:8px;display:grid;gap:8px;align-items:center;border:1px solid #cbd5e1;cursor:pointer;transition:all .2s;-webkit-touch-callout:none;-webkit-user-select:none;user-select:none}}
.card.active{{border-color:var(--p);border-left:5px solid var(--p);background:#eef2ff}}
.stop-num{{width:32px;height:32px;background:var(--p);color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;flex-shrink:0}}
.stop-num.warning {{
background: repeating-linear-gradient(45deg, #000, #000 4px, #f59e0b 4px, #f59e0b 8px) !important;
color: white !important;
text-shadow: 1px 1px 2px black, -1px -1px 2px black, 0px 0px 3px black;
border: 2px solid black;
}}
.stop-info{{display:flex;flex-direction:column;gap:3px;min-width:0}}
.name{{font-size:.85rem;font-weight:800;color:#1e293b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.addr{{font-size:.75rem;color:#64748b;font-weight:600;line-height:1.1}}
.orario-badge{{display:inline-flex;align-items:center;gap:3px;background:#eff6ff;color:#2563eb;font-size:0.65rem;font-weight:800;padding:2px 7px;border-radius:20px;border:1px solid #bfdbfe;margin-top:1px;width:fit-content}}
.orario-badge .material-icons-round{{font-size:12px !important}}
.eta-badge{{display:inline-flex;align-items:center;gap:3px;background:#e0f2fe;color:#0369a1;font-size:0.65rem;font-weight:800;padding:2px 7px;border-radius:20px;border:1px solid #bae6fd;margin-top:1px;width:fit-content}}
.eta-badge .material-icons-round{{font-size:12px !important}}
.note-chip{{display:flex;align-items:flex-start;gap:4px;background:#fffbeb;color:#92400e;font-size:0.65rem;font-weight:700;padding:4px 7px;border-radius:8px;border:1px solid #fde68a;margin-top:3px;line-height:1.3}}
.note-chip .material-icons-round{{font-size:12px !important;flex-shrink:0;margin-top:1px}}
.btn-nav{{background:var(--accent);color:white;width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;text-decoration:none}}
.btn-call{{background:var(--call);color:white;width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;text-decoration:none}}
.btn-cam{{background:#f59e0b;color:white;width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;border:none;cursor:pointer}}
.btn-ok{{background:#10b981;color:white;width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;border:none;cursor:pointer}}
.card.consegnato{{opacity:0.5;filter:grayscale(1)}}
.card.consegnato .btn-ok{{background:#64748b}}
.nav-col{{display:grid;grid-template-columns:38px 38px;gap:5px;align-items:start;justify-content:end;}}
.material-icons-round{{font-size:18px !important}}
.fab-save{{position:fixed;bottom:20px;right:20px;background:var(--accent);color:white;border:none;border-radius:30px;padding:12px 20px;font-weight:800;font-family:'Outfit',sans-serif;box-shadow:0 4px 12px rgba(16,185,129,0.4);display:none;align-items:center;gap:8px;cursor:pointer;z-index:1000;font-size:1rem;transition:transform 0.2s;}}
.fab-save:active{{transform:scale(0.95);}}

/* Stili Modale Riordino */
#reorder-modal{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:#f8fafc;z-index:9999;flex-direction:column;}}
.rm-header{{padding:16px;background:#1e293b;color:white;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);}}
.rm-title{{margin:0;font-size:1.1rem;font-weight:800;display:flex;align-items:center;gap:8px;}}
.rm-body{{flex:1;overflow-y:auto;padding:12px;}}
.rm-footer{{padding:16px;background:white;border-top:1px solid #e2e8f0;display:flex;gap:12px;}}
.rm-btn-cancel{{flex:1;padding:14px;border:none;background:#f1f5f9;color:#475569;font-weight:700;border-radius:12px;cursor:pointer;}}
.rm-btn-save{{flex:2;padding:14px;border:none;background:var(--accent);color:white;font-weight:800;border-radius:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:0 4px 12px rgba(16,185,129,0.3);}}
.rm-item{{background:white;border:1px solid #cbd5e1;border-radius:12px;padding:12px;margin-bottom:8px;display:flex;align-items:center;gap:12px;}}
.rm-handle{{color:#94a3b8;cursor:grab;padding:4px;}}
.rm-num{{width:28px;height:28px;background:var(--p);color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:12px;flex-shrink:0;}}
.rm-info{{flex:1;min-width:0;display:flex;flex-direction:column;line-height:1.2;}}
.rm-name{{font-weight:800;color:#0f172a;font-size:0.9rem;}}
.rm-sub{{font-size:0.75rem;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.sortable-ghost{{opacity:0.4; background-color:#f1f5f9;}}
#expand-modal-list .card {{ cursor: default; transition: none !important; }}
.sortable-drag {{ transition: none !important; cursor: grabbing !important; opacity: 1 !important; }}
.drag-handle-modal {{ cursor: grab; padding: 4px; display: flex; align-items: center; color: #94a3b8; touch-action: none; }}
.drag-handle-modal:active {{ cursor: grabbing; color: #3b82f6; }}
.sortable-fallback {{ opacity: 1 !important; background: white !important; cursor: grabbing !important; box-shadow: 0 10px 20px rgba(0,0,0,0.15) !important; transform: scale(1.02); z-index: 99999; }}
.compact-stop-item {{ display: flex; align-items: center; gap: 12px; background: white; padding: 12px 16px; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); user-select: none; margin-bottom: 8px; touch-action: none; }}
.compact-num {{ font-weight: 800; color: white; background: var(--p); border-radius: 4px; padding: 2px 8px; font-size: 0.85rem; min-width: 32px; text-align: center; }}
.compact-name {{ font-weight: 700; color: #0f172a; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: left; line-height: 1.2; }}
.compact-city {{ color: #64748b; font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100px; text-align: right; line-height: 1.2; }}
</style>
</head>
<body>
<div class="main-container">
<div id="map-wrapper">
<div id="map"></div>
<div id="top-left-controls" style="position:absolute; left:10px; top:10px; z-index:10; pointer-events:none; display:flex; gap:8px; align-items:center;"></div>
<div id="bottom-right-controls" style="position:absolute; right:10px; bottom:24px; z-index:10; pointer-events:none; display:flex; flex-direction:column; gap:10px; align-items:center;"></div>
</div>
<div id="sidebar">
<div class="header">
<div style="display:flex; justify-content:space-between; align-items:center;">
<p class="trip-title" style="margin:0;">&#x1F69B; {viaggio_id}</p>
<button onclick="apriModalEspansa()" style="background:#e2e8f0; color:#0f172a; border:none; padding:6px 12px; border-radius:20px; font-weight:bold; font-size:12px; display:flex; align-items:center; gap:4px; box-shadow:0 1px 3px rgba(0,0,0,0.1);"><span class="material-icons-round" style="font-size:16px;">swap_vert</span> Ordina</button>
</div>
<div class="stats-row">
<div><div class="stat-val">&#x23F0; {ora_partenza_dep}</div><div class="stat-lbl">Partenza</div></div>
<div><div class="stat-val">&#x1F6E3;&#xFE0F; {float(km or 0):.1f} km</div><div class="stat-lbl">Km Reali</div></div>
<div><div class="stat-val">&#x1F552; {fmt_min(t_guida_min)}</div><div class="stat-lbl">Guida</div></div>
<div><div class="stat-val">&#x23F1;&#xFE0F; {fmt_min(t_tot_min)}</div><div class="stat-lbl">Totale</div></div>
<div><div class="stat-val">&#x1F4E6; {len(punti)}</div><div class="stat-lbl">Tappe</div></div>
</div>
</div>
<div id="delivery-list">{fermate_html}</div>
</div>
<button id="fab-save" class="fab-save" onclick="saveSequence()"><span class="material-icons-round">save</span> Salva Sequenza</button>
<div id="cam-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); z-index:9999; flex-direction:column; align-items:center; justify-content:center; padding:20px;">
    <div style="background:white; border-radius:12px; padding:20px; width:100%; max-width:400px; text-align:center; box-sizing:border-box;">
        <h3 style="margin-top:0; font-family:'Outfit',sans-serif;">Segnalazione</h3>
        <p id="cam-cliente-name" style="font-weight:bold; color:var(--p); margin-bottom:15px; font-family:'Outfit',sans-serif;"></p>
        <button onclick="selectCamType('merce_rotta')" style="width:100%; padding:15px; margin-bottom:10px; background:#ef4444; color:white; border:none; border-radius:8px; font-weight:bold; font-size:16px; font-family:'Outfit',sans-serif;">🔴 Merce Rifiutata / Rotta</button>
        <button onclick="selectCamType('reso_pregresso')" style="width:100%; padding:15px; margin-bottom:15px; background:#3b82f6; color:white; border:none; border-radius:8px; font-weight:bold; font-size:16px; font-family:'Outfit',sans-serif;">🔵 Reso / Ritiro</button>
        <button onclick="closeCamModal()" style="width:100%; padding:15px; background:#e2e8f0; color:#475569; border:none; border-radius:8px; font-weight:bold; font-size:16px; font-family:'Outfit',sans-serif;">Annulla</button>
    </div>
</div>
<div id="expand-trip-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; box-sizing:border-box; background:rgba(15,23,42,0.8); z-index:9999; flex-direction:column; align-items:center; justify-content:center; padding:16px;">
<div style="background:white; border-radius:16px; width:100%; max-width:500px; height:90vh; display:flex; flex-direction:column; overflow:hidden;">
<div style="padding:16px; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center; background:#f8fafc;">
<h3 style="margin:0; font-family:'Outfit',sans-serif;">Modifica Sequenza</h3>
<div style="display:flex; gap:10px;">
<button onclick="chiudiModalEspansa()" style="background:#e2e8f0; color:#475569; border:none; padding:8px 16px; border-radius:8px; font-weight:bold; cursor:pointer;">Annulla</button>
<button onclick="applicaOrdineEspanso()" style="background:var(--p); color:white; border:none; padding:8px 16px; border-radius:8px; font-weight:bold; cursor:pointer;">Applica</button>
</div>
</div>
<div id="expand-modal-list" style="flex:1; overflow-y:auto; padding:8px; background:#f1f5f9; display:flex; flex-direction:column; gap:8px;"></div>
</div>
</div>
<input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none;" onchange="handleFile(event)">
</div>
<script>
const PUNTI={punti_js};
const POLYLINES={polylines_js};
const DEPOT={{lat:{depot["lat"]},lng:{depot["lon"]}}};
let map,markers=[];
function initMap(){{
map=new google.maps.Map(document.getElementById("map"),{{
center:PUNTI.length?{{lat:PUNTI[0].lat,lng:PUNTI[0].lng}}:DEPOT,
zoom:11,mapTypeId:"roadmap",disableDefaultUI:true,zoomControl:false,mapTypeControl:false}});
POLYLINES.forEach(enc=>{{
const path=google.maps.geometry.encoding.decodePath(enc);
new google.maps.Polyline({{path,geodesic:true,strokeColor:"#4f46e5",strokeOpacity:.85,strokeWeight:4,map}});
}});
new google.maps.Marker({{position:DEPOT,map,
icon:{{path:google.maps.SymbolPath.CIRCLE,scale:14,fillColor:"#1e293b",fillOpacity:1,strokeWeight:0}},
label:{{text:"D",color:"white",fontWeight:"bold"}}}});
PUNTI.forEach((p,i)=>{{
let fillColor = "#4f46e5";
let strokeColor = "white";
let strokeWeight = 2;
let labelColor = "white";
if (p.is_parziale) {{
fillColor = "#f59e0b";
strokeColor = "#000000";
strokeWeight = 3;
labelColor = "#000000";
}}
const m=new google.maps.Marker({{position:{{lat:p.lat,lng:p.lng}},map,
icon:{{path:google.maps.SymbolPath.CIRCLE,scale:13,fillColor:fillColor,fillOpacity:1,strokeWeight:strokeWeight,strokeColor:strokeColor}},
label:{{text:String(i+1),color:labelColor,fontWeight:"bold",fontSize:"12px"}}}});
m.addListener("click",()=>selectCard(i));
markers.push(m);
}});

const topLeftControls = document.getElementById("top-left-controls");
const bottomRightControls = document.getElementById("bottom-right-controls");

const mapTypeSelect = document.createElement("select");
mapTypeSelect.innerHTML = `
    <option value="roadmap">Mappa</option>
    <option value="hybrid">Satellite</option>
    <option value="terrain">Rilievo</option>
`;
mapTypeSelect.style.cssText = "background:white; border:none; border-radius:8px; height:34px; font-size:12px; font-weight:bold; box-shadow:0 2px 6px rgba(0,0,0,0.3); color:#0f172a; padding:0 8px; cursor:pointer; pointer-events:auto; outline:none;";
mapTypeSelect.onchange = (e) => {{
    map.setMapTypeId(e.target.value);
}};

const toggleBtn = document.createElement("button");
toggleBtn.innerHTML = '<span class="material-icons-round" style="font-size:20px;">unfold_less</span>';
toggleBtn.style.cssText = "background:white;border:none;border-radius:8px;width:34px;height:34px;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 6px rgba(0,0,0,0.3);cursor:pointer;color:#0f172a;pointer-events:auto;";
toggleBtn.onclick = () => {{
    const mapWrapper = document.getElementById("map-wrapper");
    if(mapWrapper.classList.contains("collapsed")){{
        mapWrapper.classList.remove("collapsed");
        toggleBtn.innerHTML = '<span class="material-icons-round" style="font-size:20px;">unfold_less</span>';
    }} else {{
        mapWrapper.classList.add("collapsed");
        toggleBtn.innerHTML = '<span class="material-icons-round" style="font-size:20px;">unfold_more</span>';
    }}
    setTimeout(() => google.maps.event.trigger(map, "resize"), 300);
}};

topLeftControls.appendChild(mapTypeSelect);
topLeftControls.appendChild(toggleBtn);

const zoomContainer = document.createElement("div");
zoomContainer.style.cssText = "display:flex; flex-direction:column; border-radius:8px; background:white; box-shadow:0 2px 6px rgba(0,0,0,0.3); overflow:hidden; pointer-events:auto;";

const zoomIn = document.createElement("button");
zoomIn.innerHTML = '<span class="material-icons-round" style="font-size:20px;">add</span>';
zoomIn.style.cssText = "background:white; border:none; width:34px; height:34px; display:flex; align-items:center; justify-content:center; cursor:pointer; border-bottom:1px solid #e2e8f0; color:#475569; padding:0;";
zoomIn.onclick = () => map.setZoom(map.getZoom() + 1);

const zoomOut = document.createElement("button");
zoomOut.innerHTML = '<span class="material-icons-round" style="font-size:20px;">remove</span>';
zoomOut.style.cssText = "background:white; border:none; width:34px; height:34px; display:flex; align-items:center; justify-content:center; cursor:pointer; color:#475569; padding:0;";
zoomOut.onclick = () => map.setZoom(map.getZoom() - 1);

zoomContainer.appendChild(zoomIn);
zoomContainer.appendChild(zoomOut);

bottomRightControls.appendChild(zoomContainer);
}}

function selectCard(i){{
document.querySelectorAll(".card").forEach(c=>c.classList.remove("active"));
const card=document.getElementById("card-"+i);
if(card){{card.classList.add("active");card.scrollIntoView({{behavior:"smooth",block:"center"}});}}
if(markers[i]){{map.panTo(markers[i].getPosition());map.setZoom(16);}}
}}

let sequenceChanged = false;

function apriModalEspansa() {{
    const list = document.getElementById("expand-modal-list");
    list.innerHTML = "";
    
    let displayIndex = 1;
    document.querySelectorAll("#delivery-list .card").forEach(c => {{
        if (!c.id.startsWith("card-")) return;
        
        const idxStr = c.id.replace("card-", "");
        const pIndex = parseInt(idxStr, 10);
        const p = PUNTI[pIndex];
        if(!p) return;
        
        const div = document.createElement("div");
        div.className = "compact-stop-item";
        div.id = "modal-" + c.id;
        
        const addressParts = (p.indirizzo || "").split(",");
        const city = addressParts.length > 1 ? addressParts.slice(1).join(',').trim() : (p.indirizzo || "");
        
        div.innerHTML = `
            <div class="drag-handle-modal" style="touch-action: none;">
                <span class="material-icons-round">drag_indicator</span>
            </div>
            <div class="compact-num">${{displayIndex++}}</div>
            <div class="compact-name">${{p.nome || p.ragione_sociale || ''}}</div>
            <div class="compact-city">${{city}}</div>
        `;
        list.appendChild(div);
    }});

    document.getElementById("expand-trip-modal").style.display = "flex";
    
    if (window.expandSortable) window.expandSortable.destroy();
    window.expandSortable = new Sortable(list, {{
        animation: 150,
        ghostClass: 'sortable-ghost',
        forceFallback: true,
        fallbackClass: 'sortable-fallback',
        handle: '.drag-handle-modal',
        onEnd: function() {{
            const items = list.querySelectorAll('.compact-stop-item');
            items.forEach((item, i) => {{
                const num = item.querySelector('.compact-num');
                if(num) num.textContent = i + 1;
            }});
        }}
    }});
}}

function chiudiModalEspansa() {{
    document.getElementById("expand-trip-modal").style.display = "none";
}}

function applicaOrdineEspanso() {{
    const mainList = document.getElementById("delivery-list");
    const modalCards = document.querySelectorAll("#expand-modal-list .compact-stop-item");
    const newOrderIds = Array.from(modalCards).map(mc => mc.id.replace("modal-", ""));
    
    const currentCards = Array.from(document.querySelectorAll("#delivery-list .card")).filter(c => c.id.startsWith("card-"));
    let changed = false;
    for(let i=0; i<newOrderIds.length; i++) {{
        if(currentCards[i] && currentCards[i].id !== newOrderIds[i]) {{
            changed = true; break;
        }}
    }}
    
    if(changed) {{
        const arrivoCard = document.getElementById("arrivo-card");
        newOrderIds.forEach(id => {{
            const c = document.getElementById(id);
            if(c) {{
                if (arrivoCard) {{
                    mainList.insertBefore(c, arrivoCard);
                }} else {{
                    mainList.appendChild(c);
                }}
            }}
        }});
        
        // Aggiorna i numeri visivi delle fermate originali
        const updatedCards = document.querySelectorAll("#delivery-list .card");
        let counter = 1;
        updatedCards.forEach(c => {{
            if (c.id.startsWith("card-")) {{
                const stopNum = c.querySelector(".stop-num");
                if (stopNum && stopNum.innerText !== "R") {{
                    stopNum.innerText = counter;
                }}
                counter++;
            }}
        }});
        
        sequenceChanged = true;
        document.getElementById("fab-save").style.display = "flex";
    }}
    chiudiModalEspansa();
}}

async function saveSequence() {{
    if(!sequenceChanged) return;
    const btn = document.getElementById("fab-save");
    btn.innerHTML = '<span class="material-icons-round">autorenew</span> Salvataggio...';
    btn.style.pointerEvents = "none";
    
    const cards = document.querySelectorAll("#delivery-list .card");
    const sequenza = Array.from(cards)
        .filter(c => c.id.startsWith("card-"))
        .map(c => parseInt(c.id.replace("card-", "")));
        
    try {{
        let realViaggioId = "{actual_viaggio_id if actual_viaggio_id else viaggio_id}";
        if (realViaggioId.includes(" - ")) {{
            realViaggioId = realViaggioId.split(" - ")[1];
        }}
        
        const url = `https://europe-west1-{PROJECT_ID}.cloudfunctions.net/autista_aggiorna_sequenza`;
        const res = await fetch(url, {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{ viaggio_id: realViaggioId, sequenza: sequenza }})
        }});
        if(res.ok) {{
            btn.innerHTML = '<span class="material-icons-round">check</span> Fatto!';
            setTimeout(() => window.location.reload(), 1000);
        }} else {{
            throw new Error("Errore salvataggio");
        }}
    }} catch(e) {{
        alert("Errore durante l'aggiornamento. Riprova.");
        btn.innerHTML = '<span class="material-icons-round">save</span> Salva Sequenza';
        btn.style.pointerEvents = "auto";
    }}
}}

const TRIP_ID = "{actual_viaggio_id or viaggio_id}";

function toggleConsegnato(e, idx) {{
    e.stopPropagation();
    const card = document.getElementById('card-' + idx);
    const isConsegnato = card.classList.toggle('consegnato');
    
    let stats = JSON.parse(localStorage.getItem('consegne_' + TRIP_ID) || '{{}}');
    stats[idx] = isConsegnato;
    localStorage.setItem('consegne_' + TRIP_ID, JSON.stringify(stats));
}}

document.addEventListener('DOMContentLoaded', () => {{
    const stats = JSON.parse(localStorage.getItem('consegne_' + TRIP_ID) || '{{}}');
    Object.keys(stats).forEach(idx => {{
        if(stats[idx]) {{
            const card = document.getElementById('card-' + idx);
            if(card) card.classList.add('consegnato');
        }}
    }});
}});

let currentCamIdx = -1;
let currentCamType = "";
function openCamera(e, idx) {{
    e.stopPropagation();
    currentCamIdx = idx;
    document.getElementById("cam-cliente-name").innerText = PUNTI[idx].nome;
    document.getElementById("cam-modal").style.display = "flex";
}}
function closeCamModal() {{
    document.getElementById("cam-modal").style.display = "none";
}}
function selectCamType(type) {{
    currentCamType = type;
    closeCamModal();
    document.getElementById("cameraInput").click();
}}
function handleFile(e) {{
    const file = e.target.files[0];
    if(!file) return;
    
    const btn = document.getElementById("fab-save");
    const origHtml = btn.innerHTML;
    btn.innerHTML = '<span class="material-icons-round" style="animation: spin 1s linear infinite;">autorenew</span> Invio in corso...';
    btn.style.display = "flex";
    btn.style.pointerEvents = "none";
    
    const reader = new FileReader();
    reader.onload = function(event) {{
        const img = new Image();
        img.onload = async function() {{
            const canvas = document.createElement("canvas");
            let width = img.width;
            let height = img.height;
            const MAX_DIM = 1200;
            if (width > height) {{
                if (width > MAX_DIM) {{ height *= MAX_DIM / width; width = MAX_DIM; }}
            }} else {{
                if (height > MAX_DIM) {{ width *= MAX_DIM / height; height = MAX_DIM; }}
            }}
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(img, 0, 0, width, height);
            const base64 = canvas.toDataURL("image/jpeg", 0.7);
            
            try {{
                let realViaggioId = "{actual_viaggio_id if actual_viaggio_id else viaggio_id}";
                if (realViaggioId.includes(" - ")) realViaggioId = realViaggioId.split(" - ")[1];
                
                const url = `https://europe-west1-{PROJECT_ID}.cloudfunctions.net/autista_salva_reso`;
                const res = await fetch(url, {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify({{
                        viaggio_id: realViaggioId,
                        codice_cliente: PUNTI[currentCamIdx].codice_cliente || "UNK",
                        nome_cliente: PUNTI[currentCamIdx].nome,
                        tipo_segnalazione: currentCamType,
                        foto_base64: base64
                    }})
                }});
                if(res.ok) {{
                    alert("Foto inviata in ufficio con successo!");
                }} else {{
                    alert("Errore nell'invio della foto.");
                }}
            }} catch(err) {{
                alert("Errore di rete durante l'invio.");
            }} finally {{
                btn.innerHTML = origHtml;
                if(!sequenceChanged) btn.style.display = "none";
                btn.style.pointerEvents = "auto";
                document.getElementById("cameraInput").value = "";
            }}
        }}
        img.src = event.target.result;
    }}
    reader.readAsDataURL(file);
}}
</script>

<!-- Modal Riordino -->
<div id="reorder-modal">
    <div class="rm-header">
        <h2 class="rm-title"><span class="material-icons-round">low_priority</span> Riordina Tappe</h2>
    </div>
    <div class="rm-body" id="rm-list">
        <!-- populated by JS -->
    </div>
    <div class="rm-footer">
        <button class="rm-btn-cancel" onclick="chiudiModalRiordino()">Annulla</button>
        <button class="rm-btn-save" id="rm-btn-save" onclick="applicaESalvaRiordino()">
            <span class="material-icons-round">save</span> Salva Ordine
        </button>
    </div>
</div>

<script>
let modalSortable = null;
const puntiDati = {punti_js};

function apriModalRiordino() {{
    const list = document.getElementById("rm-list");
    list.innerHTML = "";
    puntiDati.forEach((p, idx) => {{
        const div = document.createElement("div");
        div.className = "rm-item";
        div.dataset.index = idx;
        const addressParts = (p.indirizzo || "").split(",");
        const city = addressParts.length > 1 ? addressParts[1].trim() : (p.indirizzo || "");
        div.innerHTML = `
            <div class="material-icons-round rm-handle">drag_indicator</div>
            <div class="rm-num">${{idx + 1}}</div>
            <div class="rm-info">
                <span class="rm-name">${{p.nome}}</span>
                <span class="rm-sub">${{p.ragione_sociale || ''}}</span>
            </div>
            <div class="rm-sub" style="flex-shrink:0; text-align:right;">${{city}}</div>
        `;
        list.appendChild(div);
    }});
    
    document.getElementById("reorder-modal").style.display = "flex";
    
    if (modalSortable) modalSortable.destroy();
    modalSortable = new Sortable(list, {{
        animation: 150,
        handle: ".rm-handle",
        ghostClass: "sortable-ghost",
        delay: 150,
        delayOnTouchOnly: true,
        fallbackTolerance: 3
    }});
}}

function chiudiModalRiordino() {{
    document.getElementById("reorder-modal").style.display = "none";
}}

async function applicaESalvaRiordino() {{
    const list = document.getElementById("rm-list");
    const items = list.querySelectorAll(".rm-item");
    const nuovaSequenza = Array.from(items).map(item => parseInt(item.dataset.index));
    
    const changed = nuovaSequenza.some((val, i) => val !== i);
    if (!changed) {{
        chiudiModalRiordino();
        return;
    }}
    
    const btn = document.getElementById("rm-btn-save");
    btn.innerHTML = '<span class="material-icons-round">autorenew</span> Salvataggio...';
    btn.style.pointerEvents = "none";
    
    try {{
        let realViaggioId = '{actual_viaggio_id if actual_viaggio_id else viaggio_id}';
        if (realViaggioId.includes(" - ")) {{
            realViaggioId = realViaggioId.split(" - ").pop();
        }}
        
        const resp = await fetch("https://europe-west1-{os.environ.get('GCP_PROJECT', 'log-solution-60007')}.cloudfunctions.net/autista_aggiorna_sequenza", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{
                viaggio_id: realViaggioId,
                sequenza: nuovaSequenza
            }})
        }});
        
        const res = await resp.json();
        if (res.status === "ok") {{
            alert("Sequenza aggiornata con successo! La pagina si ricaricherà.");
            window.location.reload();
        }} else {{
            alert("Errore nel salvataggio: " + res.message);
            btn.innerHTML = '<span class="material-icons-round">save</span> Salva Ordine';
            btn.style.pointerEvents = "auto";
        }}
    }} catch(err) {{
        alert("Errore di rete: " + err.message);
        btn.innerHTML = '<span class="material-icons-round">save</span> Salva Ordine';
        btn.style.pointerEvents = "auto";
    }}
}}
</script>
</body></html>"""



def core_ricalcola_percorso(viaggio_id, nuovi_punti, num_locked=0):
    """
    Riceve un viaggio con le tappe riordinate manualmente dal frontend.
    - Le prime `num_locked` tappe sono H10 bloccate (non si toccano).
    - Le restanti vengono riottimizzate con OR-Tools + Distance Matrix API.
    - Salva il nuovo ordine su Firestore e rigenera la mappa autista.
    """
    start_time = time.time()

    if not viaggio_id or not nuovi_punti:
        return {"status": "errore", "message": "viaggio_id o punti mancanti", "errori": [], "data": {}}

    tenant_viaggio = get_tenant_from_viaggio_id(viaggio_id)
    doc_ref = get_db().collection('clienti').document(tenant_viaggio).collection('viaggi ddt').document(viaggio_id)
    doc_viaggio = doc_ref.get()
    if not doc_viaggio.exists:
        return {"status": "errore", "message": "Viaggio non trovato", "errori": [], "data": {}}

    # Normalizza coordinate
    punti_norm = []
    for p in nuovi_punti:
        try:
            punti_norm.append({**p, "lat": float(p["lat"]), "lon": float(p.get("lon", p.get("lng", 0)))})
        except:
            pass

    # Parti bloccate (H10) + parti da riottimizzare
    locked   = punti_norm[:num_locked]
    to_optim = punti_norm[num_locked:]

    punti_finali = locked[:]

    if to_optim:
        try:
            from ortools.constraint_solver import routing_enums_pb2, pywrapcp

            depot = _get_depot_for_points_cloud(punti_norm)
            start_node = locked[-1] if locked else depot
            all_locs   = [start_node] + to_optim + [depot]
            n          = len(all_locs)

            dist_matrix = _crea_matrice_distanze_cloud(all_locs, [])

            manager = pywrapcp.RoutingIndexManager(n, 1, [0], [n - 1])
            routing = pywrapcp.RoutingModel(manager)

            def dist_cb(fi, ti):
                return dist_matrix[manager.IndexToNode(fi)][manager.IndexToNode(ti)]

            cb_idx = routing.RegisterTransitCallback(dist_cb)
            routing.SetArcCostEvaluatorOfAllVehicles(cb_idx)
            params = pywrapcp.DefaultRoutingSearchParameters()
            params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
            params.time_limit.seconds = 10

            sol = routing.SolveWithParameters(params)
            if sol:
                idx = routing.Start(0)
                while not routing.IsEnd(idx):
                    node = manager.IndexToNode(idx)
                    if 0 < node < n - 1:
                        punti_finali.append(all_locs[node])
                    idx = sol.Value(routing.NextVar(idx))
            else:
                punti_finali.extend(to_optim)

        except Exception as e:
            print(f"[RICALCOLA] OR-Tools fallback ordine manuale: {e}")
            punti_finali.extend(to_optim)

    # Ricalcola KM e tempi con Directions API
    depot = _get_depot_for_points_cloud(punti_finali)
    km, sec_guida, polylines = _get_directions_data(punti_finali, depot=depot)

    # Aggiorna Firestore
    doc_ref.update({
        "punti_ottimizzati": punti_finali,
        "ordine_manuale":    True,
        "num_locked":        num_locked,
        "km_reali":          km,
        "t_guida_min":       sec_guida // 60,
        "t_tot_min":         (sec_guida // 60) + len(punti_finali) * TIME_PER_STOP_MIN,
        "status":            "ottimizzato"
    })

    # Rigenera mappa autista aggiornata
    viaggio = doc_viaggio.to_dict()
    distinta_url = viaggio.get("distinta_light")
    ora_partenza_calc = viaggio.get("_stats", {}).get("ora_partenza", "07:00")
    
    cliente_zona = viaggio.get("cliente_zona", "")
    nome_giro = viaggio.get("nome_giro", viaggio_id)
    if cliente_zona and cliente_zona.upper() not in nome_giro.upper():
        titolo_giro = f"{cliente_zona.upper()} - {nome_giro}"
    else:
        titolo_giro = nome_giro
        
    html = _genera_html_mappa(titolo_giro, punti_finali, km, sec_guida, polylines, depot=depot, distinta_url=distinta_url, ora_partenza_dep=ora_partenza_calc, actual_viaggio_id=viaggio_id)
    bucket = storage.bucket(name=BUCKET_NAME)
    data_v = viaggio.get("data", "sconosciuta").replace("/", "-")
    html_path = f"CONSEGNE/CONSEGNE_{data_v}/MAPPE_AUTISTI/{viaggio_id}.html"
    blob = bucket.blob(html_path)
    blob.upload_from_string(html.encode("utf-8"), content_type="text/html; charset=utf-8")
    url_pubblica = _genera_url_storage_token(blob)

    elapsed = time.time() - start_time
    _registra_statistica("ricalcola_percorso", elapsed)

    return {
        "status": "ok",
        "message": f"Percorso ricalcolato in {elapsed:.2f}s ({num_locked} tappe bloccate)",
        "errori": [],
        "data": {
            "viaggio_id":    viaggio_id,
            "km_reali":      km,
            "t_guida_min":   sec_guida // 60,
            "t_tot_min":     (sec_guida // 60) + len(punti_finali) * TIME_PER_STOP_MIN,
            "n_tappe":       len(punti_finali),
            "n_locked":      num_locked,
            "mappa_url":     blob.public_url,
            "tempo_sec":     elapsed
        }
    }


# ─── PUNTO #6: RIEPILOGO FATTURAZIONE MENSILE ────────────────────────────────

# Costanti fatturazione
VALORE_DDT_STANDARD = 16.50   # € per DDT standard (Frutta e Latte)
VALORE_DDT_SPECIALE = 16.50   # € per DDT aree speciali (stessa tariffa, separati per contabilità)









def parse_fascia_oraria(val):
    if val is None or (hasattr(val, "isna") and val.isna()) or val == "":
        return "", ""
    val_str = str(val).strip()
    match_range = re.findall(r'(\d{2}:\d{2})', val_str)
    if len(match_range) == 2:
        return match_range[0], match_range[1]
    match_dopo = re.search(r'(?:Dopo le|dopo le)\s*(\d{2}:\d{2})', val_str)
    if match_dopo:
        return match_dopo.group(1), ""
    match_entro = re.search(r'(?:Entro le|entro le)\s*(\d{2}:\d{2})', val_str)
    if match_entro:
        return "", match_entro.group(1)
    return "", ""

def _genera_pdf_placeholder_grand_chef_io(codice: str, nome: str, ind: str, cit: str, prov: str, note: str, om: str, oM: str, data: str) -> io.BytesIO:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    out_stream = io.BytesIO()
    doc = SimpleDocTemplate(out_stream, pagesize=A4, leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('gc_title', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#0f172a'), spaceAfter=15)
    body_style = ParagraphStyle('gc_body', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#334155'))
    label_style = ParagraphStyle('gc_label', parent=styles['Normal'], fontSize=10, leading=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#0f172a'))
    
    elements = []
    elements.append(Paragraph(f"SCHEDA DI CONSEGNA - CANALE GRAND CHEF", title_style))
    elements.append(Spacer(1, 10))
    
    data_table = [
        [Paragraph("Codice Cliente:", label_style), Paragraph(codice, body_style)],
        [Paragraph("Destinatario:", label_style), Paragraph(nome, body_style)],
        [Paragraph("Indirizzo:", label_style), Paragraph(ind, body_style)],
        [Paragraph("Città:", label_style), Paragraph(f"{cit} ({prov})", body_style)],
        [Paragraph("Data Consegna:", label_style), Paragraph(data, body_style)],
        [Paragraph("Fascia Oraria:", label_style), Paragraph(f"Da {om or '—'} A {oM or '14:00'}", body_style)],
        [Paragraph("Note Consegna:", label_style), Paragraph(note or "Nessuna nota", body_style)]
    ]
    
    t = Table(data_table, colWidths=[120, 380])
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f8fafc')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 40))
    
    elements.append(Paragraph("<b>FIRMA PER RICEVUTA</b>", label_style))
    elements.append(Spacer(1, 15))
    sig_table = [
        [Paragraph("Data: ____________________", body_style), Paragraph("Firma Leggibile: ___________________________", body_style)]
    ]
    t_sig = Table(sig_table, colWidths=[200, 300])
    t_sig.setStyle(TableStyle([
        ('PADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(t_sig)
    
    doc.build(elements)
    out_stream.seek(0)
    return out_stream

def _genera_pdf_placeholder_cattel_io(codice: str, nome: str, ind: str, cit: str, prov: str, note: str, om: str, oM: str, data: str) -> io.BytesIO:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    out_stream = io.BytesIO()
    doc = SimpleDocTemplate(out_stream, pagesize=A4, leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('cattel_title', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#0f172a'), spaceAfter=15)
    body_style = ParagraphStyle('cattel_body', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#334155'))
    label_style = ParagraphStyle('cattel_label', parent=styles['Normal'], fontSize=10, leading=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#0f172a'))
    
    elements = []
    elements.append(Paragraph(f"SCHEDA DI CONSEGNA - CANALE CATTEL", title_style))
    elements.append(Spacer(1, 10))
    
    data_table = [
        [Paragraph("Codice Cliente:", label_style), Paragraph(codice, body_style)],
        [Paragraph("Destinatario:", label_style), Paragraph(nome, body_style)],
        [Paragraph("Indirizzo:", label_style), Paragraph(ind, body_style)],
        [Paragraph("Città:", label_style), Paragraph(f"{cit} ({prov})", body_style)],
        [Paragraph("Data Consegna:", label_style), Paragraph(data, body_style)],
        [Paragraph("Fascia Oraria:", label_style), Paragraph(f"Da {om or '—'} A {oM or '14:00'}", body_style)],
        [Paragraph("Note Consegna:", label_style), Paragraph(note or "Nessuna nota", body_style)]
    ]
    
    t = Table(data_table, colWidths=[120, 380])
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f8fafc')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 40))
    
    elements.append(Paragraph("<b>FIRMA PER RICEVUTA</b>", label_style))
    elements.append(Spacer(1, 15))
    sig_table = [
        [Paragraph("Data: ____________________", body_style), Paragraph("Firma Leggibile: ___________________________", body_style)]
    ]
    t_sig = Table(sig_table, colWidths=[200, 300])
    t_sig.setStyle(TableStyle([
        ('PADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(t_sig)
    
    doc.build(elements)
    out_stream.seek(0)
    return out_stream

def _processa_excel_dac_core_logic(excel_bytes: bytes, db_mappati: dict, data_consegna: str, job_id: str, tenant_name: str) -> dict:
    import pandas as pd
    
    nuovi_dati = {}
    split_files = {}
    deliveries_list = []
    
    f_io = io.BytesIO(excel_bytes)
    df = pd.read_excel(f_io, sheet_name=0)
    df_clean = df.dropna(how='all')
    
    def _str_val(val):
        return str(val).strip() if pd.notna(val) and str(val).strip() not in ("", "nan") else ""

    for idx, row in df_clean.iterrows():
        # Map columns by name if possible, otherwise skip
        if 'Codice' not in row:
            continue
            
        codice = clean_client_code(_str_val(row.get('Codice', '')))
        if not codice:
            continue
            
        ragione_sociale = _str_val(row.get('Ragione Sociale', ''))
        indirizzo = _str_val(row.get('Indirizzo', ''))
        cap = _str_val(row.get('CAP', ''))
        localita = _str_val(row.get('Città', ''))
        provincia = _str_val(row.get('Provincia', ''))
        
        # Parse orari
        ap_mat = _str_val(row.get('Apertura Mattina', ''))
        ch_mat = _str_val(row.get('Chiusura Mattina', ''))
        ap_pom = _str_val(row.get('Apertura Pomeriggio', ''))
        ch_pom = _str_val(row.get('Chiusura Pomeriggio', ''))
        
        orario_min = ap_mat if ap_mat else (ap_pom if ap_pom else "")
        orario_max = ch_pom if ch_pom else (ch_mat if ch_mat else "")
        if not orario_max and (orario_min != ""):
            orario_max = "18:00" # fallback
            
        note = _str_val(row.get('Giorno Chiusura', ''))
        colli = _str_val(row.get('Colli', ''))
        peso_kg = _str_val(row.get('Peso', ''))
        
        codice_l = codice.lower()
        # Se è il magazzino, va comunque aggiunto come "consegna" per creare il giro
        if codice_l not in db_mappati:
            nuovi_dati[codice] = {
                "dest": ragione_sociale,
                "ind": indirizzo,
                "cap": cap,
                "cit": localita,
                "prov": provincia,
                "om": orario_min,
                "oM": orario_max,
                "tipo": tenant_name
            }
        else:
            # Crea placeholder PDF
            fname = f"{codice}_{data_consegna}.pdf"
            pdf_io = _genera_pdf_placeholder_grand_chef_io(
                codice, ragione_sociale, indirizzo,
                localita, provincia, note, orario_min, orario_max, data_consegna
            )
            split_files[fname] = pdf_io
            
            deliveries_list.append({
                "codice_consegna": codice,
                "data": data_consegna,
                "num_ddt": f"{tenant_name}_{codice}",
                "ragsoc": ragione_sociale,
                "ind": indirizzo,
                "loc": localita,
                "prv": provincia,
                "cap": cap,
                "colli": colli,
                "peso": peso_kg,
                "bancali": "",
                "note": note,
                "orari": f"{orario_min} - {orario_max}" if (orario_min or orario_max) else "",
                "om": orario_min,
                "oM": orario_max,
                "pdf_url": "", 
                "storage_path": f"split_ddt/{data_consegna}/{tenant_name}/{fname}",
                "job_id": job_id,
                "tipo": tenant_name,
                "zona": f"{tenant_name}_{job_id}"
            })
            
    return {
        "split_files": split_files,
        "nuovi_dati": nuovi_dati,
        "nuovi_orari": {},
        "nuovi_articoli": {},
        "deliveries": deliveries_list
    }

def _processa_excel_cattel_core_logic(excel_bytes: bytes, db_mappati: dict, data_consegna: str, job_id: str, tenant_name: str) -> dict:
    import pandas as pd
    import re
    
    nuovi_dati = {}
    split_files = {}
    deliveries_list = []
    
    f_io = io.BytesIO(excel_bytes)
    xl = pd.ExcelFile(f_io)
    
    def normalize_address(addr):
        if not addr:
            return ""
        addr = str(addr).lower().strip()
        addr = re.sub(r'\(\s*[a-zA-Z]{2}\s*\)', '', addr)
        addr = re.sub(r'\b\d{5}\b', '', addr)
        addr = re.sub(r'[^\w\s]', '', addr)
        addr = re.sub(r'\b(via|viale|piazza|corso|localita|loc|strada|vicolo|lato|piaz)\b', '', addr)
        return " ".join(addr.split())

    indirizzi_master = {}
    for code_db, cust in db_mappati.items():
        addr_raw = cust.get("ind") or cust.get("indirizzo") or ""
        norm_addr = normalize_address(addr_raw)
        if norm_addr and cust.get("lat") and cust.get("lon"):
            indirizzi_master[norm_addr] = cust

    print(f"[Parser Cattel] Inizio estrazione dai fogli ({xl.sheet_names}) ignorando 'Riepilogo'.")
    
    for s_name in xl.sheet_names:
        if s_name.lower() == "riepilogo":
            continue
            
        targa = s_name.strip()
        df = xl.parse(s_name, header=None)
        
        # Estrarre autista dalla cella C2 (Riga 2, Colonna 3, quindi indice row 1, col 2)
        autista = ""
        if len(df) > 1 and len(df.columns) > 2:
            autista_val = df.iloc[1, 2]
            autista = str(autista_val).strip() if pd.notna(autista_val) else ""
            
        # L'intestazione è alla riga 4 (indice 3). I dati partono dalla riga 6 (indice 5).
        # L'ultima riga è il magazzino d'arrivo, quindi ci fermiamo a len(df) - 1.
        if len(df) <= 5:
            continue
            
        last_idx = len(df) - 1
        
        for i in range(5, last_idx):
            row = df.iloc[i]
            
            codice = clean_client_code(row.iloc[0]) if len(row) > 0 else ""
            if not codice or str(codice).lower() == 'nan' or str(codice).upper() == 'SOMMACAMPAGNA':
                continue
                
            ragione_sociale = str(row.iloc[1]).strip() if len(row) > 1 and pd.notna(row.iloc[1]) else ""
            indirizzo = str(row.iloc[2]).strip() if len(row) > 2 and pd.notna(row.iloc[2]) else ""
            colli = str(row.iloc[9]).strip() if len(row) > 9 and pd.notna(row.iloc[9]) else ""
            
            # Estrazione località e provincia dall'indirizzo (se presenti)
            localita = ""
            provincia = ""
            if indirizzo:
                m_prov = re.search(r'\(([^)]+)\)', indirizzo)
                if m_prov:
                    provincia = m_prov.group(1).strip().upper()
                parts = indirizzo.split(',')
                if len(parts) > 1:
                    cit_part = parts[-1].strip()
                    if re.search(r'[a-zA-Z]{2,}', cit_part):
                        cit_part = re.sub(r'\(.*?\)', '', cit_part).strip()
                        cit_part = re.sub(r'\d{5}', '', cit_part).strip()
                        localita = cit_part
                        
            orario_min = "08:00"
            orario_max = "14:00"
            note = ""
            
            codice_l = codice.lower()
            if codice_l not in db_mappati:
                if codice not in nuovi_dati:
                    norm_new_addr = normalize_address(indirizzo)
                    match_found = False
                    matched_cust = None
                    if norm_new_addr and norm_new_addr in indirizzi_master:
                        matched_cust = indirizzi_master[norm_new_addr]
                        match_found = True
                        
                    if match_found and matched_cust:
                        nuovi_dati[codice] = {
                            "dest": ragione_sociale,
                            "ind": indirizzo,
                            "cap": matched_cust.get("cap") or "",
                            "cit": matched_cust.get("cit") or matched_cust.get("citta") or localita,
                            "prov": matched_cust.get("prov") or matched_cust.get("provincia") or provincia,
                            "om": matched_cust.get("om") or orario_min,
                            "oM": matched_cust.get("oM") or orario_max,
                            "tipo": tenant_name,
                            "lat": matched_cust.get("lat"),
                            "lon": matched_cust.get("lon"),
                            "stato_suggerito": "giallo",
                            "matched_name": matched_cust.get("cliente") or matched_cust.get("nome_consegna") or "",
                            "matched_brand": matched_cust.get("tipologia_grado") or "MASTER"
                        }
                    else:
                        nuovi_dati[codice] = {
                            "dest": ragione_sociale,
                            "ind": indirizzo,
                            "cap": "",
                            "cit": localita,
                            "prov": provincia,
                            "om": orario_min,
                            "oM": orario_max,
                            "tipo": tenant_name,
                            "stato_suggerito": "rosso",
                            "codice_frutta": codice,
                            "codice_latte": "p00000"
                        }
            else:
                cust_d = db_mappati[codice_l]
                fname = f"{codice}_{data_consegna}.pdf"
                pdf_io = _genera_pdf_placeholder_cattel_io(
                    codice,
                    cust_d.get("cliente") or cust_d.get("nome_consegna") or ragione_sociale,
                    cust_d.get("ind") or cust_d.get("indirizzo") or indirizzo,
                    cust_d.get("cit") or cust_d.get("citta") or localita,
                    cust_d.get("prov") or cust_d.get("provincia") or provincia,
                    cust_d.get("note") or note,
                    cust_d.get("om") or orario_min,
                    cust_d.get("oM") or orario_max,
                    data_consegna
                )
                split_files[fname] = pdf_io
                
                # Zona logistica include solo targa per Cattel (rimosso autista come richiesto)
                zona_cod = f"{tenant_name}_{targa}"
                
                deliveries_list.append({
                    "codice_consegna": codice,
                    "data": data_consegna,
                    "num_ddt": f"{tenant_name}_{codice}",
                    "pdf_name": fname,
                    "tipo": tenant_name,
                    "zona": zona_cod,
                    "gc_colli": colli,
                    "gc_peso_kg": "",
                    "gc_num_cartone": "",
                    "cattel_zona_viaggio": targa,
                    "autista": autista
                })
                
    return {
        "split_files": split_files,
        "nuovi_dati": nuovi_dati,
        "nuovi_orari": {},
        "nuovi_articoli": {},
        "deliveries": deliveries_list
    }

def _processa_excel_chef_core_logic(excel_bytes: bytes, db_mappati: dict, data_consegna: str, job_id: str, tenant_name: str) -> dict:
    import pandas as pd
    
    nuovi_dati = {}
    split_files = {}
    deliveries_list = []
    
    f_io = io.BytesIO(excel_bytes)
    df = pd.read_excel(f_io, sheet_name=0, header=None)
    df_clean = df.dropna(how='all')
    
    header_row_idx = None
    for idx, row in df_clean.iterrows():
        row_vals = [str(val).strip().lower() for val in row.values if pd.notna(val)]
        if any('ragione sociale' in rv for rv in row_vals) or any('codice' in rv for rv in row_vals):
            header_row_idx = idx
            break
            
    if header_row_idx is not None:
        df_data = df_clean.loc[header_row_idx + 1:]
        
        def _cell(row_data, col_idx):
            return str(row_data.iloc[col_idx]).strip() if len(row_data) > col_idx and pd.notna(row_data.iloc[col_idx]) and str(row_data.iloc[col_idx]).strip() not in ("", "nan") else ""
            
        for _, row in df_data.iterrows():
            if str(row.iloc[0]).lower().strip() == 'totale':
                continue
                
            codice = clean_client_code(row.iloc[0])
            if not codice:
                continue
                
            ragione_sociale = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ""
            indirizzo = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else ""
            localita = str(row.iloc[7]).strip() if pd.notna(row.iloc[7]) else ""
            provincia = str(row.iloc[8]).strip() if pd.notna(row.iloc[8]) else ""
            note = str(row.iloc[14]).strip() if len(row) > 14 and pd.notna(row.iloc[14]) else ""
            fascia = str(row.iloc[15]).strip() if len(row) > 15 and pd.notna(row.iloc[15]) else ""
            
            orario_min, orario_max = parse_fascia_oraria(fascia)
            if not orario_min and not orario_max and note:
                orario_min, orario_max = parse_fascia_oraria(note)
                
            if not orario_max:
                orario_max = "14:00"
                
            colli = _cell(row, 9)
            peso_kg = _cell(row, 10)
            num_cartone = _cell(row, 13)
                
            codice_l = codice.lower()
            if codice_l not in db_mappati:
                nuovi_dati[codice] = {
                    "dest": ragione_sociale,
                    "ind": indirizzo,
                    "cap": "",
                    "cit": localita,
                    "prov": provincia,
                    "om": orario_min,
                    "oM": orario_max,
                    "tipo": tenant_name
                }
            else:
                fname = f"{codice}_{data_consegna}.pdf"
                pdf_io = _genera_pdf_placeholder_grand_chef_io(
                    codice, ragione_sociale, indirizzo,
                    localita, provincia, note, orario_min, orario_max, data_consegna
                )
                split_files[fname] = pdf_io
                
                deliveries_list.append({
                    "codice_consegna": codice,
                    "data": data_consegna,
                    "num_ddt": f"{tenant_name}_{codice}",
                    "pdf_name": fname,
                    "tipo": tenant_name,
                    "zona": f"{tenant_name}_{job_id}",
                    "gc_colli": colli,
                    "gc_peso_kg": peso_kg,
                    "gc_num_cartone": num_cartone,
                    "orario_min": orario_min,
                    "orario_max": orario_max,
                    "note": note
                })
                
    return {
        "split_files": split_files,
        "nuovi_dati": nuovi_dati,
        "nuovi_orari": {},
        "nuovi_articoli": {},
        "deliveries": deliveries_list
    }

import re

def enrich_delivery_with_canonical_schema(
    legacy_delivery,
    tenant,
    competenza,
    job_id,
    delivery_index,
    data_elab,
    etichetta
):
    enriched = dict(legacy_delivery)
    
    # Costruisci l'identificativo univoco
    base_id = f"{tenant}_{competenza}_{job_id}_{delivery_index:04d}"
    sanitized_id = re.sub(r'[^a-zA-Z0-9_\-]', '', base_id)
    
    # Document storage path
    pdf_name = legacy_delivery.get("pdf_name", "")
    storage_path = legacy_delivery.get("storage_path", "")
    if not storage_path and pdf_name:
        storage_path = f"split_ddt/{data_elab}/{etichetta}/{pdf_name}"
        
    # Logistics handling
    colli = legacy_delivery.get("colli")
    if colli in (None, ""):
        colli = legacy_delivery.get("gc_colli")
        
    peso_kg = legacy_delivery.get("peso")
    if peso_kg in (None, ""):
        peso_kg = legacy_delivery.get("gc_peso_kg")
        
    # Time windows
    time_windows = []
    start = legacy_delivery.get("orario_min") or legacy_delivery.get("om") or ""
    end = legacy_delivery.get("orario_max") or legacy_delivery.get("oM") or ""
    if start or end:
        time_windows.append({
            "start": start,
            "end": end
        })
        
    # Aggiungi campi canonici
    enriched["schema_version"] = "1.0"
    enriched["delivery_id"] = sanitized_id
    
    enriched["source"] = {
        "tenant": tenant,
        "competenza": competenza,
        "job_id": job_id,
        "parser_type": etichetta
    }
    
    enriched["customer"] = {
        "codice_originale": legacy_delivery.get("codice_consegna", ""),
        "ragione_sociale": legacy_delivery.get("ragsoc", ""),
        "indirizzo": legacy_delivery.get("ind", ""),
        "cap": legacy_delivery.get("cap", ""),
        "citta": legacy_delivery.get("loc", ""),
        "provincia": legacy_delivery.get("prv", "")
    }
    
    enriched["document"] = {
        "numero_ddt": legacy_delivery.get("num_ddt", ""),
        "data": legacy_delivery.get("data", data_elab),
        "pdf_name": pdf_name,
        "storage_path": storage_path
    }
    
    enriched["logistics"] = {
        "colli": colli,
        "peso_kg": peso_kg,
        "cartoni": legacy_delivery.get("gc_num_cartone"),
        "bancali": legacy_delivery.get("bancali"),
        "targa": legacy_delivery.get("cattel_zona_viaggio", ""),
        "autista": legacy_delivery.get("autista", ""),
        "zona_origine": legacy_delivery.get("zona", "")
    }
    
    enriched["time_windows"] = time_windows
    
    return enriched

def core_processa_job_pdf(job_id, tenant="DNR"):
    start_time = time.time()
    db = get_db()
    job_ref = db.collection('clienti').document(tenant).collection('processing_jobs').document(job_id)
    
    @firestore.transactional
    def acquire_job(transaction, ref):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            return None
        doc_data = snapshot.to_dict()
        if doc_data.get("status") != "uploaded":
            return doc_data
        transaction.update(ref, {
            "status": "processing",
            "updated_at": firestore.SERVER_TIMESTAMP,
            "started_at": firestore.SERVER_TIMESTAMP
        })
        return doc_data

    transaction = db.transaction()
    data = acquire_job(transaction, job_ref)
    
    if not data: return {"status": "errore", "message": "Job non trovato"}
    if data.get("status") != "uploaded": return {"status": "errore", "message": "Stato job non valido per elaborazione"}
    data_lavoro_forzata = data.get('data_lavoro')
    
    competenza = data.get("competenza") or data.get("type", "FRUTTA").upper()
    if competenza in ("GRAND_CHEF", "GRAND CHEF", "GRAN CHEF"):
        competenza = "GRAN_CHEF"
    print(f"[INFO] Elaborazione job {job_id} con competenza {competenza}")
    
    try:
        bucket = storage.bucket(name=BUCKET_NAME)
        path = data.get("storage_path")
        etichetta = data.get("type", "FRUTTA").upper()
        is_excel = data.get("is_excel", False) or etichetta == "GRAND_CHEF"
        
        # 1. Carica Mappatura dal tenant corretto per isolare i dati
        db_mappati = {}
        clienti_ref = db.collection('clienti').document(tenant).collection('raccolta clienti')
        for doc in clienti_ref.stream():
            d = doc.to_dict()
            cf = str(d.get('codice_frutta') or '').strip().lower()
            cl = str(d.get('codice_latte') or '').strip().lower()
            if cf and cf != 'p00000' and cf != 'nan': db_mappati[cf] = d
            if cl and cl != 'p00000' and cl != 'nan': db_mappati[cl] = d
        
        articoli_ref = db.collection('clienti').document(tenant).collection('codici articoli')
        db_articoli = {doc.id: doc.to_dict() for doc in articoli_ref.stream()}
        
        # 2. Download
        blob = bucket.blob(path)
        file_bytes = blob.download_as_bytes()
        
        # 3. Processing
        if is_excel:
            data_elab = data_lavoro_forzata or datetime.now().strftime("%d-%m-%Y")
            if competenza == "CATTEL":
                risultato = _processa_excel_cattel_core_logic(file_bytes, db_mappati, data_elab, job_id, competenza)
            elif competenza == "DAC":
                risultato = _processa_excel_dac_core_logic(file_bytes, db_mappati, data_elab, job_id, competenza)
            else:
                risultato = _processa_excel_chef_core_logic(file_bytes, db_mappati, data_elab, job_id, competenza)
        else:
            risultato = _processa_pdf_core_logic(file_bytes, etichetta, db_mappati, db_articoli)
        
        split_files = risultato["split_files"]
        deliveries = risultato["deliveries"]
        
        deliveries = [
            enrich_delivery_with_canonical_schema(
                legacy_delivery=delivery,
                tenant=tenant,
                competenza=competenza,
                job_id=job_id,
                delivery_index=index,
                data_elab=data_elab,
                etichetta=etichetta
            )
            for index, delivery in enumerate(deliveries)
        ]
        
        nuovi_dati = risultato["nuovi_dati"]
        nuovi_orari = risultato.get("nuovi_orari", {})
        nuovi_articoli = risultato.get("nuovi_articoli", {})
        
        # 5. Salvataggio nuovi dati dinamici nel tenant corretto
        for l, info in nuovi_dati.items():
            db.collection('clienti').document(tenant).collection('nuovi codici consegna').document(l).set(info, merge=True)
            
        for l, info in nuovi_orari.items():
            db.collection('clienti').document(tenant).collection('nuovi orari mancanti').document(l).set(info, merge=True)
            
        for c, info in nuovi_articoli.items():
            doc_id = str(c).replace('/', '-').replace(' ', '_')
            db.collection('clienti').document(tenant).collection('nuovi articoli rilevati').document(doc_id).set(info, merge=True)
            
        if not deliveries:
            job_ref.update({
                "status": "completed", 
                "completed_at": firestore.SERVER_TIMESTAMP,
                "message": "Nessun DDT trovato (Clienti da mappare?)",
                "nuovi_clienti": len(nuovi_dati),
                "nuovi_articoli": len(nuovi_articoli),
                "nuovi_orari": len(nuovi_orari),
                "nuovi_clienti_list": list(nuovi_dati.keys()),
                "nuovi_articoli_list": list(nuovi_articoli.keys()),
                "nuovi_orari_list": list(nuovi_orari.keys()),
                "updated_at": firestore.SERVER_TIMESTAMP
            })
            return {"status": "ok", "pdf_generati": 0}
            
        # Applica il campo competenza a ciascun DDT
        for ddt in deliveries:
            ddt["competenza"] = competenza

        # Se l'utente ha scelto una data nel calendario, ha la precedenza
        if data_lavoro_forzata:
            data_elab = data_lavoro_forzata
            print(f"[INFO] Uso data forzata dal calendario: {data_elab}")
        else:
            data_elab = deliveries[0]["data"]
            print(f"[INFO] Uso data estratta dal file: {data_elab}")
        
        # --- PULIZIA PREVENTIVA RIMOSSA (Gestita centralmente al caricamento) ---
        print(f"[INFO] Elaborazione file per {data_elab} - {etichetta}")

        # 4. Upload split e salvataggio DDT
        for fname, out_stream in split_files.items():
            out_path = f"split_ddt/{data_elab}/{etichetta}/{fname}"
            split_blob = bucket.blob(out_path)
            if hasattr(out_stream, "seek"):
                out_stream.seek(0)
            split_blob.upload_from_file(out_stream, content_type='application/pdf')

            
        # 6. Salvataggio Metadati Temporanei (per Step 2)
        metadata_ddt = {
            "data_elab": data_elab,
            "tipo": etichetta,
            "competenza": competenza,
            "deliveries": deliveries
        }
        meta_path = f"split_ddt/{data_elab}/{etichetta}/ddt_estratti_{job_id}.json"
        bucket.blob(meta_path).upload_from_string(
            json.dumps(metadata_ddt, indent=2), 
            content_type='application/json'
        )
        
        elapsed = time.time() - start_time
        job_ref.update({
            "status": "completed",
            "completed_at": firestore.SERVER_TIMESTAMP,
            "data_rilevata": data_elab,
            "meta_path_json": meta_path,
            "pdf_generati": len(split_files),
            "nuovi_clienti": len(nuovi_dati),
            "nuovi_articoli": len(nuovi_articoli),
            "nuovi_orari": len(nuovi_orari),
            "nuovi_clienti_list": list(nuovi_dati.keys()),
            "nuovi_articoli_list": list(nuovi_articoli.keys()),
            "nuovi_orari_list": list(nuovi_orari.keys()),
            "tempo_sec": round(elapsed, 2),
            "updated_at": firestore.SERVER_TIMESTAMP
        })
        
        return {"status": "ok", "pdf_generati": len(split_files), "tempo_sec": round(elapsed, 2)}
        
    except Exception as e:
        job_ref.update({"status": "error", "error_message": str(e), "updated_at": firestore.SERVER_TIMESTAMP, "failed_at": firestore.SERVER_TIMESTAMP})
        return {"status": "errore", "message": str(e)}

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
def _genera_kml_zone(data, zone_list):
    """Genera un file KML base per Google Earth"""
    kml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        f'<name>Zone {data}</name>'
    ]
    for z in zone_list:
        kml.append(f'<Folder><name>Zona {z["id_zona"]}</name>')
        for p in z["lista_punti"]:
            if p["lat"] and p["lon"]:
                kml.append(f'<Placemark><name>{p["nome"]}</name><Point><coordinates>{p["lon"]},{p["lat"]},0</coordinates></Point></Placemark>')
        kml.append('</Folder>')
    kml.append('</Document></kml>')
    return "\n".join(kml)



def _genera_html_mappa_generale(data, zone_list):
    """Template della mappa generale con selettore a tendina per il giro"""
    zone_json = json.dumps(zone_list)
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>Mappa Zone - {data}</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&display=swap" rel="stylesheet">
    <script src="https://maps.googleapis.com/maps/api/js?key={GOOGLE_MAPS_API_KEY}&libraries=marker,geometry"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Outfit', sans-serif; display: flex; height: 100vh; overflow: hidden; background: #f8fafc; }}
        #sidebar {{ width: 400px; background: white; border-right: 1px solid #e2e8f0; padding: 20px; display: flex; flex-direction: column; gap: 14px; box-shadow: 2px 0 12px rgba(0,0,0,0.06); z-index: 10; }}
        #map {{ flex: 1; }}
        .sidebar-title {{ font-size: 20px; font-weight: 800; color: #1e293b; }}
        .sidebar-subtitle {{ font-size: 13px; color: #64748b; margin-top: 2px; }}
        #giroSelector {{ width: 100%; height: 46px; border: 2px solid #e2e8f0; border-radius: 12px; padding: 0 14px; font-size: 14px; font-weight: 700; color: #1e293b; background: #f8fafc; outline: none; cursor: pointer; font-family: inherit; transition: border-color 0.2s; }}
        #giroSelector:focus {{ border-color: #4f46e5; }}
        #zone-list {{ overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 8px; }}
        .zone-card {{ border: 2px solid #e2e8f0; border-radius: 14px; padding: 14px; background: #fff; transition: all 0.2s; cursor: pointer; }}
        .zone-card.active {{ border-color: var(--zone-color, #4f46e5); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
        .zone-card:hover {{ border-color: #cbd5e1; }}
        .zone-header {{ display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 14px; }}
        .color-pill {{ width: 14px; height: 14px; border-radius: 4px; flex-shrink: 0; }}
        .zone-meta {{ font-size: 12px; color: #64748b; margin-top: 6px; margin-left: 24px; }}
        .point-list {{ margin-top: 10px; display: none; max-height: 260px; overflow-y: auto; border-top: 1px solid #f1f5f9; padding-top: 10px; }}
        .point-item {{ font-size: 12px; color: #475569; padding: 4px 0 4px 8px; border-left: 3px solid transparent; }}
        .point-item.highlight {{ border-left-color: var(--zone-color, #4f46e5); font-weight: 700; color: #1e293b; }}
        .badge-parziale {{ background: #f59e0b; color: black; font-weight: 800; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 5px; }}
        .expand-btn {{ font-size: 11px; color: #94a3b8; float: right; }}
    </style>
</head>
<body>
    <div id="sidebar">
        <div>
            <div class="sidebar-title">🗺️ Mappa Zone — {data}</div>
            <div class="sidebar-subtitle">Seleziona un giro per evidenziarlo sulla mappa</div>
        </div>
        <select id="giroSelector" onchange="selezionaGiro(this.value)">
            <option value="__all__">📍 Tutti i giri</option>
        </select>
        <div id="zone-list"></div>
    </div>
    <div id="map"></div>
    <script>
        const ZONE = {zone_json};
        let map;
        // Struttura: [{{ zone, markers: [], polylines: [] }}]
        let zoneData = [];
        let selectedIdx = null;

        function initMap() {{
            map = new google.maps.Map(document.getElementById("map"), {{
                center: {{ lat: 45.44, lng: 11.71 }}, zoom: 9,
                mapTypeControl: true,
                streetViewControl: false,
                fullscreenControl: true
            }});

            const select = document.getElementById("giroSelector");
            const list = document.getElementById("zone-list");

            ZONE.forEach((z, idx) => {{
                // Aggiungi option al dropdown
                const opt = document.createElement("option");
                opt.value = idx;
                opt.textContent = `${{z.nome_giro}} (${{z.lista_punti.length}} tappe)`;
                select.appendChild(opt);

                // Crea card nel pannello
                const card = document.createElement("div");
                card.className = "zone-card";
                card.style.setProperty("--zone-color", z.color);
                card.id = `card-${{idx}}`;
                card.onclick = (e) => {{
                    if (e.target.tagName === "INPUT") return;
                    document.getElementById("giroSelector").value = idx;
                    selezionaGiro(idx);
                }};

                const header = document.createElement("div");
                header.className = "zone-header";
                header.innerHTML = `
                    <div class="color-pill" style="background:${{z.color}}"></div>
                    <span style="flex:1">${{z.nome_giro}}</span>
                    <span class="expand-btn" id="expand-${{idx}}">▼</span>
                `;
                card.appendChild(header);

                const meta = document.createElement("div");
                meta.className = "zone-meta";
                meta.textContent = `${{z.lista_punti.length}} tappe`;
                card.appendChild(meta);

                const ptContainer = document.createElement("div");
                ptContainer.className = "point-list";
                ptContainer.id = `pts-${{idx}}`;

                // Costruisci markers e lista punti
                let markers = [];
                z.lista_punti.forEach((p, i) => {{
                    if (p.lat && p.lon) {{
                        let isParziale = p.rientri_alert && Array.isArray(p.rientri_alert) && p.rientri_alert.some(r => r.is_parziale);
                        const fillColor = isParziale ? "#f59e0b" : z.color;
                        const strokeColor = isParziale ? "#000" : "white";
                        const strokeWeight = isParziale ? 3 : 2;
                        const labelColor = isParziale ? "#000" : "white";

                        const marker = new google.maps.Marker({{
                            position: {{ lat: p.lat, lng: p.lon }},
                            map: map,
                            title: p.nome,
                            icon: {{ 
                                path: google.maps.SymbolPath.CIRCLE, 
                                scale: isParziale ? 13 : 11, 
                                fillColor: fillColor, 
                                fillOpacity: 1, 
                                strokeWeight: strokeWeight, 
                                strokeColor: strokeColor 
                            }},
                            label: {{
                                text: String(i + 1),
                                color: labelColor,
                                fontWeight: "bold",
                                fontSize: "11px"
                            }}
                        }});

                        const iw = new google.maps.InfoWindow({{
                            content: `<div style="font-family:'Outfit';padding:6px;min-width:150px"><strong>${{p.nome}}</strong><br><span style="color:#64748b;font-size:12px">Giro: ${{z.nome_giro}}</span></div>`
                        }});
                        marker.addListener('click', () => iw.open(map, marker));

                        markers.push(marker);

                        const ptItem = document.createElement("div");
                        ptItem.className = "point-item";
                        ptItem.innerHTML = `<strong>${{i+1}}.</strong> ${{p.nome}}${{isParziale ? ' <span class="badge-parziale">PARZIALE</span>' : ''}}`;
                        ptContainer.appendChild(ptItem);
                    }}
                }});

                // Costruisci polylines
                let polylines = [];
                if (z._polylines && Array.isArray(z._polylines)) {{
                    z._polylines.forEach(enc => {{
                        try {{
                            const path = google.maps.geometry.encoding.decodePath(enc);
                            const poly = new google.maps.Polyline({{
                                path: path,
                                geodesic: true,
                                strokeColor: z.color || "#4f46e5",
                                strokeOpacity: 0.8,
                                strokeWeight: 4,
                                map: map
                            }});
                            polylines.push(poly);
                        }} catch (e_poly) {{
                            console.error("Errore decodifica polyline:", e_poly);
                        }}
                    }});
                }}

                card.appendChild(ptContainer);
                list.appendChild(card);
                zoneData.push({{ zone: z, markers, polylines, card, ptContainer }});

                // Click sul titolo per espandere lista punti
                header.querySelector("span").onclick = (e) => {{
                    e.stopPropagation();
                    document.getElementById("giroSelector").value = idx;
                    selezionaGiro(idx);
                }};
            }});
        }}

        window.selezionaGiro = function(val) {{
            const all = val === "__all__" || val === "" || val === null;
            const idx = all ? null : parseInt(val);
            selectedIdx = idx;

            zoneData.forEach((zd, i) => {{
                const show = all || i === idx;
                zd.markers.forEach(m => m.setMap(show ? map : null));
                zd.polylines.forEach(p => p.setMap(show ? map : null));
                zd.card.classList.toggle("active", i === idx);
                const ptsEl = document.getElementById(`pts-${{i}}`);
                const expandEl = document.getElementById(`expand-${{i}}`);
                if (i === idx) {{
                    ptsEl.style.display = "block";
                    if (expandEl) expandEl.innerHTML = "▲";
                }} else {{
                    ptsEl.style.display = "none";
                    if (expandEl) expandEl.innerHTML = "▼";
                }}
            }});

            // Zoom sulla zona selezionata
            if (!all && zoneData[idx]) {{
                const bounds = new google.maps.LatLngBounds();
                zoneData[idx].markers.forEach(m => bounds.extend(m.getPosition()));
                if (!bounds.isEmpty()) {{
                    map.fitBounds(bounds, {{ top: 60, right: 60, bottom: 60, left: 60 }});
                }}
                // Scroll alla card
                zoneData[idx].card.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }} else if (all) {{
                // Zoom su tutti i punti
                const bounds = new google.maps.LatLngBounds();
                zoneData.forEach(zd => zd.markers.forEach(m => bounds.extend(m.getPosition())));
                if (!bounds.isEmpty()) map.fitBounds(bounds);
            }}
        }};

        window.onload = initMap;
    </script>
</body>
</html>"""


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


def _ottimizza_singolo_viaggio_cloud(punti, depot_partenza, depot_arrivo, use_time_windows):
    try:
        from ortools.constraint_solver import routing_enums_pb2
        from ortools.constraint_solver import pywrapcp
    except ImportError:
        print("[OR-Tools] ortools non installato, ottimizzazione saltata.")
        return punti

    all_locs = [depot_partenza, depot_arrivo] + punti
    n = len(all_locs)
    
    errori_lista = []
    distance_matrix = _crea_matrice_distanze_cloud(all_locs, errori_lista)

    manager = pywrapcp.RoutingIndexManager(n, 1, [0], [1])
    routing = pywrapcp.RoutingModel(manager)

    def distance_callback(from_index, to_index):
        return int(distance_matrix[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)])

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)
    
    # Mantieni vive le callback in Python (anti-GC)
    routing._distance_callback = distance_callback

    solution = None
    if use_time_windows:
        try:
            def time_callback(from_index, to_index):
                from_node = manager.IndexToNode(from_index)
                to_node = manager.IndexToNode(to_index)
                dist = distance_matrix[from_node][to_node]
                travel_time = (dist / 1000.0 / 35.0) * 60
                service_time = 12 if from_node != 0 else 0
                return int(travel_time + service_time)

            time_callback_index = routing.RegisterTransitCallback(time_callback)
            routing._time_callback = time_callback
            
            routing.AddDimension(
                time_callback_index,
                30,
                1440,
                False,
                "Time"
            )
            time_dimension = routing.GetDimensionOrDie("Time")

            def parse_time_to_minutes(time_str, default_val):
                if not time_str: return default_val
                m = re.match(r"(\d{2}):(\d{2})", str(time_str).strip())
                if m:
                    return int(m.group(1)) * 60 + int(m.group(2))
                return default_val

            for i, p in enumerate(punti):
                _om = p.get("orario_min") or p.get("ora_min") or ""
                _oM = p.get("orario_max") or p.get("ora_max") or ""
                if not _om and not _oM:
                    continue
                min_min = parse_time_to_minutes(_om, 300)
                max_min = parse_time_to_minutes(_oM, 1140)
                if min_min > max_min:
                    continue
                # FIX LOGICA: i punti ottimizzabili iniziano all'indice 2 (dopo depot_partenza e depot_arrivo)
                node_index = manager.NodeToIndex(i + 2)
                time_dimension.CumulVar(node_index).SetRange(min_min, max_min)

            search_parameters = pywrapcp.DefaultRoutingSearchParameters()
            search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
            search_parameters.time_limit.seconds = 10
            solution = routing.SolveWithParameters(search_parameters)
        except Exception as e:
            print(f"[OR-Tools] Errore vincoli orari: {e}")
            solution = None

    if not use_time_windows or solution is None:
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        search_parameters.time_limit.seconds = 10
        manager2 = pywrapcp.RoutingIndexManager(n, 1, [0], [1])
        routing2 = pywrapcp.RoutingModel(manager2)
        def distance_callback_fallback(from_index, to_index):
            return int(distance_matrix[manager2.IndexToNode(from_index)][manager2.IndexToNode(to_index)])
        cb2 = routing2.RegisterTransitCallback(distance_callback_fallback)
        routing2._distance_callback_fallback = distance_callback_fallback
        routing2.SetArcCostEvaluatorOfAllVehicles(cb2)
        solution = routing2.SolveWithParameters(search_parameters)
        manager, routing = manager2, routing2

    if solution:
        percorso_ottimizzato = []
        index = routing.Start(0)
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            if node_index != 0 and node_index != 1:
                percorso_ottimizzato.append(punti[node_index - 2])
            index = solution.Value(routing.NextVar(index))
        return percorso_ottimizzato

    return punti





def core_web_calcola_percorsi(data_consegna, id_zona=None, aggiorna_traffico=False, usa_or_tools=True, tenant="DNR"):
    start_time = time.time()
    db = get_db()
    bucket = storage.bucket(name=BUCKET_NAME)
    
    path_base = f"{tenant}/REPORTS/{data_consegna}"
    blob_json = bucket.blob(f"{path_base}/viaggi_giornalieri_Johnson.json")
    if not blob_json.exists():
        return {"status": "errore", "message": f"Nessun file viaggi_giornalieri_Johnson.json trovato per il {data_consegna}."}
        
    try:
        raw_json = json.loads(blob_json.download_as_string().decode('utf-8'))
        # Retrocompatibilità: nuovo formato { "cliente": "...", "zone": [...] }
        # oppure vecchio formato diretto: [...]
        cliente_progetto = None
        if isinstance(raw_json, dict):
            zone_list = raw_json.get("zone", [])
            cliente_progetto = raw_json.get("cliente")
        else:
            zone_list = raw_json
    except Exception as e:
        return {"status": "errore", "message": f"Errore lettura JSON: {str(e)}"}
        
    calcolati = []
    modificato = False
    
    listini = {}
    try:
        try:
            tenants = [doc.id for doc in db.collection("clienti").list_documents()]
        except Exception as e:
            print(f"[calcola_percorsi] Errore lookup tenant per listini: {e}")
            tenants = ["DNR", "GRAN CHEF", "CATTEL", "BAUER", "DAC"]
            
        for cli in tenants:
            doc = db.collection("clienti").document(cli).collection("impostazioni").document("listino").get()
            if doc.exists:
                listini[cli] = doc.to_dict()
    except Exception as e:
        print(f"Errore lettura listini: {e}")
        
    magazzini_cache = {}
    try:
        mag_docs = db.collection("clienti_fatturazione").get()
        for d in mag_docs:
            c = d.to_dict()
            if "magazzini" in c:
                for idx, m in enumerate(c["magazzini"]):
                    magazzini_cache[f"{d.id}_{idx}"] = m
    except Exception as e:
        print(f"Errore lettura magazzini_cache: {e}")
    
    for zone in zone_list:
        zid = zone.get("id_zona")
        if id_zona:
            if isinstance(id_zona, list) and zid not in id_zona:
                continue
            elif isinstance(id_zona, str) and zid != id_zona:
                continue
        
        if zid in ("DDT_DA_INSERIRE", "PUNTI_DI_CONSEGNA"):
            continue
            
        cliente_zona = zone.get("cliente_zona", tenant)
        nome_giro = zone.get("nome_giro", "") or zone.get("nome_zona", "Senza Nome")
        titolo_giro = f"{cliente_zona.upper()} - {nome_giro}" if cliente_zona else f"Giro {nome_giro}"
            
        is_bloccato = zone.get("_bloccato") or zone.get("_stato") == "bloccato"
            
        punti = zone.get("lista_punti", [])
        if not punti:
            continue
            
        is_grand_chef = any("GRAND" in str(p.get("tipologia_grado") or "").upper() or "CHEF" in str(p.get("tipologia_grado") or "").upper() or "GRANCHEF" in str(p.get("zona") or "").upper() for p in punti)
        is_cattel = any("CATTEL" in str(p.get("zona") or "").upper() or "CATTEL" in str(p.get("codice_frutta") or "").upper() for p in punti)
        is_bauer = any("BAUER" in str(p.get("zona") or "").upper() or "BAUER" in str(p.get("codice_frutta") or "").upper() for p in punti)
        is_dac = any("DAC" in str(p.get("zona") or "").upper() or "DAC" in str(p.get("codice_frutta") or "").upper() for p in punti)
        
        depot_partenza = _get_depot_for_points_cloud(punti)
        depot_arrivo = depot_partenza
        
        mag_p_id = zone.get("_magazzino_partenza_id")
        if mag_p_id and mag_p_id in magazzini_cache:
            m = magazzini_cache[mag_p_id]
            depot_partenza = {"nome": m.get("nome", "Magazzino"), "lat": _safe_float(m.get("lat", 0)) or 0.0, "lon": _safe_float(m.get("lon", 0)) or 0.0}
            
        mag_a_id = zone.get("_magazzino_arrivo_id")
        if mag_a_id and mag_a_id in magazzini_cache:
            m = magazzini_cache[mag_a_id]
            depot_arrivo = {"nome": m.get("nome", "Magazzino"), "lat": _safe_float(m.get("lat", 0)) or 0.0, "lon": _safe_float(m.get("lon", 0)) or 0.0}
        
        if usa_or_tools and not is_bloccato:
            punti_ottimizzati = _ottimizza_singolo_viaggio_cloud(punti, depot_partenza, depot_arrivo, is_grand_chef or is_cattel or is_bauer or is_dac)
        else:
            punti_ottimizzati = punti
        
        punti_pieni = []
        for p in punti_ottimizzati:
            try:
                p_norm = {**p, "lat": float(p["lat"]), "lon": float(p.get("lon", p.get("lng", 0)))}
                punti_pieni.append(p_norm)
            except:
                punti_pieni.append(p)
                
        target_arr_time_str = zone.get("orario_arrivo_primo_cliente", "")
        if not target_arr_time_str:
            target_arr_time_min = 390
        else:
            m = re.match(r"(\d{2}):(\d{2})", str(target_arr_time_str).strip())
            if m:
                target_arr_time_min = int(m.group(1)) * 60 + int(m.group(2))
            else:
                target_arr_time_min = 390
                
        km, sec_guida, polylines, punti_simulati, ora_partenza_calc = _get_directions_and_simulate_cloud(punti_pieni, depot_partenza, depot_arrivo, is_grand_chef, data_consegna, aggiorna_traffico, target_arr_time_min)
        
        tot_ddt = 0
        for p in punti_simulati:
            tot_ddt += len([c for c in p.get("codici_ddt_frutta", []) if c and c != "p00000"])
            tot_ddt += len([c for c in p.get("codici_ddt_latte", []) if c and c != "p00000"])
            if not p.get("codici_ddt_frutta") and not p.get("codici_ddt_latte"):
                if p.get("codice_frutta") and p.get("codice_frutta") != "p00000": tot_ddt += 1
                if p.get("codice_latte") and p.get("codice_latte") != "p00000": tot_ddt += 1
                
        # Calcolo fatturato in base ai listini
        if is_grand_chef:
            fatturato_val = _safe_float(listini.get("GRAN CHEF", {}).get("tariffa_viaggio", 350.00)) or 350.00
            fatturato_str = f"{fatturato_val:.2f}"
        elif is_cattel:
            fatturato_val = _safe_float(listini.get("CATTEL", {}).get("tariffa_patente_b", 340.00)) or 340.00
            fatturato_str = f"{fatturato_val:.2f}"
        elif is_bauer:
            fatturato_val = _safe_float(listini.get("BAUER", {}).get("tariffa_viaggio", 390.00)) or 390.00
            fatturato_str = f"{fatturato_val:.2f}"
        elif is_dac:
            fatturato_val = _safe_float(listini.get("DAC", {}).get("tariffa_viaggio", 350.00)) or 350.00
            fatturato_str = f"{fatturato_val:.2f}"
        else:
            # DNR / Progetto Scuole (Default)
            tariffa_ddt = _safe_float(listini.get("DNR", {}).get("tariffa_ddt", 16.50)) or 16.50
            fatturato_str = f"{tot_ddt * tariffa_ddt:.2f}"
            
        stats = {
            "km": km,
            "t_guida": sec_guida // 60,
            "t_sosta": len(punti_simulati) * (12 if is_grand_chef else 8),
            "t_tot": (sec_guida // 60) + len(punti_simulati) * (12 if is_grand_chef else 8),
            "tot_ddt": tot_ddt,
            "fatturato": fatturato_str,
            "depot": depot_partenza["nome"],
            "is_gc": is_grand_chef,
            "ora_partenza": ora_partenza_calc
        }
        
        zone["lista_punti"] = punti_simulati
        zone["_polylines"] = polylines
        zone["_stats"] = stats
        zone["_stato"] = "calcolato"
        
        # Scrittura/aggiornamento deterministico in Firestore 'clienti/DNR/viaggi ddt'
        viaggio_id = f"{data_consegna}_{zid}"
        try:
            # Estrae gli ID dei DDT associati a questo viaggio
            ddt_ids = []
            for p in punti_simulati:
                for c_frutta in p.get("codici_ddt_frutta", []):
                    if c_frutta and c_frutta != "p00000":
                        ddt_ids.append(f"{data_consegna}_{c_frutta}")
                for c_latte in p.get("codici_ddt_latte", []):
                    if c_latte and c_latte != "p00000":
                        ddt_ids.append(f"{data_consegna}_{c_latte}")
            
            tenant_viaggio = get_tenant_from_viaggio_id(viaggio_id) or tenant
            doc_ref = db.collection('clienti').document(tenant_viaggio).collection('viaggi ddt').document(viaggio_id)
            
            # Preserva lo stato esistente (es. se è già completato/stampato) e i link
            existing_doc = doc_ref.get()
            current_status = "ottimizzato"
            mappa_url = ""
            distinta_url = ""
            
            # Nome dal payload frontend (che è la "fonte di verità" se modificato)
            frontend_nome = zone.get("nome_giro")
            nome_giro_da_salvare = frontend_nome if frontend_nome else zid
            
            if existing_doc.exists:
                existing_data = existing_doc.to_dict()
                current_status = existing_data.get("status", "ottimizzato")
                mappa_url = existing_data.get("mappa_url", "")
                distinta_url = existing_data.get("distinta_url", "")
                
                # Se il frontend non ha inviato un nome custom (cioè ha inviato solo zid o vuoto),
                # ma su Firestore avevamo già un nome custom, PRESERVIAMO il nome di Firestore.
                # Altrimenti vince sempre il frontend!
                existing_nome = existing_data.get("nome_giro", "")
                if existing_nome and existing_nome != zid:
                    if not frontend_nome or frontend_nome == zid:
                        nome_giro_da_salvare = existing_nome
            
            doc_ref.set({
                "id_zona": zid,
                "nome_giro": nome_giro_da_salvare,
                "cliente_zona": zone.get("cliente_zona", ""),
                "color": zone.get("color", "#4f46e5"),
                "data_lavoro": data_consegna,
                "data": data_consegna,
                "punti": punti_simulati,
                "punti_ottimizzati": punti_simulati,
                "ddt_ids": ddt_ids,
                "km_reali": km,
                "t_guida_min": sec_guida // 60,
                "t_tot_min": (sec_guida // 60) + len(punti_simulati) * (12 if is_grand_chef else 8),
                "status": "bloccato" if is_bloccato else current_status,
                "mappa_url": mappa_url,
                "distinta_url": distinta_url,
                "_stats": stats,
                "updated_at": firestore.SERVER_TIMESTAMP
            }, merge=True)
            print(f"[Firestore] Scritto viaggio {viaggio_id} con successo.")
        except Exception as e_fs:
            print(f"[Firestore ERROR] Impossibile scrivere viaggio {viaggio_id}: {e_fs}")

        # === RIGENERA HTML MAPPA AUTISTA aggiornata con nuovi orari ===
        try:
            data_viaggio_str = data_consegna.replace("/", "-")
            html_path = f"CONSEGNE/CONSEGNE_{data_viaggio_str}/MAPPE_AUTISTI/{viaggio_id}.html"
            html_mappa = _genera_html_mappa(
                titolo_giro, punti_simulati, km, sec_guida, polylines,
                depot=depot_partenza, distinta_url=distinta_url, ora_partenza_dep=ora_partenza_calc, actual_viaggio_id=viaggio_id
            )
            html_blob = bucket.blob(html_path)
            html_blob.upload_from_string(html_mappa.encode("utf-8"), content_type="text/html; charset=utf-8")
            new_mappa_url = _genera_url_storage_token(html_blob)
            doc_ref.update({"mappa_url": new_mappa_url})
            print(f"[Mappa] Rigenerata mappa autista per {viaggio_id} con partenza {ora_partenza_calc}")
        except Exception as e_map:
            print(f"[Mappa ERROR] Impossibile rigenerare mappa per {viaggio_id}: {e_map}")

        calcolati.append(zone["nome_giro"])
        modificato = True

    if modificato:
        if cliente_progetto:
            payload_da_salvare = {
                "cliente": cliente_progetto,
                "zone": zone_list
            }
        else:
            payload_da_salvare = zone_list
        blob_json.upload_from_string(json.dumps(payload_da_salvare, indent=2), content_type='application/json')
        
    # === GHOST TRIP CLEANUP ===
    try:
        active_viaggio_ids = {f"{data_consegna}_{z.get('id_zona')}" for z in zone_list if z.get('id_zona')}
        viaggi_ref = db.collection('clienti').document(tenant).collection('viaggi ddt')
        query_viaggi = viaggi_ref.where('data_lavoro', '==', data_consegna).stream()
        for doc in query_viaggi:
            if doc.id not in active_viaggio_ids:
                print(f"[Ghost Cleanup] Eliminazione viaggio fantasma: {doc.id}")
                doc.reference.delete()
    except Exception as cleanup_err:
        print(f"[Ghost Cleanup] Errore durante la pulizia dei viaggi fantasma: {cleanup_err}")
        
    elapsed = time.time() - start_time
    return {
        "status": "ok",
        "message": f"Calcolati percorsi per: {', '.join(calcolati)} in {elapsed:.2f}s",
        "tempo_sec": elapsed,
        "calcolati": calcolati
    }

def _normalizza_unita(u: str) -> str:
    u = u.strip().lower()
    mapping = {
        "bottiglia": "Bottiglie", "bottiglie": "Bottiglie",
        "fardello": "Fardelli",   "fardelli": "Fardelli",
        "cartone": "Cartoni",     "cartoni": "Cartoni",
        "cluster": "Cluster",
        "porzione": "Porzioni",   "porzioni": "Porzioni",
        "collo": "Colli",         "colli": "Colli",
        "fetta": "Fette",         "fette": "Fette",
        "brick": "Brick",
        "confezione": "Confezioni", "confezioni": "Confezioni",
        "manifesto": "Manifesti", "manifesti": "Manifesti",
        "fascetta": "Fascette",
        "busta": "Buste",         "buste": "Buste",
        "pz": "pz"
    }
    return mapping.get(u, u.title() if u else u)

def _parse_quantita_da_cella(cell) -> list:
    if not cell or not str(cell).strip():
        return []
    text = str(cell).replace("\n", " ").replace("  ", " ")
    quantita = []
    for m in re.finditer(r"(?:^|e\s+)(\d+)\s+(" + UNITA_QTY + r")", text, re.I):
        quantita.append((int(m.group(1)), _normalizza_unita(m.group(2))))
    if not quantita and re.search(r"^(\d+)\s*$", text.strip()):
        quantita.append((int(text.strip()), "pz"))
    return quantita

def _is_primary_code(text, articoli_noti):
    if not text: return False
    text = text.strip().upper()
    if text in articoli_noti: return True
    for prefix in articoli_noti:
        if prefix.endswith('-') and text.startswith(prefix):
            return True
    return bool(re.match(r'^([A-Z0-9]{2,}-[A-Z0-9\-]+|--\d{6})', text))

def _normalizza_cella_codice(raw, articoli_noti):
    righe = [l.strip() for l in raw.split('\n')
             if l.strip() and not l.strip().startswith("Codice:")]
    if not righe:
        return "", ""
    codice_base = ""
    idx_base = -1
    for i, riga in enumerate(righe):
        if _is_primary_code(riga, articoli_noti):
            codice_base = riga.strip()
            idx_base = i
            break
    if not codice_base:
        codice_base = righe[0]
        idx_base = 0
    if codice_base.endswith('-') and len(righe) > idx_base + 1:
        pezzi = righe[idx_base + 1].split()
        if pezzi:
            codice_base += pezzi[0]
            righe[idx_base + 1] = " ".join(pezzi[1:]).strip()
    righe_variante = [r for r in righe[idx_base + 1:] if r.strip()]
    variante_raw = " ".join(righe_variante).strip()
    variante_raw = re.sub(r'\s+', ' ', variante_raw)
    variante_raw = re.sub(r'-{2,}', '-', variante_raw).strip('-').strip()
    return codice_base, variante_raw

def _estrai_articoli_da_tabella_cloud(pdf_bytes, articoli_noti):
    import pdfplumber
    import io
    from decimal import Decimal
    
    risultato = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if not tables: continue
            tab = next((t for t in tables if t and len(t) > 1
                        and "Cod. Articolo" in " ".join(str(c or "") for c in t[0])), None)
            if not tab: continue
            
            for row in tab[1:]:
                if not row or len(row) < 4: continue
                raw_codice = str(row[0] or "").strip()
                if not raw_codice: continue
                
                codice_base, variante_raw = _normalizza_cella_codice(raw_codice, articoli_noti)
                if not codice_base: continue
                
                descrizione = re.sub(r'\s+', ' ', str(row[1] or "").replace('\n', ' ')).strip()
                try:
                    kg = Decimal(str(row[2] or "0").replace(",", ".").strip() or "0")
                except:
                    kg = Decimal("0")
                    
                quantita_raw = str(row[3] or "").strip()
                quantita = _parse_quantita_da_cella(quantita_raw)
                
                if not quantita and "10-GEL" in codice_base:
                    porz = str(row[4] or "").strip() if len(row) > 4 else ""
                    if porz.isdigit():
                        quantita = [(int(porz), "pz")]
                        
                if not quantita: continue
                
                confezionamento = str(row[5] or "").strip() if len(row) > 5 else ""
                
                risultato.append({
                    "codice_base": codice_base,
                    "variante_raw": variante_raw,
                    "descrizione": descrizione,
                    "kg": kg,
                    "quantita": quantita,
                    "confezionamento": confezionamento
                })
    return risultato

def _consolida_quantita_cloud(codice, lista_qty):
    if codice not in CONSOLIDAMENTO:
        by_unit = defaultdict(int)
        for qty, unit in lista_qty:
            by_unit[_normalizza_unita(unit)] += qty
        result = [(v, k) for k, v in sorted(by_unit.items()) if v > 0]
        return result, " e ".join(f"{q} {u}" for q, u in result)

    unit_princ, unit_second, ratio = CONSOLIDAMENTO[codice]
    tot_princ = tot_second = 0
    for qty, unit in lista_qty:
        ul = unit.lower()
        if unit_princ.lower() in ul or ul in ("fardello", "fardelli", "cartoni", "cartone",
                                               "brick", "colli", "confezioni", "manifesti", "fascette"):
            tot_princ += qty
        else:
            tot_second += qty

    extra_princ   = tot_second // ratio
    resto_second  = tot_second % ratio
    tot_princ    += extra_princ

    result = []
    if tot_princ > 0:
        result.append((tot_princ, unit_princ))
    if resto_second > 0:
        result.append((resto_second, unit_second))
    display = " e ".join(f"{q} {u}" for q, u in result)
    return result, display

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

def _genera_pagina_riepilogo_zone_cloud(viaggi, data_ddt, pdf_non_trovati=None):
    if pdf_non_trovati is None: pdf_non_trovati = []
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    def _zona_valida(z: str) -> bool:
        return len(z.strip()) >= 2

    def _zona_base(z: str) -> str:
        z = z.strip()
        z = re.sub(r'^[^0-9]+', '', z)
        z = re.sub(r'[^0-9]+$', '', z)
        return z

    tutte_le_zone = set()
    giri_con_zone = []
    for v in viaggi:
        zone_v = [z for z in v.get("zone", []) if _zona_valida(z)]
        if not zone_v:
            zid = v.get("id_zona", "")
            if _zona_valida(zid):
                zone_v = [zid]
        nome_v = v.get("nome_giro", "?")
        giri_con_zone.append((nome_v, zone_v))
        tutte_le_zone.update(_zona_base(z) for z in zone_v if _zona_base(z))

    out_stream = io.BytesIO()
    try:
        doc = SimpleDocTemplate(
            out_stream, pagesize=A4,
            leftMargin=20*mm, rightMargin=20*mm,
            topMargin=20*mm, bottomMargin=20*mm
        )
        styles = getSampleStyleSheet()
        st_titolo = ParagraphStyle("zt_c", parent=styles["Heading1"], fontSize=16, spaceAfter=6)
        st_sub    = ParagraphStyle("zs_c", parent=styles["Normal"],   fontSize=10, spaceAfter=4,
                                   textColor=colors.HexColor("#475569"))
        st_zona   = ParagraphStyle("zz_c", parent=styles["Normal"],   fontSize=16,
                                   spaceBefore=6, spaceAfter=6,
                                   leading=22,
                                   textColor=colors.HexColor("#1e293b"),
                                   fontName="Helvetica-Bold")
        st_err    = ParagraphStyle("zerr_c", parent=styles["Normal"], fontSize=12,
                                   spaceBefore=2, spaceAfter=2, textColor=colors.red, fontName="Helvetica-Bold")

        elementi = []
        elementi.append(Paragraph(f"RIEPILOGO ZONE — {data_ddt}", st_titolo))
        
        if pdf_non_trovati:
            elementi.append(Paragraph("ATTENZIONE - DDT MANCANTI:", ParagraphStyle("zerr_tit_c", parent=st_err, fontSize=14)))
            for err in pdf_non_trovati:
                elementi.append(Paragraph(f"&#x25cf; {err}", st_err))
            elementi.append(Spacer(1, 8*mm))
            
        elementi.append(Paragraph("Zone coperte da tutti i giri di oggi:", st_sub))
        elementi.append(Spacer(1, 8*mm))

        for zona in sorted(tutte_le_zone):
            elementi.append(Paragraph(f"&#x25cf;  {zona}", st_zona))

        elementi.append(Spacer(1, 12*mm))
        elementi.append(Paragraph("— Dettaglio per giro:", st_sub))
        elementi.append(Spacer(1, 4*mm))

        dati_tab = [["Giro", "Zone"]]
        for nome_v, zone_v in giri_con_zone:
            zone_display = ", ".join(sorted(zone_v)) if zone_v else "—"
            dati_tab.append([nome_v, zone_display])

        ts = TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  colors.HexColor("#1e293b")),
            ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
            ("FONTSIZE",       (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("GRID",           (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("LEFTPADDING",    (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 6),
            ("TOPPADDING",     (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ])
        t = Table(dati_tab, colWidths=[70*mm, 100*mm])
        t.setStyle(ts)
        elementi.append(t)

        doc.build(elementi)
        out_stream.seek(0)
        return out_stream.getvalue()
    except Exception as e:
        print(f"[RIEPILOGO] Errore: {e}")
        return None

def _blocco_distinta_cloud(viaggio, articoli_viaggio, data_ddt, copia, n_ddt_totali=0, rientri_giro=None, pdf_non_trovati_giro=None):
    if rientri_giro is None: rientri_giro = []
    if pdf_non_trovati_giro is None: pdf_non_trovati_giro = []
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet
    
    styles = getSampleStyleSheet()
    st_titolo = ParagraphStyle("titolo_c", parent=styles["Heading1"], fontSize=14, spaceAfter=3)
    st_sub    = ParagraphStyle("sub_c",    parent=styles["Normal"],   fontSize=9,  spaceAfter=2)
    st_body   = ParagraphStyle("body_c_l", parent=styles["Normal"],   fontSize=8,  leading=9)
    st_warn   = ParagraphStyle("warn_c",   parent=styles["Normal"],   fontSize=8, textColor=colors.red)

    nome_giro = viaggio.get("nome_giro", "Sconosciuto")
    cliente_zona = viaggio.get("cliente_zona", "")
    if cliente_zona and cliente_zona.upper() not in nome_giro.upper():
        nome_giro_stampato = f"{cliente_zona.upper()} - {nome_giro}"
    else:
        nome_giro_stampato = nome_giro
        
    zone_list = viaggio.get("zone", [])
    if not isinstance(zone_list, list):
        zone_list = [viaggio.get("id_zona", "")]
    zone = ", ".join(zone_list)
    n_fermate = len(viaggio.get("lista_punti", []))
    label = f"{'COPIA AUTISTA' if copia == 1 else 'COPIA UFFICIO'}"
    elementi = []

    elementi.append(Paragraph(f"DISTINTA DI CARICO - {nome_giro_stampato}  [{label}]", st_titolo))
    elementi.append(Paragraph(f"Zone: {zone}  |  Fermate Totali: {n_fermate}  |  DDT Totali: {n_ddt_totali}  |  Data: {data_ddt}", st_sub))
    
    if rientri_giro:
        visti = set()
        normali = []
        parziali = []
        for r in rientri_giro:
            k = f"{r['codice']} ({r['data_ddt']})"
            if k not in visti:
                visti.add(k)
                if r.get("is_parziale"):
                    parziali.append(r)
                else:
                    normali.append(k)
        
        if normali:
            normali.sort()
            riga2 = f"<font color='red'><b>DDT da Rientri:</b></font> {', '.join(normali)} <font color='gray'><i>(merce già in distinta di carico)</i></font>"
            elementi.append(Paragraph(riga2, st_sub))
            
        if parziali:
            for p in sorted(parziali, key=lambda x: x["codice"]):
                r_parz = f"<font color='red'><b>DDT da rientri con merce:</b></font> {p['codice']} ({p['data_ddt']})"
                elementi.append(Paragraph(r_parz, st_sub))
                elementi.append(Paragraph("<i>Merce non presente nella distinta di carico, procedere con la presa manuale come da nota integrativa:</i>", st_sub))
                if p.get("nota_integrativa"):
                    elementi.append(Paragraph(f"<b>NOTA:</b> {p['nota_integrativa']}", st_sub))
                elementi.append(Spacer(1, 2*mm))
                
    if pdf_non_trovati_giro:
        elementi.append(Spacer(1, 2*mm))
        for err in pdf_non_trovati_giro:
            elementi.append(Paragraph(f"<b>ATTENZIONE: {err}</b>", st_warn))
            
    elementi.append(Spacer(1, 4*mm))

    elementi.append(Paragraph("RIEPILOGO ARTICOLI DA CARICARE PER GIRO:", st_body))
    dati_art = [["Codice Articolo", "Descrizione Natura Qualità", "Quantità Consolidata", "Confezionamento"]]
    
    for chiave, art in sorted(articoli_viaggio.items(), key=lambda x: (x[0][0], x[0][1])):
        _, display = _consolida_quantita_cloud(art["codice_base"], art["quantita"])
        variante = art.get("variante_raw", "")
        codice_stampato = f"{art['codice_base']} {variante}".strip() if variante else art["codice_base"]

        dati_art.append([
            Paragraph(codice_stampato, st_body),
            Paragraph(art.get("descrizione", ""), st_body),
            Paragraph(display or "—", st_body),
            Paragraph(art.get("confezionamento", "") or "—", st_body),
        ])
        
    ts_art = TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  colors.HexColor("#10b981")),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTSIZE",       (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0fdf4")]),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("LEFTPADDING",    (0, 0), (-1, -1), 2*mm),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 5*mm),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
    ])
    t_art = Table(dati_art, colWidths=[35*mm, 75*mm, 35*mm, 35*mm])
    t_art.setStyle(ts_art)
    elementi.append(t_art)
    elementi.append(Spacer(1, 10*mm))

    elementi.append(Paragraph("ORDINE DI CONSEGNA (Fermata 1 = Prima consegna):", st_body))
    fermate = viaggio.get("lista_punti", [])

    st_body_c = ParagraphStyle("body_c_c", parent=styles["Normal"], fontSize=8, leading=9, alignment=1)
    st_body_r = ParagraphStyle("body_r_c", parent=styles["Normal"], fontSize=8, leading=9, alignment=2)
    st_bold   = ParagraphStyle("bold_c",   parent=styles["Normal"], fontSize=8, leading=9, fontName="Helvetica-Bold")

    dati_fermate = [["#", "Cod. F", "Cod. L", "Nome", "Indirizzo", "Kg", "Colli", "N°Cart."]]
    ts_gc_rows = []
    tot_kg = 0.0
    tot_colli = 0

    for idx, f in enumerate(fermate, 1):
        cf = f.get("codice_frutta", "") or ""
        cl = f.get("codice_latte",  "") or ""
        is_gc = ("GRAND CHEF" in str(f.get("tipologia_grado", "")).upper()
                 or "GRAN CHEF" in str(f.get("tipologia_grado", "")).upper()
                 or str(f.get("zona", "")).startswith("GranChef"))

        if is_gc:
            kg_raw = f.get("gc_peso_kg", "")
            col_raw = f.get("gc_colli", "")
            car_raw = f.get("gc_num_cartone", "")
            kg_str = str(kg_raw).strip() if kg_raw not in (None, "", "None") else ""
            col_str = str(int(float(col_raw))) if col_raw not in (None, "", "None") else ""
            car_str = str(car_raw).strip() if car_raw not in (None, "", "None") else ""
            try: tot_kg += float(kg_raw) if kg_raw not in (None, "", "None") else 0
            except: pass
            try: tot_colli += int(float(col_raw)) if col_raw not in (None, "", "None") else 0
            except: pass
            ts_gc_rows.append(("BACKGROUND", (5, idx), (7, idx), colors.HexColor("#fffbeb")))
        else:
            kg_str = col_str = car_str = ""

        dati_fermate.append([
            Paragraph(str(idx), st_body),
            Paragraph(cf if cf != "p00000" else "—", st_body),
            Paragraph(cl if cl != "p00000" else "—", st_body),
            Paragraph(f.get("nome", ""), st_body),
            Paragraph(f.get("indirizzo", ""), st_body),
            Paragraph(kg_str,  st_body_r),
            Paragraph(col_str, st_body_c),
            Paragraph(car_str, st_body_c),
        ])

    if tot_kg > 0 or tot_colli > 0:
        kg_tot_str  = f"{tot_kg:.2f}" if tot_kg  > 0 else ""
        col_tot_str = str(tot_colli)  if tot_colli > 0 else ""
        dati_fermate.append([
            Paragraph("", st_body),
            Paragraph("", st_body),
            Paragraph("", st_body),
            Paragraph("", st_body),
            Paragraph("TOTALE GIRO", st_bold),
            Paragraph(kg_tot_str,  st_bold),
            Paragraph(col_tot_str, st_bold),
            Paragraph("", st_body),
        ])
        ts_gc_rows.append(("BACKGROUND", (0, len(dati_fermate)-1), (-1, len(dati_fermate)-1), colors.HexColor("#fef3c7")))
        ts_gc_rows.append(("FONTNAME",   (0, len(dati_fermate)-1), (-1, len(dati_fermate)-1), "Helvetica-Bold"))

    ts_fermate = TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  colors.HexColor("#1e293b")),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  colors.white),
        ("FONTSIZE",       (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID",           (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("LEFTPADDING",    (0, 0), (-1, -1), 2*mm),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 2*mm),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("ALIGN",          (5, 0), (7, -1),  "CENTER"),
    ] + ts_gc_rows)
    
    t_fermate = Table(dati_fermate, colWidths=[10*mm, 18*mm, 18*mm, 45*mm, 56*mm, 16*mm, 14*mm, 14*mm])
    t_fermate.setStyle(ts_fermate)
    elementi.append(t_fermate)

    return elementi

def _genera_distinta_pdf_cloud(viaggio, articoli_viaggio, data_ddt, pdf_ddt_streams, rientri_giro=None, pdf_non_trovati_giro=None):
    import tempfile, os
    from reportlab.platypus import SimpleDocTemplate, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import mm
    from reportlab.lib.pagesizes import A4
    from pypdf import PdfWriter, PdfReader

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(tmp_fd)

    try:
        doc = SimpleDocTemplate(
            tmp_path, pagesize=A4,
            leftMargin=15*mm, rightMargin=15*mm,
            topMargin=15*mm, bottomMargin=15*mm
        )
        styles = getSampleStyleSheet()
        elementi = []
        
        elementi += _blocco_distinta_cloud(viaggio, articoli_viaggio, data_ddt, 1, len(pdf_ddt_streams), rientri_giro, pdf_non_trovati_giro)
        elementi.append(PageBreak())
        elementi += _blocco_distinta_cloud(viaggio, articoli_viaggio, data_ddt, 2, len(pdf_ddt_streams), rientri_giro, pdf_non_trovati_giro)
        
        doc.build(elementi)

        reader_tmp = PdfReader(tmp_path)
        n_tot = len(reader_tmp.pages)
        n_per_copia = n_tot // 2

        writer_light = PdfWriter()
        for i in range(n_per_copia):
            writer_light.add_page(reader_tmp.pages[i])
        
        light_stream = io.BytesIO()
        writer_light.write(light_stream)
        light_stream.seek(0)

        writer_full = PdfWriter()
        for i in range(n_per_copia):
            writer_full.add_page(reader_tmp.pages[i])
        for i in range(n_per_copia, n_tot):
            writer_full.add_page(reader_tmp.pages[i])

        for pdf_name, pdf_bytes in pdf_ddt_streams:
            is_gc_pdf = pdf_name.startswith("100") or any(x in pdf_name.lower() for x in ("chef", "grand", "gran"))
            ddt_reader = PdfReader(io.BytesIO(pdf_bytes))
            if is_gc_pdf:
                for page in ddt_reader.pages:
                    writer_full.add_page(page)
            else:
                for page in ddt_reader.pages:
                    writer_full.add_page(page)
                for page in ddt_reader.pages:
                    writer_full.add_page(page)

        full_stream = io.BytesIO()
        writer_full.write(full_stream)
        full_stream.seek(0)

        return full_stream, light_stream
    except Exception as e:
        print(f"[DISTINTA] Errore assemblaggio: {e}")
        # Fallback a un PDF minimo se fallisce
        shutil_stream = io.BytesIO()
        with open(tmp_path, "rb") as f_tmp:
            shutil_stream.write(f_tmp.read())
        shutil_stream.seek(0)
        return shutil_stream, shutil_stream
    finally:
        try: os.unlink(tmp_path)
        except: pass

def core_genera_completo_giornata(data_consegna, tenant="DNR"):
    if not tenant or not isinstance(tenant, str):
        raise ValueError("Tenant mancante o non valido in core_genera_completo_giornata")
    start_time = time.time()
    db = get_db()
    bucket = storage.bucket(name=BUCKET_NAME)
    
    path_base = f"REPORTS/{data_consegna}"
    blob_json = bucket.blob(f"{path_base}/viaggi_giornalieri_Johnson.json")
    if not blob_json.exists():
        return {"status": "errore", "message": f"Nessun file viaggi_giornalieri_Johnson.json trovato per il {data_consegna}."}
        
    try:
        raw_json = json.loads(blob_json.download_as_string().decode('utf-8'))
        if isinstance(raw_json, dict):
            zone_list = raw_json.get("zone", [])
            cliente_progetto = raw_json.get("cliente")
        else:
            zone_list = raw_json
    except Exception as e:
        return {"status": "errore", "message": f"Errore lettura JSON: {str(e)}"}
        
    deliveries_all = []
    prefix_search = f"split_ddt/{data_consegna}/"
    try:
        blobs = bucket.list_blobs(prefix=prefix_search)
        for blob in blobs:
            if "ddt_estratti" in blob.name and blob.name.endswith(".json"):
                try:
                    meta_data = json.loads(blob.download_as_string().decode('utf-8'))
                    deliveries_all.extend(meta_data.get("deliveries", []))
                except Exception as e_meta:
                    print(f"[METADATA] Errore lettura {blob.name}: {e_meta}")
    except Exception as e_list:
        print(f"[METADATA] Errore scansione storage: {e_list}")

    articoli_noti, config_cons = get_config_app()
    
    rientri_list = []
    try:
        for doc in db.collection('clienti').document('DNR').collection('rientri ddt').stream():
            r_data = doc.to_dict() or {}
            r_cod = str(r_data.get('codice_consegna') or r_data.get('Codice consegna') or '').strip()
            r_data_ddt = r_data.get('data_ddt') or r_data.get('Data e Num DDT') or ''
            stato = str(r_data.get('stato') or r_data.get('Stato') or '').strip().lower()
            if data_consegna in stato or f"ddt {data_consegna}" in stato:
                rientri_list.append({
                    "codice": r_cod,
                    "data_ddt": r_data_ddt,
                    "is_parziale": bool(r_data.get('is_parziale') or False) or (str(r_data.get('Tipo') or r_data.get('tipo') or '').lower().strip() == 'parziale'),
                    "nota_integrativa": str(r_data.get('note') or r_data.get('Note') or r_data.get('nota_integrativa') or '').strip()
                })
    except Exception as e_r:
        print(f"[RIENTRI] Errore recupero: {e_r}")

    links = []
    pdf_non_trovati_giorno = []
    
    for zone in zone_list:
        zid = zone.get("id_zona")
        if zid in ("DDT_DA_INSERIRE", "PUNTI_DI_CONSEGNA"):
            continue
            
        punti = zone.get("lista_punti", [])
        if not punti:
            continue
            
        nome_giro = zone.get("nome_giro", "?")
        
        pdf_ddt_streams = []
        pdf_non_trovati_giro = []
        articoli_viaggio = defaultdict(lambda: {"codice_base": "", "variante_raw": "", "descrizione": "", "quantita": [], "confezionamento": ""})
        
        for p in punti:
            cf = str(p.get("codice_frutta", "")).strip().lower()
            cd_frutta = p.get("codici_ddt_frutta", [])
            
            cl = str(p.get("codice_latte", "")).strip().lower()
            cd_latte = p.get("codici_ddt_latte", [])
            
            ddt_trovati = []
            if cf and cf != "p00000":
                if cd_frutta:
                    for num in cd_frutta:
                        match = next((d for d in deliveries_all if str(d.get("codice_consegna")).strip().lower() == cf and str(d.get("num_ddt")).strip() == str(num)), None)
                        if match: ddt_trovati.append(match)
                else:
                    match = next((d for d in deliveries_all if str(d.get("codice_consegna")).strip().lower() == cf and d.get("tipo") in ("FRUTTA", "GRAND_CHEF", "DAC")), None)
                    if match: ddt_trovati.append(match)
                    
            if cl and cl != "p00000":
                if cd_latte:
                    for num in cd_latte:
                        match = next((d for d in deliveries_all if str(d.get("codice_consegna")).strip().lower() == cl and str(d.get("num_ddt")).strip() == str(num)), None)
                        if match: ddt_trovati.append(match)
                else:
                    match = next((d for d in deliveries_all if str(d.get("codice_consegna")).strip().lower() == cl and d.get("tipo") in ("LATTE", "GRAND_CHEF", "DAC")), None)
                    if match: ddt_trovati.append(match)

            for ddt in ddt_trovati:
                tipo_ddt = ddt.get("tipo")
                pdf_name = ddt.get("pdf_name")
                storage_path = f"split_ddt/{data_consegna}/{tipo_ddt}/{pdf_name}"
                blob_ddt = bucket.blob(storage_path)
                if blob_ddt.exists():
                    try:
                        pdf_bytes = blob_ddt.download_as_bytes()
                        pdf_ddt_streams.append((pdf_name, pdf_bytes))
                        art_estrai = _estrai_articoli_da_tabella_cloud(pdf_bytes, articoli_noti)
                        for art in art_estrai:
                            key = (art["codice_base"], art["variante_raw"])
                            articoli_viaggio[key]["codice_base"] = art["codice_base"]
                            articoli_viaggio[key]["variante_raw"] = art["variante_raw"]
                            articoli_viaggio[key]["descrizione"] = art["descrizione"]
                            articoli_viaggio[key]["quantita"].extend(art["quantita"])
                            if art["confezionamento"]:
                                articoli_viaggio[key]["confezionamento"] = art["confezionamento"]
                    except Exception as e_pdf:
                        msg = f"Errore lettura {pdf_name}: {e_pdf}"
                        pdf_non_trovati_giro.append(msg)
                        pdf_non_trovati_giorno.append(f"{nome_giro}: {msg}")
                else:
                    msg = f"DDT PDF mancante nello Storage: {pdf_name}"
                    pdf_non_trovati_giro.append(msg)
                    pdf_non_trovati_giorno.append(f"{nome_giro}: {msg}")

        punti_codici = {str(p.get("codice_frutta") or "").strip().lower(), str(p.get("codice_latte") or "").strip().lower()}
        rientri_giro = [r for r in rientri_list if r["codice"].strip().lower() in punti_codici]

        full_stream, light_stream = _genera_distinta_pdf_cloud(zone, articoli_viaggio, data_consegna, pdf_ddt_streams, rientri_giro, pdf_non_trovati_giro)
        
        viaggio_id = f"{data_consegna}_{zid}"
        tenant_viaggio = get_tenant_from_viaggio_id(viaggio_id) or tenant
        tenant_folder = tenant_viaggio.upper().replace(" ", "_")
        
        full_blob = bucket.blob(f"{tenant_folder}/REPORTS/{data_consegna}/DISTINTE_VIAGGIO/DISTINTA_{nome_giro}.pdf")
        if full_blob.exists():
            full_blob.delete()
        full_blob.upload_from_file(full_stream, content_type="application/pdf")
        distinta_completa_url = _genera_url_storage_token(full_blob)
        
        light_blob = bucket.blob(f"{tenant_folder}/REPORTS/{data_consegna}/DISTINTE_VIAGGIO/DISTINTA_LIGHT_{nome_giro}.pdf")
        if light_blob.exists():
            light_blob.delete()
        light_blob.upload_from_file(light_stream, content_type="application/pdf")
        distinta_light_url = _genera_url_storage_token(light_blob)

        # Salva i link direttamente nel documento del viaggio
        doc_ref = get_db().collection('clienti').document(tenant_viaggio).collection('viaggi ddt').document(viaggio_id)
        try:
            doc_ref.set({
                "distinta_light": distinta_light_url,
                "distinta_completa": distinta_completa_url,
                "_stats": zone.get("_stats", {})
            }, merge=True)
        except Exception as e_fs:
            print(f"[ERROR] Impossibile aggiornare Firestore per {viaggio_id}: {e_fs}")

        km = zone.get("_stats", {}).get("km", 0.0)
        sec_guida = zone.get("_stats", {}).get("t_guida", 0) * 60
        polylines = zone.get("_polylines", [])
        
        punti_html = []
        for p in punti:
            try:
                punti_html.append({**p, "lat": float(p["lat"]), "lon": float(p.get("lon", p.get("lng", 0)))})
            except:
                punti_html.append(p)
                
        depot = _get_depot_for_points_cloud(punti_html)
        ora_partenza_calc = zone.get("_stats", {}).get("ora_partenza", "07:00")
        
        cliente_zona = zone.get("cliente_zona", "")
        if cliente_zona and cliente_zona.upper() not in nome_giro.upper():
            titolo_giro = f"{cliente_zona.upper()} - {nome_giro}"
        else:
            titolo_giro = f"Giro {nome_giro}"
            
        html_map_content = _genera_html_mappa(titolo_giro, punti_html, km, sec_guida, polylines, depot=depot, distinta_url=distinta_light_url, ora_partenza_dep=ora_partenza_calc)
        
        map_blob = bucket.blob(f"{path_base}/MAPPE_AUTISTI/{nome_giro}.html")
        map_blob.upload_from_string(html_map_content.encode('utf-8'), content_type="text/html; charset=utf-8")
        map_url = _genera_url_storage_token(map_blob)

        links.append({
            "v_id": nome_giro,
            "titolo_giro": titolo_giro,
            "date": data_consegna,
            "url": map_url,
            "zones": zone.get("zone", [zone.get("id_zona", "?")]),
            "distinta_light": distinta_light_url,
            "distinta_completa": distinta_completa_url
        })

    # Master PDF
    master_distinte_url = None
    try:
        from pypdf import PdfWriter
        riepilogo_zone_pdf = _genera_pagina_riepilogo_zone_cloud(zone_list, data_consegna, pdf_non_trovati_giorno)
        
        master_writer = PdfWriter()
        if riepilogo_zone_pdf:
            master_writer.append(io.BytesIO(riepilogo_zone_pdf))
            
        for zone in zone_list:
            zid = zone.get("id_zona")
            if zid in ("DDT_DA_INSERIRE", "PUNTI_DI_CONSEGNA"): continue
            nome_giro = zone.get("nome_giro")
            giro_blob = bucket.blob(f"{path_base}/DISTINTE_VIAGGIO/DISTINTA_{nome_giro}.pdf")
            if giro_blob.exists():
                master_writer.append(io.BytesIO(giro_blob.download_as_bytes()))
                
        master_stream = io.BytesIO()
        master_writer.write(master_stream)
        master_stream.seek(0)
        
        master_blob = bucket.blob(f"{path_base}/MASTER_DISTINTE_{data_consegna}.pdf")
        if master_blob.exists():
            master_blob.delete()
        master_blob.upload_from_file(master_stream, content_type="application/pdf")
        master_distinte_url = _genera_url_storage_token(master_blob)
        print(f"[MASTER] Generato MASTER_DISTINTE_{data_consegna}.pdf con successo.")
    except Exception as e_master:
        print(f"[MASTER] Errore assemblaggio: {e_master}")

    whatsapp_lines = [f"{l.get('titolo_giro', 'Giro ' + l['v_id'])} - Mappa: {l['url']}" for l in links]
    whatsapp_txt = "\n".join(whatsapp_lines)
    bucket.blob(f"{path_base}/LINK_WHATSAPP_AUTISTI.txt").upload_from_string(whatsapp_txt.encode('utf-8'), content_type="text/plain; charset=utf-8")

    manifest_data = {
        "date": data_consegna,
        "links": links
    }
    if master_distinte_url:
        manifest_data["master_distinte_url"] = master_distinte_url
    bucket.blob(f"{path_base}/manifest_link_viaggi.json").upload_from_string(json.dumps(manifest_data, indent=2), content_type='application/json')

    punti_totali = sum(len(z.get("lista_punti", [])) for z in zone_list if z.get("id_zona") not in ("DDT_DA_INSERIRE", "PUNTI_DI_CONSEGNA"))
    zone_totali = len([z for z in zone_list if z.get("id_zona") not in ("DDT_DA_INSERIRE", "PUNTI_DI_CONSEGNA")])

    # === MAPPA GENERALE con selettore giri ===
    mappa_generale_url = ""
    try:
        zone_per_mappa = []
        for z in zone_list:
            if z.get("id_zona") not in ("DDT_DA_INSERIRE", "PUNTI_DI_CONSEGNA"):
                c = z.get("cliente_zona", "")
                n = z.get("nome_giro") or z.get("id_zona", "?")
                if c and c.upper() not in n.upper():
                    n = f"{c.upper()} - {n}"
                zone_per_mappa.append({
                    "nome_giro": n,
                    "color": z.get("color", "#4f46e5"),
                    "_polylines": z.get("_polylines", []),
                    "lista_punti": [
                        {**p, "lat": _safe_float(p.get("lat")), "lon": _safe_float(p.get("lon", p.get("lng", 0)))}
                        for p in z.get("lista_punti", []) if _safe_float(p.get("lat")) is not None
                    ]
                })
        html_mappa_gen = _genera_html_mappa_generale(data_consegna, zone_per_mappa)
        mappa_gen_blob = bucket.blob(f"{path_base}/MAPPA_GENERALE_{data_consegna}.html")
        mappa_gen_blob.upload_from_string(html_mappa_gen.encode("utf-8"), content_type="text/html; charset=utf-8")
        mappa_generale_url = _genera_url_storage_token(mappa_gen_blob)
        print(f"[MAPPA GENERALE] Generata con {len(zone_per_mappa)} giri.")
    except Exception as e_mg:
        print(f"[MAPPA GENERALE ERROR] {e_mg}")
        mappa_generale_url = links[0]["url"] if links else ""

    report_meta = {
        "data_consegna": data_consegna,
        "punti_totali": punti_totali,
        "zone_totali": zone_totali,
        "mappa_url": mappa_generale_url,
        "created_at": firestore.SERVER_TIMESTAMP,
        "tipo": "REPORT_GENERALE"
    }
    db.collection('clienti').document('report_logistici').collection('giornate').document(data_consegna).set(report_meta)

    # === GHOST TRIP CLEANUP ===
    try:
        active_viaggio_ids = {f"{data_consegna}_{z.get('id_zona')}" for z in zone_list if z.get('id_zona') and z.get('id_zona') not in ("DDT_DA_INSERIRE", "PUNTI_DI_CONSEGNA")}
        try:
            tenants = [doc.id for doc in db.collection('clienti').list_documents() if doc.id != "report_logistici"]
        except:
            tenants = ["DNR", "CATTEL", "GRAN CHEF", "BAUER", "DAC"]
        for t in tenants:
            viaggi_ref = db.collection('clienti').document(t).collection('viaggi ddt')
            query_viaggi = viaggi_ref.where('data_lavoro', '==', data_consegna).stream()
            for doc in query_viaggi:
                if doc.id not in active_viaggio_ids:
                    print(f"[Ghost Cleanup] Eliminazione viaggio svuotato/cancellato da {t}: {doc.id}")
                    doc.reference.delete()
    except Exception as cleanup_err:
        print(f"[Ghost Cleanup] Errore durante la pulizia dei viaggi vuoti: {cleanup_err}")

    elapsed = time.time() - start_time
    _registra_statistica("genera_completo_giornata", elapsed)

    return {
        "status": "ok",
        "message": f"Pipeline completata in {elapsed:.2f}s per {zone_totali} giri.",
        "tempo_sec": elapsed,
        "giri": zone_totali
    }

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
    try:
        data_consegna = req.data.get("data_consegna")
        id_zona = req.data.get("id_zona") or req.data.get("target_zones")
        aggiorna_traffico = bool(req.data.get("aggiorna_traffico", False))
        usa_or_tools = bool(req.data.get("usa_or_tools", True))
        tenant = req.data.get("tenant", "DNR")
        return core_web_calcola_percorsi(data_consegna, id_zona, aggiorna_traffico, usa_or_tools, tenant)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Global exception: {str(e)}"}

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_2, timeout_sec=540,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def genera_completo_giornata(req: https_fn.CallableRequest):
    try:
        data_consegna = req.data.get("data_consegna")
        tenant = req.data.get("tenant", "DNR")
        return core_genera_completo_giornata(data_consegna, tenant)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Global exception: {str(e)}"}

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=540,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def processa_job_pdf(req: https_fn.CallableRequest):
    return core_processa_job_pdf(req.data.get("job_id"), req.data.get("tenant", "DNR"))

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=300,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def genera_distinta_viaggio(req: https_fn.CallableRequest):
    return core_genera_distinta_viaggio(req.data.get("viaggio_id"))

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=300,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def ottimizza_viaggio(req: https_fn.CallableRequest):
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )
    return core_ottimizza_viaggio(req.data.get("viaggio_id"))

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=300,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def genera_mappa_autista(req: https_fn.CallableRequest):
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
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
    return core_ricalcola_percorso(
        req.data.get("viaggio_id"),
        req.data.get("punti", []),
        int(req.data.get("num_locked", 0))
    )

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
    if not req.auth:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
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
    """Alias compatibile con mappa_percorsi.html che reindirizza al core_web_calcola_percorsi."""
    try:
        data_consegna = req.data.get("data_consegna")
        zona_ids = req.data.get("zona_ids") or req.data.get("target_zones")
        return core_web_calcola_percorsi(data_consegna, id_zona=zona_ids)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Global exception: {str(e)}"}


        print(f"[BAT7B] Directions API errore tratta {lat_f},{lon_f}->{lat_t},{lon_t}: {e}")
    return max(1, int(_haversine(p_from, p_to) / 12))




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
    from services.history_service import handle_recupera_viaggio_storico
    return handle_recupera_viaggio_storico(
        req,
        tenant_resolver=get_tenant_from_viaggio_id,
        bucket_name=BUCKET_NAME
    )

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_256, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post"]))
def rilascia_recupero_storico(req: https_fn.CallableRequest):
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
    try:
        data = req.get_json()
        viaggio_id = data.get("viaggio_id")
        nuova_sequenza = data.get("sequenza") # list of indices, e.g. [2, 0, 1]
        
        db = get_db()
        doc_ref = db.collection("clienti").document("DNR").collection("viaggi ddt").document(viaggio_id)
        doc = doc_ref.get()
        if not doc.exists:
            return https_fn.Response(json.dumps({"status": "errore", "message": "Viaggio non trovato"}), status=404)
            
        viaggio = doc.to_dict()
        vecchi_punti = viaggio.get("punti_ottimizzati") or viaggio.get("punti", [])
        
        # Riordina i punti in base alla nuova sequenza degli indici inviata dall'autista
        nuovi_punti = []
        for idx in nuova_sequenza:
            if idx < len(vecchi_punti):
                nuovi_punti.append(vecchi_punti[idx])
                
        # Se mancano dei punti (per qualche strano motivo), aggiungiamoli in fondo
        for i, p in enumerate(vecchi_punti):
            if i not in nuova_sequenza:
                nuovi_punti.append(p)
                
        # Calcola distanze ed ETA - _get_directions_data mantiene l'ordine che gli passiamo
        depot = _get_depot_for_points_cloud(nuovi_punti)
        km, sec_guida, polylines = _get_directions_data(nuovi_punti, depot=depot)
        punti_finali = nuovi_punti  # l'ordine è già quello richiesto dall'autista

        
        distinta_url = viaggio.get("distinta_url") or viaggio.get("distinta_light")
        ora_partenza_calc = viaggio.get("_stats", {}).get("ora_partenza", "07:00")
        
        cliente_zona = viaggio.get("cliente_zona", "")
        nome_giro = viaggio.get("nome_giro", viaggio_id)
        if cliente_zona and cliente_zona.upper() not in nome_giro.upper():
            titolo_giro = f"{cliente_zona.upper()} - {nome_giro}"
        else:
            titolo_giro = nome_giro
            
        # Rigenera HTML della mappa per l'autista
        html = _genera_html_mappa(titolo_giro, punti_finali, km, sec_guida, polylines, depot=depot, distinta_url=distinta_url, ora_partenza_dep=ora_partenza_calc, actual_viaggio_id=viaggio_id)
        
        bucket = storage.bucket(name=BUCKET_NAME)
        data_v = viaggio.get("data", "sconosciuta").replace("/", "-")
        html_path = f"CONSEGNE/CONSEGNE_{data_v}/MAPPE_AUTISTI/{viaggio_id}.html"
        blob = bucket.blob(html_path)
        blob.upload_from_string(html.encode("utf-8"), content_type="text/html; charset=utf-8")
        
        # Aggiorna JSON in Storage per la mappa_zone
        try:
            data_str = viaggio.get("data_lavoro") or viaggio.get("data")
            if data_str:
                data_consegna = data_str.replace("/", "-")
                json_path = f"REPORTS/{data_consegna}/viaggi_giornalieri_Johnson.json"
                json_blob = bucket.blob(json_path)
                if json_blob.exists():
                    raw_json = json.loads(json_blob.download_as_string().decode('utf-8'))
                    if isinstance(raw_json, dict):
                        zone_list = raw_json.get("zone", [])
                    else:
                        zone_list = raw_json
                        
                    modificato_json = False
                    id_zona_str = viaggio_id.split('_', 1)[1] if '_' in viaggio_id else viaggio_id
                    for z in zone_list:
                        if z.get("id_zona") == id_zona_str:
                            z["lista_punti"] = punti_finali
                            modificato_json = True
                            break
                            
                    if modificato_json:
                        json_blob.upload_from_string(json.dumps(raw_json, indent=2), content_type='application/json')
                        print(f"Aggiornato JSON Storage per {viaggio_id}")
        except Exception as json_err:
            print(f"Errore aggiornamento JSON Storage: {json_err}")

        # Aggiorna database e timestamp
        doc_ref.update({
            "punti_ottimizzati": punti_finali,
            "_stats.km_reali": km,
            "_stats.minuti_guida": sec_guida // 60,
            "ultimo_aggiornamento": firestore.SERVER_TIMESTAMP
        })
        
        return https_fn.Response(json.dumps({"status": "ok"}), status=200, headers={'Content-Type': 'application/json'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return https_fn.Response(json.dumps({"status": "errore", "message": str(e)}), status=500, headers={'Content-Type': 'application/json'})

@https_fn.on_request(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=60,
    cors=options.CorsOptions(cors_origins=ALLOWED_ORIGINS, cors_methods=["get", "post", "options"]))
def autista_salva_reso(req: https_fn.Request) -> https_fn.Response:
    try:
        data = req.get_json()
        viaggio_id = data.get("viaggio_id")
        codice_cliente = data.get("codice_cliente", "UNK")
        nome_cliente = data.get("nome_cliente", "Sconosciuto")
        tipo_segnalazione = data.get("tipo_segnalazione", "reso_pregresso")
        base64_img = data.get("foto_base64", "")
        
        if not base64_img:
            return https_fn.Response(json.dumps({"status": "errore", "message": "Nessuna foto fornita"}), status=400)
            
        # Pulisci header base64 se presente (es. data:image/jpeg;base64,....)
        if "," in base64_img:
            base64_img = base64_img.split(",")[1]
            
        import base64
        image_data = base64.b64decode(base64_img)
        
        data_oggi = datetime.now().strftime("%Y-%m-%d")
        timestamp_ms = int(time.time() * 1000)
        
        # 1. Carica su Storage
        bucket = storage.bucket(name=BUCKET_NAME)
        file_path = f"RESI/{data_oggi}/{codice_cliente}_{timestamp_ms}.jpg"
        blob = bucket.blob(file_path)
        blob.upload_from_string(image_data, content_type='image/jpeg')
        # Costruisci URL pubblico o tramite get_signed_url
        blob.make_public()
        url_foto = blob.public_url
        
        # 2. Salva su Firestore
        db = get_db()
        db.collection("clienti").document("DNR").collection("resi_e_ritiri").add({
            "id_viaggio": viaggio_id,
            "autista": "Sconosciuto", # in futuro lo recupereremo dal viaggio o dall'auth
            "data_evento": data_oggi,
            "timestamp": timestamp_ms,
            "codice_cliente": codice_cliente,
            "nome_cliente": nome_cliente,
            "tipo_segnalazione": tipo_segnalazione,
            "url_foto": url_foto,
            "letto_da_ufficio": False
        })
        
        return https_fn.Response(json.dumps({"status": "ok", "url_foto": url_foto}), status=200, headers={'Content-Type': 'application/json'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return https_fn.Response(json.dumps({"status": "errore", "message": str(e)}), status=500, headers={'Content-Type': 'application/json'})

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.GB_1, timeout_sec=120)
def genera_riepiloghi_aziendali_light(req: https_fn.CallableRequest) -> typing.Any:
    try:
        # Verifica auth
        if not req.auth or not req.auth.uid:
            return {"status": "errore", "message": "Non autorizzato"}
            
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
    from services.admin_service import handle_admin_update_role
    return handle_admin_update_role(req)

@https_fn.on_call(timeout_sec=300)
@https_fn.on_call(region="europe-west1", timeout_sec=300, memory=options.MemoryOption.GB_1)
def elabora_centro_costi(req: https_fn.CallableRequest) -> typing.Any:
    if not req.auth:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    
    file_path = req.data.get("filePath")
    mese_riferimento = req.data.get("meseRiferimento")
    
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

