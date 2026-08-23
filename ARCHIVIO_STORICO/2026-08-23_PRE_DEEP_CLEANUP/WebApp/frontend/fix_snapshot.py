import os
import re

directory = "G:/Il mio Drive/App/AppLogSolutionsWeb/frontend"
extensions = (".html", ".js")

# Regex to match onSnapshot(...) without includeMetadataChanges
# It looks for: onSnapshot( [arg1] , (snapshot) => {
# We need to be careful with things like onSnapshot(collection(...), (snapshot) => {
# A safe regex:
# onSnapshot\(\s*(.*?)\s*,\s*(?:async\s*)?\(\s*(?:snapshot|snap|docSnap)\s*\)\s*=>
# Wait, some have the error callback.
# Let's use a simpler string replace where possible, or regex:
# onSnapshot( <expr> , (snap) =>

pattern = re.compile(r'onSnapshot\(\s*(.*?)\s*,\s*(async\s*)?\(\s*(snapshot|snap|docSnap)\s*\)\s*=>')

count = 0
for root, _, files in os.walk(directory):
    for file in files:
        if file.endswith(extensions):
            path = os.path.join(root, file)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(path, 'r', encoding='cp1252') as f:
                    content = f.read()
                    
            if "onSnapshot" in content and "includeMetadataChanges" not in content:
                # Replace
                new_content = pattern.sub(r'onSnapshot(\1, { includeMetadataChanges: true }, \2(\3) =>', content)
                
                # Also handle where they don't use arrow functions?
                # onSnapshot(docRef, function(doc) {
                # Just catch the arrow functions we saw in grep.
                
                if new_content != content:
                    try:
                        with open(path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        print(f"Updated: {path}")
                        count += 1
                    except Exception as e:
                        print(f"Error writing {path}: {e}")

print(f"Total files updated: {count}")
