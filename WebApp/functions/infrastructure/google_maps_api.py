import os
import math
import json
import time
import logging
import hashlib
import re
try:
    import requests
except ImportError:
    requests = None

from infrastructure.firebase_setup import load_storage_cache, save_storage_cache

logger = logging.getLogger('AppLogSolutions')

TRAFFIC_SLOTS_MIN = [600, 630, 660, 690, 720, 750, 780]

def nearest_slot(current_minutes):
    slots = TRAFFIC_SLOTS_MIN
    if current_minutes < slots[0] - 15 or current_minutes > slots[-1] + 15:
        return None
    nearest = min(slots, key=lambda s: abs(s - current_minutes))
    return f"{nearest // 60:02d}{nearest % 60:02d}"

def get_weekday_timestamp(hour, minute):
    import datetime
    now = datetime.datetime.now()
    days_ahead = 0
    while True:
        candidate = now + datetime.timedelta(days=days_ahead)
        if candidate.weekday() < 5:
            ts = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if ts > now:
                return int(ts.timestamp())
        days_ahead += 1

def get_traffic_duration(p1, p2, slot_str):
    if not slot_str: return None
    h = int(slot_str[:2])
    m = int(slot_str[2:])
    dep_ts = get_weekday_timestamp(h, m)
    orig = f"{p1.get('lat',0)},{p1.get('lon', p1.get('lng', 0))}"
    dest = f"{p2.get('lat',0)},{p2.get('lon', p2.get('lng', 0))}"
    url = (f"https://maps.googleapis.com/maps/api/distancematrix/json"
           f"?origins={orig}&destinations={dest}"
           f"&departure_time={dep_ts}&traffic_model=best_guess"
           f"&key={GOOGLE_MAPS_API_KEY}")
    try:
        resp = requests.get(url, timeout=10).json()
        if resp.get('status') == 'OK':
            el = resp['rows'][0]['elements'][0]
            if el.get('status') == 'OK':
                dur = el.get('duration_in_traffic', el.get('duration', {})).get('value')
                return dur
    except Exception as e:
        print(f"[TRAFFIC] Errore API: {e}")
    return None

def _route_key(punti_pieni):
    seq = "|".join(f"{round(p.get('lat',0.0),5)},{round(p.get('lon', p.get('lng',0.0)),5)}" for p in punti_pieni)
    return hashlib.md5(seq.encode()).hexdigest()

def _leggi_percorsi_cache(key):
    cache = load_storage_cache("directions_cache_v2.json")
    return cache.get(key)

def _scrivi_percorsi_cache(key, data):
    cache = load_storage_cache("directions_cache_v2.json")
    cache[key] = data
    save_storage_cache("directions_cache_v2.json")

def _leggi_cache_completa_firestore(p1, p2):
    cache = load_storage_cache("distanze_reali_cache.json")
    key = _cache_key(p1, p2)
    val = cache.get(key)
    if val: return val
    rev_key = _cache_key(p2, p1)
    val_rev = cache.get(rev_key)
    if val_rev: return val_rev
    return None

def _leggi_traffic_cache(p1, p2, slot_str):
    cache = load_storage_cache("distanze_traffico_cache.json")
    key = _cache_key(p1, p2)
    val = cache.get(key)
    if val: return val.get(slot_str)
    rev_key = _cache_key(p2, p1)
    val_rev = cache.get(rev_key)
    if val_rev: return val_rev.get(slot_str)
    return None

def _scrivi_traffic_cache(p1, p2, slot_str, dur_sec):
    try:
        cache = load_storage_cache("distanze_traffico_cache.json")
        key = _cache_key(p1, p2)
        if key not in cache: cache[key] = {}
        cache[key][slot_str] = int(dur_sec)
        save_storage_cache("distanze_traffico_cache.json")
    except:
        pass

GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
AVG_SPEED_KMH = 35.0

DEPOT_VEGGIANO = {"lat": 45.442805, "lon": 11.714498, "nome": "DEPOSITO VEGGIANO", "indirizzo": "Via Alessandro Volta 25/a, 35030 Veggiano (PD)"}
DEPOT_CASTENEDOLO = {"lat": 45.471591, "lon": 10.298200, "nome": "DEPOSITO CASTENEDOLO", "indirizzo": "Via Vulcania snc, 25014 Castenedolo (BS)"}
DEPOT_SOMMACAMPAGNA = {"lat": 45.414500, "lon": 10.898500, "nome": "DEPOSITO SOMMACAMPAGNA", "indirizzo": "Via Caselle 90/b, 37066 Sommacampagna (VR)"}

def _haversine(p1, p2):
    """Calcolo distanza in linea d'aria (fallback di emergenza)."""
    R = 6371000  # metri
    lat1, lon1 = math.radians(p1['lat']), math.radians(p1['lon'])
    lat2, lon2 = math.radians(p2['lat']), math.radians(p2['lon'])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return int(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def _cache_key(p1, p2):
    """Chiave univoca per la coppia di punti (arrotondata a 5 decimali = ~1 metro)."""
    return f"{round(p1['lat'],5)},{round(p1['lon'],5)}_{round(p2['lat'],5)},{round(p2['lon'],5)}"

def _leggi_cache_firestore(p1, p2):
    cache = load_storage_cache("distanze_reali_cache.json")
    key = _cache_key(p1, p2)
    val = cache.get(key)
    if val: return val.get('dist')
    rev_key = _cache_key(p2, p1)
    val_rev = cache.get(rev_key)
    if val_rev: return val_rev.get('dist')
    return None

def _scrivi_cache_firestore(coppie):
    if not coppie: return
    cache = load_storage_cache("distanze_reali_cache.json")
    for key, dist, dur in coppie:
        cache[key] = {'dist': dist, 'dur': dur}
    save_storage_cache("distanze_reali_cache.json")
    print(f"[CACHE] Scritte {len(coppie)} nuove distanze su Storage.")

def _crea_matrice_distanze_cloud(punti, errori_lista):
    """
    Crea la matrice delle distanze (in metri) con 3 livelli:
      1. Cache Firestore (gratis, istantaneo)
      2. Google Distance Matrix API (preciso, a pagamento)
      3. Haversine (fallback di emergenza)
    """
    n = len(punti)
    matrix = [[0] * n for _ in range(n)]
    da_calcolare = []  # coppie (i, j) mancanti dalla cache

    # FASE 1: lettura dalla cache Firestore
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            dist = _leggi_cache_firestore(punti[i], punti[j])
            if dist is not None:
                matrix[i][j] = dist
            else:
                da_calcolare.append((i, j))

    if not da_calcolare:
        print(f"[CACHE] Matrice completa da cache Firestore ({n} punti).")
        return matrix

    print(f"[MATRIX] {len(da_calcolare)} coppie mancanti → richiesta a Google Distance Matrix API.")

    # FASE 2: Google Distance Matrix API con chunking 10x10
    nuove_coppie = []

    if not GOOGLE_MAPS_API_KEY or not requests:
        print("[MATRIX] Chiave API mancante o requests non disponibile → uso Haversine.")
        for i, j in da_calcolare:
            matrix[i][j] = _haversine(punti[i], punti[j])
        return matrix

    CHUNK_SIZE = 10
    try:
        # Raggruppa per righe (origins)
        righe_da_calc = sorted(set(i for i, j in da_calcolare))
        for r_start in range(0, n, CHUNK_SIZE):
            r_end = min(r_start + CHUNK_SIZE, n)
            righe_blocco = [i for i in range(r_start, r_end) if i in righe_da_calc]
            if not righe_blocco:
                continue

            origins = "|".join([f"{punti[i]['lat']},{punti[i]['lon']}" for i in righe_blocco])

            for c_start in range(0, n, CHUNK_SIZE):
                c_end = min(c_start + CHUNK_SIZE, n)
                # Salta blocco se tutte le coppie sono già note
                coppie_blocco = [(i, j) for i in righe_blocco for j in range(c_start, c_end) if i != j and matrix[i][j] == 0]
                if not coppie_blocco:
                    continue

                destinations = "|".join([f"{punti[j]['lat']},{punti[j]['lon']}" for j in range(c_start, c_end)])
                url = (
                    f"https://maps.googleapis.com/maps/api/distancematrix/json"
                    f"?origins={origins}&destinations={destinations}&key={GOOGLE_MAPS_API_KEY}"
                )
                resp = requests.get(url, timeout=10).json()

                if resp.get('status') == 'OK':
                    for i_local, row_data in enumerate(resp['rows']):
                        i_global = righe_blocco[i_local]
                        for j_local, elem in enumerate(row_data['elements']):
                            j_global = c_start + j_local
                            if i_global == j_global:
                                continue
                            if elem.get('status') == 'OK':
                                dist = elem['distance']['value']
                                dur = elem['duration']['value']
                                matrix[i_global][j_global] = dist
                                nuove_coppie.append((_cache_key(punti[i_global], punti[j_global]), dist, dur))
                            else:
                                # Fallback puntuale
                                matrix[i_global][j_global] = _haversine(punti[i_global], punti[j_global])
                elif resp.get('status') == 'REQUEST_DENIED':
                    print("[MATRIX] ERRORE: API Google negata. Controlla la chiave GOOGLE_MAPS_API_KEY.")
                    # Fallback totale
                    for i, j in da_calcolare:
                        if matrix[i][j] == 0:
                            matrix[i][j] = _haversine(punti[i], punti[j])
                    return matrix

    except Exception as e:
        print(f"[MATRIX] Eccezione durante API Google: {e} → Haversine di emergenza.")
        for i, j in da_calcolare:
            if matrix[i][j] == 0:
                matrix[i][j] = _haversine(punti[i], punti[j])

    # FASE 3: Salva le nuove distanze in cache Firestore
    _scrivi_cache_firestore(nuove_coppie)

    return matrix

def _get_directions_data(percorso_punti, depot=None):
    """Chiama Directions API. Restituisce (km, sec_guida, lista_polylines)."""
    if depot is None:
        depot = _get_depot_for_points_cloud(percorso_punti)
    punti_pieni = [depot] + percorso_punti + [depot]
    km_tot, sec_tot, polylines, nuove_coppie = 0.0, 0, [], []

    km_stima = sum(_haversine(punti_pieni[k], punti_pieni[k+1]) / 1000 * 1.3
                   for k in range(len(punti_pieni) - 1))
    sec_stima = int((km_stima / AVG_SPEED_KMH) * 3600)

    if not GOOGLE_MAPS_API_KEY or not requests:
        return round(km_stima, 1), sec_stima, []

    CHUNK = 10
    try:
        for i in range(0, len(punti_pieni) - 1, CHUNK):
            sub = punti_pieni[i:i + CHUNK + 1]
            origin = f"{sub[0]['lat']},{sub[0]['lon']}"
            dest   = f"{sub[-1]['lat']},{sub[-1]['lon']}"
            
            url = (f"https://maps.googleapis.com/maps/api/directions/json"
                   f"?origin={origin}&destination={dest}")
                   
            waypts_list = [f"{p['lat']},{p['lon']}" for p in sub[1:-1]]
            if waypts_list:
                waypts = "|".join(waypts_list)
                url += f"&waypoints={waypts}"
                
            url += f"&key={GOOGLE_MAPS_API_KEY}"
            
            r = requests.get(url, timeout=8).json()
            if r.get("status") == "OK":
                route = r["routes"][0]
                legs  = route["legs"]
                km_tot  += sum(l["distance"]["value"] for l in legs) / 1000.0
                sec_tot += sum(l["duration"]["value"]  for l in legs)
                polylines.append(route["overview_polyline"]["points"])
                if len(legs) == len(sub) - 1:
                    for idx_l, leg in enumerate(legs):
                        key = _cache_key(sub[idx_l], sub[idx_l + 1])
                        nuove_coppie.append((key, leg["distance"]["value"], leg["duration"]["value"]))
    except Exception as e:
        print(f"[DIRECTIONS] Eccezione: {e}")

    if nuove_coppie:
        _scrivi_cache_firestore(nuove_coppie)

    final_km  = round(km_tot  if km_tot  > 0 else km_stima, 1)
    final_sec = sec_tot if sec_tot > 0 else sec_stima
    return final_km, final_sec, polylines

    save_storage_cache("directions_cache.json")

def _get_depot_for_points_cloud(punti):
    # Se c'è anche una sola consegna Cattel, forziamo il deposito a Sommacampagna
    if any(p.get("tipo") == "CATTEL" or p.get("competenza") == "CATTEL" for p in punti):
        return DEPOT_SOMMACAMPAGNA

    conteggio = {
        "BS": 0, "VR": 0, "MN": 0, "PD": 0,
        "UD": 0, "BL": 0, "TV": 0, "VI": 0, "ALTRO": 0,
    }
    for p in punti:
        prov_val = str(p.get("provincia") or p.get("prov") or "").upper().strip()
        if prov_val in conteggio:
            conteggio[prov_val] += 1
            continue
        ind = str(p.get("indirizzo") or "").upper()
        m = re.search(r"\(([A-Z]{2})\)", ind)
        if m:
            prov = m.group(1)
            if prov in conteggio:
                conteggio[prov] += 1
            else:
                conteggio["ALTRO"] += 1
        else:
            conteggio["ALTRO"] += 1

    castenedolo_tot   = conteggio["BS"]
    sommacampagna_tot = conteggio["VR"] + conteggio["MN"]
    veggiano_tot      = (conteggio["PD"] + conteggio["VI"] + conteggio["BL"] +
                         conteggio["UD"] + conteggio["TV"] + conteggio["ALTRO"])

    if castenedolo_tot > sommacampagna_tot and castenedolo_tot > veggiano_tot:
        return DEPOT_CASTENEDOLO
    elif sommacampagna_tot > castenedolo_tot and sommacampagna_tot > veggiano_tot:
        return DEPOT_SOMMACAMPAGNA
    elif veggiano_tot > castenedolo_tot and veggiano_tot > sommacampagna_tot:
        return DEPOT_VEGGIANO

    return DEPOT_SOMMACAMPAGNA

def _get_directions_and_simulate_cloud(percorso, depot_partenza, depot_arrivo, is_grand_chef, data_consegna, aggiorna_traffico, target_arr_time_min=390):
    punti_pieni = [depot_partenza] + percorso + [depot_arrivo]
    
    _dir_key = _route_key(punti_pieni)
    _dir_cached = None # BYPASS CACHE PER FORZARE RICALCOLO
    
    if _dir_cached:
        km_tot = _dir_cached["km"]
        sec_tot = _dir_cached["sec"]
        polylines = _dir_cached["polylines"]
    else:
        km_tot, sec_tot, polylines = 0.0, 0, []
        km_stima = sum(_haversine(punti_pieni[k], punti_pieni[k+1]) / 1000 * 1.3 for k in range(len(punti_pieni) - 1))
        sec_stima = int((km_stima / 35.0) * 3600)
        
        if GOOGLE_MAPS_API_KEY and requests:
            CHUNK = 10
            try:
                for i in range(0, len(punti_pieni) - 1, CHUNK):
                    sub = punti_pieni[i:i + CHUNK + 1]
                    origin = f"{sub[0]['lat']},{sub[0]['lon']}"
                    dest = f"{sub[-1]['lat']},{sub[-1]['lon']}"
                    
                    url = (f"https://maps.googleapis.com/maps/api/directions/json"
                           f"?origin={origin}&destination={dest}")
                    
                    waypts_list = [f"{p['lat']},{p['lon']}" for p in sub[1:-1]]
                    if waypts_list:
                        waypts = "|".join(waypts_list)
                        url += f"&waypoints={waypts}"
                        
                    url += f"&key={GOOGLE_MAPS_API_KEY}"
                    
                    r = requests.get(url, timeout=10).json()
                    if r.get("status") == "OK":
                        route = r["routes"][0]
                        legs = route["legs"]
                        km_tot += sum(l["distance"]["value"] for l in legs) / 1000.0
                        sec_tot += sum(l["duration"]["value"] for l in legs)
                        polylines.append(route["overview_polyline"]["points"])
                        if len(legs) == len(sub) - 1:
                            for idx_l, leg in enumerate(legs):
                                key = _cache_key(sub[idx_l], sub[idx_l + 1])
                                _scrivi_cache_firestore([(key, leg["distance"]["value"], leg["duration"]["value"])])
                    else:
                        print(f"[DIRECTIONS] Errore API Google: Status={r.get('status')} Msg={r.get('error_message')}")
            except Exception as e:
                print(f"[DIRECTIONS] Errore: {e}")
                
        if km_tot > 0:
            _scrivi_percorsi_cache(_dir_key, {"km": km_tot, "sec": sec_tot, "polylines": polylines})
        else:
            km_tot, sec_tot = km_stima, sec_stima

    sosta = 12 if is_grand_chef else 8
    current_time = target_arr_time_min
    
    def parse_time_to_minutes(time_str, default_val):
        if not time_str: return default_val
        m = re.match(r"(\d{2}):(\d{2})", str(time_str).strip())
        if m:
            return int(m.group(1)) * 60 + int(m.group(2))
        return default_val

    def format_minutes_to_time(minutes):
        minutes = int(minutes) % 1440
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    for idx, p in enumerate(percorso):
        p_precedente = percorso[idx - 1] if idx > 0 else depot_partenza
        durata_guida_sec = 0
        
        cached = _leggi_cache_completa_firestore(p_precedente, p)
        if cached:
            durata_guida_sec = cached['dur']
            if aggiorna_traffico:
                slot_time = target_arr_time_min if idx == 0 else current_time
                slot = nearest_slot(slot_time)
                if slot:
                    traf = _leggi_traffic_cache(p_precedente, p, slot)
                    if traf is None:
                        traf = get_traffic_duration(p_precedente, p, slot)
                        if traf:
                            _scrivi_traffic_cache(p_precedente, p, slot, traf)
                    if traf:
                        durata_guida_sec = traf
        else:
            _api_ok = False
            if GOOGLE_MAPS_API_KEY and requests:
                try:
                    _orig = f"{p_precedente['lat']},{p_precedente['lon']}"
                    _dest = f"{p['lat']},{p['lon']}"
                    _url = (f"https://maps.googleapis.com/maps/api/distancematrix/json"
                            f"?origins={_orig}&destinations={_dest}&key={GOOGLE_MAPS_API_KEY}")
                    _resp = requests.get(_url, timeout=10).json()
                    if _resp.get('status') == 'OK':
                        _el = _resp['rows'][0]['elements'][0]
                        if _el.get('status') == 'OK':
                            _dist = _el['distance']['value']
                            _dur = _el['duration']['value']
                            _scrivi_cache_firestore([(_cache_key(p_precedente, p), _dist, _dur)])
                            durata_guida_sec = _dur
                            _api_ok = True
                except:
                    pass
            if not _api_ok:
                dist_m = _haversine(p_precedente, p) * 1.3
                durata_guida_sec = (dist_m / 1000.0 / 35.0) * 3600
                
        durata_guida_min = durata_guida_sec / 60.0 + 4
        
        if idx == 0:
            current_time = target_arr_time_min - durata_guida_min
            partenza_magazzino_min = current_time
            
        arr_time_min = current_time + durata_guida_min
        
        dep_time_min = arr_time_min + sosta
        p["ora_arrivo"] = format_minutes_to_time(arr_time_min)
        p["ora_ripartenza"] = format_minutes_to_time(dep_time_min)
        
        oM = p.get("orario_max") or p.get("ora_max") or ""
        if oM:
            p["ritardo"] = arr_time_min > parse_time_to_minutes(oM, 840) + 1
        else:
            p["ritardo"] = False
            
        current_time = dep_time_min
        
    ora_partenza_calc = format_minutes_to_time(partenza_magazzino_min) if len(percorso) > 0 else "07:00"
    return km_tot, sec_tot, polylines, percorso, ora_partenza_calc

# ─── CLOUD FUNCTION PER BAT 7B: AGGIORNA TRAFFICO SERALE ──────────────────────

def _get_directions_sec_with_traffic(p_from, p_to):
    """
    Tempo di percorrenza con traffico reale (Directions API departure_time=now).
    Restituisce i secondi di guida stimati con traffico attuale.
    """
    if not GOOGLE_MAPS_API_KEY or not requests:
        # fallback haversine: ~43 km/h medi
        return max(1, int(_haversine(p_from, p_to) / 12))

    lat_f = p_from.get('lat', 0)
    lon_f = p_from.get('lon', p_from.get('lng', 0))
    lat_t = p_to.get('lat', 0)
    lon_t = p_to.get('lon', p_to.get('lng', 0))
    url = (
        f"https://maps.googleapis.com/maps/api/directions/json"
        f"?origin={lat_f},{lon_f}"
        f"&destination={lat_t},{lon_t}"
        f"&mode=driving&departure_time=now&traffic_model=best_guess"
        f"&key={GOOGLE_MAPS_API_KEY}"
    )
    try:
        resp = requests.get(url, timeout=8).json()
        if resp.get('status') == 'OK' and resp.get('routes'):
            leg = resp['routes'][0]['legs'][0]
            # duration_in_traffic disponibile quando departure_time è impostato
            sec = leg.get('duration_in_traffic', leg.get('duration', {})).get('value', 0)
            return max(1, sec)
    except Exception as e:
        logger.error(f"[MAPS] Errore API: {e}")
    
    return max(1, int(_haversine(p_from, p_to) / 12))
