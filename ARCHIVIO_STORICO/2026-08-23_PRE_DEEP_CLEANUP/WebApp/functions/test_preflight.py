import json

def get_tenant_from_cz(cz):
    if not cz: return "DNR"
    cz = cz.upper().strip()
    if cz == "CATTEL": return "CATTEL"
    if cz == "GRAN CHEF": return "GRAN_CHEF"
    return "DNR"

def calcola_preflight(old_zone, ddt_presenti):
    # ddt_presenti = ["CATTEL", "GRAN_CHEF", "DNR"] presenti in split_ddt
    
    elaborati = {"CATTEL": False, "GRAN_CHEF": False, "DNR": False}
    contaminati = False
    
    for zona in old_zone:
        stops = zona.get("stops", [])
        
        # Quali tenant sono presenti in questo viaggio?
        tenants_in_trip = set()
        for stop in stops:
            cz = stop.get("cliente_zona", "")
            tenants_in_trip.add(get_tenant_from_cz(cz))
            
        for t in tenants_in_trip:
            if t in elaborati:
                elaborati[t] = True
                
        # Controllo contaminazione:
        # Se in questo viaggio c'è almeno un tenant che DEVE essere aggiornato (è in ddt_presenti)
        # E allo stesso tempo c'è almeno un tenant che NON DEVE essere aggiornato (non in ddt_presenti)
        # Allora c'è contaminazione!
        
        tenants_da_aggiornare = tenants_in_trip.intersection(set(ddt_presenti))
        tenants_da_preservare = tenants_in_trip - set(ddt_presenti)
        
        if len(tenants_da_aggiornare) > 0 and len(tenants_da_preservare) > 0:
            contaminati = True

    return elaborati, contaminati
