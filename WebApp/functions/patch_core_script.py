import sys
import re

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

def find_block(text, start_str):
    idx = text.find(start_str)
    if idx == -1: return None, -1, -1
    
    lines = text[idx:].split('\n')
    indent = len(lines[0]) - len(lines[0].lstrip())
    
    end_idx = idx
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            end_idx += len(line) + 1
            continue
            
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= indent:
            break
        end_idx += len(line) + 1
        
    return text[idx:end_idx], idx, end_idx

old_def_start = "def core_genera_report_giornaliero(uid, data_consegna, azioni=None):"
old_block, idx, end_idx = find_block(content, old_def_start)

if not old_block:
    print("Not found")
    sys.exit(1)

# Now I'll create the new block string, doing it carefully

new_block = """def core_genera_report_giornaliero(uid, data_consegna):
    \"\"\"
    Implementa gli step 2, 3 e 4 del workflow locale con logica a blocchi:
    - Identifica fornitori da sovrascrivere (quelli presenti in split_ddt)
    - Elimina vecchi viaggi DB per quei fornitori
    - Mantiene intatti (cassaforte) i viaggi che non contengono fornitori da sovrascrivere
    - Genera nuovi giri di default per i nuovi dati
    \"\"\"
    start_time = time.time()
    db = get_db()
    bucket = storage.bucket(name=BUCKET_NAME)
    if not data_consegna:
        return {"status": "errore", "message": "Data mancante"}

    print(f"[INFO] Generazione report per il {data_consegna}")
    
    # 1. Recupera i DDT scansionando la cartella dello Storage
    ddt_list = []
    prefix_search = f"split_ddt/{data_consegna}/"
    print(f"[INFO] Scansione Storage per data {data_consegna}...")
    
    tenant_con_ddt = set()
    
    try:
        # Caricamento bulk clienti da DNR, GRAN CHEF e CATTEL
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
                
                # Identifica tenant dal path
                if "/CATTEL/" in blob.name: tenant_con_ddt.add("CATTEL")
                elif "/GRAND_CHEF/" in blob.name: tenant_con_ddt.add("GRAN_CHEF")
                elif "/FRUTTA/" in blob.name or "/LATTE/" in blob.name: tenant_con_ddt.add("DNR")
                
                try:
                    import json
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
        # Debug Radar
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

    print(f"[INFO] Tenant con nuovi dati (da sovrascrivere): {tenant_con_ddt}")

    # 0.5. Sovrascrittura Selettiva (Elimina i viaggi Firestore per i tenant che vogliamo sovrascrivere)
    if tenant_con_ddt:
        try:
            viaggi_ref = db.collection('clienti').document('DNR').collection('viaggi ddt')
            viaggi = viaggi_ref.where("data_lavoro", "==", data_consegna).stream()
            for v in viaggi:
                cz = v.to_dict().get("cliente_zona", "")
                
                # Check se il viaggio appartiene a un tenant da sovrascrivere
                v_tenant = "DNR"
                if cz == "CATTEL": v_tenant = "CATTEL"
                elif cz == "GRAN CHEF": v_tenant = "GRAN_CHEF"
                
                if v_tenant in tenant_con_ddt:
                    v.reference.delete()
        except Exception as e:
            print(f"[ERROR] Eliminazione vecchi viaggi fallita: {e}")

    # PRE-SALVATAGGIO: Leggi i viaggi esistenti prima di cancellarli per logica Cassaforte
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

    # 2. Aggrega per cliente (Step 2 locale)
    punti_map = {} # chiave: tripla_chiave o codice_cliente
    for ddt in ddt_list:
        cod = ddt.get('codice_consegna')
        cod_l = str(cod).strip().lower()
        tipo = ddt.get('tipo', 'FRUTTA')
        competenza = ddt.get('competenza') or tipo
        
        cliente_info = db_mappati.get(cod_l)
        nome = ddt.get('nome', cod)
        
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
            
            if note_val.lower() == "nan": note_val = ""
            if tel_val.lower() == "nan": tel_val = ""
            if om_frutta.lower() == "nan": om_frutta = ""
            if oM_frutta.lower() == "nan": oM_frutta = ""
            if om_latte.lower() == "nan": om_latte = ""
            if oM_latte.lower() == "nan": oM_latte = ""
            
            if tipo == "FRUTTA":
                om_val = om_frutta if om_frutta else (str(cliente_info.get("orario_min") or "").strip())
                oM_val = oM_frutta if oM_frutta else (str(cliente_info.get("orario_max") or "").strip())
            else:
                om_val = om_latte if om_latte else (str(cliente_info.get("orario_min") or "").strip())
                oM_val = oM_latte if oM_latte else (str(cliente_info.get("orario_max") or "").strip())
                
            if om_val.lower() == "nan": om_val = ""
            if oM_val.lower() == "nan": oM_val = ""
            
        if ddt.get("orario_min"): om_val = str(ddt["orario_min"]).strip()
        if ddt.get("orario_max"): oM_val = str(ddt["orario_max"]).strip()
        if ddt.get("note"): note_val = str(ddt["note"]).strip()

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
            
            if not esistente.get("orario_min") and om_val: esistente["orario_min"] = om_val
            if not esistente.get("orario_max") and oM_val: esistente["orario_max"] = oM_val
            if not esistente.get("note") and note_val: esistente["note"] = note_val
            if not esistente.get("telefono") and tel_val: esistente["telefono"] = tel_val
        
        if tipo == 'FRUTTA':
            punti_map[chiave]["codici_ddt_frutta"].append(ddt.get('num_ddt', 'UNK'))
        else:
            punti_map[chiave]["codici_ddt_latte"].append(ddt.get('num_ddt', 'UNK'))
            
        if "competenze" not in punti_map[chiave]:
            punti_map[chiave]["competenze"] = []
        if competenza not in punti_map[chiave]["competenze"]:
            punti_map[chiave]["competenze"].append(competenza)

    # --- INTEGRAZIONE RIENTRI DDT ---
    try:
        rientri_ref = db.collection('clienti').document('DNR').collection('rientri ddt')
        for r_doc in rientri_ref.stream():
            r_data = r_doc.to_dict() or {}
            stato = str(r_data.get('stato') or r_data.get('Stato') or '').strip().lower()
            if 'allegato' in stato and data_consegna not in stato: continue
                
            r_cod = str(r_data.get('codice_consegna') or r_data.get('Codice consegna') or '').strip()
            if not r_cod: continue
            r_data_ddt = r_data.get('data_ddt') or r_data.get('Data e Num DDT') or ''
            r_cod_l = r_cod.lower()
            
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

    # 3. Organizza per Zone (Step 4 locale)
    zone_finali = []
    color_index = 0
    palette = ["#4f46e5", "#10b981", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1", "#a855f7", "#3b82f6", "#22c55e", "#d946ef", "#84cc16"]

    # --- LOGICA A BLOCCHI (CASSAFORTE) ---
    def get_tenant_from_cz(cz):
        if not cz: return "DNR"
        cz = cz.upper().strip()
        if cz == "CATTEL": return "CATTEL"
        if cz == "GRAN CHEF": return "GRAN_CHEF"
        return "DNR"

    for zid, old_z in mappa_zone_esistenti.items():
        # Verifichiamo se il vecchio viaggio contiene ALMENO UN cliente dei tenant da sovrascrivere
        da_scartare = False
        stops = old_z.get("lista_punti", [])
        if not stops: stops = old_z.get("stops", [])
        
        for stop in stops:
            cz = stop.get("cliente_zona", "")
            stop_tenant = get_tenant_from_cz(cz)
            if stop_tenant in tenant_con_ddt:
                da_scartare = True
                break
                
        if not da_scartare:
            # Il viaggio è sicuro, non contiene clienti sovrascritti -> CASSAFORTE
            old_z_copy = dict(old_z)
            # Riassegna la palette per mantenere uniformità
            old_z_copy["color"] = palette[color_index % len(palette)]
            zone_finali.append(old_z_copy)
            color_index += 1

    # Raggruppa i NUOVI punti da elaborare
    zone_dict = defaultdict(list)
    for p in punti_map.values():
        z_id = p.get("zona", "0000")
        if not z_id: z_id = "0000"
        zone_dict[z_id].append(p)

    # Costruisci Zone Normali
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
            "lista_punti": zone_dict[zid], "cliente_zona": "CATTEL"
        })
        color_index += 1

    for idx_bauer, zid in enumerate(bauer_keys, start=1):
        zone_finali.append({
            "id_zona": zid, "nome_giro": f"Bauer {idx_bauer:02d}", "color": palette[color_index % len(palette)],
            "lista_punti": zone_dict[zid], "cliente_zona": "BAUER"
        })
        color_index += 1
        
    for idx_gc, zid in enumerate(sorted_gc_keys, start=1):
        zone_finali.append({
            "id_zona": zid, "nome_giro": f"Gran Chef {idx_gc:02d}", "color": palette[color_index % len(palette)],
            "lista_punti": zone_dict[zid], "cliente_zona": "GRAN CHEF"
        })
        color_index += 1
        
    for sp_key, label, c_z in [
        ("0000", "0000 - Non Assegnato", ""), 
        ("PUNTI_DI_CONSEGNA", "PUNTI_DI_CONSEGNA - Anomalia", ""),
        ("DDT_DA_INSERIRE", "DDT DA INSERIRE - Inserimento Rapido", "")
    ]:
        if sp_key in zone_dict and zone_dict[sp_key]:
            zone_finali.append({
                "id_zona": sp_key, "nome_giro": label, "color": "#cbd5e1",
                "lista_punti": zone_dict[sp_key], "cliente_zona": c_z
            })

    # Ordina e formatta
    master_json = []
    zone_finali_ordinate = sorted(zone_finali, key=lambda x: (
        x["id_zona"] in ["0000", "PUNTI_DI_CONSEGNA", "DDT_DA_INSERIRE"],
        x["id_zona"]
    ))
    
    for z in zone_finali_ordinate:
        if not z.get('lista_punti'):
            if z.get('stops'):
                z['lista_punti'] = z['stops']
            else:
                z['lista_punti'] = []
            
        # Pulisce codici nan nei punti originali
        for p in z["lista_punti"]:
            if str(p.get("codice_frutta", "")).lower() == "nan": p["codice_frutta"] = "p00000"
            if str(p.get("codice_latte", "")).lower() == "nan": p["codice_latte"] = "p00000"
            
        z_dict = {
            "id_zona": z["id_zona"],
            "nome_giro": z["nome_giro"],
            "color": z["color"],
            "cliente_zona": z.get("cliente_zona", ""),
            "stops": z["lista_punti"]
        }
        master_json.append(z_dict)

    # Scrittura JSON Master nello Storage
    output_str = json.dumps({"data_consegna": data_consegna, "zone": master_json}, indent=2)
    bucket.blob(f"REPORTS/{data_consegna}/viaggi_giornalieri_Johnson.json").upload_from_string(
        output_str, content_type='application/json'
    )
    
    # Scrittura su Firestore (Salvataggio Viaggi)
    for z in master_json:
        doc_id = f"{data_consegna}_{z['id_zona']}"
        viaggio_ref = db.collection('clienti').document('DNR').collection('viaggi ddt').document(doc_id)
        
        # Manteniamo t_guida_min, t_tot_min, km_reali, autista se erano presenti nella cassaforte
        old_viaggio_data = {}
        if z["id_zona"] in mappa_zone_esistenti:
            old_viaggio_data = mappa_zone_esistenti[z["id_zona"]]
            
        viaggio_data = {
            'data_lavoro': data_consegna,
            'id_zona': z['id_zona'],
            'nome_giro': z['nome_giro'],
            'cliente_zona': z['cliente_zona'],
            'colore': z['color'],
            'stops': z['stops'],
            'autista': old_viaggio_data.get('autista', ''),
            't_guida_min': old_viaggio_data.get('t_guida_min', 0),
            't_tot_min': old_viaggio_data.get('t_tot_min', 0),
            'km_reali': old_viaggio_data.get('km_reali', 0),
            'traffico_aggiornato_at': old_viaggio_data.get('traffico_aggiornato_at', ''),
            'updated_at': firestore.SERVER_TIMESTAMP
        }
        try:
            viaggio_ref.set(viaggio_data, merge=True)
        except Exception as e_s:
            print(f"[ERROR] Salvataggio {doc_id} in Firestore fallito: {e_s}")

    # Genera report PDF/HTML
    res_links = _genera_link_per_tutti_i_giri(master_json, data_consegna, db, bucket)
    
    elapsed = time.time() - start_time
    print(f"[INFO] Report giornaliero generato in {elapsed:.2f}s")
    
    return {
        "status": "ok",
        "message": "Report generato con successo",
        "data_consegna": data_consegna,
        "zone_generate": len(master_json),
        "links": res_links,
        "tempo_sec": round(elapsed, 2)
    }"""

# Perform replacement
content = content.replace(old_block, new_block)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Replace success!")
