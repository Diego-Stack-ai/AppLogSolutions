import sys

with open('frontend/elaborazione.html', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = "document.querySelectorAll('.btn-elimina').forEach(btn => {"
if start_marker not in content:
    sys.exit(1)
    
start_idx = content.find(start_marker)
end_marker = "const savedDate = localStorage.getItem('master_date');"
end_idx = content.find(end_marker, start_idx)

new_func = """document.querySelectorAll('.btn-elimina').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const tr = e.target.closest('tr') || e.target.closest('.card');
                const rawDate = tr.dataset.date || btn.dataset.date;
                if (!rawDate) return;
                
                const parts = rawDate.split('/');
                let formattedDate = rawDate;
                if (parts.length === 3) {
                    formattedDate = \-\-\;
                }
                
                // Call the unified function for Tabula Rasa
                window.cancellaGiornataTotale(formattedDate);
            });
        });
        
        """

new_content = content[:start_idx] + new_func + content[end_idx:]

with open('frontend/elaborazione.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Listener Replace success")
