from firebase_admin import firestore
from firebase_functions import https_fn
from infrastructure.firebase_setup import get_db
import typing
import json
from firebase_admin import storage

def handle_rilascia_recupero_storico(req: https_fn.CallableRequest) -> typing.Any:
    """
    Elimina i record temporanei creati per l'R&D in viaggi ddt e reports_logistici.
    """
    data_consegna = req.data.get("data_consegna")
    if not data_consegna:
        return {"status": "errore", "message": "data_consegna mancante"}
        
    print(f"[R&D RILASCIO] Pulizia record sandbox per {data_consegna}...")
    db = get_db()
    
    try:
        # Elimina da reports_logistici se is_recupero_rd == True
        rep_ref = db.collection('clienti').document('report_logistici').collection('giornate').document(data_consegna)
        doc = rep_ref.get()
        if doc.exists and doc.to_dict().get("is_recupero_rd", False):
            rep_ref.delete()
            
        # Elimina da viaggi ddt in tutti i tenant
        try:
            tenants = [doc.id for doc in db.collection('clienti').list_documents() if doc.id != "report_logistici"]
        except:
            tenants = ["DNR", "CATTEL", "GRAN CHEF", "BAUER", "DAC"]
            
        count = 0
        for t in tenants:
            viaggi_ref = db.collection('clienti').document(t).collection('viaggi ddt')
            viaggi = viaggi_ref.where("data_lavoro", "==", data_consegna).where("is_recupero_rd", "==", True).stream()
            for v in viaggi:
                viaggi_ref.document(v.id).delete()
                count += 1
            
        print(f"[R&D RILASCIO] ✓ Pulizia completata per {data_consegna}. {count} record eliminati.")
        return {"status": "ok", "message": f"Sessione di studio per il {data_consegna} conclusa e ripulita con successo."}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "errore", "message": f"Errore rilascio sandbox: {str(e)}"}


def handle_recupera_viaggio_storico(req: https_fn.CallableRequest, tenant_resolver, bucket_name) -> typing.Any:
    azione = req.data.get("azione", "lista_mesi")
    mese = req.data.get("mese")
    data_consegna = req.data.get("data_consegna")
    
    db = get_db()
    bucket = storage.bucket(name=bucket_name)
    
    if azione == "lista_mesi":
        # Trova i mesi disponibili analizzando i prefissi
        blobs = bucket.list_blobs(prefix="ARCHIVIO_STORICO_RD/")
        mesi_set = set()
        for b in blobs:
            parts = b.name.split('/')
            if len(parts) > 1 and parts[1]:
                mesi_set.add(parts[1])
        mesi_list = sorted(list(mesi_set), reverse=True)
        return {"status": "ok", "mesi": mesi_list}
        
    elif azione == "lista_giornate":
        if not mese:
            return {"status": "errore", "message": "Mese non specificato"}
        blobs = bucket.list_blobs(prefix=f"ARCHIVIO_STORICO_RD/{mese}/")
        date_set = set()
        for b in blobs:
            parts = b.name.split('/')
            if len(parts) > 2 and parts[2]:
                date_set.add(parts[2])
        date_list = sorted(list(date_set), reverse=True)
        return {"status": "ok", "giornate": date_list}
        
    elif azione == "recupera":
        if not mese or not data_consegna:
            return {"status": "errore", "message": "Mese o data mancante per il ripristino"}
            
        print(f"[R&D RECUPERO] Avvio ripristino sandbox per {data_consegna} ({mese})...")
        pref_dest = f"ARCHIVIO_STORICO_RD/{mese}/{data_consegna}"
        
        try:
            # 1. Ripristina report logistico (se necessario)
            rep_blob = bucket.blob(f"{pref_dest}/firestore_report.json")
            if rep_blob.exists():
                rep_data = json.loads(rep_blob.download_as_string().decode('utf-8'))
                rep_data["is_recupero_rd"] = True
                rep_data["archiviato_ui"] = False
                db.collection('clienti').document('report_logistici').collection('giornate').document(data_consegna).set(rep_data)
                
            # 2. Ripristina tutti i viaggi ddt associati sotto i rispettivi tenant
            viaggi_pref = f"{pref_dest}/viaggi_ddt/"
            blobs = bucket.list_blobs(prefix=viaggi_pref)
            
            count = 0
            for b in blobs:
                if b.name.endswith(".json"):
                    v_data = json.loads(b.download_as_string().decode('utf-8'))
                    v_data["is_recupero_rd"] = True
                    v_data["archiviato_ui"] = False
                    # Ricava l'id del documento dal nome file
                    doc_id = b.name.split('/')[-1].replace('.json', '')
                    t_viaggio = tenant_resolver(doc_id) or "DNR"
                    db.collection('clienti').document(t_viaggio).collection('viaggi ddt').document(doc_id).set(v_data)
                    count += 1
                    
            print(f"[R&D RECUPERO] ✓ Ripristino completato per {data_consegna}. {count} viaggi ddt ripristinati in sandbox.")
            return {"status": "ok", "message": f"Viaggio {data_consegna} ripristinato in Sandbox R&D ({count} zone attive).", "viaggi_ripristinati": count}
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"status": "errore", "message": f"Errore ripristino sandbox: {str(e)}"}
            
    return {"status": "errore", "message": "Azione non riconosciuta"}





def handle_ripristina_cache_backup(req: https_fn.CallableRequest):
    """
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
