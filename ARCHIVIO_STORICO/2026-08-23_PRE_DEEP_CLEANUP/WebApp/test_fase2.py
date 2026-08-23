import sys
import json
import re

def enrich_delivery_with_canonical_schema(
    legacy_delivery,
    tenant,
    competenza,
    job_id,
    delivery_index,
    data_elab,
    etichetta
):
    enriched = dict(legacy_delivery)
    
    # Costruisci l'identificativo univoco
    base_id = f"{tenant}_{competenza}_{job_id}_{delivery_index:04d}"
    sanitized_id = re.sub(r'[^a-zA-Z0-9_\-]', '', base_id)
    
    # Document storage path
    pdf_name = legacy_delivery.get("pdf_name", "")
    storage_path = legacy_delivery.get("storage_path", "")
    if not storage_path and pdf_name:
        storage_path = f"split_ddt/{data_elab}/{etichetta}/{pdf_name}"
        
    # Logistics handling
    colli = legacy_delivery.get("colli")
    if colli in (None, ""):
        colli = legacy_delivery.get("gc_colli")
        
    peso_kg = legacy_delivery.get("peso")
    if peso_kg in (None, ""):
        peso_kg = legacy_delivery.get("gc_peso_kg")
        
    # Time windows
    time_windows = []
    start = legacy_delivery.get("orario_min") or legacy_delivery.get("om") or ""
    end = legacy_delivery.get("orario_max") or legacy_delivery.get("oM") or ""
    if start or end:
        time_windows.append({
            "start": start,
            "end": end
        })
        
    # Aggiungi campi canonici
    enriched["schema_version"] = "1.0"
    enriched["delivery_id"] = sanitized_id
    
    enriched["source"] = {
        "tenant": tenant,
        "competenza": competenza,
        "job_id": job_id,
        "parser_type": etichetta
    }
    
    enriched["customer"] = {
        "codice_originale": legacy_delivery.get("codice_consegna", ""),
        "ragione_sociale": legacy_delivery.get("ragsoc", ""),
        "indirizzo": legacy_delivery.get("ind", ""),
        "cap": legacy_delivery.get("cap", ""),
        "citta": legacy_delivery.get("loc", ""),
        "provincia": legacy_delivery.get("prv", "")
    }
    
    enriched["document"] = {
        "numero_ddt": legacy_delivery.get("num_ddt", ""),
        "data": legacy_delivery.get("data", data_elab),
        "pdf_name": pdf_name,
        "storage_path": storage_path
    }
    
    enriched["logistics"] = {
        "colli": colli,
        "peso_kg": peso_kg,
        "cartoni": legacy_delivery.get("gc_num_cartone"),
        "bancali": legacy_delivery.get("bancali"),
        "targa": legacy_delivery.get("cattel_zona_viaggio", ""),
        "autista": legacy_delivery.get("autista", ""),
        "zona_origine": legacy_delivery.get("zona", "")
    }
    
    enriched["time_windows"] = time_windows
    
    return enriched

def run_tests():
    deliveries = {
        "FRUTTA": {
            "codice_consegna": "f123",
            "data": "02-08-2026",
            "num_ddt": "54321",
            "pdf_name": "f123_02-08-2026_54321.pdf",
            "tipo": "FRUTTA",
            "competenza": "DNR_FRUTTA",
            "zona": "VR"
        },
        "GRAND_CHEF": {
            "codice_consegna": "g456",
            "gc_colli": 5,
            "gc_peso_kg": 15.5,
            "gc_num_cartone": 2,
            "orario_min": "08:00",
            "orario_max": "12:00",
            "pdf_name": "g456_02-08-2026.pdf"
        },
        "CATTEL": {
            "codice_consegna": "c789",
            "cattel_zona_viaggio": "TRUCK_1",
            "autista": "Mario",
            "gc_colli": 10
        },
        "DAC": {
            "codice_consegna": "dac001",
            "ragsoc": "Rist DAC",
            "ind": "Via Roma",
            "loc": "Milano",
            "prv": "MI",
            "cap": "20100",
            "orari": "Mattina",
            "colli": 20,
            "peso": 100,
            "bancali": 2,
            "storage_path": "split_ddt/02-08-2026/DAC/dac001_02-08-2026.pdf"
        }
    }
    
    contexts = {
        "FRUTTA": ("DNR", "DNR_FRUTTA", "jobF", 0, "02-08-2026", "FRUTTA"),
        "GRAND_CHEF": ("GRAN_CHEF", "GRAN_CHEF", "jobG", 1, "02-08-2026", "GRAND_CHEF"),
        "CATTEL": ("CATTEL", "CATTEL", "jobC", 2, "02-08-2026", "CATTEL"),
        "DAC": ("DAC", "DAC", "jobD", 3, "02-08-2026", "DAC")
    }

    all_good = True
    ids = set()

    print("=== INIZIO TEST FASE 2 ===")
    for tipo, legacy in deliveries.items():
        ctx = contexts[tipo]
        print(f"\\nTest {tipo}...")
        
        try:
            enriched = enrich_delivery_with_canonical_schema(
                legacy, ctx[0], ctx[1], ctx[2], ctx[3], ctx[4], ctx[5]
            )
        except Exception as e:
            print(f"ERRORE durante l'arricchimento: {e}")
            all_good = False
            continue

        # 1. Tutti i campi legacy devono esistere intatti
        legacy_intatti = all(legacy[k] == enriched[k] for k in legacy)
        if not legacy_intatti:
            print("FALLITO: Campi legacy alterati o mancanti.")
            all_good = False
            
        # 2. schema_version presente
        if enriched.get("schema_version") != "1.0":
            print("FALLITO: schema_version errato o assente.")
            all_good = False
            
        # 3. delivery_id univoco
        d_id = enriched.get("delivery_id")
        if not d_id or d_id in ids:
            print("FALLITO: delivery_id non univoco o assente.")
            all_good = False
        ids.add(d_id)
        
        # 4. dizionari canonici presenti
        for key in ["source", "customer", "document", "logistics", "time_windows"]:
            if key not in enriched:
                print(f"FALLITO: chiave canonica {key} mancante.")
                all_good = False
                
        # 5. Storage path corretto
        storage_path = enriched["document"].get("storage_path")
        expected_path = ""
        if tipo == "DAC":
            expected_path = "split_ddt/02-08-2026/DAC/dac001_02-08-2026.pdf"
        elif tipo == "FRUTTA":
            expected_path = "split_ddt/02-08-2026/FRUTTA/f123_02-08-2026_54321.pdf"
        elif tipo == "GRAND_CHEF":
            expected_path = "split_ddt/02-08-2026/GRAND_CHEF/g456_02-08-2026.pdf"
            
        if storage_path != expected_path:
            print(f"FALLITO: storage_path errato per {tipo}. Atteso: '{expected_path}', Trovato: '{storage_path}'")
            all_good = False

        # 6. Time windows
        tw = enriched["time_windows"]
        if tipo == "GRAND_CHEF" and (len(tw) != 1 or tw[0]["start"] != "08:00"):
            print("FALLITO: time_windows non estratto correttamente per GRAND_CHEF")
            all_good = False
        if tipo == "DAC" and len(tw) != 0:
            print("FALLITO: time_windows non vuoto per DAC (il campo orari NON doveva essere parsato)")
            all_good = False
            
        # 7. Serializzazione JSON
        try:
            json.dumps(enriched)
        except Exception as e:
            print(f"FALLITO: json.dumps ha generato errore: {e}")
            all_good = False
            
        # Stampa risultato
        print(f"Prima (chiavi legacy): {len(legacy)}")
        print(f"Dopo (chiavi totali): {len(enriched)}")
        print(json.dumps(enriched, indent=2))
        
    if all_good:
        print("\\n✅ TUTTI I TEST SUPERATI!")
    else:
        print("\\n❌ ALCUNI TEST SONO FALLITI!")

if __name__ == "__main__":
    run_tests()
