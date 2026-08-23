import os
import json
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'dev_key.json'
import firebase_admin
from firebase_admin import firestore, storage

app = firebase_admin.initialize_app(None, {'storageBucket': 'log-solutions-sviluppo.firebasestorage.app'})
db = firestore.client(app=app)
bucket = storage.bucket(app=app)

trip_id = '25-07-2026_CATTEL_0000_01_bda95be14aaa'

inventory = {
    'processing_jobs': [],
    'title_locks': [],
    'storage_files': [],
    'mappe': [],
    'distinte': [],
    'viaggio': None
}

# 1. Viaggio
viaggio_ref = db.collection('clienti').document('CATTEL').collection('viaggi ddt').document(trip_id)
v = viaggio_ref.get()
if v.exists:
    inventory['viaggio'] = {'path': v.reference.path, 'data': v.to_dict()}

# 2. Processing Jobs
jobs = db.collection('clienti').document('CATTEL').collection('processing_jobs').stream()
for j in jobs:
    d = j.to_dict()
    if str(d).find(trip_id) != -1 or d.get('dataViaggi') == '25-07-2026' or d.get('sourceJobId') == 'jgsbJytUKVtXWx0nKwRd' or j.id == 'jgsbJytUKVtXWx0nKwRd':
        inventory['processing_jobs'].append({'path': j.reference.path, 'data': d})

# 3. Title Locks
locks = db.collection('clienti').document('CATTEL').collection('trip_title_locks').stream()
for l in locks:
    d = l.to_dict()
    if d.get('tripId') == trip_id or d.get('targa') == '0000' or l.id == '65c48b90050d571b38947b8f':
        inventory['title_locks'].append({'path': l.reference.path, 'data': d})

# 4. Storage Files
blobs = bucket.list_blobs()
for b in blobs:
    if 'CATTEL' in b.name and '25-07-2026' in b.name:
        inventory['storage_files'].append({
            'name': b.name,
            'generation': b.generation,
            'createTime': str(b.time_created),
            'updateTime': str(b.updated),
            'size': b.size,
            'contentType': b.content_type
        })

# 5. Mappe
mappe = db.collection('mappe_viaggi').where('tripId', '==', trip_id).stream()
for m in mappe:
    inventory['mappe'].append({'path': m.reference.path, 'data': m.to_dict()})
# check distinte or other collections if trip_id is in them
all_colls = db.collections()
for coll in all_colls:
    if coll.id not in ['viaggi', 'processing_jobs', 'trip_title_locks', 'mappe_viaggi']:
        try:
            docs = coll.where('tripId', '==', trip_id).stream()
            for doc in docs:
                inventory['distinte'].append({'path': doc.reference.path, 'data': doc.to_dict()})
        except Exception:
            pass

with open('inventory.json', 'w') as f:
    json.dump(inventory, f, default=str, indent=2)

print("Inventory saved to inventory.json")
