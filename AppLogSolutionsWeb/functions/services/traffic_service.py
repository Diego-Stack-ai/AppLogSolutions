from datetime import datetime
import time as time_module

def handle_aggiorna_traffico_serale(
    data_consegna,
    db,
    get_directions_with_traffic_fn,
    haversine_fn,
    registra_statistica_fn,
    depot_cloud,
    time_per_stop_min
):
    """
    BAT 7B Web: Ricalcola tempi percorrenza con traffico reale attuale.
    Legge tutti i viaggi del giorno da Firestore (status ottimizzato/completato),
    chiama Directions API con departure_time=now per ogni tratta,
    aggiorna t_guida_min, t_tot_min, km_reali in Firestore.
    """
    start = time_module.time()

    if not data_consegna:
        return {"status": "errore", "message": "data_consegna mancante", "errori": [], "data": {}}

    print(f"[BAT7B] Avvio aggiornamento traffico per {data_consegna}")
    db_ref = db.collection('clienti').document('DNR').collection('viaggi ddt')
    snap = db_ref.where('data_lavoro', '==', data_consegna).get()

    zone_aggiornate = 0
    errori = []

    for doc in snap:
        viaggio    = doc.to_dict()
        viaggio_id = doc.id
        stato      = viaggio.get('status', '')
        if stato not in ('ottimizzato', 'completato'):
            continue

        punti = viaggio.get('punti_ottimizzati', [])
        if len(punti) < 2:
            continue

        try:
            sec_tot  = 0
            km_tot   = 0.0
            # Percorso completo: deposito -> punti -> deposito
            tutti = [depot_cloud] + list(punti) + [depot_cloud]
            for i in range(len(tutti) - 1):
                sec      = get_directions_with_traffic_fn(tutti[i], tutti[i + 1])
                sec_tot += sec
                km_tot  += haversine_fn(tutti[i], tutti[i + 1]) / 1000.0  # m -> km

            t_guida_min = sec_tot // 60
            t_tot_min   = t_guida_min + len(punti) * time_per_stop_min

            db_ref.document(viaggio_id).update({
                't_guida_min':           t_guida_min,
                't_tot_min':             t_tot_min,
                'km_reali':              round(km_tot, 1),
                'traffico_aggiornato_at': datetime.now().isoformat()
            })
            zone_aggiornate += 1
            print(f"[BAT7B] OK {viaggio_id}: {t_guida_min}min guida, {km_tot:.1f}km (con traffico)")

        except Exception as e:
            errori.append(f"{viaggio_id}: {str(e)}")
            print(f"[BAT7B WARN] {viaggio_id}: {e}")

    elapsed = time_module.time() - start
    registra_statistica_fn('aggiorna_traffico_serale', elapsed, len(errori))

    return {
        "status": "ok" if not errori else "parziale",
        "message": f"{zone_aggiornate} zone aggiornate con traffico reale in {elapsed:.1f}s",
        "errori": errori,
        "data": {
            "zone_aggiornate": zone_aggiornate,
            "elapsed_sec":     round(elapsed, 1)
        }
    }
