import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('prod_key.json')
app = firebase_admin.initialize_app(cred, name='prod')
db = firestore.client(app=app)

presenze = db.collection('presenze').where('mese', '==', '2026-07').stream()

out = '# Riepilogo Presenze Luglio 2026 (PRODUZIONE)\n\n'
out += '| Data | Autista | Targa | Viaggio | Cliente |\n'
out += '|---|---|---|---|---|\n'
c = 0
for doc in presenze:
    d = doc.to_dict()
    out += f"| {d.get('data','-')} | {d.get('autistaNome','-')} | {d.get('targa','-')} | {d.get('viaggio','-')} | {d.get('cliente','-')} |\n"
    c += 1

out = f"## Totale Presenze Trovate: {c}\n\n" + out

with open('C:\\Users\\Diego\\.gemini\\antigravity\\brain\\781e2882-d49e-4511-a802-d8295dbfdf99\\presenze_luglio_produzione.md', 'w', encoding='utf-8') as f:
    f.write(out)
print(f"Scritte {c} presenze.")
