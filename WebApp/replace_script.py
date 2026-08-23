import sys

with open('functions/main.py', 'r', encoding='utf-8') as f:
    content = f.read()
    
with open('new_elimina.py', 'r', encoding='utf-8') as f:
    new_func = f.read()
    
start_marker = '@https_fn.on_call(region="europe-west1", memory=options.MemoryOption.MB_256, timeout_sec=120,\n    cors=options.CorsOptions(cors_origins="*", cors_methods=["get", "post"]))\ndef elimina_giornata_logistica'

if start_marker not in content:
    print("Start marker not found")
    sys.exit(1)
    
start_idx = content.find(start_marker)
end_marker = '# ─── CLOUD FUNCTION ALIAS PER CALCOLA PERCORSI ────────────────────────────────'
end_idx = content.find(end_marker, start_idx)

if end_idx == -1:
    print("End marker not found")
    sys.exit(1)

new_content = content[:start_idx] + new_func + "\n\n" + content[end_idx:]

with open('functions/main.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Replace success")
