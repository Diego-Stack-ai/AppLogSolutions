from firebase_functions import https_fn

def handle_ottimizza_viaggio(req: https_fn.CallableRequest):
    viaggio_id = req.data.get("viaggio_id")
    from main import core_ottimizza_viaggio
    return core_ottimizza_viaggio(viaggio_id)

def handle_ricalcola_percorso(req: https_fn.CallableRequest):
    viaggio_id = req.data.get("viaggio_id")
    punti = req.data.get("punti", [])
    num_locked = int(req.data.get("num_locked", 0))
    from main import core_ricalcola_percorso
    return core_ricalcola_percorso(viaggio_id, punti, num_locked)

def handle_genera_distinta_viaggio(req: https_fn.CallableRequest):
    viaggio_id = req.data.get("viaggio_id")
    from main import core_genera_distinta_viaggio
    return core_genera_distinta_viaggio(viaggio_id)

def handle_calcola_percorsi_zone(req: https_fn.CallableRequest):
    data_consegna = req.data.get("data_consegna")
    zona_ids = req.data.get("zona_ids") or req.data.get("target_zones")
    from main import core_web_calcola_percorsi
    
    try:
        return core_web_calcola_percorsi(data_consegna, id_zona=zona_ids)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Global exception: {str(e)}"}

def handle_web_calcola_percorsi(req: https_fn.CallableRequest):
    data_consegna = req.data.get("data_consegna")
    zona_id = req.data.get("zona_ids") or req.data.get("target_zones") 
    from main import core_web_calcola_percorsi
    return core_web_calcola_percorsi(data_consegna, id_zona=zona_id)

def handle_genera_completo_giornata(req: https_fn.CallableRequest):
    data_consegna = req.data.get("data_consegna")
    tenant = req.data.get("tenant", "DNR")
    from main import core_genera_completo_giornata
    return core_genera_completo_giornata(data_consegna, tenant)
