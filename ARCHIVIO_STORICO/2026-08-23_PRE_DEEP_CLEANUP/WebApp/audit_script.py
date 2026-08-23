import firebase_admin
from firebase_admin import credentials, firestore
import json
import os
import datetime

# Setup apps
cred_prod = credentials.Certificate('prod_key.json')
cred_dev = credentials.Certificate('dev_key.json')

app_prod = firebase_admin.initialize_app(cred_prod, name='prod')
app_dev = firebase_admin.initialize_app(cred_dev, name='dev')

db_prod = firestore.client(app=app_prod)
db_dev = firestore.client(app=app_dev)

TARGET_DATE = '2026-07-25'
TARGET_DATE_ALT = '25-07-2026'
TARGET_DATE_SLASH = '25/07/2026'
TARGET_DATE_NO_DASH = '20260725'

TENANTS = ['DNR', 'GRAN CHEF', 'CATTEL', 'BAUER', 'Cattel', 'PROGETTO SCUOLE']

data = {
    'prod': {},
    'dev': {}
}

def extract_efficient(db, env_name):
    env_data = {
        'jobs': [],
        'deliveries': [],
        'viaggi': [],
        'title_locks': []
    }
    
    for t in TENANTS:
        tenant_ref = db.collection('clienti').document(t)
        
        try:
            jobs_query = tenant_ref.collection('processing_jobs').order_by('createdAt', direction=firestore.Query.DESCENDING).limit(50).stream()
            job_ids = []
            for j in jobs_query:
                d = j.to_dict()
                ds = str(d)
                if TARGET_DATE in ds or TARGET_DATE_ALT in ds or TARGET_DATE_SLASH in ds or TARGET_DATE_NO_DASH in ds:
                    d['_id'] = j.id
                    d['_tenant'] = t
                    env_data['jobs'].append(d)
                    job_ids.append(j.id)
            
            if not job_ids:
                jobs_query = tenant_ref.collection('processing_jobs').limit(100).stream()
                for j in jobs_query:
                    d = j.to_dict()
                    ds = str(d)
                    if TARGET_DATE in ds or TARGET_DATE_ALT in ds or TARGET_DATE_SLASH in ds or TARGET_DATE_NO_DASH in ds:
                        if j.id not in job_ids:
                            d['_id'] = j.id
                            d['_tenant'] = t
                            env_data['jobs'].append(d)
                            job_ids.append(j.id)
            
            # Since there could be thousands of deliveries, we need to collect them.
            for j_id in job_ids:
                dels = tenant_ref.collection('deliveries').where('sourceJobId', '==', j_id).stream()
                for dl in dels:
                    d = dl.to_dict()
                    d['_id'] = dl.id
                    d['_tenant'] = t
                    env_data['deliveries'].append(d)
                    
                viaggi = tenant_ref.collection('viaggi').where('sourceJobId', '==', j_id).stream()
                for v in viaggi:
                    vd = v.to_dict()
                    vd['_id'] = v.id
                    vd['_tenant'] = t
                    env_data['viaggi'].append(vd)
                    
            try:
                locks = tenant_ref.collection('trip_title_locks').stream()
                for lk in locks:
                    ld = lk.to_dict()
                    if TARGET_DATE in str(ld) or TARGET_DATE_ALT in str(ld) or TARGET_DATE_SLASH in str(ld):
                        ld['_id'] = lk.id
                        ld['_tenant'] = t
                        env_data['title_locks'].append(ld)
            except Exception:
                pass

        except Exception as e:
            print(f"Error reading tenant {t} in {env_name}: {e}")
            
    return env_data

print("Extracting Prod...")
data['prod'] = extract_efficient(db_prod, 'prod')
print("Extracting Dev...")
data['dev'] = extract_efficient(db_dev, 'dev')

with open('audit_data_output.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, default=str, ensure_ascii=False)

print("Done. Wrote to audit_data_output.json")
