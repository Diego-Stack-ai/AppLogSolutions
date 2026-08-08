def handle_pulisci_cartelle_elaborazione(data_consegna, tipologie, bucket, db):
    try:
        if not data_consegna:
            return {"status": "errore", "message": "Data non fornita"}
            
        for t in tipologie:
            cart_out_base = f"split_ddt/{data_consegna}/{t.upper()}/"
            blobs = bucket.list_blobs(prefix=cart_out_base)
            for b in blobs:
                try:
                    b.delete()
                except Exception:
                    pass
                    
            tenant = "GRAN CHEF" if t.upper() == "GRAND_CHEF" else ("CATTEL" if t.upper() == "CATTEL" else ("DAC" if t.upper() == "DAC" else "DNR"))
            jobs_ref = db.collection('clienti').document(tenant).collection('processing_jobs')
            old_jobs = jobs_ref.where('data_lavoro', '==', data_consegna).stream()
            for oj in old_jobs:
                try:
                    oj.reference.delete()
                except Exception:
                    pass
                    
        return {"status": "ok", "message": f"Pulizia completata per {data_consegna}"}
    except Exception as e:
        return {"status": "errore", "message": str(e)}
