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
