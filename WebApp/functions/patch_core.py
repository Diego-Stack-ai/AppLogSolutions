import sys
import re

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Trovo l'inizio e la fine di core_genera_report_giornaliero
def find_block(text, start_str):
    idx = text.find(start_str)
    if idx == -1: return None, -1, -1
    
    lines = text[idx:].split('\n')
    indent = len(lines[0]) - len(lines[0].lstrip())
    
    end_idx = idx
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            end_idx += len(line) + 1
            continue
            
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= indent:
            break
        end_idx += len(line) + 1
        
    return text[idx:end_idx], idx, end_idx

old_def_start = "def core_genera_report_giornaliero(uid, data_consegna, azioni=None):"
old_block, idx, end_idx = find_block(content, old_def_start)

if not old_block:
    print("Non ho trovato core_genera_report_giornaliero")
    sys.exit(1)

# Scriviamo il nuovo script di sostituzione che sovrascriverà core_genera_report_giornaliero
# Ma prima devo vedere come è fatto all'interno.
print(old_block[:500])
