# Memoria Storica: Disaccoppiamento DNR e Isolamento Totale Tenant

Questo documento serve come memoria storica e TODO-list (Debito Tecnico) da affrontare **immediatamente dopo aver completato e validato la pagina "Fatturazione V2"**.

## 🎯 L'Obiettivo
Attualmente il sistema utilizza in modo improprio il committente "DNR" trattandolo come una sorta di tenant "radice" (root) o contenitore di default. L'obiettivo è **rendere ogni tenant (DNR, GRAN CHEF, CATTEL, ecc.) un contenitore indipendente e paritetico**, eliminando ogni forma di favoritismo strutturale verso DNR all'interno del codice sorgente.

## 🚨 Il Problema Attuale
Nel codice frontend e nelle funzioni, DNR è spesso hardcoded in questo modo:
1. Come **Fallback globale**: `const activeTenant = localStorage.getItem('activeTenant') || 'DNR';`.
2. Come **Percorso di Salvataggio Forzato**: Molte schermate di impostazioni o pianificazione salvano o leggono dati puntando fisso a `clienti/DNR/...` (es. *codici articoli*, *rientri ddt*).
3. Come **Padrone dei Reports**: Su Google Cloud Storage i file vengono salvati nella root se il tenant è DNR, o in sottocartelle per gli altri.
Tutto questo causa il riversamento (o "risucchio") di viaggi e dati di vari committenti all'interno della cartella DNR, sporcando l'architettura dei dati.

## 📥 Analisi Prioritaria: I Dati in Entrata (Data Ingestion)
Il primo passaggio da compiere sarà **analizzare i flussi dei dati in entrata**. 
Bisogna capire esattamente come vengono trattati e salvati i dati al momento della loro genesi:
- **Flussi di Importazione**: Indagare sugli script di importazione (es. file Excel dei viaggi o dei KPI) per vedere se l'inserimento avviene forzatamente sotto DNR.
- **Creazione Pianificazione**: Analizzare il momento esatto in cui un dispatcher crea o assegna un viaggio, per evitare che la riga di codice `salvaPianificazione("DNR", ...)` lo dirotti nel tenant sbagliato.
- **Smistamento alla Nascita**: Assicurarsi che qualsiasi dato in entrata sia obbligato a dichiarare il suo *vero* tenant di appartenenza (Cattel, Gran Chef, ecc.) prima di toccare il database Firestore, inibendo il fallback automatico a DNR se il tenant non è esplicito.

## 🛠️ Azioni da Intraprendere sul Codice
Una volta avviato questo cantiere, bisognerà intervenire sui seguenti file per rimuovere i riferimenti a DNR:
- [ ] `elaborazione.html`
- [ ] `gestione.html` (isolare codici articoli, rientri, anagrafiche)
- [ ] `impostazioni.html`
- [ ] `mappa_zone.html` e `mappa_google.html` (struttura salvataggio Cloud Storage e lettura punti)
- [ ] `pianificazione.html` (isolare salvataggio e recupero assegnazioni)
- [ ] Script Python / Backend Functions di Importazione e sincronizzazione.

---
*Creato dall'Agente durante i lavori di Fatturazione V2 per non perdere traccia di questo fondamentale refactoring strutturale.*
