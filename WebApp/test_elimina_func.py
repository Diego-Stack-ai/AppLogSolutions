import datetime
import hashlib
import json
from collections import defaultdict

def _get_tenant_storage_aliases(tenant_id):
    if tenant_id == 'GRAN CHEF':
        return ['GRAN CHEF', 'GRAN_CHEF', 'GRAND CHEF', 'GRAND_CHEF', 'GRANCHEF']
    if tenant_id == 'GRAND_CHEF':
        return ['GRAND_CHEF', 'GRAN_CHEF', 'GRAN CHEF', 'GRAND CHEF', 'GRANCHEF']
    t_nosp = tenant_id.replace(' ', '_')
    return list(set([tenant_id, t_nosp]))

def canonical_hash(data):
    s = json.dumps(data, sort_keys=True)
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

def build_manifest(db, bucket, data_consegna, all_tenants):
    manifest = {
        'DELETE_CANDIDATES': {
            'firestore': [],
            'storage': []
        },
        'PRESERVED_DATA': {
            'firestore': []
        }
    }
    
    # 1. Processing jobs (quarantine)
    try:
        q_docs = db.collection('processing_jobs_quarantine').where('data_lavoro', '==', data_consegna).stream()
        for doc in q_docs:
            manifest['DELETE_CANDIDATES']['firestore'].append({
                'sistema': 'firestore', 'path': doc.reference.path, 'tenant': 'N/A',
                'categoria': 'quarantine', 'data': data_consegna, 'motivazione': 'Errori specifici della giornata'
            })
    except Exception: pass

    # 2. Iterazione sui tenants per Firestore
    for tenant in all_tenants:
        # A. Processing jobs
        try:
            jobs = db.collection('clienti').document(tenant).collection('processing_jobs').where('data_lavoro', '==', data_consegna).stream()
            for job in jobs:
                manifest['DELETE_CANDIDATES']['firestore'].append({
                    'sistema': 'firestore', 'path': job.reference.path, 'tenant': tenant,
                    'categoria': 'processingJobs', 'data': data_consegna, 'motivazione': 'Job operativo giornaliero'
                })
        except Exception: pass
        
        # B. Viaggi ddt
        try:
            viaggi = db.collection('clienti').document(tenant).collection('viaggi ddt').where('data_lavoro', '==', data_consegna).stream()
            for v in viaggi:
                manifest['DELETE_CANDIDATES']['firestore'].append({
                    'sistema': 'firestore', 'path': v.reference.path, 'tenant': tenant,
                    'categoria': 'trips', 'data': data_consegna, 'tripId': v.id, 'motivazione': 'Viaggio operativo giornaliero'
                })
        except Exception: pass

        # C. Title locks (anche orfani)
        try:
            locks = db.collection('clienti').document(tenant).collection('trip_title_locks').where('data_lavoro', '==', data_consegna).stream()
            for l in locks:
                data = l.to_dict()
                is_orphan = 'tripId' not in data
                cat = 'orphanTitleLocks' if is_orphan else 'titleLocks'
                manifest['DELETE_CANDIDATES']['firestore'].append({
                    'sistema': 'firestore', 'path': l.reference.path, 'tenant': tenant,
                    'categoria': cat, 'data': data_consegna, 'tripId': data.get('tripId', 'N/A'), 'motivazione': 'Lock di concorrenza giornaliero'
                })
        except Exception: pass

        # D. Pianificazione viaggi
        try:
            piani = db.collection('clienti').document(tenant).collection('pianificazione_viaggi').where('data_lavoro', '==', data_consegna).stream()
            for p in piani:
                manifest['DELETE_CANDIDATES']['firestore'].append({
                    'sistema': 'firestore', 'path': p.reference.path, 'tenant': tenant,
                    'categoria': 'planning', 'data': data_consegna, 'motivazione': 'Assegnazione operativa giornaliera'
                })
        except Exception: pass

        # E. ddt (se esistente)
        try:
            ddts = db.collection('clienti').document(tenant).collection('ddt').where('data_consegna', '==', data_consegna).stream()
            for d in ddts:
                manifest['DELETE_CANDIDATES']['firestore'].append({
                    'sistema': 'firestore', 'path': d.reference.path, 'tenant': tenant,
                    'categoria': 'deliveries', 'data': data_consegna, 'motivazione': 'Dettaglio spedizione giornaliero'
                })
        except Exception: pass

        # F. reports_logistici
        try:
            rep = db.collection('clienti').document(tenant).collection('reports_logistici').document(data_consegna).get()
            if rep.exists:
                manifest['DELETE_CANDIDATES']['firestore'].append({
                    'sistema': 'firestore', 'path': rep.reference.path, 'tenant': tenant,
                    'categoria': 'dailyReports', 'data': data_consegna, 'motivazione': 'Statistica esclusiva della giornata'
                })
        except Exception: pass
        
        # PRESERVED: Registriamo solo a livello di collection per la UI
        manifest['PRESERVED_DATA']['firestore'].append({'path': f'clienti/{tenant}/raccolta clienti', 'categoria': 'customers'})
        manifest['PRESERVED_DATA']['firestore'].append({'path': f'clienti/{tenant}/nuovi articoli rilevati', 'categoria': 'articles'})
        manifest['PRESERVED_DATA']['firestore'].append({'path': f'clienti/{tenant}/nuovi codici consegna', 'categoria': 'geocoding'})

    manifest['PRESERVED_DATA']['firestore'].append({'path': 'distanze_cache', 'categoria': 'distanceCaches'})
    manifest['PRESERVED_DATA']['firestore'].append({'path': 'percorsi_stradali_cache', 'categoria': 'distanceCaches'})

    # 3. Storage Enumeration
    # Costruiamo la lista esatta dei prefissi da cercare
    data_f = data_consegna.replace('/', '-')
    search_prefixes = [
        f"split_ddt/{data_consegna}/",
        f"REPORTS/{data_consegna}/",
        f"CONSEGNE/CONSEGNE_{data_f}/",
        "input_pdf_fornitore/",
        "uploads/",
        "processing_jobs/"
    ]
    for tenant in all_tenants:
        aliases = _get_tenant_storage_aliases(tenant)
        for al in aliases:
            search_prefixes.append(f"{al}/REPORTS/{data_consegna}/")
            search_prefixes.append(f"{al}/CONSEGNE/CONSEGNE_{data_f}/")
            
    # Per input_pdf_fornitore e root folders, facciamo un list e filtriamo.
    # Ma list_blobs puo essere lento su tutto il bucket. Facciamo list solo per i prefissi.
    try:
        # Per i prefissi che contengono gia la data, tutto cio che c'e dentro e da cancellare (derivato)
        for pref in search_prefixes:
            blobs = bucket.list_blobs(prefix=pref)
            for b in blobs:
                # Se il prefisso e una cartella condivisa (input_pdf, uploads), verifichiamo la data
                if pref in ["input_pdf_fornitore/", "uploads/", "processing_jobs/"]:
                    # Deve contenere la data esatta (25-07-2026) nel nome o nei metadati 
                    # E deve corrispondere logicamente (potremmo stringere il check, ma la stringa data e molto specifica)
                    if data_consegna in b.name or data_f in b.name:
                        manifest['DELETE_CANDIDATES']['storage'].append({
                            'sistema': 'storage', 'path': b.name, 'tenant': 'N/A',
                            'categoria': 'inputFiles' if 'input' in pref else 'temporaryFiles',
                            'data': data_consegna, 'motivazione': 'Nome file contiene la data',
                            'generation': b.generation
                        })
                else:
                    # Derivato specifico
                    manifest['DELETE_CANDIDATES']['storage'].append({
                        'sistema': 'storage', 'path': b.name, 'tenant': 'N/A',
                        'categoria': 'intermediateFiles',
                        'data': data_consegna, 'motivazione': 'Cartella output specifica della data',
                        'generation': b.generation
                    })
    except Exception as e:
        print(f"Error enumerating storage: {e}")

    # Deduplica storage paths (alcuni alias potrebbero sovrapporsi)
    seen = set()
    dedup_storage = []
    for s in manifest['DELETE_CANDIDATES']['storage']:
        if s['path'] not in seen:
            seen.add(s['path'])
            dedup_storage.append(s)
    manifest['DELETE_CANDIDATES']['storage'] = dedup_storage

    return manifest

print("Compile success 2")
