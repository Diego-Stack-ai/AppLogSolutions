def handle_risolvi_tenant_consegna(codice_consegna: str, db) -> dict:
    """
    Risolve il tenant logistico in base al codice consegna cercando
    dinamicamente su tutte le anagrafiche.
    Ritorna:
      - {"status": "ok", "tenant": "NOME"} (se univoco)
      - {"status": "error", "message": "CODICE_NON_TROVATO"}
      - {"status": "error", "message": "CODICE_AMBIGUO"}
    """
    codice = str(codice_consegna).strip().lower()
    if not codice:
        return {"status": "error", "message": "CODICE_NON_TROVATO"}
        
    tenants_list = [doc.id for doc in db.collection('clienti').list_documents()]
    
    matches = []
    
    for t in tenants_list:
        coll_ref = db.collection('clienti').document(t).collection('raccolta clienti')
        # Prova lookup diretto su ID document
        doc_snap = coll_ref.document(codice).get()
        if doc_snap.exists:
            matches.append(t)
            continue
            
        # Ricerca per codice frutta
        frutta_snap = coll_ref.where('codice_frutta', '==', codice).limit(1).get()
        if len(frutta_snap) > 0:
            matches.append(t)
            continue
            
        # Ricerca per codice latte
        latte_snap = coll_ref.where('codice_latte', '==', codice).limit(1).get()
        if len(latte_snap) > 0:
            matches.append(t)
            continue
            
    matches = list(set(matches))
    
    if len(matches) == 0:
        return {"status": "error", "message": "CODICE_NON_TROVATO"}
    elif len(matches) == 1:
        return {"status": "ok", "tenant": matches[0]}
    else:
        return {"status": "error", "message": "CODICE_AMBIGUO"}
