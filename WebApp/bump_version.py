import os
import re
import sys

FRONTEND_DIR = 'frontend'

if len(sys.argv) < 2:
    print("Usage: python bump_version.py <new_version>")
    sys.exit(1)

new_version = sys.argv[1]

# 1. Update sw.js
sw_path = os.path.join(FRONTEND_DIR, 'sw.js')
if os.path.exists(sw_path):
    with open(sw_path, 'r', encoding='utf-8') as f:
        sw_content = f.read()
    sw_content = re.sub(r"const CACHE_NAME = 'log-solution-v.*?';", f"const CACHE_NAME = 'log-solution-v{new_version}';", sw_content)
    with open(sw_path, 'w', encoding='utf-8') as f:
        f.write(sw_content)
    print("Updated sw.js")

# 2. Update script.js
script_path = os.path.join(FRONTEND_DIR, 'script.js')
if os.path.exists(script_path):
    with open(script_path, 'r', encoding='utf-8') as f:
        script_content = f.read()
    script_content = re.sub(r'const APP_VERSION = ".*?";', f'const APP_VERSION = "{new_version}";', script_content)
    with open(script_path, 'w', encoding='utf-8') as f:
        f.write(script_content)
    print("Updated script.js")

# 3. Update HTML, JS files
for root, dirs, files in os.walk(FRONTEND_DIR):
    for file in files:
        if file.endswith('.html') or file.endswith('.js'):
            if file in ['sw.js', 'script.js']: continue
            file_path = os.path.join(root, file)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            new_content = re.sub(r'\?v=\d+\.\d+', f'?v={new_version}', content)
            if new_content != content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"Updated {file}")

print(f"Version bumped to {new_version} successfully.")
