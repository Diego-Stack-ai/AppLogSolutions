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

    # 1. Trova tutte le righe che usano `app` come argomento: getStorage(app), getFunctions(app), getAuth(app)
    # Se il file usa (app), assicuriamoci che l'import da firebase-init.js includa `app`.
    
    uses_app = re.search(r'\b(getStorage|getFunctions|getAuth|getFirestore)\s*\(\s*app', content)
    has_init_import = re.search(r'import\s+\{([^}]+)\}\s+from\s+["\']./core/firebase-init.js["\']', content)
    
    if uses_app:
        if has_init_import:
            import_statement = has_init_import.group(0)
            imported_vars = has_init_import.group(1).replace(' ', '').split(',')
            
            if 'app' not in imported_vars:
                imported_vars.append('app')
                new_import = f'import {{ {", ".join(imported_vars)} }} from "./core/firebase-init.js"'
                content = content.replace(import_statement, new_import)
        else:
            # Non ha proprio l'import da firebase-init, aggiungiamolo dopo il primo import
            import_line = '        import { db, app } from "./core/firebase-init.js";\n'
            first_import_match = re.search(r'(<script type="module">)(\s*\n)([ \t]*import )', content)
            if first_import_match:
                replacement = first_import_match.group(1) + first_import_match.group(2) + \
                             import_line + \
                             first_import_match.group(3)
                content = content.replace(first_import_match.group(0), replacement, 1)

    if content != original:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception:
            with open(filepath, 'w', encoding='cp1252') as f:
                f.write(content)
        print(f"  [OK] {os.path.basename(filepath)} - import app aggiunto")
        return True
    return False

def main():
    fixed = 0
    for page in TARGET_PAGES:
        filepath = os.path.join(FRONTEND, page)
        if os.path.exists(filepath):
            if fix_file(filepath):
                fixed += 1
    print(f"Totale file corretti per 'app': {fixed}")

if __name__ == "__main__":
    main()
