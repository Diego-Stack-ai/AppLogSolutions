import json
import uuid
import time
import math
import copy
from datetime import datetime
from google.cloud.firestore_v1.base_query import FieldFilter
from firebase_admin import firestore, storage
from core.utils import get_db, _safe_float, normalize_code, _genera_url_storage_token, _registra_statistica, _is_primary_code

from services.map_service import _genera_html_mappa, _genera_html_mappa_generale, _genera_kml_zone
from infrastructure.google_maps_api import _get_directions_data, _get_depot_for_points_cloud, _crea_matrice_distanze_cloud, _get_directions_and_simulate_cloud
from infrastructure.firebase_setup import BUCKET_NAME
from collections import defaultdict
import re

from firebase_functions import https_fn

_CACHED_CONSOLIDAMENTO = None
_CACHE_TIMESTAMP = 0
_CACHED_ARTICOLI_NOTI = None
CACHE_TTL = 300
TIME_PER_STOP_MIN = 8
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

def handle_ottimizza_viaggio(req: https_fn.CallableRequest):
    viaggio_id = req.data.get("viaggio_id")
    tenant = req.data.get("tenant")
    if not tenant:
        raise ValueError("Tenant esplicito mancante nella richiesta")
    return core_ottimizza_viaggio(viaggio_id, tenant)

def handle_ricalcola_percorso(req: https_fn.CallableRequest):
    viaggio_id = req.data.get("viaggio_id")
    punti = req.data.get("punti", [])
    num_locked = int(req.data.get("num_locked", 0))
    tenant = req.data.get("tenant")
    if not tenant:
        raise ValueError("Tenant esplicito mancante nella richiesta")
    return core_ricalcola_percorso(viaggio_id, punti, num_locked, tenant)

def handle_genera_distinta_viaggio(req: https_fn.CallableRequest):
    viaggio_id = req.data.get("viaggio_id")
    tenant = req.data.get("tenant")
    if not tenant:
        raise ValueError("Tenant esplicito mancante nella richiesta")
    return core_genera_distinta_viaggio(viaggio_id, tenant)

def handle_calcola_percorsi_zone(req: https_fn.CallableRequest):
    data_consegna = req.data.get("data_consegna")
    zona_ids = req.data.get("zona_ids") or req.data.get("target_zones")
        
    try:
        return core_web_calcola_percorsi(data_consegna, id_zona=zona_ids)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Global exception: {str(e)}"}

def handle_web_calcola_percorsi(req: https_fn.CallableRequest):
    data_consegna = req.data.get("data_consegna")
    zona_id = req.data.get("id_zona") or req.data.get("target_zones") or req.data.get("zona_ids")
    tenant = req.data.get("tenant")
    aggiorna_traffico = req.data.get("aggiorna_traffico", False)
    usa_or_tools = req.data.get("usa_or_tools", True)
    
    return core_web_calcola_percorsi(
        data_consegna, 
        id_zona=zona_id, 
        aggiorna_traffico=aggiorna_traffico,
        usa_or_tools=usa_or_tools,
        tenant=tenant
    )

def handle_genera_completo_giornata(req: https_fn.CallableRequest):
    data_consegna = req.data.get("data_consegna")
    tenant = req.data.get("tenant", "DNR")
    return core_genera_completo_giornata(data_consegna, tenant)


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

def _get_viaggio_doc_self_healing(viaggio_id, tenant):
    if not tenant:
        raise ValueError("Tenant esplicito mancante. Il routing richiede un tenant valido per operare sui nuovi viaggi.")
    db = get_db()
    tenant_viaggio = tenant
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

def core_ottimizza_viaggio(viaggio_id, tenant):
    start_time = time.time()
    print("[INFO] Start ottimizza_viaggio")

    if not viaggio_id:
        return {"status": "errore", "message": "viaggio_id mancante", "errori": ["viaggio_id mancante"], "data": {}}
        
        
    doc_ref, doc_viaggio, tenant_viaggio = _get_viaggio_doc_self_healing(viaggio_id, tenant)
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

def core_genera_distinta_viaggio(viaggio_id, tenant):
    start_time = time.time()
    print("[INFO] Start genera_distinta_viaggio")
    
    if not viaggio_id:
        return {"status": "errore", "message": "viaggio_id mancante", "errori": ["viaggio_id mancante"], "data": {}}

    doc_ref, doc_viaggio, tenant_viaggio = _get_viaggio_doc_self_healing(viaggio_id, tenant)
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

def core_ricalcola_percorso(viaggio_id, nuovi_punti, num_locked=0, tenant=None):
    """
    Riceve un viaggio con le tappe riordinate manualmente dal frontend.
    - Le prime `num_locked` tappe sono H10 bloccate (non si toccano).
    - Le restanti vengono riottimizzate con OR-Tools + Distance Matrix API.
    - Salva il nuovo ordine su Firestore e rigenera la mappa autista.
    """
    start_time = time.time()

    if not viaggio_id or not nuovi_punti:
        return {"status": "errore", "message": "viaggio_id o punti mancanti", "errori": [], "data": {}}

    doc_ref, doc_viaggio, tenant_viaggio = _get_viaggio_doc_self_healing(viaggio_id, tenant)
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

def core_web_calcola_percorsi(data_consegna, id_zona=None, aggiorna_traffico=False, usa_or_tools=True, tenant=None):
    if not tenant:
        raise ValueError("Tenant esplicito mancante nella richiesta per core_web_calcola_percorsi")
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
        if id_zona is not None:
            norm_zid = str(zid).strip()
            if isinstance(id_zona, list):
                norm_targets = [str(x).strip() for x in id_zona]
                if norm_zid not in norm_targets:
                    continue
            else:
                norm_target = str(id_zona).strip()
                if norm_zid != norm_target:
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
            
            tenant_viaggio = tenant
            if not tenant_viaggio:
                raise ValueError("Tenant esplicito mancante. Impossibile calcolare il percorso.")
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
    
    if not calcolati:
        return {
            "status": "errore",
            "message": "Nessun viaggio selezionato/elaborato per i criteri richiesti."
        }
        
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

def core_genera_completo_giornata(data_consegna, tenant=None):
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
        tenant_viaggio = tenant
        if not tenant_viaggio:
            raise ValueError("Tenant esplicito mancante. Impossibile generare la distinta PDF.")
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
