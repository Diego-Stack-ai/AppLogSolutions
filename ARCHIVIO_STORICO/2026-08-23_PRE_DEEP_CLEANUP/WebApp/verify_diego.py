import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json
import os

try:
    cred = credentials.Certificate('functions/serviceAccountKey.json')
    firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Errore caricamento serviceAccountKey: {e}")
    try:
        firebase_admin.initialize_app()
    except ValueError:
        pass # already initialized

db = firestore.client()

def verify():
    print("Ricerca utenti con 'diego' o 'boschetto' nel nome...")
    docs = db.collection('dipendenti').stream()
    found = False
    for doc in docs:
        data = doc.to_dict()
        nome = str(data.get('nome', '')).lower()
        if 'diego' in nome or 'boschetto' in nome:
            found = True
            print("---")
            print(f"UID: {doc.id}")
            email = data.get('email', '')
            masked_email = email.split('@')[0][:3] + "***@" + email.split('@')[-1] if '@' in email else email
            print(f"Masked Email: {masked_email}")
            print(f"Nome nel DB: {data.get('nome')}")
            print(f"Ruolo attuale: {data.get('ruolo')}")
            print(f"Is Amministratore (verificato): {data.get('ruolo') == 'amministratore'}")
    
    if not found:
        print("Nessun utente 'Diego Boschetto' trovato.")

if __name__ == '__main__':
    verify()
