import re
import os

FRONTEND = r"G:\Il mio Drive\App\AppLogSolutionsWeb\frontend"

TARGET_PAGES = [
    "gestione_articoli.html",
    "gestione_orari.html",
    "gestione_rientri.html",
    "gestione_nuovi_clienti.html",
    "gestione_anomalie.html",
    "gestione.html",
    "centrale_resi.html",
    "gestione_mezzi.html",
    "presenze.html",
    "mappa_zone.html",
    "mappa_google.html",
    "mappa_riepilogativa.html",
    "link_viaggi.html",
    "impostazioni.html",
    "fatturazione.html",
    "elaborazione.html"
]

def fix_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(filepath, 'r', encoding='cp1252') as f:
            content = f.read()

    original = content

    # Rimuovi la riga con getApps()/initializeApp
    pattern_app = r'[ \t]*(?:const|let|var) app = getApps\(\)\.length .*? getApps\(\)\[0\];[ \t]*\r?\n?'
    content = re.sub(pattern_app, '', content)
    
    pattern_app2 = r'[ \t]*(?:const|let|var) app = getApps\(\)\.length .*? initializeApp\(firebaseConfig\);[ \t]*\r?\n?'
    content = re.sub(pattern_app2, '', content)
    
    # Rimuovi eventuali import residui di getApps/initializeApp
    pattern_app_import_only = r'[ \t]*import \{ getApps, initializeApp \} from "https://www\.gstatic\.com/firebasejs/[^"]+/firebase-app\.js";[ \t]*\r?\n'
    content = re.sub(pattern_app_import_only, '', content)

    if content != original:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception:
            with open(filepath, 'w', encoding='cp1252') as f:
                f.write(content)
        print(f"  [OK] {os.path.basename(filepath)} - pulito")
        return True
    return False

def main():
    fixed = 0
    for page in TARGET_PAGES:
        filepath = os.path.join(FRONTEND, page)
        if os.path.exists(filepath):
            if fix_file(filepath):
                fixed += 1
    print(f"Totale file puliti: {fixed}")

if __name__ == "__main__":
    main()
