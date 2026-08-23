# Confronto tra i due modali "Gestione Consegne"

Hai notato una differenza tra due componenti che, pur condividendo la stessa funzione di base (il riordino delle consegne a schermo intero o in sovrimpressione), presentano caratteristiche distinte in base a chi li sta usando: l'operatore in logistica (su Mappe dell'app) o l'autista (sul link generato).

Ecco tutte le differenze che ho individuato analizzando il codice di `mappa_zone.html` e il generatore di mappe in `main.py`:

## 1. Aspetto generale e dimensioni
- **In "Mappe dell'app" (`mappa_zone.html`):**
  - **Larghezza:** È pensato per schermi desktop. Il box centrale arriva fino a `max-width: 1200px`.
  - **Estetica:** Lo sfondo scuro ha un effetto di sfocatura (`backdrop-filter: blur(4px)`) ed è presente un'ombreggiatura importante (`box-shadow: 0 25px 50px...`).
- **Nel "Link dei viaggi" (Mappe Autisti in `main.py`):**
  - **Larghezza:** È progettato principalmente per gli smartphone degli autisti. Ha un `max-width: 500px`.
  - **Estetica:** Manca l'effetto blur sullo sfondo e non ha la grande ombra esterna, per risultare più leggero e performante sui dispositivi mobili.

## 2. Intestazione e Testi
- **In "Mappe dell'app":**
  - Il titolo è dinamico (es. mostra il nome del giro).
  - C'è un sottotitolo esplicativo: *"{N} fermate - Trascina per riordinare dall'alto al basso in un colpo solo"*.
  - I pulsanti in alto a destra sono **"Annulla"** e **"Applica Ordine"**.
- **Nel "Link dei viaggi":**
  - Il titolo è fisso e recita: **"Modifica Sequenza"**.
  - Non c'è alcun sottotitolo.
  - I pulsanti in alto a destra sono semplicemente **"Annulla"** e **"Applica"**.

## 3. Contenuto della lista (Le singole fermate)
- **In "Mappe dell'app":**
  - Le fermate vengono renderizzate da zero usando un design "compatto" (`compact-stop-item`).
  - Mostrano chiaramente l'orario di arrivo stimato e un badge rosso **"RITARDO"** se la consegna è prevista oltre l'orario limite.
  - **Pulsante Elimina:** Su ogni riga è presente un pulsante con la "X" (`close`) per poter rimuovere definitivamente una fermata dal viaggio.
- **Nel "Link dei viaggi":**
  - Il modale semplicemente "clona" le enormi carte (le card del giro) già presenti nella lista laterale della mappa, nascondendo solo i bottoni "CONSEGNATO".
  - Il quadratino a sinistra (che normalmente contiene il numero della fermata) viene svuotato e sostituito con l'icona di trascinamento (`drag_indicator`).
  - **Assenza di eliminazione:** Gli autisti non hanno il pulsante "X" per eliminare le tappe. Possono solo riordinarle.

## 4. Bottone di apertura
- **In "Mappe dell'app":** Si apre cliccando sull'icona `fullscreen` (il cerchietto con dentro la specie di quadratino a cui ti riferivi) situata sulle carte dei giri.
- **Nel "Link dei viaggi":** Si apre cliccando sul pulsante **"Ordina"** (con l'icona `swap_vert`, due frecce verticali) posizionato in alto nel menu laterale della mappa.
