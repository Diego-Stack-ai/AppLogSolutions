import sys

with open('frontend/elaborazione.html', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = "document.getElementById('btn-elimina-giornata-data').addEventListener('click', async () => {"
if start_marker not in content:
    sys.exit(1)
    
start_idx = content.find(start_marker)
end_marker = "} catch (err) {"
end_idx = content.find(end_marker, start_idx)

# Find the end of the catch block
end_idx = content.find("}", end_idx) + 1

# Actually there are closing brackets for the event listener. 
end_marker_2 = "});\n        \n        const savedDate = localStorage.getItem('master_date');"
end_idx = content.find(end_marker_2, start_idx) + 4 # up to });\n

new_func = """document.getElementById('btn-elimina-giornata-data').addEventListener('click', async () => {
            const dateInput = document.getElementById('master-date-selector').value;
            if (!dateInput) return Swal.fire('Attenzione', 'Seleziona una data nel calendario in alto.', 'warning');
            const formattedDate = dateInput.split('-').reverse().join('-');
            
            // Re-route to the unified Tabula Rasa function
            window.cancellaGiornataTotale(formattedDate);
        });
"""

new_content = content[:start_idx] + new_func + content[end_idx:]

with open('frontend/elaborazione.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Listener 2 Replace success")
