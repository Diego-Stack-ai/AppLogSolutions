import time

def handle_genera_mappa_autista(
    viaggio_id,
    distinta_url,
    tenant,
    get_viaggio_doc_fn,
    get_depot_fn,
    get_directions_data_fn,
    genera_html_fn,
    bucket,
    genera_url_token_fn,
    registra_statistica_fn,
    time_per_stop_min
):
    start_time = time.time()
    if not viaggio_id:
        return {"status": "errore", "message": "viaggio_id mancante", "errori": ["viaggio_id mancante"], "data": {}}

    doc_ref, doc_viaggio, tenant_viaggio = get_viaggio_doc_fn(viaggio_id, tenant)
    if not doc_viaggio.exists:
        return {"status": "errore", "message": "Viaggio non trovato", "errori": ["Viaggio non trovato"], "data": {}}

    viaggio = doc_viaggio.to_dict()
    punti = viaggio.get("punti_ottimizzati") or viaggio.get("punti", [])
    if not punti:
        return {"status": "errore", "message": "Viaggio senza punti", "errori": ["Punti vuoti"], "data": {}}

    punti_norm = []
    for p in punti:
        try:
            punti_norm.append({**p, "lat": float(p["lat"]), "lon": float(p.get("lon", p.get("lng", 0)))})
        except:
            pass

    depot = get_depot_fn(punti_norm)
    km, sec_guida, polylines = get_directions_data_fn(punti_norm, depot=depot)

    if not distinta_url:
        distinta_url = viaggio.get("distinta_url") or viaggio.get("distinta_light")

    ora_partenza_calc = viaggio.get("_stats", {}).get("ora_partenza", "07:00")
    
    cliente_zona = viaggio.get("cliente_zona", "")
    nome_giro = viaggio.get("nome_giro", viaggio_id)
    if cliente_zona and cliente_zona.upper() not in nome_giro.upper():
        titolo_giro = f"{cliente_zona.upper()} - {nome_giro}"
    else:
        titolo_giro = nome_giro
        
    html = genera_html_fn(titolo_giro, punti_norm, km, sec_guida, polylines, depot=depot, distinta_url=distinta_url, ora_partenza_dep=ora_partenza_calc, actual_viaggio_id=viaggio_id)

    data_viaggio = viaggio.get("data", "sconosciuta").replace("/", "-")
    html_path = f"{tenant_viaggio}/CONSEGNE/CONSEGNE_{data_viaggio}/MAPPE_AUTISTI/{viaggio_id}.html"
    blob = bucket.blob(html_path)
    blob.upload_from_string(html.encode("utf-8"), content_type="text/html; charset=utf-8")
    url_pubblica = genera_url_token_fn(blob)

    doc_ref.update({
        "mappa_url": url_pubblica,
        "km_reali": km,
        "t_guida_min": sec_guida // 60,
        "t_tot_min": (sec_guida // 60) + len(punti_norm) * time_per_stop_min
    })

    elapsed = time.time() - start_time
    registra_statistica_fn("genera_mappa_autista", elapsed)

    return {
        "status": "ok",
        "message": f"Mappa generata in {elapsed:.2f}s ({len(polylines)} tratti stradali)",
        "errori": [],
        "data": {
            "viaggio_id": viaggio_id,
            "mappa_url": url_pubblica,
            "km_reali": km,
            "t_guida_min": sec_guida // 60,
            "n_polylines": len(polylines),
            "tempo_sec": elapsed
        }
    }
