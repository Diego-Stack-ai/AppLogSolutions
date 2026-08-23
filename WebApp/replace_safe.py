import sys

with open('functions/main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open('new_elimina.py', 'r', encoding='utf-8') as f:
    new_func = f.read()

start_idx = -1
for i, line in enumerate(lines):
    if line.startswith('def elimina_giornata_logistica(req:'):
        start_idx = i - 2
        break

end_idx = -1
for i in range(start_idx, len(lines)):
    if 'CLOUD FUNCTION ALIAS PER CALCOLA PERCORSI' in lines[i]:
        end_idx = i
        break

if start_idx != -1 and end_idx != -1:
    new_content = ''.join(lines[:start_idx]) + new_func + '\n\n' + ''.join(lines[end_idx:])
    with open('functions/main.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Success')
else:
    print('Failed')
