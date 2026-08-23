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

def clean_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(filepath, 'r', encoding='cp1252') as f:
            content = f.read()

    original = content

    # Rimuovi *qualsiasi* dichiarazione di `const app = ...`
    pattern_app = r'[ \t]*const app = [^\n]+;\r?\n?'
    content = re.sub(pattern_app, '', content)

    # Rimuovi *qualsiasi* dichiarazione di `const db = getFirestore(app);`
    pattern_db = r'[ \t]*const db = getFirestore\(app\);\r?\n?'
    content = re.sub(pattern_db, '', content)
    
    # Rimuovi doppi import errati che abbiamo inavvertitamente introdotto in fatturazione
    # Ripulisco se ho fatto danni con il tool multi_replace prima.
    
    if content != original:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception:
            with open(filepath, 'w', encoding='cp1252') as f:
                f.write(content)
        print(f"  [CLEANED] {os.path.basename(filepath)}")
        return True
    return False

def main():
    fixed = 0
    for page in TARGET_PAGES:
        filepath = os.path.join(FRONTEND, page)
        if os.path.exists(filepath):
            if clean_file(filepath):
                fixed += 1
    print(f"Totale file puliti: {fixed}")

if __name__ == "__main__":
    main()
