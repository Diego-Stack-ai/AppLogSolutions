from infrastructure.firebase_setup import BUCKET_NAME
from core.utils import _genera_url_storage_token, _build_tripla_chiave
from firebase_admin import storage, firestore
from firebase_functions import https_fn
import typing, io, requests
from datetime import datetime
import time
from collections import defaultdict
from core.permissions import require_page_permission
try:
    from pypdf import PdfReader, PdfWriter
except:
    pass
from infrastructure.firebase_setup import get_db

def get_tenant_from_viaggio_id(v_id):
    return v_id.split("_")[1] if "_" in v_id else "DNR"

def _resolve_tenant_from_source(cliente_zona: str) -> str:
    cz = str(cliente_zona).strip().upper()
    if cz in ("FRUTTA", "LATTE", "DNR_FRUTTA", "DNR_LATTE"):
        return "DNR"
    if cz in ("GRAND_CHEF", "GRAN_CHEF", "GRAN CHEF"):
        return "GRAN CHEF"
    if cz == "CATTEL":
        return "CATTEL"
    if cz == "DAC":
        return "DAC"
    
    raise ValueError(f"Committente/Tenant non riconosciuto per la sorgente: '{cz}'")

def handle_genera_report_giornaliero(req: https_fn.CallableRequest):
    # Local imports to avoid circular dependency for helpers
    return core_genera_report_giornaliero(req.auth.uid if req.auth else None, req.data.get("data_consegna"), req.data.get("tipologie_da_elaborare", []))

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
            tenant = "DNR" # DNR è il tenant canonico e non deve essere sovrascritto
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
        tenant_v = _resolve_tenant_from_source(z.get('cliente_zona', ''))
        tenants_con_viaggi.add(tenant_v)
        
    for t_v in tenants_con_viaggi:
        # Filtriamo le zone di competenza di questo tenant
        master_json_t = []
        for z in master_json:
            t_z = _resolve_tenant_from_source(z.get('cliente_zona', ''))
            if t_z == t_v:
                master_json_t.append(z)
                
        output_str_t = json.dumps({"data_consegna": data_consegna, "zone": master_json_t, "tenant": t_v}, indent=2)
        bucket.blob(f"{t_v}/REPORTS/{data_consegna}/viaggi_giornalieri_Johnson.json").upload_from_string(
            output_str_t, content_type='application/json'
        )
    
    # Scrittura su Firestore (Salvataggio Viaggi divisi per Tenant)
    for z in master_json:
        doc_id = f"{data_consegna}_{z['id_zona']}"
        tenant_viaggio = _resolve_tenant_from_source(z.get('cliente_zona', ''))
        viaggio_ref = db.collection('clienti').document(tenant_viaggio).collection('viaggi ddt').document(doc_id)
        
        # Manteniamo t_guida_min, t_tot_min, km_reali, autista se erano presenti nella cassaforte
        old_viaggio_data = {}
        if z["id_zona"] in mappa_zone_esistenti:
            old_viaggio_data = mappa_zone_esistenti[z["id_zona"]]
            
        viaggio_data = {
            'tenant': tenant_viaggio,
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
def genera_report_giornaliero(req: https_fn.CallableRequest):
    require_page_permission(req, page_key="page_elaborazione", required_level="write")
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
def handle_genera_riepiloghi_aziendali_light(req: https_fn.CallableRequest) -> typing.Any:
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
                real_tenant = doc.to_dict().get('tenant') or _resolve_tenant_from_source(doc.to_dict().get('cliente_zona', ''))
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

