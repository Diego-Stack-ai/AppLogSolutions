import firebase_admin
from firebase_admin import credentials, firestore
import json

cred_prod = credentials.Certificate('prod_key.json')
cred_dev = credentials.Certificate('dev_key.json')

app_prod = firebase_admin.initialize_app(cred_prod, name='prod4')
app_dev = firebase_admin.initialize_app(cred_dev, name='dev4')

db_prod = firestore.client(app=app_prod)
db_dev = firestore.client(app=app_dev)

TARGET_DATE = '25-07-2026'
TENANTS = ['DNR', 'GRAN CHEF', 'CATTEL', 'BAUER', 'Cattel', 'PROGETTO SCUOLE']

data = {
    'prod': {'viaggi': [], 'jobs': []},
    'dev': {'viaggi': [], 'jobs': []}
}

def extract_viaggi(db, env_name):
    env_data = {'viaggi': [], 'jobs': []}
    for t in TENANTS:
        tenant_ref = db.collection('clienti').document(t)
        
        # jobs
        try:
            jobs_query = tenant_ref.collection('processing_jobs').stream()
            for j in jobs_query:
                d = j.to_dict()
                ds = str(d)
                if '25-07-2026' in ds or '2026-07-25' in ds:
                    d['_id'] = j.id
                    d['_tenant'] = t
                    env_data['jobs'].append(d)
        except Exception:
            pass

        # viaggi
        try:
            viaggi = tenant_ref.collection('viaggi ddt').stream()
            for v in viaggi:
                vd = v.to_dict()
                ds = str(vd)
                if '25-07-2026' in ds or '2026-07-25' in ds or '25/07/2026' in ds or '20260725' in ds:
                    vd['_id'] = v.id
                    vd['_tenant'] = t
                    env_data['viaggi'].append(vd)
        except Exception as e:
            print(f"Error reading viaggi ddt for {t}: {e}")
            
    return env_data

print("Extracting Prod viaggi...")
data['prod'] = extract_viaggi(db_prod, 'prod4')
print("Extracting Dev viaggi...")
data['dev'] = extract_viaggi(db_dev, 'dev4')

with open('audit_data_viaggi.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, default=str, ensure_ascii=False)

print("Done. Wrote to audit_data_viaggi.json")
