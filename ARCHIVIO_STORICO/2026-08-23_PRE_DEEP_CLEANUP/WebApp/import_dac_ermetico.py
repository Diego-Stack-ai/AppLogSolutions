import firebase_admin
from firebase_admin import credentials, firestore

# 1. INIZIALIZZAZIONE ERMETICA SU SVILUPPO
print("Inizializzazione Firebase con dev_key.json (Ambiente di Sviluppo)...")
cred = credentials.Certificate('dev_key.json')
app = firebase_admin.initialize_app(cred, name='dev_dac_import')
db = firestore.client(app=app)

# 2. DATI DA IMPORTARE
punti_consegna = [
    { "cliente": "LORO DUE S.A.S. DI GIRARDI PAOLO&C.", "indirizzo": "Viale Aquileia 9", "cap": "33170", "città": "Pordenone", "provincia": "PN", "lat": 45.961958, "lng": 12.676260 },
    { "cliente": "SAN PEPPE SRL", "indirizzo": "Via Sclavons 67", "cap": "33084", "città": "Cordenons", "provincia": "PN", "lat": 45.980559, "lng": 12.697875 },
    { "cliente": "RUSALEN ANNA MARIA", "indirizzo": "Via Amerigo Vespucci 12", "cap": "33080", "città": "Porcia", "provincia": "PN", "lat": 45.948461, "lng": 12.608518 },
    { "cliente": "ZONA ROSSA DI MARIA POLITO", "indirizzo": "Via Tolmezzo 10", "cap": "33074", "città": "Fontanafredda", "provincia": "PN", "lat": 45.953372, "lng": 12.535818 },
    { "cliente": "DUE LUNE BAR DI PERROTTA MARIANO", "indirizzo": "Via Trieste 184", "cap": "33081", "città": "Aviano", "provincia": "PN", "lat": 46.097249, "lng": 12.595248 },
    { "cliente": "BUONISSIMO DI AVIANO SNC DI MUHAMMA", "indirizzo": "Via Mazzini 15", "cap": "33081", "città": "Aviano", "provincia": "PN", "lat": 46.070826, "lng": 12.587397 },
    { "cliente": "MAMI&FAMILY SNC DI POMO MARCO & C.", "indirizzo": "Piazza Duomo 16", "cap": "33081", "città": "Aviano", "provincia": "PN", "lat": 46.068939, "lng": 12.589504 },
    { "cliente": "ALLA CATINA RIST.SNC DI PALUMBO A.", "indirizzo": "Viale Venezia 119", "cap": "33170", "città": "Pordenone", "provincia": "PN", "lat": 45.973681, "lng": 12.662884 },
    { "cliente": "ALLA FRASCA OSTERIA SAS DI PICCININ", "indirizzo": "Via Pra' 45", "cap": "33170", "città": "Pordenone", "provincia": "PN", "lat": 45.960306, "lng": 12.697069 },
    { "cliente": "DAL CICO SAS DI GHELLER GINO", "indirizzo": "Via San Giorgio 4", "cap": "33170", "città": "Pordenone", "provincia": "PN", "lat": 45.960128, "lng": 12.657357 },
    { "cliente": "MAGLIULO ANGELA RAFFAELA", "indirizzo": "Via Dogana 11", "cap": "33170", "città": "Pordenone", "provincia": "PN", "lat": 45.947823, "lng": 12.657902 },
    { "cliente": "PIZZERIA RIST. JENNY DOPPIO O DI RE", "indirizzo": "Via Trieste 8", "cap": "33082", "città": "Azzano Decimo", "provincia": "PN", "lat": 45.880294, "lng": 12.716458 },
    { "cliente": "SOCIETA' AGRICOLA NONIS S.S. DI NON", "indirizzo": "Via Treviso 17", "cap": "33078", "città": "San Vito al Tagliamento", "provincia": "PN", "lat": 45.906671, "lng": 12.837920 },
    { "cliente": "MT24 SRL", "indirizzo": "Viale Narconi 14", "cap": "33078", "città": "San Vito al Tagliamento", "provincia": "PN", "lat": 45.914746, "lng": 12.856062 },
    { "cliente": "DIESSE SRLS", "indirizzo": "Piazza del Popolo 46/49", "cap": "33078", "città": "San Vito al Tagliamento", "provincia": "PN", "lat": 45.915298, "lng": 12.855937 },
    { "cliente": "LUNA NUOVA DI POSHNJARI KLEANDA", "indirizzo": "Via Isonzo 4", "cap": "33078", "città": "San Vito al Tagliamento", "provincia": "PN", "lat": 45.915573, "lng": 12.874485 },
    { "cliente": "MAMAN SNC DI MICHELE VADORI & C", "indirizzo": "Via Fornace 1", "cap": "33075", "città": "Morsano al Tagliamento", "provincia": "PN", "lat": 45.878859, "lng": 12.948425 },
    { "cliente": "DCN DI NEGREI DARIO CLAUDIUS SAS", "indirizzo": "Viale Stazione 1", "cap": "33079", "città": "Sesto al Reghena", "provincia": "PN", "lat": 45.850406, "lng": 12.878284 }
]

def crea_committente_dac():
    print("\n[STEP 1] Creazione tenant DAC in 'clienti_fatturazione' (se non esiste)...")
    tenant_ref = db.collection('clienti_fatturazione').document('DAC')
    if not tenant_ref.get().exists:
        tenant_ref.set({"nome": "DAC"})
        print("-> Tenant DAC creato.")
    else:
        print("-> Tenant DAC già esistente.")

def importa_anagrafica():
    print(f"\n[STEP 2] Inserimento di {len(punti_consegna)} punti di consegna nella root 'clienti/DAC/raccolta clienti'...")
    raccolta_ref = db.collection('clienti').document('DAC').collection('raccolta clienti')
    
    count = 0
    for punto in punti_consegna:
        payload = {
            "A chi va consegnato": punto["cliente"],
            "Indirizzo": punto["indirizzo"],
            "CAP": punto["cap"],
            "Città": punto["città"],
            "Provincia": punto["provincia"],
            "lat": punto["lat"],
            "lng": punto["lng"],
            "Orario min": "",
            "Orario max": "",
            "Tipologia consegna": "",
            "Codice Frutta": "",
            "Codice Latte": ""
        }
        
        # Salviamo il documento, lasciando che Firestore generi un ID automatico
        raccolta_ref.add(payload)
        count += 1
        print(f"  + Inserito: {punto['cliente']}")
        
    print(f"\n✅ Operazione completata. Inseriti {count} record anagrafici sotto il tenant DAC in ambiente di Sviluppo.")

if __name__ == "__main__":
    try:
        crea_committente_dac()
        importa_anagrafica()
    except Exception as e:
        print(f"❌ Errore durante l'importazione: {str(e)}")
