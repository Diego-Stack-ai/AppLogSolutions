import os
import json
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'dev_key.json'
import firebase_admin
from firebase_admin import firestore, storage

app = firebase_admin.initialize_app(None, {'storageBucket': 'log-solutions-sviluppo.firebasestorage.app'})
db = firestore.client(app=app)
bucket = storage.bucket(app=app)

trip_id = '25-07-2026_CATTEL_0000_01_bda95be14aaa'

report = {
    'viaggi_rimasti': [],
    'jobs_rimasti': [],
    'locks_rimasti': [],
    'storage_orfani': [],
    'mappe_orfane': [],
    'distinte_orfane': []
}

# 1. Viaggi 25-07-2026
viaggi = db.collection('clienti').document('CATTEL').collection('viaggi ddt').where('data_lavoro', '==', '25-07-2026').stream()
for v in viaggi:
    report['viaggi_rimasti'].append(v.id)
# Also check explicit ID
doc = db.collection('clienti').document('CATTEL').collection('viaggi ddt').document(trip_id).get()
if doc.exists and doc.id not in report['viaggi_rimasti']:
    report['viaggi_rimasti'].append(doc.id)

# 2. Jobs 25-07-2026
jobs = db.collection('clienti').document('CATTEL').collection('processing_jobs').where('dataViaggi', '==', '25-07-2026').stream()
for j in jobs:
    report['jobs_rimasti'].append(j.id)
doc = db.collection('clienti').document('CATTEL').collection('processing_jobs').document('jgsbJytUKVtXWx0nKwRd').get()
if doc.exists and doc.id not in report['jobs_rimasti']:
    report['jobs_rimasti'].append(doc.id)

# 3. Locks
locks = db.collection('clienti').document('CATTEL').collection('trip_title_locks').stream()
for l in locks:
    d = l.to_dict()
    if d.get('tripId') == trip_id or d.get('targa') == '0000' or l.id == '65c48b90050d571b38947b8f':
        report['locks_rimasti'].append(l.id)

# 4. Storage
blobs = bucket.list_blobs()
for b in blobs:
    if 'CATTEL' in b.name and '25-07-2026' in b.name and 'REPORTS' not in b.name and 'input_pdf_fornitore' not in b.name:
        report['storage_orfani'].append(b.name)
    if 'jgsbJytUKVtXWx0nKwRd' in b.name and b.name not in report['storage_orfani']:
        report['storage_orfani'].append(b.name)

# 5. Mappe
mappe = db.collection('mappe_viaggi').where('tripId', '==', trip_id).stream()
for m in mappe:
    report['mappe_orfane'].append(m.id)

print(json.dumps(report, indent=2))
