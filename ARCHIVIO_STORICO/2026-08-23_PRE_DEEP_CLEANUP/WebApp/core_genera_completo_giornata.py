def core_genera_completo_giornata(data_consegna, tenant='DNR'):
    start_time = time.time()
    db = get_db()
    bucket = storage.bucket(name=BUCKET_NAME)
    path_base = f'{tenant}/REPORTS/{data_consegna}' if tenant != 'DNR' else f'REPORTS/{data_consegna}'
    blob_json = bucket.blob(f'{path_base}/viaggi_giornalieri_Johnson.json')
    if not blob_json.exists():
        return {'status': 'errore', 'message': f'Nessun file viaggi_giornalieri_Johnson.json trovato per il {data_consegna}.'}
    try:
        raw_json = json.loads(blob_json.download_as_string().decode('utf-8'))
        if isinstance(raw_json, dict):
            zone_list = raw_json.get('zone', [])
            cliente_progetto = raw_json.get('cliente')
        else:
            zone_list = raw_json
    except Exception as e:
        return {'status': 'errore', 'message': f'Errore lettura JSON: {str(e)}'}
    deliveries_all = []
    prefix_search = f'split_ddt/{data_consegna}/'
    try:
        blobs = bucket.list_blobs(prefix=prefix_search)
        for blob in blobs:
            if 'ddt_estratti' in blob.name and blob.name.endswith('.json'):
                try:
                    meta_data = json.loads(blob.download_as_string().decode('utf-8'))
                    deliveries_all.extend(meta_data.get('deliveries', []))
                except Exception as e_meta:
                    print(f'[METADATA] Errore lettura {blob.name}: {e_meta}')
    except Exception as e_list:
        print(f'[METADATA] Errore scansione storage: {e_list}')
    (articoli_noti, config_cons) = get_config_app()
    rientri_list = []
    try:
        for doc in db.collection('clienti').document('DNR').collection('rientri ddt').stream():
            r_data = doc.to_dict() or {}
            r_cod = str(r_data.get('codice_consegna') or r_data.get('Codice consegna') or '').strip()
            r_data_ddt = r_data.get('data_ddt') or r_data.get('Data e Num DDT') or ''
            stato = str(r_data.get('stato') or r_data.get('Stato') or '').strip().lower()
            if data_consegna in stato or f'ddt {data_consegna}' in stato:
                rientri_list.append({'codice': r_cod, 'data_ddt': r_data_ddt, 'is_parziale': bool(r_data.get('is_parziale') or False) or str(r_data.get('Tipo') or r_data.get('tipo') or '').lower().strip() == 'parziale', 'nota_integrativa': str(r_data.get('note') or r_data.get('Note') or r_data.get('nota_integrativa') or '').strip()})
    except Exception as e_r:
        print(f'[RIENTRI] Errore recupero: {e_r}')
    links = []
    pdf_non_trovati_giorno = []
    for zone in zone_list:
        zid = zone.get('id_zona')
        if zid in ('DDT_DA_INSERIRE', 'PUNTI_DI_CONSEGNA'):
            continue
        punti = zone.get('lista_punti', [])
        if not punti:
            continue
        nome_giro = zone.get('nome_giro', '?')
        pdf_ddt_streams = []
        pdf_non_trovati_giro = []
        articoli_viaggio = defaultdict(lambda : {'codice_base': '', 'variante_raw': '', 'descrizione': '', 'quantita': [], 'confezionamento': ''})
        for p in punti:
            cf = str(p.get('codice_frutta', '')).strip().lower()
            cd_frutta = p.get('codici_ddt_frutta', [])
            cl = str(p.get('codice_latte', '')).strip().lower()
            cd_latte = p.get('codici_ddt_latte', [])
            ddt_trovati = []
            if cf and cf != 'p00000':
                if cd_frutta:
                    for num in cd_frutta:
                        match = next((d for d in deliveries_all if str(d.get('codice_consegna')).strip().lower() == cf and str(d.get('num_ddt')).strip() == str(num)), None)
                        if match:
                            ddt_trovati.append(match)
                else:
                    match = next((d for d in deliveries_all if str(d.get('codice_consegna')).strip().lower() == cf and d.get('tipo') in ('FRUTTA', 'GRAND_CHEF', 'DAC')), None)
                    if match:
                        ddt_trovati.append(match)
            if cl and cl != 'p00000':
                if cd_latte:
                    for num in cd_latte:
                        match = next((d for d in deliveries_all if str(d.get('codice_consegna')).strip().lower() == cl and str(d.get('num_ddt')).strip() == str(num)), None)
                        if match:
                            ddt_trovati.append(match)
                else:
                    match = next((d for d in deliveries_all if str(d.get('codice_consegna')).strip().lower() == cl and d.get('tipo') in ('LATTE', 'GRAND_CHEF', 'DAC')), None)
                    if match:
                        ddt_trovati.append(match)
            for ddt in ddt_trovati:
                tipo_ddt = ddt.get('tipo')
                pdf_name = ddt.get('pdf_name')
                storage_path = f'split_ddt/{data_consegna}/{tipo_ddt}/{pdf_name}'
                blob_ddt = bucket.blob(storage_path)
                if blob_ddt.exists():
                    try:
                        pdf_bytes = blob_ddt.download_as_bytes()
                        pdf_ddt_streams.append((pdf_name, pdf_bytes))
                        art_estrai = _estrai_articoli_da_tabella_cloud(pdf_bytes, articoli_noti)
                        for art in art_estrai:
                            key = (art['codice_base'], art['variante_raw'])
                            articoli_viaggio[key]['codice_base'] = art['codice_base']
                            articoli_viaggio[key]['variante_raw'] = art['variante_raw']
                            articoli_viaggio[key]['descrizione'] = art['descrizione']
                            articoli_viaggio[key]['quantita'].extend(art['quantita'])
                            if art['confezionamento']:
                                articoli_viaggio[key]['confezionamento'] = art['confezionamento']
                    except Exception as e_pdf:
                        msg = f'Errore lettura {pdf_name}: {e_pdf}'
                        pdf_non_trovati_giro.append(msg)
                        pdf_non_trovati_giorno.append(f'{nome_giro}: {msg}')
                else:
                    msg = f'DDT PDF mancante nello Storage: {pdf_name}'
                    pdf_non_trovati_giro.append(msg)
                    pdf_non_trovati_giorno.append(f'{nome_giro}: {msg}')
        punti_codici = {str(p.get('codice_frutta') or '').strip().lower(), str(p.get('codice_latte') or '').strip().lower()}
        rientri_giro = [r for r in rientri_list if r['codice'].strip().lower() in punti_codici]
        (full_stream, light_stream) = _genera_distinta_pdf_cloud(zone, articoli_viaggio, data_consegna, pdf_ddt_streams, rientri_giro, pdf_non_trovati_giro)
        full_blob = bucket.blob(f'REPORTS/{data_consegna}/DISTINTE_VIAGGIO/DISTINTA_{nome_giro}.pdf')
        if full_blob.exists():
            full_blob.delete()
        full_blob.upload_from_file(full_stream, content_type='application/pdf')
        distinta_completa_url = _genera_url_storage_token(full_blob)
        light_blob = bucket.blob(f'REPORTS/{data_consegna}/DISTINTE_VIAGGIO/DISTINTA_LIGHT_{nome_giro}.pdf')
        if light_blob.exists():
            light_blob.delete()
        light_blob.upload_from_file(light_stream, content_type='application/pdf')
        distinta_light_url = _genera_url_storage_token(light_blob)
        viaggio_id = f'{data_consegna}_{zid}'
        doc_ref = get_db().collection('clienti').document('DNR').collection('viaggi ddt').document(viaggio_id)
        try:
            doc_ref.set({'distinta_light': distinta_light_url, 'distinta_completa': distinta_completa_url, '_stats': zone.get('_stats', {})}, merge=True)
        except Exception as e_fs:
            print(f'[ERROR] Impossibile aggiornare Firestore per {viaggio_id}: {e_fs}')
        km = zone.get('_stats', {}).get('km', 0.0)
        sec_guida = zone.get('_stats', {}).get('t_guida', 0) * 60
        polylines = zone.get('_polylines', [])
        punti_html = []
        for p in punti:
            try:
                punti_html.append({**p, 'lat': float(p['lat']), 'lon': float(p.get('lon', p.get('lng', 0)))})
            except:
                punti_html.append(p)
        depot = _get_depot_for_points_cloud(punti_html)
        ora_partenza_calc = zone.get('_stats', {}).get('ora_partenza', '07:00')
        cliente_zona = zone.get('cliente_zona', '')
        if cliente_zona and cliente_zona.upper() not in nome_giro.upper():
            titolo_giro = f'{cliente_zona.upper()} - {nome_giro}'
        else:
            titolo_giro = f'Giro {nome_giro}'
        html_map_content = _genera_html_mappa(titolo_giro, punti_html, km, sec_guida, polylines, depot=depot, distinta_url=distinta_light_url, ora_partenza_dep=ora_partenza_calc)
        map_blob = bucket.blob(f'{path_base}/MAPPE_AUTISTI/{nome_giro}.html')
        map_blob.upload_from_string(html_map_content.encode('utf-8'), content_type='text/html; charset=utf-8')
        map_url = _genera_url_storage_token(map_blob)
        links.append({'v_id': nome_giro, 'titolo_giro': titolo_giro, 'date': data_consegna, 'url': map_url, 'zones': zone.get('zone', [zone.get('id_zona', '?')]), 'distinta_light': distinta_light_url, 'distinta_completa': distinta_completa_url})
    master_distinte_url = None
    try:
        from pypdf import PdfWriter
        riepilogo_zone_pdf = _genera_pagina_riepilogo_zone_cloud(zone_list, data_consegna, pdf_non_trovati_giorno)
        master_writer = PdfWriter()
        if riepilogo_zone_pdf:
            master_writer.append(io.BytesIO(riepilogo_zone_pdf))
        for zone in zone_list:
            zid = zone.get('id_zona')
            if zid in ('DDT_DA_INSERIRE', 'PUNTI_DI_CONSEGNA'):
                continue
            nome_giro = zone.get('nome_giro')
            giro_blob = bucket.blob(f'{path_base}/DISTINTE_VIAGGIO/DISTINTA_{nome_giro}.pdf')
            if giro_blob.exists():
                master_writer.append(io.BytesIO(giro_blob.download_as_bytes()))
        master_stream = io.BytesIO()
        master_writer.write(master_stream)
        master_stream.seek(0)
        master_blob = bucket.blob(f'{path_base}/MASTER_DISTINTE_{data_consegna}.pdf')
        if master_blob.exists():
            master_blob.delete()
        master_blob.upload_from_file(master_stream, content_type='application/pdf')
        master_distinte_url = _genera_url_storage_token(master_blob)
        print(f'[MASTER] Generato MASTER_DISTINTE_{data_consegna}.pdf con successo.')
    except Exception as e_master:
        print(f'[MASTER] Errore assemblaggio: {e_master}')
    whatsapp_lines = [f"{l.get('titolo_giro', 'Giro ' + l['v_id'])} - Mappa: {l['url']}" for l in links]
    whatsapp_txt = '\n'.join(whatsapp_lines)
    bucket.blob(f'{path_base}/LINK_WHATSAPP_AUTISTI.txt').upload_from_string(whatsapp_txt.encode('utf-8'), content_type='text/plain; charset=utf-8')
    manifest_data = {'date': data_consegna, 'links': links}
    if master_distinte_url:
        manifest_data['master_distinte_url'] = master_distinte_url
    bucket.blob(f'{path_base}/manifest_link_viaggi.json').upload_from_string(json.dumps(manifest_data, indent=2), content_type='application/json')
    punti_totali = sum((len(z.get('lista_punti', [])) for z in zone_list if z.get('id_zona') not in ('DDT_DA_INSERIRE', 'PUNTI_DI_CONSEGNA')))
    zone_totali = len([z for z in zone_list if z.get('id_zona') not in ('DDT_DA_INSERIRE', 'PUNTI_DI_CONSEGNA')])
    mappa_generale_url = ''
    try:
        zone_per_mappa = []
        for z in zone_list:
            if z.get('id_zona') not in ('DDT_DA_INSERIRE', 'PUNTI_DI_CONSEGNA'):
                c = z.get('cliente_zona', '')
                n = z.get('nome_giro') or z.get('id_zona', '?')
                if c and c.upper() not in n.upper():
                    n = f'{c.upper()} - {n}'
                zone_per_mappa.append({'nome_giro': n, 'color': z.get('color', '#4f46e5'), '_polylines': z.get('_polylines', []), 'lista_punti': [{**p, 'lat': _safe_float(p.get('lat')), 'lon': _safe_float(p.get('lon', p.get('lng', 0)))} for p in z.get('lista_punti', []) if _safe_float(p.get('lat')) is not None]})
        html_mappa_gen = _genera_html_mappa_generale(data_consegna, zone_per_mappa)
        mappa_gen_blob = bucket.blob(f'{path_base}/MAPPA_GENERALE_{data_consegna}.html')
        mappa_gen_blob.upload_from_string(html_mappa_gen.encode('utf-8'), content_type='text/html; charset=utf-8')
        mappa_generale_url = _genera_url_storage_token(mappa_gen_blob)
        print(f'[MAPPA GENERALE] Generata con {len(zone_per_mappa)} giri.')
    except Exception as e_mg:
        print(f'[MAPPA GENERALE ERROR] {e_mg}')
        mappa_generale_url = links[0]['url'] if links else ''
    report_meta = {'data_consegna': data_consegna, 'punti_totali': punti_totali, 'zone_totali': zone_totali, 'mappa_url': mappa_generale_url, 'created_at': firestore.SERVER_TIMESTAMP, 'tipo': 'REPORT_GENERALE'}
    db.collection('clienti').document(tenant).collection('reports_logistici').document(data_consegna).set(report_meta)
    try:
        active_viaggio_ids = {f"{data_consegna}_{z.get('id_zona')}" for z in zone_list if z.get('id_zona') and z.get('id_zona') not in ('DDT_DA_INSERIRE', 'PUNTI_DI_CONSEGNA')}
        viaggi_ref = db.collection('clienti').document(tenant).collection('viaggi ddt')
        query_viaggi = viaggi_ref.where('data_lavoro', '==', data_consegna).stream()
        for doc in query_viaggi:
            if doc.id not in active_viaggio_ids:
                print(f'[Ghost Cleanup] Eliminazione viaggio svuotato/cancellato: {doc.id}')
                doc.reference.delete()
    except Exception as cleanup_err:
        print(f'[Ghost Cleanup] Errore durante la pulizia dei viaggi vuoti: {cleanup_err}')
    elapsed = time.time() - start_time
    _registra_statistica('genera_completo_giornata', elapsed)
    return {'status': 'ok', 'message': f'Pipeline completata in {elapsed:.2f}s per {zone_totali} giri.', 'tempo_sec': elapsed, 'giri': zone_totali}
