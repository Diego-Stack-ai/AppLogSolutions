import os
import re

root = 'frontend'

with open(os.path.join(root, 'script.js'), 'r', encoding='utf-8') as f:
    c_script = f.read()

match = re.search(r'APP_VERSION\s*=\s*"([\d\.]+)"', c_script)
if match:
    v_old_str = match.group(1)
    
    if v_old_str.startswith('5.'):
        # Force jump to 6.000
        v_new = '6.000'
    else:
        # Handle 6.xxx logic
        try:
            major, minor = v_old_str.split('.')
            minor_int = int(minor) + 1
            if minor_int >= 1000:
                major = str(int(major) + 1)
                minor_int = 0
            v_new = f"{major}.{minor_int:03d}"
        except:
            v_new = '6.000'
else:
    v_new = '6.000'

print(f"Nuova versione calcolata: {v_new}")

with open(os.path.join(root, 'sw.js'), 'r', encoding='utf-8') as f:
    c_sw = f.read()
c_sw = re.sub(r'log-solution-v[\d\.]+', f'log-solution-v{v_new}', c_sw)
with open(os.path.join(root, 'sw.js'), 'w', encoding='utf-8') as f:
    f.write(c_sw)

c_script = re.sub(r'APP_VERSION\s*=\s*"[\d\.]+"', f'APP_VERSION = "{v_new}"', c_script)
with open(os.path.join(root, 'script.js'), 'w', encoding='utf-8') as f:
    f.write(c_script)

htmls = [f for f in os.listdir(root) if f.endswith('.html')]
for h in htmls:
    p = os.path.join(root, h)
    try:
        with open(p, 'r', encoding='utf-8') as f:
            c_h = f.read()
        enc = 'utf-8'
    except UnicodeDecodeError:
        with open(p, 'r', encoding='cp1252') as f:
            c_h = f.read()
        enc = 'cp1252'
    c_h = re.sub(r'\?v=[\d\.]+', f'?v={v_new}', c_h)
    with open(p, 'w', encoding=enc) as f:
        f.write(c_h)

js_files = [f for f in os.listdir(root) if f.endswith('.js') and f not in ['script.js', 'sw.js']]
for js_file in js_files:
    p = os.path.join(root, js_file)
    try:
        with open(p, 'r', encoding='utf-8') as f:
            c_js = f.read()
        enc = 'utf-8'
    except UnicodeDecodeError:
        with open(p, 'r', encoding='cp1252') as f:
            c_js = f.read()
        enc = 'cp1252'
    c_js = re.sub(r'\?v=[\d\.]+', f'?v={v_new}', c_js)
    with open(p, 'w', encoding=enc) as f:
        f.write(c_js)

print(f"Versione bumpata a {v_new}")
