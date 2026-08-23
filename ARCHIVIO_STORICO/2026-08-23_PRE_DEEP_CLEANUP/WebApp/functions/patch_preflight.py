import sys
import re

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# We want to replace check_dati_disponibili with preflight_elaborazione_mappe

old_func = """@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_256, timeout_sec=60,
    cors=options.CorsOptions(cors_origins="*", cors_methods=["get", "post"]))
def check_dati_disponibili(req: https_fn.CallableRequest):
    \"\"\"
    Rileva quali blocchi (CATTEL, GRAN_CHEF, DNR) hanno file raw ddt_estratti 
    presenti nello Storage per una certa data.
    Restituisce un dictionary: {"CATTEL": bool, "GRAN_CHEF": bool, "DNR": bool}
    \"\"\"
    data_consegna = req.data.get("data_consegna")
    if not data_consegna:
        return {"status": "errore", "message": "data_consegna mancante"}
        
    bucket = storage.bucket(name=BUCKET_NAME)
    
    risultato = {
        "CATTEL": False,
        "GRAN_CHEF": False,
        "DNR": False
    }
    
    # Controlliamo CATTEL
    if list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/CATTEL/ddt_estratti")):
        risultato["CATTEL"] = True
        
    # Controlliamo GRAN_CHEF
    if list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/GRAND_CHEF/ddt_estratti")):
        risultato["GRAN_CHEF"] = True
        
    # Controlliamo DNR (FRUTTA o LATTE)
    if list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/FRUTTA/ddt_estratti")) or \\
       list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/LATTE/ddt_estratti")):
        risultato["DNR"] = True
        
    return {"status": "ok", "dati_disponibili": risultato}"""

new_func = """def get_tenant_from_cz(cz):
    if not cz: return "DNR"
    cz = cz.upper().strip()
    if cz == "CATTEL": return "CATTEL"
    if cz == "GRAN CHEF": return "GRAN_CHEF"
    return "DNR"

@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_256, timeout_sec=60,
    cors=options.CorsOptions(cors_origins="*", cors_methods=["get", "post"]))
def preflight_elaborazione_mappe(req: https_fn.CallableRequest):
    \"\"\"
    Pre-flight check per l'elaborazione mappe.
    Rileva quali blocchi hanno nuovi dati in split_ddt e se i vecchi viaggi 
    hanno contaminazioni (fornitori misti).
    Restituisce un dizionario con i dati necessari al frontend per decidere lo scenario (A, B o C).
    \"\"\"
    import json
    data_consegna = req.data.get("data_consegna")
    if not data_consegna:
        return {"status": "errore", "message": "data_consegna mancante"}
        
    bucket = storage.bucket(name=BUCKET_NAME)
    
    in_elaborazione = {
        "CATTEL": False,
        "GRAN_CHEF": False,
        "DNR": False
    }
    
    # Controlliamo CATTEL
    if list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/CATTEL/ddt_estratti")):
        in_elaborazione["CATTEL"] = True
        
    # Controlliamo GRAN_CHEF
    if list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/GRAND_CHEF/ddt_estratti")):
        in_elaborazione["GRAN_CHEF"] = True
        
    # Controlliamo DNR (FRUTTA o LATTE)
    if list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/FRUTTA/ddt_estratti")) or \\
       list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/LATTE/ddt_estratti")):
        in_elaborazione["DNR"] = True
        
    # Troviamo quali file ddt_estratti causano l'elaborazione per usarli nel calcolo contaminazione
    ddt_presenti = []
    for k, v in in_elaborazione.items():
        if v:
            ddt_presenti.append(k)

    # Adesso leggiamo i viaggi vecchi (cassaforte) per vedere se ci sono viaggi contaminati
    elaborati_esistenti = {"CATTEL": False, "GRAN_CHEF": False, "DNR": False}
    contaminati = False
    
    try:
        blob_old_json = bucket.blob(f"REPORTS/{data_consegna}/viaggi_giornalieri_Johnson.json")
        if blob_old_json.exists():
            old_data = json.loads(blob_old_json.download_as_string().decode('utf-8'))
            old_zones = old_data.get("zone", []) if isinstance(old_data, dict) else old_data
            
            for zona in old_zones:
                stops = zona.get("stops", [])
                
                # Quali tenant sono presenti in questo viaggio?
                tenants_in_trip = set()
                for stop in stops:
                    cz = stop.get("cliente_zona", "")
                    tenants_in_trip.add(get_tenant_from_cz(cz))
                    
                for t in tenants_in_trip:
                    if t in elaborati_esistenti:
                        elaborati_esistenti[t] = True
                        
                # Controllo contaminazione:
                tenants_da_aggiornare = tenants_in_trip.intersection(set(ddt_presenti))
                tenants_da_preservare = tenants_in_trip - set(ddt_presenti)
                
                if len(tenants_da_aggiornare) > 0 and len(tenants_da_preservare) > 0:
                    contaminati = True
    except Exception as e:
        print(f"[WARN] preflight: Impossibile leggere viaggi_giornalieri_Johnson.json: {e}")

    return {
        "status": "ok",
        "in_elaborazione": in_elaborazione,
        "elaborati_esistenti": elaborati_esistenti,
        "contaminazione": contaminati
    }"""

if old_func in content:
    content = content.replace(old_func, new_func)
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Sostituito con successo.")
else:
    print("Non trovato.")
