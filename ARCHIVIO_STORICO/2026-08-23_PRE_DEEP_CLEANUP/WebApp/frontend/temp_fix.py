import re
import sys

def fix_presenze():
    with open('presenze.html', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Remove the duplicate import
    content = re.sub(
        r'window\.closeNavettaModal = function\(\) \{[\s\S]*?\}\s*;\s*import \{ setDoc, doc \} from "https://www\.gstatic\.com/firebasejs/10\.8\.0/firebase-firestore\.js";',
        '''window.closeNavettaModal = function() {
            document.getElementById('navettaModal').style.display = 'none';
        };''',
        content
    )
    
    with open('presenze.html', 'w', encoding='utf-8') as f:
        f.write(content)

def fix_script():
    with open('script.js', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Fix the corrupted emoji
    content = re.sub(
        r'<div style="flex:1;">.*Nuova versione disponibile!</div>',
        '<div style="flex:1;">?? Nuova versione disponibile!</div>',
        content
    )
    
    # Fix the other console.log corrupted emojis in script.js just in case
    content = re.sub(r'console\.log\("\[SW\] Nuova versione attiva.*?ricarico', 'console.log("[SW] Nuova versione attiva - ricarico', content)
    content = re.sub(r'console\.log\("\[SW\] SW in attesa trovato.*?invio', 'console.log("[SW] SW in attesa trovato - invio', content)
    
    with open('script.js', 'w', encoding='utf-8') as f:
        f.write(content)

fix_presenze()
fix_script()
print("Fixed files!")
