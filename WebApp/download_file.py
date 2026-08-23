import os
from firebase_admin import credentials, storage
import firebase_admin

cred = credentials.Certificate('prod_key.json')
app = firebase_admin.initialize_app(cred, {'storageBucket': 'log-solution-60007.firebasestorage.app'})
bucket = storage.bucket(app=app)
blob = bucket.blob('input_pdf_fornitore/CATTEL_25-07-2026_ReportPianificazione.xlsx')
blob.download_to_filename('CATTEL_25-07-2026_ReportPianificazione.xlsx')
print("Downloaded!")
