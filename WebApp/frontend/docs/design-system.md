# AppLogSolutions Web - Design System v2.0 (UI Style Guide)

> ⚠️ **SYSTEM RULE:**
> Questo documento è VINCOLANTE per tutta la UI dell’app.
> Qualsiasi UI deve rispettarlo senza eccezioni.
> In caso di conflitto, fermarsi e proporre alternativa compatibile.

Questo manuale ufficiale non descrive solo l'aspetto visivo di AppLogSolutions, ma stabilisce le regole per mantenerne la coerenza strutturale man mano che il progetto cresce. Seguendo queste linee guida, chiunque può sviluppare nuove interfacce garantendo la stessa UX, accessibilità ed estetica in tutta l'applicazione.

---

## 1. Libreria dei Componenti

L'utilizzo di classi standard è fondamentale per evitare ridondanze nel CSS. Non inventare nuovi bottoni se ne esiste già uno che assolve alla stessa funzione.

### Button Primary
- **Classe:** `.btn-primary`
- **Utilizzo:** L'azione o la Call-To-Action (CTA) principale di una schermata (es. "Salva", "Invia", "Accedi").
- **Varianti ammesse:** `:disabled` (opacità ridotta, pointer-events none), `.loading` (non implementata di default, solitamente usa la sovrascrittura di testo).
- **Icone ammesse:** Sì (preferibilmente alla sinistra del testo).
- **Dimensioni:** Padding `16px`, width fissa/100% in mobile, border-radius `12px`.
- **Regola D'Oro:** Massimo UN `.btn-primary` per modulo o sezione. Per il resto usa bottoni secondari.

### Button Elabora / Azione
- **Classe:** `.btn-elabora` (o varianti asincrone `.glass-btn`)
- **Utilizzo:** Simile al Primary, ma per innescare script o calcoli pesanti. Solitamente accompagnato da uno spinner visivo.
- **Varianti:** Può essere inibito dinamicamente impostando `disabled=true`.

### Button Secondary / Icon Button
- **Classi:** `.btn-edit`, `.btn-delete`, `.btn-dettagli`, `.icon-btn`
- **Utilizzo:** Azioni secondarie relative a liste o tabelle. `.icon-btn` è un pulsante trasparente usato all'interno di input o righi tabella (es. tasto X per pulire).
- **Hover:** Colori dedicati al contesto visivo (`.btn-delete` diviene rosso pastello al passaggio del mouse).

### Glass Panel / Card
- **Classi:** `.glass-panel`, `.form-card`
- **Utilizzo:** Contenitore primario per racchiudere logiche e dati (es. la lista in pianificazione o le card in dashboard). 
- **Regole:** Non annidare multipli `.glass-panel` uno dentro l'altro. 

### Badge
- **Classi:** `.suggestion-badge`, `.badge-[cliente]`
- **Utilizzo:** Etichette dinamiche e filtri (Pianificazione).
- **Varianti:** `badge-disabled` (grigio opaco).

---

## 2. Gerarchia Tipografica

La font-family globale è `Outfit` (Google Fonts).

| Elemento | Font | Peso | Dimensione Desktop | Dimensione Mobile |
| :--- | :--- | :--- | :--- | :--- |
| **Titolo Landing/Logo** | Outfit | 800 (ExtraBold) | 32 px | 28 px |
| **Titolo Pagina (h2)** | Outfit | 700 (Bold) | 24 px | 18 px |
| **Sottotitolo (h3)** | Outfit | 600 (SemiBold)| 18 px | 16 px |
| **Titolo Sezione (h4)**| Outfit | 700 (Bold) | 13 px (Uppercase) | 11 px (Uppercase)|
| **Testo normale (p)** | Outfit | 400 (Regular) | 16 px | 14 px |
| **Testo input/select** | Outfit | 400 (Regular) | 15 px | 16 px* |
| **Testo secondario/table**| Outfit | 400/500 | 14 px | 10.5 px |
| **Caption/Micro copy**| Outfit | 400 (Regular) | 12 px | 10 px |

*(Nota: Input text e select su mobile hanno un override fisso a 16px per impedire lo zoom involontario di Safari/Chrome su iOS).*

---

## 3. Sistema di Spaziature (Spacing Scale)

L'applicazione segue un sistema a base 4/8 per mantenere margini e padding armoniosi e proporzionati. Non inserire margini arbitrari (es. `13px` o `27px`).

| Taglia | Dimensione | Utilizzo Principale |
| :--- | :--- | :--- |
| **XS** | `4 px` | Spazio minimo tra un'icona e un testo all'interno di un pulsante. |
| **S** | `8 px` | Spaziatura tra componenti di un input group (es. label e campo testo). |
| **M** | `16 px` | Padding base di un bottone, margine tra elementi in lista. |
| **L** | `24 px` | Spaziatura esterna del layout (gutter principale del `.main-container`). |
| **XL** | `32 px` | Spaziatura tra sezioni distinte della pagina o padding di una card grande. |
| **XXL** | `48 px` o `+` | Margini inferiori per staccare dal footer/navbar. |

*(Le griglie `.form-grid` usano un gap predefinito di `20px` su desktop e `12px` su mobile).*

---

## 4. Design Tokens (Variabili CSS)

### Colori Principali
- **Primary**: `#4f46e5` (Indigo, usato per pulsanti e link)
- **Primary Hover**: `#4338ca`
- **Success**: `#10b981` (Verde, usato per conferme e stati positivi)
- **Danger/Error**: `#ef4444` (Rosso, usato per errori, cancellazioni o logout)
- **Warning/Secondary**: `#f59e0b` / `#0ea5e9` (Arancione/Azzurro)

### Superfici e Sfondi
- **Background Globale**: `#f8fafc` (con un leggero gradiente radiale)
- **Superficie Carte (Glassmorphism)**: `rgba(255, 255, 255, 0.85)` (variabile `--surface`) con `backdrop-filter: blur(20px)`
- **Sfondo Input**: `rgba(255, 255, 255, 0.9)`

### Testo
- **Testo Principale**: `#0f172a` (Slate 900)
- **Testo Muted (Secondario)**: `#64748b` (Slate 500)

---

## 5. Iconografia

AppLogSolutions usa **Material Icons Round** di Google.
- **Dimensioni Standard:** `24px` nei pulsanti, `18px` in contesti densi, `48px` nelle icone delle modali.
- **Colori:** Ereditano il colore del testo genitore tramite `currentColor`.
- **Regole di accoppiamento:**
  - Quando un'azione è inequivocabile (es. il cestino per eliminare), l'icona da sola (con attributo `title="..."` e `aria-label`) è sufficiente.
  - Nei pulsanti primari (es. "Salva"), l'icona (se usata) deve precedere il testo e usare una spaziatura **XS (4px)**.

---

## 6. Stati dei Componenti

Tutti i componenti interattivi devono comunicare il proprio stato all'utente:

| Stato | Comportamento Visivo | Cursore / Pointer |
| :--- | :--- | :--- |
| **Normal** | Aspetto base definito in CSS. | `pointer` (bottoni), `text` (input) |
| **Hover** | Input: Nessun effetto forte. Pulsanti: Traslazione `translateY(-2px)`, ombra aumentata, colore scurito (es. `--primary-hover`). | `pointer` |
| **Focus / Active** | Input: `box-shadow` azzurro/indigo, bordo evidenziato. Indispensabile per accessibilità. | `text` / `pointer` |
| **Disabled** | Opacità dimezzata (`opacity: 0.5`), colore smorzato o scala di grigi. | `not-allowed` / `default` |
| **Loading** | Il testo del bottone viene spesso rimpiazzato dallo spinner o dal testo "Elaborazione...". L'elemento riceve stato `disabled`. | `wait` o `progress` |
| **Errore / Successo** | Bordo e testo mutano in Rosso (`#ef4444`) o Verde (`#10b981`). | `default` |

---

## 7. Regole di Accessibilità (A11y)

Le interfacce non devono solo essere belle, ma usabili per tutti (autisti al buio o ragioniera sotto la luce neon).

1. **Contrasto minimo:** Il testo deve sempre avere un contrasto sufficiente rispetto allo sfondo. Non usare mai grigio chiaro su sfondo bianco. `--text-main` (`#0f172a`) e `--text-muted` (`#64748b`) sono i colori omologati.
2. **Dimensione target cliccabili (Mobile):** I pulsanti destinati al mobile (`.logout-btn`, menu a tendina) devono avere un'area cliccabile di almeno **44x44 px**. Non fare bottoncini microscopici per gli autisti.
3. **Focus Ring visibile:** Non rimuovere MAI `outline: none;` dagli input senza rimpiazzarlo con un `box-shadow` evidente (già configurato nel file `styles.css` sotto `input:focus`).
4. **Accessibilità Icone (Aria-label):** Se un pulsante è composto *solo* da un'icona, assicurati di usare `<button aria-label="Azione"...>` o l'attributo `title="Azione"`.

---

## 8. Pattern Architetturali delle Pagine

Quando si crea una nuova sezione/strumento nell'app (es. "Gestione Sinistri" o "Controllo Ferie"), mantenere questa anatomia top-down:

1. **Navbar (`.glass-nav`)** (Fissa, branding, logout)
2. **Titolo Pagina & Alert di Versione** (es. h2, indicazioni chiare di aggiornamento in corso)
3. **Barra dei Filtri/Azioni (`.filters-container`)**
   - Raccoglie i selettori della data, bottoni "Importa" o "Aggiungi Nuovo".
4. **Box di Riepilogo (Opzionale)** (`.summary-grid` per visualizzare KPI rapide).
5. **Tabella Dati o Contenuto Principale (`.glass-panel`)**
6. **Paginazione / Footer della Tabella**
7. **Modali e Dialog (`.modal-overlay`)** (Inseriti a fine file HTML prima del tag `<script>`).

Questo garantisce che un operatore che sa usare *Fatturazione* saprà istintivamente dove guardare anche se usa il modulo *Pianificazione* per la prima volta.
