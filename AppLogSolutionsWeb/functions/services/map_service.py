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


import requests
import json
import copy
def _genera_html_mappa(viaggio_id, punti, km, sec_guida, polylines, depot=None, distinta_url=None, ora_partenza_dep="07:00", actual_viaggio_id=None):
    """Genera HTML mappa mobile-first con polyline strade vere."""
    if depot is None:
        depot = _get_depot_for_points_cloud(punti)
    t_guida_min = sec_guida // 60
    t_sosta_min = len(punti) * TIME_PER_STOP_MIN
    t_tot_min   = t_guida_min + t_sosta_min

    def fmt_min(m):
        hh, mm = divmod(m, 60)
        return f"{hh}h {mm}m" if hh > 0 else f"{mm}m"

    depot_nome = depot.get("nome", "Deposito").title() if depot else "Deposito"
    
    fermate_html = ""
    
    # 1. Card di Partenza
    if distinta_url:
        fermate_html += f'''
            <div class="card" style="background:#f1f5f9; border-color:#94a3b8; grid-template-columns: 42px 1.4fr 1fr; padding: 10px; gap: 8px; align-items: stretch; cursor: default;">
                <div class="stop-num" style="background:#475569; align-self: center;"><span class="material-icons-round">home</span></div>
                <div class="stop-info" style="justify-content: center;">
                    <b class="name" style="font-size: 0.8rem;">PARTENZA</b>
                    <span class="addr" style="font-size: 0.7rem;">{depot_nome}</span>
                    <span class="orario-badge" style="background:#1e293b; color:white; margin-top:2px; font-size: 0.6rem;"><span class="material-icons-round" style="font-size: 10px !important;">schedule</span>Partenza: {ora_partenza_dep}</span>
                </div>
                <div style="border-left: 2px solid #bae6fd; background: #f0f9ff; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 4px; border-radius: 8px; gap: 4px;">
                    <div style="font-size: 0.52rem; font-weight: 800; text-transform: uppercase; letter-spacing: .06em; color: #0369a1;">📋 Distinta</div>
                    <a href="{distinta_url}" target="_blank" onclick="event.stopPropagation()" style="background: #0284c7; color: white; border: none; border-radius: 6px; padding: 5px 6px; font-size: 0.62rem; font-weight: 800; text-decoration: none; display: flex; align-items: center; gap: 3px; width: 100%; justify-content: center;">🔗 Apri PDF</a>
                </div>
            </div>'''
    else:
        fermate_html += f'''
            <div class="card" style="background:#f1f5f9; border-color:#94a3b8; grid-template-columns: 42px 1fr; cursor: default;">
                <div class="stop-num" style="background:#475569;"><span class="material-icons-round">home</span></div>
                <div class="stop-info">
                    <b class="name">PARTENZA</b>
                    <span class="addr">{depot_nome}</span>
                    <span class="orario-badge" style="background:#1e293b; color:white; margin-top:4px;"><span class="material-icons-round">schedule</span>Partenza: {ora_partenza_dep}</span>
                </div>
            </div>'''

    for idx, p in enumerate(punti):
        nome = p.get("nome", p.get("codice_cliente", f"Tappa {idx+1}"))
        rag_sociale = p.get("ragione_sociale", p.get("nome_cliente", ""))
        ind  = p.get("indirizzo", "")
        lat  = p.get("lat", "")
        lon  = p.get("lon", p.get("lng", ""))
        nav  = f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}&travelmode=driving"
        
        is_parz = any(r.get("is_parziale") for r in p.get("rientri_alert", []) if isinstance(r, dict))
        warn_class = " warning" if is_parz else ""
        
        # Note
        note_txt = str(p.get("note", p.get("nota_integrativa", p.get("Note", ""))) or "").strip()
        note_html = ""
        if note_txt and note_txt.lower() != "nan":
            note_safe = note_txt.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
            note_html = f'<div class="note-chip"><span class="material-icons-round">sticky_note_2</span>Note: {note_safe}</div>'
            
        # Orari
        om_val = str(p.get("orario_min") or p.get("orario_min_frutta", p.get("orario_min_latte", ""))).strip()
        oM_val = str(p.get("orario_max") or p.get("orario_max_frutta", p.get("orario_max_latte", ""))).strip()
        
        orario_html = ""
        if (om_val and om_val.lower() != "nan") or (oM_val and oM_val.lower() != "nan"):
            if om_val and oM_val:
                orario_txt = f"{om_val} - {oM_val}"
            elif om_val:
                orario_txt = f"Dalle {om_val}"
            else:
                orario_txt = f"Entro le {oM_val}"
            orario_html = f'<span class="orario-badge"><span class="material-icons-round">schedule</span>Fascia: {orario_txt}</span>'
            
        # Orario stimato arrivo / ripartenza
        ora_arr = str(p.get("ora_arrivo") or "").strip()
        ora_rip = str(p.get("ora_ripartenza") or "").strip()
        eta_html = ""
        if ora_arr and ora_rip:
            eta_html = f'<span class="eta-badge"><span class="material-icons-round">timer</span>Arrivo {ora_arr} &mdash; Ripart. {ora_rip}</span>'
        elif ora_arr:
            eta_html = f'<span class="eta-badge"><span class="material-icons-round">timer</span>Arrivo stimato {ora_arr}</span>'
            
        # Chiamata
        phone_num = _extract_phone(p)
        if phone_num:
            action_col = (
                f'<div class="nav-col">'
                f'<a href="{nav}" target="_blank" class="btn-nav" onclick="event.stopPropagation()"><span class="material-icons-round">navigation</span></a>'
                f'<a href="tel:{phone_num}" class="btn-call" onclick="event.stopPropagation()"><span class="material-icons-round">call</span></a>'
                f'<button class="btn-ok" onclick="toggleConsegnato(event, {idx})"><span class="material-icons-round">check</span></button>'
                f'<button class="btn-cam" onclick="openCamera(event, {idx})"><span class="material-icons-round">photo_camera</span></button>'
                f'</div>'
            )
            card_style = 'grid-template-columns: 42px 1fr auto;'
        else:
            action_col = (
                f'<div class="nav-col">'
                f'<a href="{nav}" target="_blank" class="btn-nav" style="grid-column:span 2; width:100%;" onclick="event.stopPropagation()"><span class="material-icons-round">navigation</span></a>'
                f'<button class="btn-ok" onclick="toggleConsegnato(event, {idx})"><span class="material-icons-round">check</span></button>'
                f'<button class="btn-cam" onclick="openCamera(event, {idx})"><span class="material-icons-round">photo_camera</span></button>'
                f'</div>'
            )
            card_style = 'grid-template-columns: 42px 1fr auto;'
            
        fermate_html += (
            f'<div class="card" id="card-{idx}" onclick="selectCard({idx})" style="{card_style}">'
            f'<div class="stop-num{warn_class}">{idx+1}</div>'
            f'<div class="stop-info">'
            f'<span class="name">{nome}</span>'
            f'<span class="addr">{ind}</span>'
            f'{orario_html}'
            f'{eta_html}'
            f'{note_html}'
            f'</div>'
            f'{action_col}</div>'
        )

    # 3. Card di Arrivo
    ora_rientro_dep = ""
    try:
        part_m = re.match(r"(\d{2}):(\d{2})", str(ora_partenza_dep).strip())
        start_min = int(part_m.group(1)) * 60 + int(part_m.group(2)) if part_m else 420
        
        t_tot_min = (sec_guida // 60) + len(punti) * TIME_PER_STOP_MIN
        hh_ret, mm_ret = divmod(start_min + int(t_tot_min), 60)
        hh_ret = hh_ret % 24
        ora_rientro_dep = f"{hh_ret:02d}:{mm_ret:02d}"
    except Exception as e_time:
        print(f"[WARN] Impossibile calcolare ora rientro: {e_time}")

    rientro_badge = f'<span class="orario-badge" style="background:#1e293b; color:white; margin-top:4px;"><span class="material-icons-round">schedule</span>Rientro stimato: {ora_rientro_dep}</span>' if ora_rientro_dep else ''
    
    fermate_html += f'''
        <div class="card" id="arrivo-card" style="background:#f1f5f9; border-color:#94a3b8; grid-template-columns: 42px 1fr; cursor: default;">
            <div class="stop-num" style="background:#475569;"><span class="material-icons-round">flag</span></div>
            <div class="stop-info">
                <b class="name">ARRIVO</b>
                <span class="addr">{depot_nome}</span>
                {rientro_badge}
            </div>
        </div>'''

    punti_js_list = []
    for p in punti:
        is_parz = any(r.get("is_parziale") for r in p.get("rientri_alert", []) if isinstance(r, dict))
        punti_js_list.append({
            "lat": float(p.get("lat", 0)),
            "lng": float(p.get("lon", p.get("lng", 0))),
            "nome": p.get("nome", ""),
            "codice_cliente": p.get("codice_cliente", ""),
            "ragione_sociale": p.get("ragione_sociale", p.get("nome_cliente", "")),
            "indirizzo": p.get("indirizzo", ""),
            "is_parziale": is_parz
        })
    punti_js     = json.dumps(punti_js_list)
    polylines_js = json.dumps(polylines)

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>Mappa {viaggio_id}</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&display=swap" rel="stylesheet">
<link href="https://fonts.googleapis.com/icon?family=Material+Icons+Round" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/sortablejs@latest/Sortable.min.js"></script>
<script src="https://maps.googleapis.com/maps/api/js?key={GOOGLE_MAPS_API_KEY}&libraries=geometry&callback=initMap" async defer></script>
<style>
:root{{--p:#4f46e5;--accent:#10b981;--call:#16a34a}}
body,html{{margin:0;padding:0;height:100%;font-family:'Outfit',sans-serif;overflow:hidden}}
.main-container{{display:flex;flex-direction:column;height:100vh}}
#map-wrapper{{position:relative;width:100%;height:42vh;transition:height 0.3s ease;flex-shrink:0}}
#map-wrapper.collapsed{{height:12vh}}
#map{{height:100%;width:100%;background:#dfe5eb}}
#sidebar{{flex:1;display:flex;flex-direction:column;background:white;border-top:2px solid #cbd5e1;overflow:hidden}}
.header{{padding:8px 12px;background:#1e293b;color:white;border-bottom:2px solid var(--accent)}}
.trip-title{{margin:0;font-size:.65rem;font-weight:800;text-transform:uppercase;color:var(--accent)}}
.stats-row{{display:flex;gap:10px;flex-wrap:wrap;margin-top:4px}}
.stat-val{{font-size:.85rem;font-weight:800;color:white}}
.stat-lbl{{font-size:.52rem;color:#94a3b8;text-transform:uppercase}}
#delivery-list{{flex:1;overflow-y:auto;padding:8px;background:#f1f5f9;padding-bottom:60px}}
.card{{background:white;border-radius:12px;padding:10px;margin-bottom:8px;display:grid;gap:8px;align-items:center;border:1px solid #cbd5e1;cursor:pointer;transition:all .2s;-webkit-touch-callout:none;-webkit-user-select:none;user-select:none}}
.card.active{{border-color:var(--p);border-left:5px solid var(--p);background:#eef2ff}}
.stop-num{{width:32px;height:32px;background:var(--p);color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;flex-shrink:0}}
.stop-num.warning {{
background: repeating-linear-gradient(45deg, #000, #000 4px, #f59e0b 4px, #f59e0b 8px) !important;
color: white !important;
text-shadow: 1px 1px 2px black, -1px -1px 2px black, 0px 0px 3px black;
border: 2px solid black;
}}
.stop-info{{display:flex;flex-direction:column;gap:3px;min-width:0}}
.name{{font-size:.85rem;font-weight:800;color:#1e293b;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.addr{{font-size:.75rem;color:#64748b;font-weight:600;line-height:1.1}}
.orario-badge{{display:inline-flex;align-items:center;gap:3px;background:#eff6ff;color:#2563eb;font-size:0.65rem;font-weight:800;padding:2px 7px;border-radius:20px;border:1px solid #bfdbfe;margin-top:1px;width:fit-content}}
.orario-badge .material-icons-round{{font-size:12px !important}}
.eta-badge{{display:inline-flex;align-items:center;gap:3px;background:#e0f2fe;color:#0369a1;font-size:0.65rem;font-weight:800;padding:2px 7px;border-radius:20px;border:1px solid #bae6fd;margin-top:1px;width:fit-content}}
.eta-badge .material-icons-round{{font-size:12px !important}}
.note-chip{{display:flex;align-items:flex-start;gap:4px;background:#fffbeb;color:#92400e;font-size:0.65rem;font-weight:700;padding:4px 7px;border-radius:8px;border:1px solid #fde68a;margin-top:3px;line-height:1.3}}
.note-chip .material-icons-round{{font-size:12px !important;flex-shrink:0;margin-top:1px}}
.btn-nav{{background:var(--accent);color:white;width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;text-decoration:none}}
.btn-call{{background:var(--call);color:white;width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;text-decoration:none}}
.btn-cam{{background:#f59e0b;color:white;width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;border:none;cursor:pointer}}
.btn-ok{{background:#10b981;color:white;width:38px;height:38px;border-radius:8px;display:flex;align-items:center;justify-content:center;border:none;cursor:pointer}}
.card.consegnato{{opacity:0.5;filter:grayscale(1)}}
.card.consegnato .btn-ok{{background:#64748b}}
.nav-col{{display:grid;grid-template-columns:38px 38px;gap:5px;align-items:start;justify-content:end;}}
.material-icons-round{{font-size:18px !important}}
.fab-save{{position:fixed;bottom:20px;right:20px;background:var(--accent);color:white;border:none;border-radius:30px;padding:12px 20px;font-weight:800;font-family:'Outfit',sans-serif;box-shadow:0 4px 12px rgba(16,185,129,0.4);display:none;align-items:center;gap:8px;cursor:pointer;z-index:1000;font-size:1rem;transition:transform 0.2s;}}
.fab-save:active{{transform:scale(0.95);}}

/* Stili Modale Riordino */
#reorder-modal{{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:#f8fafc;z-index:9999;flex-direction:column;}}
.rm-header{{padding:16px;background:#1e293b;color:white;display:flex;justify-content:space-between;align-items:center;box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);}}
.rm-title{{margin:0;font-size:1.1rem;font-weight:800;display:flex;align-items:center;gap:8px;}}
.rm-body{{flex:1;overflow-y:auto;padding:12px;}}
.rm-footer{{padding:16px;background:white;border-top:1px solid #e2e8f0;display:flex;gap:12px;}}
.rm-btn-cancel{{flex:1;padding:14px;border:none;background:#f1f5f9;color:#475569;font-weight:700;border-radius:12px;cursor:pointer;}}
.rm-btn-save{{flex:2;padding:14px;border:none;background:var(--accent);color:white;font-weight:800;border-radius:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;box-shadow:0 4px 12px rgba(16,185,129,0.3);}}
.rm-item{{background:white;border:1px solid #cbd5e1;border-radius:12px;padding:12px;margin-bottom:8px;display:flex;align-items:center;gap:12px;}}
.rm-handle{{color:#94a3b8;cursor:grab;padding:4px;}}
.rm-num{{width:28px;height:28px;background:var(--p);color:white;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:12px;flex-shrink:0;}}
.rm-info{{flex:1;min-width:0;display:flex;flex-direction:column;line-height:1.2;}}
.rm-name{{font-weight:800;color:#0f172a;font-size:0.9rem;}}
.rm-sub{{font-size:0.75rem;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.sortable-ghost{{opacity:0.4; background-color:#f1f5f9;}}
#expand-modal-list .card {{ cursor: default; transition: none !important; }}
.sortable-drag {{ transition: none !important; cursor: grabbing !important; opacity: 1 !important; }}
.drag-handle-modal {{ cursor: grab; padding: 4px; display: flex; align-items: center; color: #94a3b8; touch-action: none; }}
.drag-handle-modal:active {{ cursor: grabbing; color: #3b82f6; }}
.sortable-fallback {{ opacity: 1 !important; background: white !important; cursor: grabbing !important; box-shadow: 0 10px 20px rgba(0,0,0,0.15) !important; transform: scale(1.02); z-index: 99999; }}
.compact-stop-item {{ display: flex; align-items: center; gap: 12px; background: white; padding: 12px 16px; border-radius: 8px; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); user-select: none; margin-bottom: 8px; touch-action: none; }}
.compact-num {{ font-weight: 800; color: white; background: var(--p); border-radius: 4px; padding: 2px 8px; font-size: 0.85rem; min-width: 32px; text-align: center; }}
.compact-name {{ font-weight: 700; color: #0f172a; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: left; line-height: 1.2; }}
.compact-city {{ color: #64748b; font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100px; text-align: right; line-height: 1.2; }}
</style>
</head>
<body>
<div class="main-container">
<div id="map-wrapper">
<div id="map"></div>
<div id="top-left-controls" style="position:absolute; left:10px; top:10px; z-index:10; pointer-events:none; display:flex; gap:8px; align-items:center;"></div>
<div id="bottom-right-controls" style="position:absolute; right:10px; bottom:24px; z-index:10; pointer-events:none; display:flex; flex-direction:column; gap:10px; align-items:center;"></div>
</div>
<div id="sidebar">
<div class="header">
<div style="display:flex; justify-content:space-between; align-items:center;">
<p class="trip-title" style="margin:0;">&#x1F69B; {viaggio_id}</p>
<button onclick="apriModalEspansa()" style="background:#e2e8f0; color:#0f172a; border:none; padding:6px 12px; border-radius:20px; font-weight:bold; font-size:12px; display:flex; align-items:center; gap:4px; box-shadow:0 1px 3px rgba(0,0,0,0.1);"><span class="material-icons-round" style="font-size:16px;">swap_vert</span> Ordina</button>
</div>
<div class="stats-row">
<div><div class="stat-val">&#x23F0; {ora_partenza_dep}</div><div class="stat-lbl">Partenza</div></div>
<div><div class="stat-val">&#x1F6E3;&#xFE0F; {float(km or 0):.1f} km</div><div class="stat-lbl">Km Reali</div></div>
<div><div class="stat-val">&#x1F552; {fmt_min(t_guida_min)}</div><div class="stat-lbl">Guida</div></div>
<div><div class="stat-val">&#x23F1;&#xFE0F; {fmt_min(t_tot_min)}</div><div class="stat-lbl">Totale</div></div>
<div><div class="stat-val">&#x1F4E6; {len(punti)}</div><div class="stat-lbl">Tappe</div></div>
</div>
</div>
<div id="delivery-list">{fermate_html}</div>
</div>
<button id="fab-save" class="fab-save" onclick="saveSequence()"><span class="material-icons-round">save</span> Salva Sequenza</button>
<div id="cam-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.8); z-index:9999; flex-direction:column; align-items:center; justify-content:center; padding:20px;">
    <div style="background:white; border-radius:12px; padding:20px; width:100%; max-width:400px; text-align:center; box-sizing:border-box;">
        <h3 style="margin-top:0; font-family:'Outfit',sans-serif;">Segnalazione</h3>
        <p id="cam-cliente-name" style="font-weight:bold; color:var(--p); margin-bottom:15px; font-family:'Outfit',sans-serif;"></p>
        <button onclick="selectCamType('merce_rotta')" style="width:100%; padding:15px; margin-bottom:10px; background:#ef4444; color:white; border:none; border-radius:8px; font-weight:bold; font-size:16px; font-family:'Outfit',sans-serif;">🔴 Merce Rifiutata / Rotta</button>
        <button onclick="selectCamType('reso_pregresso')" style="width:100%; padding:15px; margin-bottom:15px; background:#3b82f6; color:white; border:none; border-radius:8px; font-weight:bold; font-size:16px; font-family:'Outfit',sans-serif;">🔵 Reso / Ritiro</button>
        <button onclick="closeCamModal()" style="width:100%; padding:15px; background:#e2e8f0; color:#475569; border:none; border-radius:8px; font-weight:bold; font-size:16px; font-family:'Outfit',sans-serif;">Annulla</button>
    </div>
</div>
<div id="expand-trip-modal" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; box-sizing:border-box; background:rgba(15,23,42,0.8); z-index:9999; flex-direction:column; align-items:center; justify-content:center; padding:16px;">
<div style="background:white; border-radius:16px; width:100%; max-width:500px; height:90vh; display:flex; flex-direction:column; overflow:hidden;">
<div style="padding:16px; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center; background:#f8fafc;">
<h3 style="margin:0; font-family:'Outfit',sans-serif;">Modifica Sequenza</h3>
<div style="display:flex; gap:10px;">
<button onclick="chiudiModalEspansa()" style="background:#e2e8f0; color:#475569; border:none; padding:8px 16px; border-radius:8px; font-weight:bold; cursor:pointer;">Annulla</button>
<button onclick="applicaOrdineEspanso()" style="background:var(--p); color:white; border:none; padding:8px 16px; border-radius:8px; font-weight:bold; cursor:pointer;">Applica</button>
</div>
</div>
<div id="expand-modal-list" style="flex:1; overflow-y:auto; padding:8px; background:#f1f5f9; display:flex; flex-direction:column; gap:8px;"></div>
</div>
</div>
<input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none;" onchange="handleFile(event)">
</div>
<script>
const PUNTI={punti_js};
const POLYLINES={polylines_js};
const DEPOT={{lat:{depot["lat"]},lng:{depot["lon"]}}};
let map,markers=[];
function initMap(){{
map=new google.maps.Map(document.getElementById("map"),{{
center:PUNTI.length?{{lat:PUNTI[0].lat,lng:PUNTI[0].lng}}:DEPOT,
zoom:11,mapTypeId:"roadmap",disableDefaultUI:true,zoomControl:false,mapTypeControl:false}});
POLYLINES.forEach(enc=>{{
const path=google.maps.geometry.encoding.decodePath(enc);
new google.maps.Polyline({{path,geodesic:true,strokeColor:"#4f46e5",strokeOpacity:.85,strokeWeight:4,map}});
}});
new google.maps.Marker({{position:DEPOT,map,
icon:{{path:google.maps.SymbolPath.CIRCLE,scale:14,fillColor:"#1e293b",fillOpacity:1,strokeWeight:0}},
label:{{text:"D",color:"white",fontWeight:"bold"}}}});
PUNTI.forEach((p,i)=>{{
let fillColor = "#4f46e5";
let strokeColor = "white";
let strokeWeight = 2;
let labelColor = "white";
if (p.is_parziale) {{
fillColor = "#f59e0b";
strokeColor = "#000000";
strokeWeight = 3;
labelColor = "#000000";
}}
const m=new google.maps.Marker({{position:{{lat:p.lat,lng:p.lng}},map,
icon:{{path:google.maps.SymbolPath.CIRCLE,scale:13,fillColor:fillColor,fillOpacity:1,strokeWeight:strokeWeight,strokeColor:strokeColor}},
label:{{text:String(i+1),color:labelColor,fontWeight:"bold",fontSize:"12px"}}}});
m.addListener("click",()=>selectCard(i));
markers.push(m);
}});

const topLeftControls = document.getElementById("top-left-controls");
const bottomRightControls = document.getElementById("bottom-right-controls");

const mapTypeSelect = document.createElement("select");
mapTypeSelect.innerHTML = `
    <option value="roadmap">Mappa</option>
    <option value="hybrid">Satellite</option>
    <option value="terrain">Rilievo</option>
`;
mapTypeSelect.style.cssText = "background:white; border:none; border-radius:8px; height:34px; font-size:12px; font-weight:bold; box-shadow:0 2px 6px rgba(0,0,0,0.3); color:#0f172a; padding:0 8px; cursor:pointer; pointer-events:auto; outline:none;";
mapTypeSelect.onchange = (e) => {{
    map.setMapTypeId(e.target.value);
}};

const toggleBtn = document.createElement("button");
toggleBtn.innerHTML = '<span class="material-icons-round" style="font-size:20px;">unfold_less</span>';
toggleBtn.style.cssText = "background:white;border:none;border-radius:8px;width:34px;height:34px;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 6px rgba(0,0,0,0.3);cursor:pointer;color:#0f172a;pointer-events:auto;";
toggleBtn.onclick = () => {{
    const mapWrapper = document.getElementById("map-wrapper");
    if(mapWrapper.classList.contains("collapsed")){{
        mapWrapper.classList.remove("collapsed");
        toggleBtn.innerHTML = '<span class="material-icons-round" style="font-size:20px;">unfold_less</span>';
    }} else {{
        mapWrapper.classList.add("collapsed");
        toggleBtn.innerHTML = '<span class="material-icons-round" style="font-size:20px;">unfold_more</span>';
    }}
    setTimeout(() => google.maps.event.trigger(map, "resize"), 300);
}};

topLeftControls.appendChild(mapTypeSelect);
topLeftControls.appendChild(toggleBtn);

const zoomContainer = document.createElement("div");
zoomContainer.style.cssText = "display:flex; flex-direction:column; border-radius:8px; background:white; box-shadow:0 2px 6px rgba(0,0,0,0.3); overflow:hidden; pointer-events:auto;";

const zoomIn = document.createElement("button");
zoomIn.innerHTML = '<span class="material-icons-round" style="font-size:20px;">add</span>';
zoomIn.style.cssText = "background:white; border:none; width:34px; height:34px; display:flex; align-items:center; justify-content:center; cursor:pointer; border-bottom:1px solid #e2e8f0; color:#475569; padding:0;";
zoomIn.onclick = () => map.setZoom(map.getZoom() + 1);

const zoomOut = document.createElement("button");
zoomOut.innerHTML = '<span class="material-icons-round" style="font-size:20px;">remove</span>';
zoomOut.style.cssText = "background:white; border:none; width:34px; height:34px; display:flex; align-items:center; justify-content:center; cursor:pointer; color:#475569; padding:0;";
zoomOut.onclick = () => map.setZoom(map.getZoom() - 1);

zoomContainer.appendChild(zoomIn);
zoomContainer.appendChild(zoomOut);

bottomRightControls.appendChild(zoomContainer);
}}

function selectCard(i){{
document.querySelectorAll(".card").forEach(c=>c.classList.remove("active"));
const card=document.getElementById("card-"+i);
if(card){{card.classList.add("active");card.scrollIntoView({{behavior:"smooth",block:"center"}});}}
if(markers[i]){{map.panTo(markers[i].getPosition());map.setZoom(16);}}
}}

let sequenceChanged = false;

function apriModalEspansa() {{
    const list = document.getElementById("expand-modal-list");
    list.innerHTML = "";
    
    let displayIndex = 1;
    document.querySelectorAll("#delivery-list .card").forEach(c => {{
        if (!c.id.startsWith("card-")) return;
        
        const idxStr = c.id.replace("card-", "");
        const pIndex = parseInt(idxStr, 10);
        const p = PUNTI[pIndex];
        if(!p) return;
        
        const div = document.createElement("div");
        div.className = "compact-stop-item";
        div.id = "modal-" + c.id;
        
        const addressParts = (p.indirizzo || "").split(",");
        const city = addressParts.length > 1 ? addressParts.slice(1).join(',').trim() : (p.indirizzo || "");
        
        div.innerHTML = `
            <div class="drag-handle-modal" style="touch-action: none;">
                <span class="material-icons-round">drag_indicator</span>
            </div>
            <div class="compact-num">${{displayIndex++}}</div>
            <div class="compact-name">${{p.nome || p.ragione_sociale || ''}}</div>
            <div class="compact-city">${{city}}</div>
        `;
        list.appendChild(div);
    }});

    document.getElementById("expand-trip-modal").style.display = "flex";
    
    if (window.expandSortable) window.expandSortable.destroy();
    window.expandSortable = new Sortable(list, {{
        animation: 150,
        ghostClass: 'sortable-ghost',
        forceFallback: true,
        fallbackClass: 'sortable-fallback',
        handle: '.drag-handle-modal',
        onEnd: function() {{
            const items = list.querySelectorAll('.compact-stop-item');
            items.forEach((item, i) => {{
                const num = item.querySelector('.compact-num');
                if(num) num.textContent = i + 1;
            }});
        }}
    }});
}}

function chiudiModalEspansa() {{
    document.getElementById("expand-trip-modal").style.display = "none";
}}

function applicaOrdineEspanso() {{
    const mainList = document.getElementById("delivery-list");
    const modalCards = document.querySelectorAll("#expand-modal-list .compact-stop-item");
    const newOrderIds = Array.from(modalCards).map(mc => mc.id.replace("modal-", ""));
    
    const currentCards = Array.from(document.querySelectorAll("#delivery-list .card")).filter(c => c.id.startsWith("card-"));
    let changed = false;
    for(let i=0; i<newOrderIds.length; i++) {{
        if(currentCards[i] && currentCards[i].id !== newOrderIds[i]) {{
            changed = true; break;
        }}
    }}
    
    if(changed) {{
        const arrivoCard = document.getElementById("arrivo-card");
        newOrderIds.forEach(id => {{
            const c = document.getElementById(id);
            if(c) {{
                if (arrivoCard) {{
                    mainList.insertBefore(c, arrivoCard);
                }} else {{
                    mainList.appendChild(c);
                }}
            }}
        }});
        
        // Aggiorna i numeri visivi delle fermate originali
        const updatedCards = document.querySelectorAll("#delivery-list .card");
        let counter = 1;
        updatedCards.forEach(c => {{
            if (c.id.startsWith("card-")) {{
                const stopNum = c.querySelector(".stop-num");
                if (stopNum && stopNum.innerText !== "R") {{
                    stopNum.innerText = counter;
                }}
                counter++;
            }}
        }});
        
        sequenceChanged = true;
        document.getElementById("fab-save").style.display = "flex";
    }}
    chiudiModalEspansa();
}}

async function saveSequence() {{
    if(!sequenceChanged) return;
    const btn = document.getElementById("fab-save");
    btn.innerHTML = '<span class="material-icons-round">autorenew</span> Salvataggio...';
    btn.style.pointerEvents = "none";
    
    const cards = document.querySelectorAll("#delivery-list .card");
    const sequenza = Array.from(cards)
        .filter(c => c.id.startsWith("card-"))
        .map(c => parseInt(c.id.replace("card-", "")));
        
    try {{
        let realViaggioId = "{actual_viaggio_id if actual_viaggio_id else viaggio_id}";
        if (realViaggioId.includes(" - ")) {{
            realViaggioId = realViaggioId.split(" - ")[1];
        }}
        
        const url = `https://europe-west1-{PROJECT_ID}.cloudfunctions.net/autista_aggiorna_sequenza`;
        const res = await fetch(url, {{
            method: "POST",
            headers: {{"Content-Type": "application/json"}},
            body: JSON.stringify({{ viaggio_id: realViaggioId, sequenza: sequenza }})
        }});
        if(res.ok) {{
            btn.innerHTML = '<span class="material-icons-round">check</span> Fatto!';
            setTimeout(() => window.location.reload(), 1000);
        }} else {{
            throw new Error("Errore salvataggio");
        }}
    }} catch(e) {{
        alert("Errore durante l'aggiornamento. Riprova.");
        btn.innerHTML = '<span class="material-icons-round">save</span> Salva Sequenza';
        btn.style.pointerEvents = "auto";
    }}
}}

const TRIP_ID = "{actual_viaggio_id or viaggio_id}";

function toggleConsegnato(e, idx) {{
    e.stopPropagation();
    const card = document.getElementById('card-' + idx);
    const isConsegnato = card.classList.toggle('consegnato');
    
    let stats = JSON.parse(localStorage.getItem('consegne_' + TRIP_ID) || '{{}}');
    stats[idx] = isConsegnato;
    localStorage.setItem('consegne_' + TRIP_ID, JSON.stringify(stats));
}}

document.addEventListener('DOMContentLoaded', () => {{
    const stats = JSON.parse(localStorage.getItem('consegne_' + TRIP_ID) || '{{}}');
    Object.keys(stats).forEach(idx => {{
        if(stats[idx]) {{
            const card = document.getElementById('card-' + idx);
            if(card) card.classList.add('consegnato');
        }}
    }});
}});

let currentCamIdx = -1;
let currentCamType = "";
function openCamera(e, idx) {{
    e.stopPropagation();
    currentCamIdx = idx;
    document.getElementById("cam-cliente-name").innerText = PUNTI[idx].nome;
    document.getElementById("cam-modal").style.display = "flex";
}}
function closeCamModal() {{
    document.getElementById("cam-modal").style.display = "none";
}}
function selectCamType(type) {{
    currentCamType = type;
    closeCamModal();
    document.getElementById("cameraInput").click();
}}
function handleFile(e) {{
    const file = e.target.files[0];
    if(!file) return;
    
    const btn = document.getElementById("fab-save");
    const origHtml = btn.innerHTML;
    btn.innerHTML = '<span class="material-icons-round" style="animation: spin 1s linear infinite;">autorenew</span> Invio in corso...';
    btn.style.display = "flex";
    btn.style.pointerEvents = "none";
    
    const reader = new FileReader();
    reader.onload = function(event) {{
        const img = new Image();
        img.onload = async function() {{
            const canvas = document.createElement("canvas");
            let width = img.width;
            let height = img.height;
            const MAX_DIM = 1200;
            if (width > height) {{
                if (width > MAX_DIM) {{ height *= MAX_DIM / width; width = MAX_DIM; }}
            }} else {{
                if (height > MAX_DIM) {{ width *= MAX_DIM / height; height = MAX_DIM; }}
            }}
            canvas.width = width;
            canvas.height = height;
            const ctx = canvas.getContext("2d");
            ctx.drawImage(img, 0, 0, width, height);
            const base64 = canvas.toDataURL("image/jpeg", 0.7);
            
            try {{
                let realViaggioId = "{actual_viaggio_id if actual_viaggio_id else viaggio_id}";
                if (realViaggioId.includes(" - ")) realViaggioId = realViaggioId.split(" - ")[1];
                
                const url = `https://europe-west1-{PROJECT_ID}.cloudfunctions.net/autista_salva_reso`;
                const res = await fetch(url, {{
                    method: "POST",
                    headers: {{"Content-Type": "application/json"}},
                    body: JSON.stringify({{
                        viaggio_id: realViaggioId,
                        codice_cliente: PUNTI[currentCamIdx].codice_cliente || "UNK",
                        nome_cliente: PUNTI[currentCamIdx].nome,
                        tipo_segnalazione: currentCamType,
                        foto_base64: base64
                    }})
                }});
                if(res.ok) {{
                    alert("Foto inviata in ufficio con successo!");
                }} else {{
                    alert("Errore nell'invio della foto.");
                }}
            }} catch(err) {{
                alert("Errore di rete durante l'invio.");
            }} finally {{
                btn.innerHTML = origHtml;
                if(!sequenceChanged) btn.style.display = "none";
                btn.style.pointerEvents = "auto";
                document.getElementById("cameraInput").value = "";
            }}
        }}
        img.src = event.target.result;
    }}
    reader.readAsDataURL(file);
}}
</script>

<!-- Modal Riordino -->
<div id="reorder-modal">
    <div class="rm-header">
        <h2 class="rm-title"><span class="material-icons-round">low_priority</span> Riordina Tappe</h2>
    </div>
    <div class="rm-body" id="rm-list">
        <!-- populated by JS -->
    </div>
    <div class="rm-footer">
        <button class="rm-btn-cancel" onclick="chiudiModalRiordino()">Annulla</button>
        <button class="rm-btn-save" id="rm-btn-save" onclick="applicaESalvaRiordino()">
            <span class="material-icons-round">save</span> Salva Ordine
        </button>
    </div>
</div>

<script>
let modalSortable = null;
const puntiDati = {punti_js};

function apriModalRiordino() {{
    const list = document.getElementById("rm-list");
    list.innerHTML = "";
    puntiDati.forEach((p, idx) => {{
        const div = document.createElement("div");
        div.className = "rm-item";
        div.dataset.index = idx;
        const addressParts = (p.indirizzo || "").split(",");
        const city = addressParts.length > 1 ? addressParts[1].trim() : (p.indirizzo || "");
        div.innerHTML = `
            <div class="material-icons-round rm-handle">drag_indicator</div>
            <div class="rm-num">${{idx + 1}}</div>
            <div class="rm-info">
                <span class="rm-name">${{p.nome}}</span>
                <span class="rm-sub">${{p.ragione_sociale || ''}}</span>
            </div>
            <div class="rm-sub" style="flex-shrink:0; text-align:right;">${{city}}</div>
        `;
        list.appendChild(div);
    }});
    
    document.getElementById("reorder-modal").style.display = "flex";
    
    if (modalSortable) modalSortable.destroy();
    modalSortable = new Sortable(list, {{
        animation: 150,
        handle: ".rm-handle",
        ghostClass: "sortable-ghost",
        delay: 150,
        delayOnTouchOnly: true,
        fallbackTolerance: 3
    }});
}}

function chiudiModalRiordino() {{
    document.getElementById("reorder-modal").style.display = "none";
}}

async function applicaESalvaRiordino() {{
    const list = document.getElementById("rm-list");
    const items = list.querySelectorAll(".rm-item");
    const nuovaSequenza = Array.from(items).map(item => parseInt(item.dataset.index));
    
    const changed = nuovaSequenza.some((val, i) => val !== i);
    if (!changed) {{
        chiudiModalRiordino();
        return;
    }}
    
    const btn = document.getElementById("rm-btn-save");
    btn.innerHTML = '<span class="material-icons-round">autorenew</span> Salvataggio...';
    btn.style.pointerEvents = "none";
    
    try {{
        let realViaggioId = '{actual_viaggio_id if actual_viaggio_id else viaggio_id}';
        if (realViaggioId.includes(" - ")) {{
            realViaggioId = realViaggioId.split(" - ").pop();
        }}
        
        const resp = await fetch("https://europe-west1-{os.environ.get('GCP_PROJECT', 'log-solution-60007')}.cloudfunctions.net/autista_aggiorna_sequenza", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{
                viaggio_id: realViaggioId,
                sequenza: nuovaSequenza
            }})
        }});
        
        const res = await resp.json();
        if (res.status === "ok") {{
            alert("Sequenza aggiornata con successo! La pagina si ricaricherà.");
            window.location.reload();
        }} else {{
            alert("Errore nel salvataggio: " + res.message);
            btn.innerHTML = '<span class="material-icons-round">save</span> Salva Ordine';
            btn.style.pointerEvents = "auto";
        }}
    }} catch(err) {{
        alert("Errore di rete: " + err.message);
        btn.innerHTML = '<span class="material-icons-round">save</span> Salva Ordine';
        btn.style.pointerEvents = "auto";
    }}
}}
</script>
</body></html>"""

def _genera_kml_zone(data, zone_list):
    """Genera un file KML base per Google Earth"""
    kml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Document>',
        f'<name>Zone {data}</name>'
    ]
    for z in zone_list:
        kml.append(f'<Folder><name>Zona {z["id_zona"]}</name>')
        for p in z["lista_punti"]:
            if p["lat"] and p["lon"]:
                kml.append(f'<Placemark><name>{p["nome"]}</name><Point><coordinates>{p["lon"]},{p["lat"]},0</coordinates></Point></Placemark>')
        kml.append('</Folder>')
    kml.append('</Document></kml>')
    return "\n".join(kml)

def _genera_html_mappa_generale(data, zone_list):
    """Template della mappa generale con selettore a tendina per il giro"""
    zone_json = json.dumps(zone_list)
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>Mappa Zone - {data}</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&display=swap" rel="stylesheet">
    <script src="https://maps.googleapis.com/maps/api/js?key={GOOGLE_MAPS_API_KEY}&libraries=marker,geometry"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Outfit', sans-serif; display: flex; height: 100vh; overflow: hidden; background: #f8fafc; }}
        #sidebar {{ width: 400px; background: white; border-right: 1px solid #e2e8f0; padding: 20px; display: flex; flex-direction: column; gap: 14px; box-shadow: 2px 0 12px rgba(0,0,0,0.06); z-index: 10; }}
        #map {{ flex: 1; }}
        .sidebar-title {{ font-size: 20px; font-weight: 800; color: #1e293b; }}
        .sidebar-subtitle {{ font-size: 13px; color: #64748b; margin-top: 2px; }}
        #giroSelector {{ width: 100%; height: 46px; border: 2px solid #e2e8f0; border-radius: 12px; padding: 0 14px; font-size: 14px; font-weight: 700; color: #1e293b; background: #f8fafc; outline: none; cursor: pointer; font-family: inherit; transition: border-color 0.2s; }}
        #giroSelector:focus {{ border-color: #4f46e5; }}
        #zone-list {{ overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 8px; }}
        .zone-card {{ border: 2px solid #e2e8f0; border-radius: 14px; padding: 14px; background: #fff; transition: all 0.2s; cursor: pointer; }}
        .zone-card.active {{ border-color: var(--zone-color, #4f46e5); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
        .zone-card:hover {{ border-color: #cbd5e1; }}
        .zone-header {{ display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 14px; }}
        .color-pill {{ width: 14px; height: 14px; border-radius: 4px; flex-shrink: 0; }}
        .zone-meta {{ font-size: 12px; color: #64748b; margin-top: 6px; margin-left: 24px; }}
        .point-list {{ margin-top: 10px; display: none; max-height: 260px; overflow-y: auto; border-top: 1px solid #f1f5f9; padding-top: 10px; }}
        .point-item {{ font-size: 12px; color: #475569; padding: 4px 0 4px 8px; border-left: 3px solid transparent; }}
        .point-item.highlight {{ border-left-color: var(--zone-color, #4f46e5); font-weight: 700; color: #1e293b; }}
        .badge-parziale {{ background: #f59e0b; color: black; font-weight: 800; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 5px; }}
        .expand-btn {{ font-size: 11px; color: #94a3b8; float: right; }}
    </style>
</head>
<body>
    <div id="sidebar">
        <div>
            <div class="sidebar-title">🗺️ Mappa Zone — {data}</div>
            <div class="sidebar-subtitle">Seleziona un giro per evidenziarlo sulla mappa</div>
        </div>
        <select id="giroSelector" onchange="selezionaGiro(this.value)">
            <option value="__all__">📍 Tutti i giri</option>
        </select>
        <div id="zone-list"></div>
    </div>
    <div id="map"></div>
    <script>
        const ZONE = {zone_json};
        let map;
        // Struttura: [{{ zone, markers: [], polylines: [] }}]
        let zoneData = [];
        let selectedIdx = null;

        function initMap() {{
            map = new google.maps.Map(document.getElementById("map"), {{
                center: {{ lat: 45.44, lng: 11.71 }}, zoom: 9,
                mapTypeControl: true,
                streetViewControl: false,
                fullscreenControl: true
            }});

            const select = document.getElementById("giroSelector");
            const list = document.getElementById("zone-list");

            ZONE.forEach((z, idx) => {{
                // Aggiungi option al dropdown
                const opt = document.createElement("option");
                opt.value = idx;
                opt.textContent = `${{z.nome_giro}} (${{z.lista_punti.length}} tappe)`;
                select.appendChild(opt);

                // Crea card nel pannello
                const card = document.createElement("div");
                card.className = "zone-card";
                card.style.setProperty("--zone-color", z.color);
                card.id = `card-${{idx}}`;
                card.onclick = (e) => {{
                    if (e.target.tagName === "INPUT") return;
                    document.getElementById("giroSelector").value = idx;
                    selezionaGiro(idx);
                }};

                const header = document.createElement("div");
                header.className = "zone-header";
                header.innerHTML = `
                    <div class="color-pill" style="background:${{z.color}}"></div>
                    <span style="flex:1">${{z.nome_giro}}</span>
                    <span class="expand-btn" id="expand-${{idx}}">▼</span>
                `;
                card.appendChild(header);

                const meta = document.createElement("div");
                meta.className = "zone-meta";
                meta.textContent = `${{z.lista_punti.length}} tappe`;
                card.appendChild(meta);

                const ptContainer = document.createElement("div");
                ptContainer.className = "point-list";
                ptContainer.id = `pts-${{idx}}`;

                // Costruisci markers e lista punti
                let markers = [];
                z.lista_punti.forEach((p, i) => {{
                    if (p.lat && p.lon) {{
                        let isParziale = p.rientri_alert && Array.isArray(p.rientri_alert) && p.rientri_alert.some(r => r.is_parziale);
                        const fillColor = isParziale ? "#f59e0b" : z.color;
                        const strokeColor = isParziale ? "#000" : "white";
                        const strokeWeight = isParziale ? 3 : 2;
                        const labelColor = isParziale ? "#000" : "white";

                        const marker = new google.maps.Marker({{
                            position: {{ lat: p.lat, lng: p.lon }},
                            map: map,
                            title: p.nome,
                            icon: {{ 
                                path: google.maps.SymbolPath.CIRCLE, 
                                scale: isParziale ? 13 : 11, 
                                fillColor: fillColor, 
                                fillOpacity: 1, 
                                strokeWeight: strokeWeight, 
                                strokeColor: strokeColor 
                            }},
                            label: {{
                                text: String(i + 1),
                                color: labelColor,
                                fontWeight: "bold",
                                fontSize: "11px"
                            }}
                        }});

                        const iw = new google.maps.InfoWindow({{
                            content: `<div style="font-family:'Outfit';padding:6px;min-width:150px"><strong>${{p.nome}}</strong><br><span style="color:#64748b;font-size:12px">Giro: ${{z.nome_giro}}</span></div>`
                        }});
                        marker.addListener('click', () => iw.open(map, marker));

                        markers.push(marker);

                        const ptItem = document.createElement("div");
                        ptItem.className = "point-item";
                        ptItem.innerHTML = `<strong>${{i+1}}.</strong> ${{p.nome}}${{isParziale ? ' <span class="badge-parziale">PARZIALE</span>' : ''}}`;
                        ptContainer.appendChild(ptItem);
                    }}
                }});

                // Costruisci polylines
                let polylines = [];
                if (z._polylines && Array.isArray(z._polylines)) {{
                    z._polylines.forEach(enc => {{
                        try {{
                            const path = google.maps.geometry.encoding.decodePath(enc);
                            const poly = new google.maps.Polyline({{
                                path: path,
                                geodesic: true,
                                strokeColor: z.color || "#4f46e5",
                                strokeOpacity: 0.8,
                                strokeWeight: 4,
                                map: map
                            }});
                            polylines.push(poly);
                        }} catch (e_poly) {{
                            console.error("Errore decodifica polyline:", e_poly);
                        }}
                    }});
                }}

                card.appendChild(ptContainer);
                list.appendChild(card);
                zoneData.push({{ zone: z, markers, polylines, card, ptContainer }});

                // Click sul titolo per espandere lista punti
                header.querySelector("span").onclick = (e) => {{
                    e.stopPropagation();
                    document.getElementById("giroSelector").value = idx;
                    selezionaGiro(idx);
                }};
            }});
        }}

        window.selezionaGiro = function(val) {{
            const all = val === "__all__" || val === "" || val === null;
            const idx = all ? null : parseInt(val);
            selectedIdx = idx;

            zoneData.forEach((zd, i) => {{
                const show = all || i === idx;
                zd.markers.forEach(m => m.setMap(show ? map : null));
                zd.polylines.forEach(p => p.setMap(show ? map : null));
                zd.card.classList.toggle("active", i === idx);
                const ptsEl = document.getElementById(`pts-${{i}}`);
                const expandEl = document.getElementById(`expand-${{i}}`);
                if (i === idx) {{
                    ptsEl.style.display = "block";
                    if (expandEl) expandEl.innerHTML = "▲";
                }} else {{
                    ptsEl.style.display = "none";
                    if (expandEl) expandEl.innerHTML = "▼";
                }}
            }});

            // Zoom sulla zona selezionata
            if (!all && zoneData[idx]) {{
                const bounds = new google.maps.LatLngBounds();
                zoneData[idx].markers.forEach(m => bounds.extend(m.getPosition()));
                if (!bounds.isEmpty()) {{
                    map.fitBounds(bounds, {{ top: 60, right: 60, bottom: 60, left: 60 }});
                }}
                // Scroll alla card
                zoneData[idx].card.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
            }} else if (all) {{
                // Zoom su tutti i punti
                const bounds = new google.maps.LatLngBounds();
                zoneData.forEach(zd => zd.markers.forEach(m => bounds.extend(m.getPosition())));
                if (!bounds.isEmpty()) map.fitBounds(bounds);
            }}
        }};

        window.onload = initMap;
    </script>
</body>
</html>"""