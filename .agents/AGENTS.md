# AGENTS.md â€” Regole Obbligatorie per questo Progetto
# AppLogSolutions Web â€” G:\Il mio Drive\App

Queste istruzioni sono VINCOLANTI per ogni agente che lavora su questo progetto.
NON devono essere ignorate, aggirate o modificate senza esplicita approvazione dell'utente.

---

## PROCEDURA OBBLIGATORIA: Aggiornamento Versione

Ogni volta che vengono apportate modifiche, sia al frontend che al backend (nuove funzionalita, bugfix, modifiche strutturali), l'agente DEVE SEMPRE far scattare e aggiornare la versione dell'applicazione.

> [!IMPORTANT]
> **UNICA PROCEDURA OPERATIVA AUTORIZZATA:** L'unica modalità consentita ed obbligatoria per effettuare l'aggiornamento (bump) della versione è l'esecuzione dello script automatizzato **`python bump_version.py`** dalla cartella radice di `AppLogSolutionsWeb`.
> Gli agenti AI e gli sviluppatori **non devono MAI eseguire questi passaggi manualmente**, al fine di prevenire errori umani o di codifica dei caratteri. La procedura manuale descritta di seguito ha il solo scopo informativo di illustrare la logica interna dello script.

### Dettaglio Logica Interna (Cosa fa lo script `bump_version.py` sotto il cofano):

1. **Aggiornamento dei File Chiave (Sempre in sincrono):**
   - `G:\Il mio Drive\App\AppLogSolutionsWeb\frontend\sw.js` (RIGA 1): Aggiorna `const CACHE_NAME = 'log-solution-vX.XX';`
   - `G:\Il mio Drive\App\AppLogSolutionsWeb\frontend\script.js` (RIGA 7): Aggiorna `const APP_VERSION = "X.XX";`

2. **Allineamento Cache Busting:**
   - Aggiorna i query string `?v=X.XX` nei tag `<link>` e `<script>` di **TUTTI** i file HTML del frontend per forzare i browser a scaricare i file JS/CSS aggiornati.

---

### Regole TASSATIVE:
- **DIVIETO DI INTERVENTO MANUALE:** Non provare mai a modificare a mano `sw.js`, `script.js` o i parametri `?v=` nei file HTML. Usa solo ed esclusivamente `python bump_version.py`.
- **Badge di Versione:** NON modificare mai il badge di versione hardcoded in dashboard.html o in qualsiasi altro file HTML. Il badge viene aggiornato automaticamente da script.js tramite `.app-version-badge`.
- **Divieto di Grep per Modifica:** NON usare grep/PowerShell per finalità di sostituzione/modifica del numero di versione (rischio di rompere SVG o coordinate GPS). L'uso di grep è consentito in sola lettura per le verifiche.
- **Controllo Versione di Partenza:** NON inventare la versione corrente. Controllare sempre script.js riga 7 prima di procedere.
- **TASSATIVO — DEPLOY CI/CD:** Dopo la modifica, NON lanciare `firebase deploy --only hosting` manualmente dal terminale locale per la produzione. L'Hosting viene deployato in automatico tramite GitHub Actions dal branch `main`.

### Sequenza Operativa del Deploy:
1. Assicurarsi di trovarsi sul branch `main`.
2. Scrivere il codice e apportare le modifiche necessarie.
3. Eseguire il bump della versione per forzare il refresh della cache:
   ```bash
   python bump_version.py
   ```
4. **Commit e Push in Produzione:** L'agente è autorizzato a:
   - Fare `git add .` e `git commit -m "..."`
   - Fare il merge su `main` e `git push`.
   - A questo punto i server GitHub si arrangeranno in automatico a fare il deploy in produzione.


---

## Struttura del Progetto

- App Web (Frontend + Cloud Functions): G:\Il mio Drive\App\AppLogSolutionsWeb\
  - Frontend: frontend/
  - Cloud Functions (Python): functions/main.py
- App Locale (script Python standalone): G:\Il mio Drive\AppLogSolutionLocale\dati\PROGRAMMA\
  - **NOTA SINCRO:** L'App Web Ã¨ al 100% svincolata a livello di codice dall'App Locale. Database (Firestore) e Storage Firebase vengono utilizzati in comune come sorgente di veritÃ , ma senza alcun automatismo in background. Il travaso dati tra i file Excel locali e Firestore avviene solo tramite script manuali dell'operatore.
- Firebase Project principale: log-solution-60007
- Firebase Project muletto (test): log-solution-muletto (TASSATIVO: NON DEVE MAI ESSERE TOCCATO, MODIFICATO O UTILIZZATO PER I DEPLOY SENZA ESPLICITO ORDINE DELL'UTENTE)
- Firestore tenant principale: clienti/DNR/

---

## Regole sul Database (Firestore)

- Le collezioni anagrafiche (raccolta clienti, articoli, orari, rientri) NON vanno mai toccate da operazioni logistiche o di pulizia.
- I dati logistici giornalieri vivono sotto clienti/DNR/reports_logistici/[data_consegna].
- Lo Storage Firebase usa i prefissi: split_ddt/[data]/, REPORTS/[data]/, CONSEGNE/CONSEGNE_[data]/.

---

## Regole sul Deploy (CI/CD Obbligatorio) 

- **TASSATIVO — AMBIENTE DI PRODUZIONE UNICO:**
  - **PRODUZIONE (`main`):** Qualsiasi operazione di deploy ufficiale (sia Hosting automatico via GitHub che Functions manuali) deve puntare unicamente al progetto `log-solution-60007`.
- TASSATIVO â€” DIVIETO SUL MULETTO: Il progetto e ambiente muletto (`log-solution-muletto`) NON DEVE MAI ESSERE TOCCATO o UTILIZZATO.
- **HOSTING (FRONTEND):** Tassativamente VIETATO fare `firebase deploy --only hosting` verso la produzione manualmente dal terminale locale. Il deploy in produzione avviene IN AUTOMATICO tramite GitHub Actions quando si effettua il `git push origin main`. L'agente deve limitarsi a unire le modifiche su `main` e fare il push. 
- **FUNCTIONS (BACKEND):** Il deploy delle Cloud Functions si esegue dal terminale locale, ma **TASSATIVAMENTE** specificando sempre il progetto di destinazione: ``--project log-solution-60007` (per l'ufficiale, solo dopo approvazione).
- Una sola funzione: `firebase deploy --only functions:nome_funzione --project [NOME_PROGETTO]` (eseguire sempre dalla cartella G:\Il mio Drive\App\AppLogSolutionsWeb).
- NON eseguire mai `firebase deploy` totale senza `--only`.
- **GESTIONE VERSIONI (BUMP):** Prima di qualsiasi deploy (prima di ogni push verso GitHub per la produzione), è **TASSATIVO** eseguire lo script `python bump_version.py` dalla cartella **radice** `G:\Il mio Drive\App\AppLogSolutionsWeb` (NON dentro frontend/). Lo script legge la versione da script.js, la incrementa, aggiorna sw.js, script.js e tutti i file HTML con fallback encoding cp1252 per i file non-UTF8.
- **COMUNICAZIONE ALL'UTENTE:** Al termine di un deploy manuale o di un bump, l'agente DEVE dichiarare in modo cristallino all'utente su quale ambiente ha operato (Produzione) e quale versione esatta ha calcolato lo script, ricordando all'utente di fare un refresh forzato (`Ctrl + F5`) se la cache del browser dovesse mostrare ancora il vecchio numero.
---

## Filiera di Controllo Prima di Modificare

Prima di modificare qualsiasi file, l'agente DEVE:
1. Verificare quale file e la sorgente di verita per quella funzionalita.
2. NON usare Set-Content con PowerShell per iniettare codice JS/HTML con backtick o caratteri speciali. Usare SEMPRE script Python scritti con write_to_file ed eseguiti con python.
3. Dopo ogni modifica a elaborazione.html o a qualsiasi pagina con JS, verificare che le stringhe confirm() e i template literal JS siano sintatticamente corretti prima di fare il deploy.

---

## CODICE DI CONDOTTA COMPORTAMENTALE DELL'AGENTE (AI GOVERNANCE)

Ogni agente che opera su questo progetto deve tassativamente rispettare i seguenti principi di luciditÃ  e trasparenza:

1. RIGORE E COERENZA CRITICA: L'agente non deve mai generare spiegazioni accomodanti o inventare pattern di sincronizzazione per compiacere l'utente. Deve analizzare il sistema con occhio critico, basandosi esclusivamente sui fatti riscontrabili nel codice.
2. TRASPARENZA SULLE IPOTESI (AVVISO UMANO): Qualora l'agente sia costretto a teorizzare o immaginare il funzionamento di un componente non ispezionato direttamente, DEVE dichiararlo esplicitamente anteponendo l'etichetta `[âš ï¸� TEORIA AI / DA VERIFICARE]`.
3. AUTOMONITORAGGIO DERIVA LOGICA: Nelle sessioni di lavoro lunghe o complesse, l'agente deve autovalutare la qualitÃ  del proprio contesto. Se rileva il rischio di allucinazioni o di assunzioni non verificate, deve fermare l'esecuzione e richiedere un reset o un allineamento esplicito all'operatore umano.

---

## GOVERNANCE DEL DISASTER RECOVERY E CONTINUITÃ€ AZIENDALE (CAVEAU DI RINASCITA)

L'infrastruttura aziendale prevede l'istituzione e la manutenzione di un sistema di Disaster Recovery di livello Enterprise situato in `G:\Il mio Drive\CAVEAU_RINASCITA_APP\`, concepito per slegare l'app da guasti cloud o perdite hardware e consentirne la rinascita da zero in 10 minuti netti.

1. **Principio di Recupero Certificato:** Il Caveau non garantisce il recupero dello stato teorico dell'app, ma il recupero dell'ultimo stato operativo verificato e certificato (strettamente associato a timestamp, commit Git, release in vigore e test superati). Solo un pacchetto in possesso di certificazione completa guadagna il titolo di "Punto di Rinascita".
2. **Barriera PRE_BACKUP_CHECK:** Lo script di estrazione DR deve avviare collaudi sintattici (compilazione Python di main.py, check validitÃ  JSON cache e controllo file critici). Se il progetto presenta il minimo errore o inconsistenza, il backup si ferma istantaneamente per garantire un caveau incorrotto.
3. **Audit e Segreti:** Il Caveau conserva la memoria evolutiva dell'app in `09_AUDIT_LOG/` (storico di backup, deploy, autori, descrizioni e motivazioni) e archivia le credenziali sensibili esclusivamente in forma protetta/crittografata in `04_SEGRETI/`.
4. **Strategia di Conservazione Fisica e Manutenzione:** Il Caveau Master adotta una triplice architettura ridondata (copia locale G:, copia su supporto fisico esterno USB/HDD, copia remota protetta). Tutte le copie condividono lo stesso checksum SHA256 e manifesto. Ogni mese o trimestre, il sistema esegue la certificazione periodica (verifica hash anti bit-rot, controllo leggibilitÃ  e spazio), rendendo il Caveau un organismo mantenuto vivo e pulsante.

---

## VINCOLO OPERATIVO UI E DESIGN SYSTEM

Da questo momento, ogni modifica o creazione UI deve rispettare tassativamente:
- `G:\Il mio Drive\App\AppLogSolutionsWeb\frontend\docs\design-system.md`
- `G:\Il mio Drive\App\AppLogSolutionsWeb\frontend\docs\design-system.json`

**Ãˆ SEVERAMENTE VIETATO:**
- Creare nuove classi CSS non presenti nel sistema.
- Usare inline styles (es. `<div style="...">`).
- Duplicare componenti UI giÃ  esistenti.
- Ignorare lo spacing system o la gerarchia tipografica.

Se una richiesta dell'utente viola il design system, l'agente DEVE fermarsi, NON generare la UI e proporre all'utente un'alternativa coerente con il sistema e le classi esistenti.

- TASSATIVO — DIVIETO ASSOLUTO DI MODIFICA SCRIPT BUMP: È severamente vietato agli agenti modificare, semplificare, tagliare o alterare lo script `bump_version.py` situato nella root di `AppLogSolutionsWeb` (NON dentro frontend/). Lo script gestisce il calcolo intelligente e progressivo della versione con fallback encoding cp1252. Lo script deve rimanere così com'è. Qualsiasi modifica richiede esplicita autorizzazione dell'utente.
