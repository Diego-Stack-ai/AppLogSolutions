import json
import time
from datetime import datetime
from firebase_functions import https_fn
from firebase_admin import firestore, storage
from core.utils import get_db, BUCKET_NAME
from services.map_service import _genera_html_mappa
from infrastructure.google_maps_api import _get_directions_data, _get_depot_for_points_cloud

def handle_autista_aggiorna_sequenza(req: https_fn.Request) -> https_fn.Response:
    try:
        data = req.get_json()
        viaggio_id = data.get("viaggio_id")
        nuova_sequenza = data.get("sequenza") # list of indices, e.g. [2, 0, 1]
        
        db = get_db()
        doc_ref = db.collection("clienti").document("DNR").collection("viaggi ddt").document(viaggio_id)
        doc = doc_ref.get()
        if not doc.exists:
            return https_fn.Response(json.dumps({"status": "errore", "message": "Viaggio non trovato"}), status=404)
            
        viaggio = doc.to_dict()
        vecchi_punti = viaggio.get("punti_ottimizzati") or viaggio.get("punti", [])
        
        # Riordina i punti in base alla nuova sequenza degli indici inviata dall'autista
        nuovi_punti = []
        for idx in nuova_sequenza:
            if idx < len(vecchi_punti):
                nuovi_punti.append(vecchi_punti[idx])
                
        # Se mancano dei punti (per qualche strano motivo), aggiungiamoli in fondo
        for i, p in enumerate(vecchi_punti):
            if i not in nuova_sequenza:
                nuovi_punti.append(p)
                
        # Calcola distanze ed ETA - _get_directions_data mantiene l'ordine che gli passiamo
        depot = _get_depot_for_points_cloud(nuovi_punti)
        km, sec_guida, polylines = _get_directions_data(nuovi_punti, depot=depot)
        punti_finali = nuovi_punti  # l'ordine è già quello richiesto dall'autista

        
        distinta_url = viaggio.get("distinta_url") or viaggio.get("distinta_light")
        ora_partenza_calc = viaggio.get("_stats", {}).get("ora_partenza", "07:00")
        
        cliente_zona = viaggio.get("cliente_zona", "")
        nome_giro = viaggio.get("nome_giro", viaggio_id)
        if cliente_zona and cliente_zona.upper() not in nome_giro.upper():
            titolo_giro = f"{cliente_zona.upper()} - {nome_giro}"
        else:
            titolo_giro = nome_giro
            
        # Rigenera HTML della mappa per l'autista
        html = _genera_html_mappa(titolo_giro, punti_finali, km, sec_guida, polylines, depot=depot, distinta_url=distinta_url, ora_partenza_dep=ora_partenza_calc, actual_viaggio_id=viaggio_id)
        
        bucket = storage.bucket(name=BUCKET_NAME)
        data_v = viaggio.get("data", "sconosciuta").replace("/", "-")
        html_path = f"CONSEGNE/CONSEGNE_{data_v}/MAPPE_AUTISTI/{viaggio_id}.html"
        blob = bucket.blob(html_path)
        blob.upload_from_string(html.encode("utf-8"), content_type="text/html; charset=utf-8")
        
        # Aggiorna JSON in Storage per la mappa_zone
        try:
            data_str = viaggio.get("data_lavoro") or viaggio.get("data")
            if data_str:
                data_consegna = data_str.replace("/", "-")
                json_path = f"REPORTS/{data_consegna}/viaggi_giornalieri_Johnson.json"
                json_blob = bucket.blob(json_path)
                if json_blob.exists():
                    raw_json = json.loads(json_blob.download_as_string().decode('utf-8'))
                    if isinstance(raw_json, dict):
                        zone_list = raw_json.get("zone", [])
                    else:
                        zone_list = raw_json
                        
                    modificato_json = False
                    id_zona_str = viaggio_id.split('_', 1)[1] if '_' in viaggio_id else viaggio_id
                    for z in zone_list:
                        if z.get("id_zona") == id_zona_str:
                            z["lista_punti"] = punti_finali
                            modificato_json = True
                            break
                            
                    if modificato_json:
                        json_blob.upload_from_string(json.dumps(raw_json, indent=2), content_type='application/json')
                        print(f"Aggiornato JSON Storage per {viaggio_id}")
        except Exception as json_err:
            print(f"Errore aggiornamento JSON Storage: {json_err}")

        # Aggiorna database e timestamp
        doc_ref.update({
            "punti_ottimizzati": punti_finali,
            "_stats.km_reali": km,
            "_stats.minuti_guida": sec_guida // 60,
            "ultimo_aggiornamento": firestore.SERVER_TIMESTAMP
        })
        
        return https_fn.Response(json.dumps({"status": "ok"}), status=200, headers={'Content-Type': 'application/json'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return https_fn.Response(json.dumps({"status": "errore", "message": str(e)}), status=500, headers={'Content-Type': 'application/json'})


def handle_autista_salva_reso(req: https_fn.Request) -> https_fn.Response:
    try:
        data = req.get_json()
        viaggio_id = data.get("viaggio_id")
        codice_cliente = data.get("codice_cliente", "UNK")
        nome_cliente = data.get("nome_cliente", "Sconosciuto")
        tipo_segnalazione = data.get("tipo_segnalazione", "reso_pregresso")
        base64_img = data.get("foto_base64", "")
        
        if not base64_img:
            return https_fn.Response(json.dumps({"status": "errore", "message": "Nessuna foto fornita"}), status=400)
            
        # Pulisci header base64 se presente (es. data:image/jpeg;base64,....)
        if "," in base64_img:
            base64_img = base64_img.split(",")[1]
            
        import base64
        image_data = base64.b64decode(base64_img)
        
        data_oggi = datetime.now().strftime("%Y-%m-%d")
        timestamp_ms = int(time.time() * 1000)
        
        # 1. Carica su Storage
        bucket = storage.bucket(name=BUCKET_NAME)
        file_path = f"RESI/{data_oggi}/{codice_cliente}_{timestamp_ms}.jpg"
        blob = bucket.blob(file_path)
        blob.upload_from_string(image_data, content_type='image/jpeg')
        # Costruisci URL pubblico o tramite get_signed_url
        blob.make_public()
        url_foto = blob.public_url
        
        # 2. Salva su Firestore
        db = get_db()
        db.collection("clienti").document("DNR").collection("resi_e_ritiri").add({
            "id_viaggio": viaggio_id,
            "autista": "Sconosciuto", # in futuro lo recupereremo dal viaggio o dall'auth
            "data_evento": data_oggi,
            "timestamp": timestamp_ms,
            "codice_cliente": codice_cliente,
            "nome_cliente": nome_cliente,
            "tipo_segnalazione": tipo_segnalazione,
            "url_foto": url_foto,
            "letto_da_ufficio": False
        })
        
        return https_fn.Response(json.dumps({"status": "ok", "url_foto": url_foto}), status=200, headers={'Content-Type': 'application/json'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return https_fn.Response(json.dumps({"status": "errore", "message": str(e)}), status=500, headers={'Content-Type': 'application/json'})
