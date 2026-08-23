#!/usr/bin/env python3
"""
fix_db_import.py
Sostituisce nelle pagine HTML il pattern di init locale di Firestore
con l'import di db da ./core/firebase-init.js che ha già la persistence abilitata.
"""
import re
import os

FRONTEND = r"G:\Il mio Drive\App\AppLogSolutionsWeb\frontend"

# Pagine da correggere (le principali, no mappe_autisti che sono generate)
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
]

def fix_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(filepath, 'r', encoding='cp1252') as f:
            content = f.read()

    original = content

    # Pattern 1: blocco completo con getApps/initializeApp + getFirestore
    # Cerca e sostituisce il blocco di 2-3 righe che:
    # 1. importa da firebase-app.js
    # 2. prende/inizializza l'app
    # 3. crea db con getFirestore(app)
    
    # Prima aggiungiamo l'import di db da firebase-init.js se non c'è già
    if "from \"./core/firebase-init.js\"" in content or "from './core/firebase-init.js'" in content:
        print(f"  [SKIP] {os.path.basename(filepath)} - già importa da firebase-init.js")
        return False

    # Trova il blocco <script type="module"> e aggiungi import db
    # Pattern: rimuove la riga const db = getFirestore(app) e aggiunge import {db} da firebase-init

    # Step 1: rimuovi/sostituisci "const db = getFirestore(app);"
    # (può avere spazi diversi prima)
    pattern_db = r'[ \t]*const db = getFirestore\(app\);[ \t]*\r?\n'
    
    if not re.search(pattern_db, content):
        print(f"  [SKIP] {os.path.basename(filepath)} - pattern db non trovato")
        return False

    # Rimuovi la riga const db = getFirestore(app);
    content = re.sub(pattern_db, '', content)

    # Step 2: rimuovi la riga con getApps()/initializeApp se presente
    # (solo se usata solo per inizializzare app per il db)
    pattern_app = r'[ \t]*(?:const|let|var) app = getApps\(\)\.length \? getApps\(\)\[0\] : initializeApp\(firebaseConfig\);[ \t]*\r?\n'
    content = re.sub(pattern_app, '', content)

    # Step 3: rimuovi import di getApps e initializeApp da firebase-app.js se non servono più
    # (solo se la riga import contiene solo getApps e initializeApp)
    pattern_app_import_only = r'[ \t]*import \{ getApps, initializeApp \} from "https://www\.gstatic\.com/firebasejs/[^"]+/firebase-app\.js";[ \t]*\r?\n'
    content = re.sub(pattern_app_import_only, '', content)

    # Step 4: Aggiungi import { db } from "./core/firebase-init.js" 
    # Dopo il primo import statement nel blocco <script type="module">
    # Cerca il primo import nel modulo
    first_import_match = re.search(r'<script type="module">\s*\n([ \t]*import [^\n]+\n)', content)
    if first_import_match:
        first_import = first_import_match.group(1)
        # Aggiungi l'import di db prima del primo import
        import_line = '        import { db } from "./core/firebase-init.js";\n'
        content = content.replace(first_import, import_line + first_import, 1)
    else:
        # Prova con script type=module senza spazi
        first_import_match = re.search(r'(<script type="module">)(\s*\n)([ \t]*import )', content)
        if first_import_match:
            replacement = first_import_match.group(1) + first_import_match.group(2) + \
                         '        import { db } from "./core/firebase-init.js";\n' + \
                         first_import_match.group(3)
            content = content.replace(first_import_match.group(0), replacement, 1)

    if content != original:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception:
            with open(filepath, 'w', encoding='cp1252') as f:
                f.write(content)
        print(f"  [OK] {os.path.basename(filepath)} - corretto")
        return True
    else:
        print(f"  [NO CHANGE] {os.path.basename(filepath)}")
        return False

def main():
    fixed = 0
    for page in TARGET_PAGES:
        filepath = os.path.join(FRONTEND, page)
        if os.path.exists(filepath):
            print(f"Elaboro: {page}")
            if fix_file(filepath):
                fixed += 1
        else:
            print(f"  [NOT FOUND] {page}")
    print(f"\nTotale file corretti: {fixed}/{len(TARGET_PAGES)}")

if __name__ == "__main__":
    main()
