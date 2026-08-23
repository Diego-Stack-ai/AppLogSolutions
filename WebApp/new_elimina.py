@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_512, timeout_sec=300,
    cors=options.CorsOptions(cors_origins="*", cors_methods=["get", "post"]))
def elimina_giornata_logistica(req: https_fn.CallableRequest):
    """
    Funzione di Tabula Rasa o Soft Delete:
    - Se soft_delete == True: imposta solo archiviato_ui: True (mantenendo intatti i dati nel Cloud per i primi 2 mesi).
    - Se passate tipologie_da_eliminare / tenant_da_eliminare: elimina solo quelle tipologie e tenant specifici (Sovrascrittura Parziale).
    - Altrimenti (TABULA RASA): elimina completamente una giornata (incluso Storage derivato, input e locks orfani).
      Supporta modalita dry_run per preview.
    """
    import hashlib
    import json
    from datetime import datetime
    
    data_consegna = req.data.get("data_consegna")
    soft_delete = req.data.get("soft_delete", False)
    dry_run = req.data.get("dry_run", False)
    manifest_id_in = req.data.get("manifestId")
    manifest_hash_in = req.data.get("manifestHash")
    
    # Parametri per eliminazione selettiva
    tipologie_da_eliminare = req.data.get("tipologie_da_eliminare", [])
    tenant_da_eliminare = req.data.get("tenant_da_eliminare", [])
    cliente_zona_da_eliminare = req.data.get("cliente_zona_da_eliminare", [])
    
    if not data_consegna:
        return {"status": "errore", "message": "data_consegna mancante"}

    db = get_db()
    all_tenants = [doc.id for doc in db.collection('clienti').stream()]
    
    # === MODALITÀ SOFT DELETE (UI) ===
    if soft_delete:
        print(f"[INFO] Richiesta Soft Delete (pulizia UI) per la giornata {data_consegna}")
        try:
            for tenant in all_tenants:
                doc_ref = db.collection('clienti').document(tenant).collection('reports_logistici').document(data_consegna)
                if doc_ref.get().exists:
                    doc_ref.update({"archiviato_ui": True, "archiviato_at": datetime.now().isoformat()})
                
                viaggi_ref = db.collection('clienti').document(tenant).collection('viaggi ddt')
                viaggi = viaggi_ref.where("data_lavoro", "==", data_consegna).stream()
                for v in viaggi:
                    viaggi_ref.document(v.id).update({"archiviato_ui": True})
                
            return {"status": "ok", "message": "Giornata rimossa dalla schermata attiva (dati conservati su Cloud)"}
        except Exception as e:
            return {"status": "errore", "message": f"Errore Soft Delete: {str(e)}"}

    bucket = storage.bucket(name=BUCKET_NAME)

    # === ELIMINAZIONE SELETTIVA (Legacy, usata dal preflight upload) ===
    if tipologie_da_eliminare:
        print(f"[INFO] Inizio eliminazione SELETTIVA per {data_consegna}")
        try:
            prefixes_to_clean = []
            for t in tipologie_da_eliminare:
                prefixes_to_clean.append(f"split_ddt/{data_consegna}/{t.upper()}/")
            for pref in prefixes_to_clean:
                for b in bucket.list_blobs(prefix=pref):
                    try:
                        b.delete()
                    except Exception: pass
            
            for tenant in all_tenants:
                viaggi_ref = db.collection('clienti').document(tenant).collection('viaggi ddt')
                viaggi_da_eliminare = viaggi_ref.where("data_lavoro", "==", data_consegna).stream()
                for v in viaggi_da_eliminare:
                    v_cliente_zona = v.to_dict().get("cliente_zona", "")
                    should_delete = False
                    if v_cliente_zona in cliente_zona_da_eliminare:
                        should_delete = True
                    elif ("PROGETTO SCUOLE" in cliente_zona_da_eliminare or "" in cliente_zona_da_eliminare) and (not v_cliente_zona or v_cliente_zona == "PROGETTO SCUOLE"):
                        should_delete = True
                    if should_delete:
                        try:
                            trip_id = v.id
                            v.reference.delete()
                            for lk in db.collection('clienti').document(tenant).collection('trip_title_locks').where('tripId', '==', trip_id).stream():
                                lk.reference.delete()
                        except Exception: pass
                
                pian_ref = db.collection('clienti').document(tenant).collection('pianificazione_viaggi')
                for p in pian_ref.stream():
                    data = p.to_dict()
                    v_cliente_zona = data.get("cliente_zona", "")
                    if data.get("data_lavoro") == data_consegna or p.id.startswith(f"{data_consegna}_"):
                        should_delete = False
                        if v_cliente_zona in cliente_zona_da_eliminare:
                            should_delete = True
                        elif ("PROGETTO SCUOLE" in cliente_zona_da_eliminare or "" in cliente_zona_da_eliminare) and (not v_cliente_zona or v_cliente_zona == "PROGETTO SCUOLE"):
                            should_delete = True
                        if should_delete:
                            try: p.reference.delete()
                            except Exception: pass
            
            tenants_to_clean = tenant_da_eliminare if tenant_da_eliminare else all_tenants
            for t in tenants_to_clean:
                tenant = "GRAN CHEF" if t == "GRAND_CHEF" else t
                jobs_ref = db.collection('clienti').document(tenant).collection('processing_jobs')
                for oj in jobs_ref.where('data_lavoro', '==', data_consegna).stream():
                    try: oj.reference.delete()
                    except Exception: pass
            
            return {"status": "ok", "message": "Pulizia selettiva completata"}
        except Exception as e:
            return {"status": "errore", "message": f"Errore selettiva: {str(e)}"}


    # === TABULA RASA COMPLETA (Hard Delete + Manifest) ===
    print(f"[INFO] Inizio TABULA RASA per {data_consegna}")
    
    def _get_aliases(t_id):
        if t_id == 'GRAN CHEF': return ['GRAN CHEF', 'GRAN_CHEF', 'GRAND CHEF', 'GRAND_CHEF', 'GRANCHEF']
        if t_id == 'GRAND_CHEF': return ['GRAND_CHEF', 'GRAN_CHEF', 'GRAN CHEF', 'GRAND CHEF', 'GRANCHEF']
        return list(set([t_id, t_id.replace(' ', '_')]))
        
    def _canonical_hash(m):
        return hashlib.sha256(json.dumps(m, sort_keys=True).encode('utf-8')).hexdigest()
        
    def _build_manifest():
        m = {
            'firestore': [],
            'storage': [],
            'preserved': [
                {'categoria': 'customers'}, {'categoria': 'articles'}, {'categoria': 'geocoding'}, 
                {'categoria': 'workingHours'}, {'categoria': 'distanceCaches'}, {'categoria': 'configuration'}
            ]
        }
        
        # Firestore
        try:
            for doc in db.collection('processing_jobs_quarantine').where('data_lavoro', '==', data_consegna).stream():
                m['firestore'].append({'path': doc.reference.path, 'cat': 'quarantine'})
        except Exception: pass
        
        for tenant in all_tenants:
            try:
                for doc in db.collection('clienti').document(tenant).collection('processing_jobs').where('data_lavoro', '==', data_consegna).stream():
                    m['firestore'].append({'path': doc.reference.path, 'cat': 'processingJobs'})
            except Exception: pass
            
            try:
                for doc in db.collection('clienti').document(tenant).collection('viaggi ddt').where('data_lavoro', '==', data_consegna).stream():
                    m['firestore'].append({'path': doc.reference.path, 'cat': 'trips'})
            except Exception: pass
            
            try:
                for doc in db.collection('clienti').document(tenant).collection('trip_title_locks').where('data_lavoro', '==', data_consegna).stream():
                    cat = 'titleLocks' if 'tripId' in doc.to_dict() else 'orphanTitleLocks'
                    m['firestore'].append({'path': doc.reference.path, 'cat': cat})
            except Exception: pass
            
            try:
                for doc in db.collection('clienti').document(tenant).collection('pianificazione_viaggi').where('data_lavoro', '==', data_consegna).stream():
                    m['firestore'].append({'path': doc.reference.path, 'cat': 'planning'})
            except Exception: pass
            
            try:
                # Cancellazione KML Mappe
                for doc in db.collection('clienti').document(tenant).collection('mappe').where('data_consegna', '==', data_consegna).stream():
                    m['firestore'].append({'path': doc.reference.path, 'cat': 'maps'})
            except Exception: pass
            
            try:
                # Cancellazione Distinte PDF
                for doc in db.collection('clienti').document(tenant).collection('distinte').where('data_consegna', '==', data_consegna).stream():
                    m['firestore'].append({'path': doc.reference.path, 'cat': 'distinte'})
            except Exception: pass
            
            try:
                rep = db.collection('clienti').document(tenant).collection('reports_logistici').document(data_consegna).get()
                if rep.exists:
                    m['firestore'].append({'path': rep.reference.path, 'cat': 'dailyReports'})
            except Exception: pass
            
        # Storage
        data_f = data_consegna.replace('/', '-')
        search_prefixes = [f"split_ddt/{data_consegna}/", f"REPORTS/{data_consegna}/", f"CONSEGNE/CONSEGNE_{data_f}/", "input_pdf_fornitore/", "uploads/", "processing_jobs/"]
        for t in all_tenants:
            for al in _get_aliases(t):
                search_prefixes.extend([f"{al}/REPORTS/{data_consegna}/", f"{al}/CONSEGNE/CONSEGNE_{data_f}/", f"mappe/{al}/{data_consegna}/", f"distinte/{al}/{data_consegna}/"])
        
        seen_s = set()
        for pref in search_prefixes:
            try:
                for b in bucket.list_blobs(prefix=pref):
                    if b.name in seen_s: continue
                    is_input = pref in ["input_pdf_fornitore/", "uploads/", "processing_jobs/"]
                    if is_input:
                        if data_consegna not in b.name and data_f not in b.name:
                            continue # Conserviamo se non ha data esplicita (rischio)
                    cat = 'inputFiles' if is_input else 'intermediateFiles'
                    m['storage'].append({'path': b.name, 'cat': cat, 'gen': b.generation})
                    seen_s.add(b.name)
            except Exception: pass
            
        # Ordine canonico per manifest stabile
        m['firestore'].sort(key=lambda x: x['path'])
        m['storage'].sort(key=lambda x: x['path'])
        return m

    # 1. Costruzione Manifest
    manifest = _build_manifest()
    m_hash = _canonical_hash(manifest)
    m_id = "MAN_" + data_consegna
    
    if dry_run:
        return {
            "status": "ok", 
            "manifest": manifest, 
            "manifestId": m_id, 
            "manifestHash": m_hash
        }
        
    # 2. Execution (Controllo Hash)
    if not manifest_id_in or not manifest_hash_in:
        return {"status": "errore", "message": "manifestId o manifestHash mancanti per l'esecuzione tabula rasa."}
        
    if manifest_hash_in != m_hash:
        return {"status": "error", "errorCode": "MANIFEST_CHANGED", "message": "I dati sono cambiati dopo la preview. Ricaricare."}
        
    residuals = []
    
    # 3. Cancellazione Atomica (Lotti)
    print(f"[INFO] Avvio distruzione confermata per {data_consegna}")
    for item in manifest['firestore']:
        try:
            db.document(item['path']).delete()
        except Exception as e:
            residuals.append({'sistema': 'firestore', 'path': item['path'], 'error': str(e)})
            
    for item in manifest['storage']:
        try:
            b = bucket.blob(item['path'], generation=item.get('gen'))
            b.delete(if_generation_match=item.get('gen'))
        except Exception as e:
            # Ignoriamo il caso in cui il blob non esiste gia (404)
            if "No such object" not in str(e) and "404" not in str(e):
                residuals.append({'sistema': 'storage', 'path': item['path'], 'error': str(e)})
            
    # 4. Audit Post-Cancellazione
    post_manifest = _build_manifest()
    has_residuals = len(post_manifest['firestore']) > 0 or len(post_manifest['storage']) > 0
    
    # Rimuoviamo i residui gia notificati nel manifest attuale che magari non esistevano piu
    if residuals or has_residuals:
        return {
            "status": "partial",
            "errorCode": "CLEANUP_PARTIAL",
            "message": "Rimossi parzialmente.",
            "residuals": residuals,
            "post_manifest": post_manifest
        }
        
    return {
        "status": "success",
        "message": "Tabula Rasa completata con ZERO residui.",
        "deleted": {
            "firestore": len(manifest['firestore']),
            "storage": len(manifest['storage'])
        },
        "preserved": True
    }
