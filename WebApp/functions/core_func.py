def core_genera_report_giornaliero(uid, data_consegna, azioni=None):
    if azioni is None: azioni = {}
    """
    Implementa gli step 2, 3 e 4 del workflow locale:
    - Aggrega i DDT per la data indicata (Step 2)
    - Crea la struttura della Lista Unificata (Step 3)
    - Genera la Mappa Generale delle Zone HTML (Step 4)
    """
    start_time = time.time()
    db = get_db()
    bucket = storage.bucket(name=BUCKET_NAME)
    if not data_consegna:
        return {"status": "errore", "message": "Data mancante"}

    print(f"[INFO] Generazione report per il {data_consegna}")
    
    # 0.5. Sovrascrittura Selettiva (Elimina i viaggi Firestore per i tenant che vogliamo sovrascrivere)
    for tenant_key, azione in azioni.items():
        if azione == "sovrascrivi":
            print(f"[INFO] Sovrascrittura richiesta per {tenant_key}. Eliminazione vecchi viaggi...")
            try:
                viaggi_ref = db.collection('clienti').document('DNR').collection('viaggi ddt')
                viaggi = viaggi_ref.where("data_lavoro", "==", data_consegna).stream()
                for v in viaggi:
                    cz = v.to_dict().get("cliente_zona", "")
                    should_delete = False
                    if tenant_key == "CATTEL" and cz == "CATTEL": should_delete = True
                    elif tenant_key == "GRAN_CHEF" and cz == "GRAN CHEF": should_delete = True
                    elif tenant_key == "DNR" and (cz == "PROGETTO SCUOLE" or not cz): should_delete = True
                    if should_delete:
                        v.reference.delete()
            except Exception as e:
                print(f"[ERROR] Sovrascrittura {tenant_key} fallita: {e}")
    
    # PRE-SALVATAGGIO: Leggi i viaggi esistenti prima di cancellarli, per mantenere i percorsi calcolati (Integrazione CATTEL/GC)
    import json
    mappa_zone_esistenti = {}
    try:
        blob_old_json = bucket.blob(f"REPORTS/{data_consegna}/viaggi_giornalieri_Johnson.json")
        if blob_old_json.exists():
            old_data = json.loads(blob_old_json.download_as_string().decode('utf-8'))
            old_zones = old_data.get("zone", []) if isinstance(old_data, dict) else old_data
            for z in old_zones:
                mappa_zone_esistenti[z.get("id_zona")] = z
    except Exception as e_old:
        print(f"[WARN] Impossibile leggere il vecchio viaggi_giornalieri_Johnson.json: {e_old}")

    # 0. Svuota le vecchie cartelle nello Storage per evitare doppioni
    try:
        data_f = data_consegna.replace('/', '-')
        prefixes_to_clean = [
            f"REPORTS/{data_consegna}/",
            f"CONSEGNE/CONSEGNE_{data_f}/"
        ]
        for pref in prefixes_to_clean:
            blobs_old = bucket.list_blobs(prefix=pref)
            for b_old in blobs_old:
                try: b_old.delete()
                except: pass
        print(f"[INFO] Pulizia cartelle completata per {data_consegna}")
    except Exception as e_clean:
        print(f"[WARN] Impossibile pulire cartelle storage: {e_clean}")
    
    # 1. Recupera i DDT scansionando la cartella dello Storage
    ddt_list = []
    prefix_search = f"split_ddt/{data_consegna}/"
    print(f"[INFO] Scansione Storage per data {data_consegna}...")
    
    try:
        # Caricamento bulk clienti da DNR, GRAN CHEF e CATTEL per evitare timeout (Deadline Exceeded)
        db_mappati = {}
        for current_tenant in ['DNR', 'GRAN CHEF', 'CATTEL']:
            clienti_ref = db.collection('clienti').document(current_tenant).collection('raccolta clienti')
            for doc in clienti_ref.stream():
                d = doc.to_dict()
                cf = str(d.get('codice_frutta') or '').strip().lower()
                cl = str(d.get('codice_latte') or '').strip().lower()
                if cf and cf != 'p00000' and cf != 'nan': db_mappati[cf] = d
                if cl and cl != 'p00000' and cl != 'nan': db_mappati[cl] = d

        blobs = bucket.list_blobs(prefix=prefix_search)
        for blob in blobs:
            if "ddt_estratti" in blob.name and blob.name.endswith(".json"):
                print(f"[INFO] Leggo file: {blob.name}")
                try:
                    meta_data = json.loads(blob.download_as_string())
                    job_competenza = meta_data.get("competenza") or meta_data.get("tipo", "FRUTTA").upper()
                    if job_competenza in ("GRAND_CHEF", "GRAND CHEF", "GRAN CHEF"):
                        job_competenza = "GRAN_CHEF"
                    for ddt in meta_data.get("deliveries", []):
                        cod = ddt.get("codice_consegna")
                        cod_l = str(cod).strip().lower()
                        cliente_info = db_mappati.get(cod_l)
                        
                        if cliente_info:
                            ddt["nome"] = cliente_info.get('cliente') or cliente_info.get('nome_consegna') or cod
                        else:
                            ddt["nome"] = cod
                        ddt["competenza"] = ddt.get("competenza") or job_competenza
                        ddt_list.append(ddt)
                except Exception as e_read:
                    print(f"[ERROR] Impossibile leggere {blob.name}: {e_read}")
    except Exception as e_list:
        print(f"[ERROR] Errore scansione storage: {e_list}")

    if not ddt_list:
        # Debug Radar: vediamo cosa c'e' effettivamente nello Storage
        cercati = [f"split_ddt/{data_consegna}/**/ddt_estratti_*.json"]
        try:
            prefix_check = f"split_ddt/{data_consegna}/"
            blobs_esistenti = list(bucket.list_blobs(prefix=prefix_check))
            files_trovati = [b.name for b in blobs_esistenti]
            msg = f"Nessun dato trovato per il {data_consegna}. Percorsi attesi: {', '.join(cercati)}. Nello Storage vedo: {', '.join(files_trovati) if files_trovati else 'NULLA'}"
        except Exception as e_debug:
            msg = f"Nessun dato trovato per il {data_consegna} e errore durante il radar: {e_debug}"
            
        print(f"[ERROR] {msg}")
        return {"status": "errore", "message": msg}

    # 2. Aggrega per cliente (Step 2 locale)
    punti_map = {} # chiave: tripla_chiave o codice_cliente
    for ddt in ddt_list:
        cod = ddt.get('codice_consegna')
        cod_l = str(cod).strip().lower()
        tipo = ddt.get('tipo', 'FRUTTA')
        competenza = ddt.get('competenza') or tipo
        
        # Cerchiamo il cliente nel dizionario pre-caricato
        cliente_info = db_mappati.get(cod_l)
        nome = ddt.get('nome', cod)
        
        # Identificativo unico del punto di consegna (per evitare duplicati nello stesso giro)
        # Calcola dinamicamente la tripla_chiave usando l'anagrafica cliente unificata per garantire il consolidamento
        if cliente_info:
            cf_key = str(cliente_info.get('codice_frutta') or 'p00000').strip().lower()
            cl_key = str(cliente_info.get('codice_latte') or 'p00000').strip().lower()
            nome_key = cliente_info.get('cliente') or cliente_info.get('nome_consegna') or nome
            chiave = _build_tripla_chiave(cf_key, cl_key, nome_key)
        else:
            chiave = ddt.get('tripla_chiave') or cod
        
        cf_val = (cliente_info.get('codice_frutta') or 'p00000') if cliente_info else (cod if tipo == 'FRUTTA' else 'p00000')
        cl_val = (cliente_info.get('codice_latte') or 'p00000') if cliente_info else (cod if tipo == 'LATTE' else 'p00000')
        
        prov_code = ""
        full_ind = ""
        citta_val = ""
        
        if cliente_info:
            prov_raw = str(cliente_info.get('provincia') or cliente_info.get('prov') or '').upper().strip()
            prov_map = {
                "BRESCIA": "BS", "VERONA": "VR", "MANTOVA": "MN", "PADOVA": "PD",
                "VICENZA": "VI", "BELLUNO": "BL", "UDINE": "UD", "TREVISO": "TV",
                "VENEZIA": "VE", "ROVIGO": "RO"
            }
            prov_code = prov_map.get(prov_raw, prov_raw)
            if len(prov_code) > 2:
                prov_code = prov_code[:2]
                
            citta_val = str(cliente_info.get('citta') or '').strip()
            ind_val = str(cliente_info.get('indirizzo') or '').strip()
            
            ind_parts = [ind_val]
            if citta_val:
                ind_parts.append(citta_val)
            full_ind = ", ".join([p for p in ind_parts if p])
            if prov_code:
                full_ind += f" ({prov_code})"
        else:
            full_ind = ddt.get('indirizzo', '')
            
        note_val = ""
        tel_val = ""
        om_frutta = ""
        oM_frutta = ""
        om_latte = ""
        oM_latte = ""
        om_val = ""
        oM_val = ""
        
        if cliente_info:
            note_val = str(cliente_info.get("note", cliente_info.get("nota_integrativa", cliente_info.get("Note", ""))) or "").strip()
            tel_val = str(cliente_info.get("telefono", cliente_info.get("tel", cliente_info.get("phone", ""))) or "").strip()
            om_frutta = str(cliente_info.get("orario_min_frutta") or "").strip()
            oM_frutta = str(cliente_info.get("orario_max_frutta") or "").strip()
            om_latte = str(cliente_info.get("orario_min_latte") or "").strip()
            oM_latte = str(cliente_info.get("orario_max_latte") or "").strip()
            
            # Clean "nan"
            if note_val.lower() == "nan": note_val = ""
            if tel_val.lower() == "nan": tel_val = ""
            if om_frutta.lower() == "nan": om_frutta = ""
            if oM_frutta.lower() == "nan": oM_frutta = ""
            if om_latte.lower() == "nan": om_latte = ""
            if oM_latte.lower() == "nan": oM_latte = ""
            
            # Determina orario_min/max per il tipo
            if tipo == "FRUTTA":
                om_val = om_frutta if om_frutta else (str(cliente_info.get("orario_min") or "").strip())
                oM_val = oM_frutta if oM_frutta else (str(cliente_info.get("orario_max") or "").strip())
            else:
                om_val = om_latte if om_latte else (str(cliente_info.get("orario_min") or "").strip())
                oM_val = oM_latte if oM_latte else (str(cliente_info.get("orario_max") or "").strip())
                
            if om_val.lower() == "nan": om_val = ""
            if oM_val.lower() == "nan": oM_val = ""
            
        # Sovrascrivi o imposta orari/note se presenti nel ddt
        if ddt.get("orario_min"):
            om_val = str(ddt["orario_min"]).strip()
        if ddt.get("orario_max"):
            oM_val = str(ddt["orario_max"]).strip()
        if ddt.get("note"):
            note_val = str(ddt["note"]).strip()

        if chiave not in punti_map:
            punti_map[chiave] = {
                "nome": nome,
                "indirizzo": full_ind,
                "provincia": prov_code,
                "prov": prov_code,
                "citta": citta_val,
                "codice_frutta": cf_val,
                "codice_latte": cl_val,
                "codici_ddt_frutta": [],
                "codici_ddt_latte": [],
                "zona": ddt.get('zona') or ((cliente_info.get('codice_zona') or cliente_info.get('zona') or '0000') if cliente_info else '0000'),
                "lat": float(cliente_info.get('lat', 0)) if cliente_info and cliente_info.get('lat') else 0,
                "lon": float(cliente_info.get('lon', 0)) if cliente_info and cliente_info.get('lon') else 0,
                "rientri_alert": [],
                "tipologia_grado": cliente_info.get('tipologia_grado', '') if cliente_info else ('GRAND CHEF' if tipo == 'GRAND_CHEF' else ''),
                "tipo": tipo,
                "competenze": [],
                "gc_colli": ddt.get("gc_colli", ""),
                "gc_peso_kg": ddt.get("gc_peso_kg", ""),
                "gc_num_cartone": ddt.get("gc_num_cartone", ""),
                "orario_min_frutta": om_frutta,
                "orario_max_frutta": oM_frutta,
                "orario_min_latte": om_latte,
                "orario_max_latte": oM_latte,
                "orario_min": om_val,
                "orario_max": oM_val,
                "note": note_val,
                "telefono": tel_val
            }
        else:
            # Se esiste già, aggiorna i codici reali se quello preesistente era fittizio/vuoto
            esistente = punti_map[chiave]
            if cf_val != 'p00000' and esistente["codice_frutta"] == 'p00000':
                esistente["codice_frutta"] = cf_val
            if cl_val != 'p00000' and esistente["codice_latte"] == 'p00000':
                esistente["codice_latte"] = cl_val
            if ddt.get("gc_colli"): esistente["gc_colli"] = ddt.get("gc_colli")
            if ddt.get("gc_peso_kg"): esistente["gc_peso_kg"] = ddt.get("gc_peso_kg")
            if ddt.get("gc_num_cartone"): esistente["gc_num_cartone"] = ddt.get("gc_num_cartone")
            if tipo == 'GRAND_CHEF':
                esistente["tipo"] = 'GRAND_CHEF'
                if not esistente.get("tipologia_grado"):
                    esistente["tipologia_grado"] = 'GRAND CHEF'
            
            # Aggiorna orari/note/telefono se mancanti
            if not esistente.get("orario_min") and om_val:
                esistente["orario_min"] = om_val
            if not esistente.get("orario_max") and oM_val:
                esistente["orario_max"] = oM_val
            if not esistente.get("note") and note_val:
                esistente["note"] = note_val
            if not esistente.get("telefono") and tel_val:
                esistente["telefono"] = tel_val
        
        if tipo == 'FRUTTA':
            punti_map[chiave]["codici_ddt_frutta"].append(ddt.get('num_ddt', 'UNK'))
        else:
            punti_map[chiave]["codici_ddt_latte"].append(ddt.get('num_ddt', 'UNK'))
            
        # Registra la competenza del DDT nel punto consolidato
        if "competenze" not in punti_map[chiave]:
            punti_map[chiave]["competenze"] = []
        if competenza not in punti_map[chiave]["competenze"]:
            punti_map[chiave]["competenze"].append(competenza)

    # --- INTEGRAZIONE RIENTRI DDT ---
    try:
        # Interroga direttamente la collezione 'rientri ddt' per garantire consistenza con il frontend
        rientri_ref = db.collection('clienti').document('DNR').collection('rientri ddt')
        
        for r_doc in rientri_ref.stream():
            r_data = r_doc.to_dict() or {}
            stato = str(r_data.get('stato') or r_data.get('Stato') or '').strip().lower()
            
            # Ignora se già allegato a una data diversa da quella in elaborazione
            if 'allegato' in stato and data_consegna not in stato:
                continue
                
            r_cod = str(r_data.get('codice_consegna') or r_data.get('Codice consegna') or '').strip()
            if not r_cod: continue
            r_data_ddt = r_data.get('data_ddt') or r_data.get('Data e Num DDT') or ''
            r_cod_l = r_cod.lower()
            
            # Cerca match tra le consegne odierne
            chiave_esistente = None
            for k in punti_map.keys():
                if str(k).strip().lower() == r_cod_l:
                    chiave_esistente = k
                    break
                    
            stato_attuale = str(r_data.get('stato') or r_data.get('Stato') or '')
            nuovo_stato = ""
            
            tipo_val = str(r_data.get('Tipo') or r_data.get('tipo') or '').lower().strip()
            is_parz = bool(r_data.get('is_parziale') or False) or (tipo_val == 'parziale')
            note_val = str(r_data.get('note') or r_data.get('Note') or r_data.get('nota_integrativa') or '').strip()
            
            rientro_obj = {
                "codice": r_cod,
                "status": "red",
                "data_ddt": r_data_ddt,
                "is_parziale": is_parz,
                "nota_integrativa": note_val
            }
            
            if chiave_esistente:
                punti_map[chiave_esistente]['rientri_alert'].append(rientro_obj)
                nuovo_stato = f"allegato DDT {data_consegna}"
            else:
                # Crea punto isolato in zona speciale
                cliente_info = db_mappati.get(r_cod_l)
                if r_cod not in punti_map:
                    punti_map[r_cod] = {
                        "nome": (cliente_info.get('cliente') or cliente_info.get('nome_consegna') or r_cod) if cliente_info else r_cod,
                        "indirizzo": cliente_info.get('indirizzo', '') if cliente_info else '',
                        "codice_frutta": cliente_info.get('codice_frutta', 'p00000') if cliente_info else 'p00000',
                        "codice_latte": cliente_info.get('codice_latte', 'p00000') if cliente_info else 'p00000',
                        "codici_ddt_frutta": [],
                        "codici_ddt_latte": [],
                        "zona": "PUNTI_DI_CONSEGNA",
                        "lat": float(cliente_info.get('lat', 0)) if cliente_info and cliente_info.get('lat') else 0,
                        "lon": float(cliente_info.get('lon', 0)) if cliente_info and cliente_info.get('lon') else 0,
                        "rientri_alert": [],
                        "_is_rientro_speciale": True
                    }
                punti_map[r_cod]['rientri_alert'].append(rientro_obj)
                nuovo_stato = "In lavorazione"
                
            # Aggiorna DB se lo stato è cambiato
            if stato_attuale != nuovo_stato:
                try:
                    db.collection('clienti').document('DNR').collection('rientri ddt').document(r_doc.id).update({
                        'Stato': nuovo_stato,
                        'stato': firestore.DELETE_FIELD
                    })
                except Exception as e_up:
                    print(f"[WARN] Impossibile aggiornare stato rientro {r_doc.id}: {e_up}")
    except Exception as e_r:
        print(f"[ERROR] Errore integrazione rientri: {e_r}")

    # 3. Organizza per Zone (Step 4 locale) e Smart Diff
    zone_finali = []
    
    # 3.1. Costruisci mappa di lookup per le chiavi
    punti_lookup = {}
    for k, p_raw in punti_map.items():
        tc = _build_tripla_chiave(p_raw.get("codice_frutta", "p00000"), p_raw.get("codice_latte", "p00000"), p_raw.get("nome", ""))
        punti_lookup[tc] = k
        p_raw["_assegnato_integrazione"] = False

    color_index = 0
    palette = ["#4f46e5", "#10b981", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1", "#a855f7", "#3b82f6", "#22c55e", "#d946ef", "#84cc16"]

    # 3.2. Integrazione Viaggi Esistenti
    for zid, old_z in mappa_zone_esistenti.items():
        cz = old_z.get("cliente_zona", "")
        tenant_key = "DNR" if (cz == "PROGETTO SCUOLE" or not cz) else cz
        if tenant_key == "GRAN CHEF": tenant_key = "GRAN_CHEF"
        
        azione = azioni.get(tenant_key, "sovrascrivi")
        if azione == "sovrascrivi":
            continue # Salta i viaggi da sovrascrivere (saranno ricreati da zero)
            
        # INTEGRAZIONE SMART DIFF
        nuova_lista_punti = []
        for p in old_z.get("lista_punti", []):
            tc_old = p.get("tripla_chiave") or _build_tripla_chiave(p.get("codice_frutta", "p00000"), p.get("codice_latte", "p00000"), p.get("nome", ""))
            real_key = punti_lookup.get(tc_old)
            if real_key:
                # Il punto esiste ancora nei dati odierni
                dati_freschi = punti_map[real_key]
                p_aggiornato = dict(p) # copia
                # Trasferisci i dati freschi che potrebbero essere cambiati (DDT, colli, etc)
                p_aggiornato["codici_ddt_frutta"] = dati_freschi.get("codici_ddt_frutta", [])
                p_aggiornato["codici_ddt_latte"] = dati_freschi.get("codici_ddt_latte", [])
                p_aggiornato["gc_colli"] = dati_freschi.get("gc_colli", "")
                p_aggiornato["gc_peso_kg"] = dati_freschi.get("gc_peso_kg", "")
                p_aggiornato["gc_num_cartone"] = dati_freschi.get("gc_num_cartone", "")
                
                nuova_lista_punti.append(p_aggiornato)
                dati_freschi["_assegnato_integrazione"] = True

        if nuova_lista_punti:
            old_z_copy = dict(old_z)
            old_z_copy["lista_punti"] = nuova_lista_punti
            zone_finali.append(old_z_copy)
            color_index += 1

    # 3.3. Raggruppa i punti rimanenti (NON assegnati in integrazione)
    zone_dict = defaultdict(list)
    punti_di_consegna_list = []
    
    for p in punti_map.values():
        if p.get("_assegnato_integrazione"):
            continue # Già piazzato in un viaggio integrato
            
        # Determina il tenant per capire se è un punto nuovo di una zona integrata
        tipo = p.get("tipo", "")
        cz = p.get("cliente_zona", "")
        tenant_key = "DNR"
        if cz == "CATTEL" or p.get("is_cattel"): tenant_key = "CATTEL"
        elif tipo == "GRAND_CHEF" or p.get("is_gc"): tenant_key = "GRAN_CHEF"
        
        azione = azioni.get(tenant_key, "sovrascrivi")
        
        if azione == "integra":
            # È un punto NUOVO in un tenant che stiamo integrando -> Va in PUNTI DI CONSEGNA
            punti_di_consegna_list.append(p)
        else:
            # È un punto di un tenant da sovrascrivere (o default) -> Raggruppa normalmente
            z_id = p.get("zona", "0000")
            if not z_id: z_id = "0000"
            zone_dict[z_id].append(p)

    # 3.4. Costruisci Zone Normali per i punti NON integrati (Sovrascrivi)
    dnr_keys = sorted([k for k in zone_dict.keys() if k not in ("DDT_DA_INSERIRE", "PUNTI_DI_CONSEGNA", "0000", "SENZA_ZONA") and not k.startswith("GC_") and not k.startswith("CATTEL_") and not k.startswith("BAUER_")])
    cattel_keys = sorted([k for k in zone_dict.keys() if k.startswith("CATTEL_")])
    bauer_keys = sorted([k for k in zone_dict.keys() if k.startswith("BAUER_")])
    gc_keys = [k for k in zone_dict.keys() if k.startswith("GC_")]
    
    gc_job_ids = [k[3:] for k in gc_keys]
    sorted_job_ids = _ordina_job_ids_gc(gc_job_ids)
    sorted_gc_keys = [f"GC_{jid}" for jid in sorted_job_ids]
    
    for idx_dnr, zid in enumerate(dnr_keys, start=1):
        zone_finali.append({
            "id_zona": zid, "nome_giro": f"V{idx_dnr:02d}", "color": palette[color_index % len(palette)],
            "lista_punti": zone_dict[zid], "cliente_zona": "PROGETTO SCUOLE"
        })
        color_index += 1
        
    for idx_cattel, zid in enumerate(cattel_keys, start=1):
        parts = zid.split('_')
        targa_label = parts[1] if len(parts) > 2 else f"Viaggio {idx_cattel}"
        zone_finali.append({
            "id_zona": zid, "nome_giro": f"Cattel {targa_label}", "color": palette[color_index % len(palette)],
            "lista_punti": zone_dict[zid], "is_cattel": True, "cliente_zona": "CATTEL"
        })
        color_index += 1
        
    for idx_bauer, zid in enumerate(bauer_keys, start=1):
        parts = zid.split('_')
        targa_label = parts[1] if len(parts) > 2 else f"Viaggio {idx_bauer}"
        zone_finali.append({
            "id_zona": zid, "nome_giro": f"Bauer {targa_label}", "color": palette[color_index % len(palette)],
            "lista_punti": zone_dict[zid], "is_bauer": True, "cliente_zona": "BAUER"
        })
        color_index += 1
        
    for idx_gc, zid in enumerate(sorted_gc_keys, start=1):
        zone_finali.append({
            "id_zona": zid, "nome_giro": f"Viaggio {idx_gc} Grand Chef", "color": palette[color_index % len(palette)],
            "lista_punti": zone_dict[zid], "is_gc": True, "cliente_zona": "GRAN CHEF"
        })
        color_index += 1
        
    for zid in ["0000", "SENZA_ZONA"]:
        if zid in zone_dict:
            zone_finali.append({
                "id_zona": zid, "nome_giro": "SENZA ZONA", "color": "#9ca3af",
                "lista_punti": zone_dict[zid]
            })
            
    # Aggiungi eventuali punti PUNTI DI CONSEGNA derivanti dall'integrazione o vecchi DDT_DA_INSERIRE
    if "DDT_DA_INSERIRE" in zone_dict:
        punti_di_consegna_list.extend(zone_dict["DDT_DA_INSERIRE"])
    if "PUNTI_DI_CONSEGNA" in zone_dict:
        punti_di_consegna_list.extend(zone_dict["PUNTI_DI_CONSEGNA"])
        
    if punti_di_consegna_list:
        zone_finali.append({
            "id_zona": "PUNTI_DI_CONSEGNA",
            "nome_giro": "⚠️ PUNTI DI CONSEGNA",
            "color": "#f59e0b",
            "lista_punti": punti_di_consegna_list
        })

    # 4. Salvataggio file JSON storici nello Storage (Standard Johnson)
    path_base = f"REPORTS/{data_consegna}"
    
    # punti_consegna.json
    bucket.blob(f"{path_base}/punti_consegna.json").upload_from_string(
        json.dumps(list(punti_map.values()), indent=2), content_type='application/json'
    )
    
    # punti_consegna_unificati_Johnson.json
    bucket.blob(f"{path_base}/punti_consegna_unificati_Johnson.json").upload_from_string(
        json.dumps(list(punti_map.values()), indent=2), content_type='application/json'
    )
    
    # viaggi_giornalieri_Johnson.json
    # Determina il cliente in base alle zone elaborate:
    # - Se ci sono zone GC_ (Gran Chef) → cliente = "GRAN CHEF"
    # - Altrimenti → cliente = "PROGETTO SCUOLE" (DNR)
    has_gc_zones = any(z.get("id_zona", "").startswith("GC_") for z in zone_finali)
    cliente_progetto = "GRAN CHEF" if has_gc_zones else "PROGETTO SCUOLE"
    
    # Wrapper con metadato cliente per la mappa (compatibile retroattivamente:
    # la mappa legge .zone se presente, oppure tratta il JSON come array diretto)
    viaggi_payload = {
        "cliente": cliente_progetto,
        "zone": zone_finali
    }
    bucket.blob(f"{path_base}/viaggi_giornalieri_Johnson.json").upload_from_string(
        json.dumps(viaggi_payload, indent=2), content_type='application/json'
    )

    # 5. Genera KML (zona_google_{data}.kml)
    kml_content = _genera_kml_zone(data_consegna, zone_finali)
    bucket.blob(f"{path_base}/zona_google_{data_consegna}.kml").upload_from_string(
        kml_content.encode('utf-8'), content_type='application/vnd.google-earth.kml+xml'
    )

    # 6. Genera HTML Mappa Generale (4_mappa_zone_google.html)
    html_mappa = _genera_html_mappa_generale(data_consegna, zone_finali)
    path_mappa = f"{path_base}/4_mappa_zone_google.html"
    blob_mappa = bucket.blob(path_mappa)
    blob_mappa.upload_from_string(html_mappa.encode('utf-8'), content_type='text/html')
    
    # 7. Registra il report su Firestore
    report_meta = {
        "data_consegna": data_consegna,
        "punti_totali": len(punti_map),
        "zone_totali": len(zone_finali),
        "mappa_url": blob_mappa.public_url,
        "created_at": firestore.SERVER_TIMESTAMP,
        "tipo": "REPORT_GENERALE"
    }
    db.collection('clienti').document('DNR').collection('reports_logistici').document(data_consegna).set(report_meta)
    
    elapsed = time.time() - start_time
    _registra_statistica('genera_report_generale', elapsed)
    
    # Safe return object (SERVER_TIMESTAMP is not JSON serializable)
    return_meta = report_meta.copy()
    return_meta["created_at"] = "timestamp"
    
    return {
        "status": "ok",
        "message": "Report Johnson generato con successo",
        "data": return_meta
    }