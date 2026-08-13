import os
import json
import firebase_admin
from firebase_admin import firestore
from firebase_functions import storage_fn, options

# Assicuriamoci che Firebase sia inizializzato (spesso già fatto nel main.py)
if not firebase_admin._apps:
    firebase_admin.initialize_app()

db = firestore.client()

# Configurazione API Key di Gemini (ideale metterla nei Firebase Secrets in produzione)
def get_genai_model(system_instruction=None, tools=None):
    import google.generativeai as genai
    GENAI_API_KEY = os.environ.get("GEMINI_API_KEY")
    if not GENAI_API_KEY:
        raise ValueError("AI_NOT_CONFIGURED")
    genai.configure(api_key=GENAI_API_KEY)
    
    generation_config = {
      "temperature": 0.0,
      "top_p": 0.95,
      "top_k": 64,
    }
    
    model = genai.GenerativeModel(
      model_name="gemini-1.5-pro-latest",
      generation_config=generation_config,
      system_instruction=system_instruction,
      tools=tools
    )
    return model

SYSTEM_PROMPT = """
Sei un assistente esperto nell'estrazione di dati logistici e contabili.
Ti verrà fornito un documento (PDF o Excel). 
Il tuo compito è leggere le tabelle dei viaggi e restituire i dati ESATTAMENTE in questo formato JSON.
Se un dato non è presente o non è calcolabile, inserisci null. Non aggiungere NESSUN testo extra oltre al JSON.

Formato Richiesto:
{
  "viaggi": [
    {
      "data": "YYYY-MM-DD",
      "targa_o_mezzo": "...",
      "autista": "Nome Cognome",
      "cliente": "Nome Cliente",
      "km": 123.5,
      "costo_o_fatturato": 150.50,
      "volume": 10.5
    }
  ]
}
"""

from firebase_functions import https_fn

def agent_extractor(req) -> any:
    """
    Agente 1: Analizza il documento caricato tramite Gemini e salva i dati.
    """
    from firebase_admin import storage as admin_storage
    import uuid
    import re
    
    file_path = req.data.get("filePath", "")
    if not file_path or not isinstance(file_path, str):
        return {"status": "error", "code": "AI_INVALID_INPUT", "message": "Nessun filePath fornito o formato non valido."}
        
    if not file_path.startswith("imports/documenti_ai/"):
        return {"status": "error", "code": "AI_FORBIDDEN", "message": "Accesso al path Storage negato."}

    print(f"[AI Extractor] Avvio elaborazione intelligente del file: {file_path}")

    try:
        # 1. Scarica il file dal bucket al filesystem temporaneo (/tmp)
        bucket = admin_storage.bucket()
        blob = bucket.blob(file_path)
        if not blob.exists():
            return {"status": "error", "message": "File non trovato nello storage."}
            
        _, ext = os.path.splitext(file_path)
        tmp_path = f"/tmp/{uuid.uuid4()}{ext}"
        blob.download_to_filename(tmp_path)
        
        # 2. Inizializza Gemini e carica il file
        import google.generativeai as genai
        model = get_genai_model(system_instruction=SYSTEM_PROMPT)
        
        print("[AI Extractor] Invio documento a Gemini API...")
        gemini_file = genai.upload_file(tmp_path)
        
        # 3. Richiedi l'estrazione
        response = model.generate_content([
            gemini_file, 
            "Estrai tutti i dati rilevanti (viaggi, presenze o costi) da questo documento e restituiscili rigorosamente nel formato JSON indicato."
        ])
        
        # 4. Pulizia
        genai.delete_file(gemini_file.name)
        os.remove(tmp_path)
        
        # 5. Parsing del risultato
        risultato_testo = response.text
        risultato_pulito = re.sub(r'```json|```', '', risultato_testo).strip()
        
        try:
            dati_json = json.loads(risultato_pulito)
        except json.JSONDecodeError:
            dati_json = {"raw_text": risultato_pulito, "parsing_error": True}
            print("[AI Extractor] WARN: La risposta non era in JSON valido.")
            
        # 6. Salvataggio in Firestore
        doc_ref = db.collection("dati_grezzi_estratti").document()
        doc_ref.set({
            "file_sorgente": file_path,
            "stato": "completato",
            "creato_il": firestore.SERVER_TIMESTAMP,
            "dati_estratti": dati_json
        })
        
        return {
            "status": "success",
            "message": f"Documento analizzato! Sono state estratte {len(dati_json.get('viaggi', []))} righe di dati strutturati."
        }
    except Exception as e:
        print(f"[AI Extractor] ERRORE: {str(e)}")
        return {"status": "error", "message": str(e)}

def agent_chat_assistant(req) -> any:
    message = req.data.get("message", "")
    mese = req.data.get("mese", "")
    
    if not message or not isinstance(message, str):
        return {"status": "error", "code": "AI_INVALID_INPUT", "message": "Messaggio non valido."}
    
    if len(message) > 1000:
        return {"status": "error", "code": "AI_INVALID_INPUT", "message": "Messaggio troppo lungo (max 1000 caratteri)."}
        
    if mese and not re.match(r"^\d{4}-\d{2}$", str(mese)):
        return {"status": "error", "code": "AI_INVALID_INPUT", "message": "Formato mese non valido (atteso YYYY-MM)."}

    # Definizione Tools per Gemini
    def get_costi_carburante(mese: str, targa: str = "") -> dict:
        """
        Recupera i costi del carburante per un dato mese.
        Args:
            mese: Mese nel formato YYYY-MM (es. 2026-07)
            targa: (Opzionale) La targa del mezzo per filtrare i costi.
        """
        try:
            doc = db.collection("costi_carburante").document(mese).get()
            if not doc.exists:
                return {"error": f"Nessun dato carburante per il mese {mese}."}
            targhe = doc.to_dict().get("targhe", {})
            if targa:
                targa = targa.upper().strip()
                return {targa: targhe.get(targa, 0)}
            return targhe
        except Exception as e:
            return {"error": str(e)}
            
    def get_presenze_viaggi(mese: str, autista: str = "") -> list:
        """
        Recupera i viaggi e le presenze per un dato mese, filtrabili per autista.
        Args:
            mese: Mese nel formato YYYY-MM
            autista: (Opzionale) Nome dell'autista
        """
        try:
            query = db.collection("presenze").where("mese", "==", mese)
            docs = query.stream()
            risultati = []
            for d in docs:
                data = d.to_dict()
                if autista:
                    aut_db = (data.get("dipendente") or data.get("autistaId") or "").upper()
                    if autista.upper() not in aut_db:
                        continue
                # Estraiamo i campi rilevanti per non saturare i token
                risultati.append({
                    "data": data.get("data", ""),
                    "cliente": data.get("cliente", ""),
                    "targa": data.get("targa", ""),
                    "autista": aut_db,
                    "margine": data.get("margine", 0)
                })
            return risultati
        except Exception as e:
            return [{"error": str(e)}]

    def get_viaggi_reali(mese: str, targa: str = "", autista: str = "") -> list:
        """
        Recupera i viaggi reali effettuati (creati con le mappe) per incrociare ricavi e km.
        Args:
            mese: Mese nel formato YYYY-MM
            targa: (Opzionale) Filtra per targa
            autista: (Opzionale) Filtra per nome autista
        """
        try:
            query = db.collection("clienti").document("DNR").collection("viaggi ddt").where("status", "==", "completato").limit(50)
            docs = query.stream()
            risultati = []
            for d in docs:
                data = d.to_dict()
                data_viaggio = data.get("data", "")
                if mese not in data_viaggio:
                    mese_inverso = mese.split("-")[1] + "-" + mese.split("-")[0]
                    if mese_inverso not in data_viaggio:
                        continue
                if targa and targa.upper() not in (data.get("targa") or "").upper():
                    continue
                if autista and autista.upper() not in (data.get("autista") or "").upper():
                    continue
                risultati.append({
                    "data": data_viaggio,
                    "targa": data.get("targa", ""),
                    "autista": data.get("autista", ""),
                    "km_totali": data.get("km_totali_stimati", 0),
                    "costo_stimato": data.get("costo_stimato", 0),
                    "ricavo_stimato": data.get("ricavo_stimato", 0)
                })
            return risultati
        except Exception as e:
            return [{"error": str(e)}]

    # Inizializzazione Gemini 1.5 Pro
    model_chat = get_genai_model(
        tools=[get_costi_carburante, get_presenze_viaggi, get_viaggi_reali],
        system_instruction="Sei l'Assistente AI del Centro Costi. Aiuti l'utente a capire i costi dei camion, gli stipendi e i ricavi. Usa sempre i tool per cercare i dati nel database, partendo dal mese di " + str(mese) + " se non specificato altrimenti. Puoi incrociare i costi con i viaggi reali delle mappe. Restituisci la risposta in modo colloquiale, chiaro e breve, adatta ad essere letta da una sintesi vocale."
    )
    
    try:
        chat = model_chat.start_chat()
        response = chat.send_message(message)
        
        return {
            "status": "success",
            "reply": response.text
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
