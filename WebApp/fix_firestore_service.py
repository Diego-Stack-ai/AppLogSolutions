import re
import os

filepath = r"G:\Il mio Drive\App\AppLogSolutionsWeb\frontend\firestore-service.js"

try:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
except UnicodeDecodeError:
    with open(filepath, 'r', encoding='cp1252') as f:
        content = f.read()

original = content

# Rimuovi vecchie re-inizializzazioni
content = re.sub(r'const\s+app\s*=\s*[^;]+;\r?\n?', '', content)
content = re.sub(r'const\s+db\s*=\s*getFirestore\(app\);\r?\n?', '', content)

if content != original:
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Fixed: {os.path.basename(filepath)}")
else:
    print(f"No changes for {os.path.basename(filepath)}")
