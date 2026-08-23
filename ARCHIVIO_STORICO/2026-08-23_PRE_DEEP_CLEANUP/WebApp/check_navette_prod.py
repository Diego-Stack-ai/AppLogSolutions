import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('prod_key.json')
if not firebase_admin._apps:
    app = firebase_admin.initialize_app(cred, name='prod')
else:
    app = firebase_admin.get_app('prod')
db = firestore.client(app=app)

presenze = db.collection('presenze').where('mese', '==', '2026-07').stream()

out = '# Analisi Navette e Attivita Aggiuntive in Presenze (Luglio 2026 - PROD)\n\n'
out += '| Data | Autista | Viaggio Principale | Cliente | Navette Extra (Attivita Aggiuntive) |\n'
out += '|---|---|---|---|---|\n'
c = 0
for doc in presenze:
    d = doc.to_dict()
    attivita = d.get('attivitaAggiuntive', [])
    if attivita or 'navetta' in str(d.get('cliente','')).lower() or 'navetta' in str(d.get('viaggio','')).lower():
        att_str = ", ".join([f"{a.get('nome','')} (Qta: {a.get('quantita','')})" for a in attivita]) if attivita else "Nessuna extra"
        out += f"| {d.get('data','-')} | {d.get('autistaNome','-')} | {d.get('viaggio','-')} | {d.get('cliente','-')} | {att_str} |\n"
        c += 1

out = f"## Trovati {c} record con Navette (principali o secondarie)\n\n" + out

with open('C:\\Users\\Diego\\.gemini\\antigravity\\brain\\781e2882-d49e-4511-a802-d8295dbfdf99\\navette_luglio_produzione.md', 'w', encoding='utf-8') as f:
    f.write(out)
print(f"Trovate {c} navette.")
