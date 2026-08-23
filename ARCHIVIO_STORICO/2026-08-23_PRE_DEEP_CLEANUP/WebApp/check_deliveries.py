from google.cloud import firestore
import json

db = firestore.Client(project="log-solutions-cantiere")
doc = db.collection("clienti").document("DAC").collection("reports_logistici").document("01-08-2026").get()
if doc.exists:
    data = doc.to_dict()
    print("Deliveries count:", len(data.get("consegne", [])))
    for d in data.get("consegne", []):
        print(d.get("codice_consegna"), d.get("ragsoc"))
else:
    print("Doc not found")
