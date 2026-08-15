from firebase_admin import firestore
import datetime
from firebase_functions import https_fn

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


from infrastructure.firebase_setup import get_db
from firebase_admin import storage, firestore
from datetime import datetime
from infrastructure.firebase_setup import BUCKET_NAME

def handle_elimina_giornata_logistica(req: https_fn.CallableRequest):
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


def handle_gestisci_archiviazione_mensile(req: https_fn.CallableRequest):
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

