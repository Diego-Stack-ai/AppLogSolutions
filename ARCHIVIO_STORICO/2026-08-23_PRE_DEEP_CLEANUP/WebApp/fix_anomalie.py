import re

file_path = "frontend/gestione_anomalie.html"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. We need to define activeTenant at the top of the script
# Find the start of the <script type="module">
content = re.sub(
    r'(<script type="module">)(\s*)(import {)',
    r"\1\2const activeTenant = localStorage.getItem('activeTenant') || 'DNR';\n\2\3",
    content
)

# 2. Replace hardcoded DNR in onSnapshot paths with activeTenant
content = re.sub(
    r"collection\(db, 'clienti', 'DNR', 'nuovi codici consegna'\)",
    r"collection(db, 'clienti', activeTenant, 'nuovi codici consegna')",
    content
)

content = re.sub(
    r"collection\(db, 'clienti', 'DNR', 'nuovi articoli rilevati'\)",
    r"collection(db, 'clienti', activeTenant, 'nuovi articoli rilevati')",
    content
)

content = re.sub(
    r"collection\(db, 'clienti', 'DNR', 'nuovi orari mancanti'\)",
    r"collection(db, 'clienti', activeTenant, 'nuovi orari mancanti')",
    content
)

# 3. Fix salvaNuovoCliente parameter default
content = re.sub(
    r"window\.salvaNuovoCliente = async \(id, tenant = 'DNR'\) => \{",
    r"window.salvaNuovoCliente = async (id, tenant = activeTenant) => {",
    content
)

# 4. Fix deleteDoc for articoli
content = re.sub(
    r"doc\(db, 'clienti', 'DNR', 'codici articoli', newCode\)",
    r"doc(db, 'clienti', activeTenant, 'codici articoli', newCode)",
    content
)
content = re.sub(
    r"doc\(db, 'clienti', 'DNR', 'nuovi articoli rilevati', originalId\)",
    r"doc(db, 'clienti', activeTenant, 'nuovi articoli rilevati', originalId)",
    content
)

# 5. Fix doc(...) for raccolta clienti updates in orari
content = re.sub(
    r"collection\(db, 'clienti', 'DNR', 'raccolta clienti'\)",
    r"collection(db, 'clienti', activeTenant, 'raccolta clienti')",
    content
)
content = re.sub(
    r"doc\(db, 'clienti', 'DNR', 'raccolta clienti', docIdToUpdate\)",
    r"doc(db, 'clienti', activeTenant, 'raccolta clienti', docIdToUpdate)",
    content
)
content = re.sub(
    r"doc\(db, 'clienti', 'DNR', 'nuovi orari mancanti', idFromPdf\)",
    r"doc(db, 'clienti', activeTenant, 'nuovi orari mancanti', idFromPdf)",
    content
)

# 6. Fix eliminaAnomalia default
content = re.sub(
    r"window\.eliminaAnomalia = async \(collectionName, id, tenant = 'DNR'\) => \{",
    r"window.eliminaAnomalia = async (collectionName, id, tenant = activeTenant) => {",
    content
)

# 7. In the 'orari' fallback logic, ensure we don't save to DNR
content = re.sub(
    r"tipologia_grado: \(window\.defaultAnomalyData && window\.defaultAnomalyData\[id\]\) \? window\.defaultAnomalyData\[id\]\.tipo : 'DNR',",
    r"tipologia_grado: (window.defaultAnomalyData && window.defaultAnomalyData[id]) ? window.defaultAnomalyData[id].tipo : activeTenant,",
    content
)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
