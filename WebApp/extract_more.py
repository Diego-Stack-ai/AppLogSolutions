import firebase_admin
from firebase_admin import credentials, firestore
import json

cred_prod = credentials.Certificate('prod_key.json')
cred_dev = credentials.Certificate('dev_key.json')

app_prod = firebase_admin.initialize_app(cred_prod, name='prod2')
app_dev = firebase_admin.initialize_app(cred_dev, name='dev2')

db_prod = firestore.client(app=app_prod)
db_dev = firestore.client(app=app_dev)

TARGET_DATE = '25-07-2026'
TENANTS = ['DNR', 'GRAN CHEF', 'CATTEL']

data = {
    'prod': {'deliveries': [], 'viaggi': []},
    'dev': {'deliveries': [], 'viaggi': []}
}

def extract_broad(db, env_name):
    env_data = {'deliveries': [], 'viaggi': []}
    for t in TENANTS:
        tenant_ref = db.collection('clienti').document(t)
        
        # deliveries
        try:
            dels = tenant_ref.collection('deliveries').where('data_lavoro', '==', TARGET_DATE).stream()
            for dl in dels:
                d = dl.to_dict()
                d['_id'] = dl.id
                d['_tenant'] = t
                env_data['deliveries'].append(d)
        except Exception as e:
            print(f"Error reading deliveries for {t}: {e}")

        # viaggi
        try:
            viaggi = tenant_ref.collection('viaggi').where('data_lavoro', '==', TARGET_DATE).stream()
            for v in viaggi:
                vd = v.to_dict()
                vd['_id'] = v.id
                vd['_tenant'] = t
                env_data['viaggi'].append(vd)
        except Exception as e:
            print(f"Error reading viaggi for {t}: {e}")
            
    return env_data

print("Extracting Broad Prod...")
data['prod'] = extract_broad(db_prod, 'prod2')
print("Extracting Broad Dev...")
data['dev'] = extract_broad(db_dev, 'dev2')

with open('audit_data_broad.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, default=str, ensure_ascii=False)

print("Done. Wrote to audit_data_broad.json")
