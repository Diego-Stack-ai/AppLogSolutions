import re
import os

SERVICES_DIR = r"G:\Il mio Drive\App\AppLogSolutionsWeb\frontend\services"

def fix_service_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(filepath, 'r', encoding='cp1252') as f:
            content = f.read()

    original = content

    # Rimuovi import app da firebase-app
    content = re.sub(r'import\s+\{[^}]*\}\s+from\s+"[^"]*firebase-app\.js";\r?\n?', '', content)
    # Rimuovi import config
    content = re.sub(r'import\s+\{\s*firebaseConfig\s*\}\s+from\s+"\.\./firebase-config\.js";\r?\n?', '', content)
    
    # Rimuovi definizioni vecchie
    content = re.sub(r'const\s+app\s*=\s*[^;]+;\r?\n?', '', content)
    content = re.sub(r'const\s+db\s*=\s*getFirestore\(app\);\r?\n?', '', content)

    # Rimuovi getFirestore dall'import di firestore se presente
    content = re.sub(r'getFirestore\s*,?\s*', '', content)
    
    # Aggiungi l'import di firebase-init
    # Verifica se c'è già
    if 'import { app, db }' not in content and 'import { db, app }' not in content:
        # Trova l'ultimo import e aggiungi
        imports = re.findall(r'^import .*;\r?\n?', content, flags=re.MULTILINE)
        if imports:
            last_import = imports[-1]
            content = content.replace(last_import, last_import + 'import { app, db } from "../core/firebase-init.js";\n')
        else:
            content = 'import { app, db } from "../core/firebase-init.js";\n' + content

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed: {os.path.basename(filepath)}")

def main():
    for f in os.listdir(SERVICES_DIR):
        if f.endswith('.js'):
            fix_service_file(os.path.join(SERVICES_DIR, f))

if __name__ == "__main__":
    main()
