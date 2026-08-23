import firebase_admin
from firebase_admin import credentials, firestore
import json
from collections import defaultdict

cred = credentials.Certificate('prod_key.json')
if not firebase_admin._apps:
    app = firebase_admin.initialize_app(cred, name='prod')
else:
    app = firebase_admin.get_app('prod')
db = firestore.client(app=app)

mese = "2026-07"
presenze = db.collection('presenze').where('mese', '==', mese).stream()

report_data = defaultdict(list)
clienti_merce = set()

for doc in presenze:
    d = doc.to_dict()
    attivita = d.get('attivitaAggiuntive', [])
    data = d.get('data', '-')
    autista = d.get('autistaNome', '-')
    targa = d.get('targa', '-')
    
    if attivita:
        for att in attivita:
            if att.get('tipo') == 'navettaMissione':
                tappe = att.get('tappe', [])
                for tappa in tappe:
                    luogo = str(tappa.get('carico', '')).strip().upper()
                    cliente = str(tappa.get('cliente_merce', '')).strip().upper()
                    # Se non c'è cliente_merce, usiamo il luogo di carico come raggruppamento (navetta standard)
                    chiave_cliente = cliente if cliente else luogo
                    
                    if chiave_cliente:
                        clienti_merce.add(chiave_cliente)
                        report_data[chiave_cliente].append({
                            'data': data,
                            'autista': autista,
                            'targa': targa,
                            'luogo_carico': luogo,
                            'cliente_merce': cliente,
                            'scarico': tappa.get('scarico', ''),
                            'mezzo': tappa.get('mezzo', ''),
                            'motrice': tappa.get('motrice', ''),
                            'rimorchio': tappa.get('rimorchio', '')
                        })

# Generazione Report Markdown
md_content = f"# Report Navette per Cliente - {mese}\n\n"
md_content += f"> Dati estratti dal Registro Presenze di Produzione (Mese: {mese})\n\n"

for cliente in sorted(list(clienti_merce)):
    navette_cliente = report_data[cliente]
    md_content += f"## Cliente: {cliente}\n"
    md_content += f"**Totale Navette Effettuate:** {len(navette_cliente)}\n\n"
    md_content += "| Data | Autista | Targa/Mezzo | Luogo Carico | Scarico |\n"
    md_content += "|---|---|---|---|---|\n"
    
    # Ordiniamo per data
    navette_cliente = sorted(navette_cliente, key=lambda x: x['data'])
    
    for n in navette_cliente:
        mezzo_effettivo = n['targa']
        if n['mezzo']: mezzo_effettivo += f" ({n['mezzo']})"
        elif n['motrice'] or n['rimorchio']: mezzo_effettivo += f" (M:{n['motrice']} R:{n['rimorchio']})"
        
        md_content += f"| {n['data']} | {n['autista']} | {mezzo_effettivo} | {n['luogo_carico']} | {n['scarico']} |\n"
    
    md_content += "\n---\n\n"

with open(r'C:\Users\39349\.gemini\antigravity\brain\0d96d8cf-9921-42ad-bb82-412b4f04601a\report_navette_clienti.md', 'w', encoding='utf-8') as f:
    f.write(md_content)

print("Report generato con successo.")
