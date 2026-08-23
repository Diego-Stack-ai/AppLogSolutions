lines = open('scratch\dati_luglio.txt', 'r', encoding='utf-8').read().splitlines()
presenze_lines = [l for l in lines if 'Viaggio' in l]
viaggi_lines = [l for l in lines if 'ClienteFatt' in l]

out = '# Riepilogo Dati Luglio 2026\n\n'
out += '## Registro Presenze (' + str(len(presenze_lines)) + ')\n'
out += '| Data | Autista | Targa | Viaggio | Cliente |\n'
out += '|---|---|---|---|---|\n'
for l in presenze_lines:
    parts = dict(x.split(': ', 1) for x in l.split(', '))
    out += f"| {parts.get('Data','-')} | {parts.get('Autista','-')} | {parts.get('Targa','-')} | {parts.get('Viaggio','-')} | {parts.get('Cliente','-')} |\n"

out += '\n## Viaggi DDT (' + str(len(viaggi_lines)) + ')\n'
out += '| Data | ClienteFatt | Autista | Colli | Mezzo |\n'
out += '|---|---|---|---|---|\n'
for l in viaggi_lines:
    parts = dict(x.split(': ', 1) for x in l.split(', '))
    out += f"| {parts.get('Data','-')} | {parts.get('ClienteFatt','-')} | {parts.get('Autista','-')} | {parts.get('Colli','-')} | {parts.get('Mezzo','-')} |\n"

with open('C:\\Users\\Diego\\.gemini\\antigravity\\brain\\781e2882-d49e-4511-a802-d8295dbfdf99\\dati_luglio_2026.md', 'w', encoding='utf-8') as f:
    f.write(out)
