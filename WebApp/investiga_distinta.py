import firebase_admin
from firebase_admin import credentials, firestore

try:
    app = firebase_admin.get_app("prod_app_investigate")
except ValueError:
    cred = credentials.Certificate("prod_key.json")
    app = firebase_admin.initialize_app(cred, name="prod_app_investigate")

db = firestore.client(app=app)

doc = db.collection("clienti").document("DNR").collection("viaggi ddt").document("16-07-2026_CATTEL_HD320FN_Cosmin  Ancuta_QO7RQENRYXZ4POWPLrah").get()
if doc.exists:
    print(doc.to_dict().keys())
    data = doc.to_dict()
    print("cliente_zona:", data.get("cliente_zona"))
    print("proprietario:", data.get("proprietario"))
    print("autista:", data.get("autista"))
    print("mezzo:", data.get("mezzo"))
