from firebase_admin import firestore
import datetime

def handle_chiudi_giornata(db) -> dict:
    print("[INFO] Tentativo chiusura giornata")
    
    try:
        tenants = [doc.id for doc in db.collection('clienti').list_documents()]
    except Exception as e:
        print(f"[chiudi_giornata] Errore lookup tenant: {e}")
        tenants = ['DNR', 'GRAN CHEF', 'CATTEL', 'DAC']
    ddt_non_assegnati = 0
    
    for t in tenants:
        ddts = list(db.collection('clienti').document(t).collection('ddt').stream())
        ddt_non_assegnati += sum(1 for d in ddts if d.to_dict().get('stato') != 'assegnato')
    
    if ddt_non_assegnati > 0:
        return {
            "status": "errore",
            "message": "Impossibile chiudere la giornata: ci sono DDT non assegnati.",
            "errori": [f"{ddt_non_assegnati} DDT in sospeso"],
            "data": {}
        }
        
    viaggi = list(db.collection('clienti').document('DNR').collection('viaggi ddt').stream())
    viaggi_non_completati = [v.id for v in viaggi if v.to_dict().get('status') != 'completato']
    
    if viaggi_non_completati:
        return {
            "status": "errore",
            "message": "Impossibile chiudere la giornata: ci sono viaggi non completati.",
            "errori": [f"Viaggi aperti: {len(viaggi_non_completati)}"],
            "data": {}
        }
        
    # --- FINALIZZAZIONE RIENTRI ---
    try:
        # Trova tutti i codici assegnati nei viaggi completati
        codici_assegnati = set()
        data_giornata = ""
        for v in viaggi:
            v_data = v.to_dict()
            if not data_giornata and v_data.get('data'):
                data_giornata = v_data.get('data')
                
            for p in v_data.get('punti', []):
                if p.get('codice_frutta') and str(p.get('codice_frutta')) != 'p00000':
                    codici_assegnati.add(str(p['codice_frutta']).lower())
                if p.get('codice_latte') and str(p.get('codice_latte')) != 'p00000':
                    codici_assegnati.add(str(p['codice_latte']).lower())
                # Rientri associati come alert
                for r_alert in p.get('rientri_alert', []):
                    if r_alert.get('codice'):
                        codici_assegnati.add(str(r_alert['codice']).lower())

        if not data_giornata:
            data_giornata = datetime.datetime.now().strftime("%d-%m-%Y")
            
        rientri = list(db.collection('clienti').document('DNR').collection('rientri ddt').stream())
        for r_doc in rientri:
            r_data = r_doc.to_dict()
            stato = str(r_data.get('stato') or r_data.get('Stato') or '').strip().lower()
            if "lavorazione" in stato:
                r_cod = str(r_data.get('codice_consegna') or r_data.get('Codice consegna') or '').strip().lower()
                if r_cod in codici_assegnati:
                    db.collection('clienti').document('DNR').collection('rientri ddt').document(r_doc.id).update({
                        "Stato": f"allegato DDT {data_giornata}",
                        "stato": firestore.DELETE_FIELD
                    })
                else:
                    db.collection('clienti').document('DNR').collection('rientri ddt').document(r_doc.id).update({
                        "Stato": "",
                        "stato": firestore.DELETE_FIELD
                    })
    except Exception as e_r:
        print(f"[WARN] Errore durante aggiornamento finale rientri: {e_r}")


    return {
        "status": "ok",
        "message": "Giornata chiusa correttamente",
        "errori": [],
        "data": {}
    }


def handle_preflight_elaborazione_mappe(data_consegna, bucket, get_tenant_from_cz_fn):
    """
    Pre-flight check per l'elaborazione mappe.
    Rileva quali blocchi hanno nuovi dati in split_ddt e se i vecchi viaggi 
    hanno contaminazioni (fornitori misti).
    Restituisce un dizionario con i dati necessari al frontend per decidere lo scenario (A, B o C).
    """
    try:
        import json
        
        if not data_consegna:
            return {"status": "errore", "message": "data_consegna mancante"}
            
        
        
        in_elaborazione = {
            "CATTEL": False,
            "GRAN_CHEF": False,
            "DAC": False,
            "DNR": False
        }
        
        # Controlliamo CATTEL
        if list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/CATTEL/ddt_estratti")):
            in_elaborazione["CATTEL"] = True
            
        # Controlliamo GRAN_CHEF
        if list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/GRAND_CHEF/ddt_estratti")):
            in_elaborazione["GRAN_CHEF"] = True
            
        # Controlliamo DAC
        if list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/DAC/ddt_estratti")):
            in_elaborazione["DAC"] = True
            
        # Controlliamo DNR (FRUTTA o LATTE)
        if list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/FRUTTA/ddt_estratti")) or \
           list(bucket.list_blobs(prefix=f"split_ddt/{data_consegna}/LATTE/ddt_estratti")):
            in_elaborazione["DNR"] = True
            
        # Troviamo quali file ddt_estratti causano l'elaborazione per usarli nel calcolo contaminazione
        ddt_presenti = [k for k, v in in_elaborazione.items() if v]

        # Adesso leggiamo i viaggi vecchi (cassaforte) per vedere se ci sono viaggi contaminati
        elaborati_esistenti = {"CATTEL": False, "GRAN_CHEF": False, "DAC": False, "DNR": False}
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
                        stop_comp = stop.get("competenze", [])
                        if stop_comp:
                            for comp in stop_comp:
                                tenants_in_trip.add(get_tenant_from_cz_fn(comp))
                        else:
                            tenants_in_trip.add(get_tenant_from_cz_fn(zona.get("cliente_zona", "")))
                        
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
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Errore interno preflight: {str(e)}"}

# ─── GESTIONE E RIPRISTINO BACKUP CACHE DISTANZE (R&D / SICUREZZA) ─────────────

