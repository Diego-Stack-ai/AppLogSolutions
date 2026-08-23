import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import sys
import argparse
from pathlib import Path
import json

def main():
    parser = argparse.ArgumentParser(description="Bootstrap system_status per amministratori.")
    parser.add_argument('--confirm', action='store_true', help="Esegue fisicamente la scrittura nel DB.")
    parser.add_argument('--credentials', type=str, help="Percorso opzionale al file JSON delle credenziali.")
    args = parser.parse_args()

    dry_run = not args.confirm

    if dry_run:
        print("MODALITA' DRY-RUN (aggiungi --confirm per scrivere sul database)\n")

    # 1. Costruzione percorsi assoluti
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent
    
    # 2 e 3. Precedenza credenziali
    cred_path = None
    if args.credentials:
        cred_path = Path(args.credentials).resolve()
    else:
        # Credenziale di sviluppo nota e verificata
        default_dev_key = project_root / 'dev_key.json'
        if default_dev_key.exists():
            cred_path = default_dev_key

    # Caricamento credenziali
    if cred_path and cred_path.exists():
        print(f"Caricamento credenziali da: {cred_path}")
        try:
            cred = credentials.Certificate(str(cred_path))
            firebase_admin.initialize_app(cred)
        except Exception as e:
            print(f"Errore caricamento credenziali Certificate: {e}")
            sys.exit(1)
    else:
        print("File di credenziali non trovato. Provo con Application Default Credentials...")
        try:
            firebase_admin.initialize_app()
        except ValueError:
            pass # already initialized
        except Exception as e:
            print(f"Errore caricamento ADC: {e}")
            sys.exit(1)

    # 4 e 6. Verifica Project ID reale
    try:
        # Usa il get_app() per leggere il project_id
        project_id = firebase_admin.get_app().project_id
        if not project_id and cred_path:
            # Fallback leggendo direttamente il json se get_app non lo espone in alcune versioni
            with open(cred_path, 'r') as f:
                cred_data = json.load(f)
                project_id = cred_data.get('project_id')
    except Exception as e:
        print(f"Impossibile determinare il project ID dall'app inizializzata: {e}")
        sys.exit(1)

    if project_id not in ['log-solutions-sviluppo', 'log-solution-60007']:
        print(f"ERRORE CRITICO: Il project_id rilevato e' '{project_id}'. Questo script PUO' ESSERE ESEGUITO SOLO SU 'log-solutions-sviluppo'.")
        sys.exit(1)

    # 5. Creazione client e stampa connessione
    try:
        db = firestore.client()
    except Exception as e:
        print(f"Errore inizializzazione client Firestore: {e}")
        sys.exit(1)

    print(f"\nConnesso al progetto verificato: {project_id}")

    print("\nRicerca amministratori attuali...")
    docs = db.collection('dipendenti').stream()
    
    admin_uids = []
    found_diego = False
    diego_is_admin = False

    print("\n--- Amministratori Rilevati ---")
    for doc in docs:
        data = doc.to_dict()
        uid = doc.id
        nome = str(data.get('nome', '')).strip()
        cognome = str(data.get('cognome', '')).strip()
        ruolo = str(data.get('ruolo', '')).lower()
        email = str(data.get('email', ''))

        nome_completo = f"{nome} {cognome}".lower()
        is_diego = 'diego' in nome_completo and 'boschetto' in nome_completo

        if is_diego:
            found_diego = True
            if ruolo == 'amministratore':
                diego_is_admin = True

        if ruolo == 'amministratore':
            # 8. UID parziale ed email oscurata
            masked_uid = uid[:3] + "..." + uid[-2:] if len(uid) > 5 else uid
            masked_email = email.split('@')[0][:3] + "***@" + email.split('@')[-1] if '@' in email else email
            print(f"- Nome: {nome} {cognome} | UID: {masked_uid} | Email: {masked_email}")
            admin_uids.append(uid)
            
    # 10. Controllo presenza amministratori
    if len(admin_uids) == 0:
        print("\nERRORE CRITICO: Nessun amministratore rilevato nel database. Operazione interrotta per prevenire lockout.")
        sys.exit(1)

    # 11. Controllo anomalia Diego Boschetto
    if not found_diego:
        print("\nERRORE CRITICO: L'account ufficiale Boschetto Diego NON e' stato rilevato nel database. Operazione interrotta.")
        sys.exit(1)
    if found_diego and not diego_is_admin:
        print("\nERRORE CRITICO: L'utente Boschetto Diego e' stato rilevato nel database ma il suo ruolo NON e' 'amministratore'. Anomalia grave, operazione interrotta.")
        sys.exit(1)

    print(f"\nTotale amministratori: {len(admin_uids)}")
    
    # 8. Mostra JSON previsto
    json_previsto = {
        'admins': admin_uids
    }
    
    json_mascherato = {
        'admins': [(uid[:3] + "..." + uid[-2:] if len(uid) > 5 else uid) for uid in admin_uids]
    }
    print(f"\nContenuto previsto per config/system_status:\n{json.dumps(json_mascherato, indent=2)}")

    if dry_run:
        print("\n[DRY-RUN] NESSUNA SCRITTURA ESEGUITA. Esegui il comando con --confirm per procedere.")
    else:
        # 9. Conferma interattiva esplicita
        print("\n" + "!"*60)
        print("ATTENZIONE: STAI PER SCRIVERE SUL DATABASE DI SVILUPPO")
        print("!"*60)
        user_input = input("Per procedere digita esplicitamente 'SCRIVI SU SVILUPPO': ")
        
        if user_input.strip() == "SCRIVI SU SVILUPPO":
            print("\nSalvataggio registro in config/system_status...")
            db.collection('config').document('system_status').set(json_previsto, merge=True)
            print("FATTO! Registro amministratori creato con successo.")
        else:
            print("\nConferma non valida. Operazione annullata.")
            sys.exit(1)

if __name__ == "__main__":
    main()
