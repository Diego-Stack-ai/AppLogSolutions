import re, os

FRONTEND = r"G:\Il mio Drive\App\AppLogSolutionsWeb\frontend"
filepath = os.path.join(FRONTEND, "gestione_articoli.html")

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

idx = content.find('<script type="module">')
if idx >= 0:
    block = content[idx:idx+600]
    print("BLOCCO TROVATO:")
    print(block)
print()
print("Ha firebase-init import?", "firebase-init" in content)
print("Ha const db = getFirestore(app):", "const db = getFirestore(app)" in content)
