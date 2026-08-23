# AppLogSolutions PRODUZIONE

> **Piattaforma Logistica Modulare**
> **Proprietà**: Loge Solution
> **Ambiente**: PRODUZIONE (Firebase: `log-solution-60007`)
> **Versione Runtime**: 6.408

## Scopo
Questa codebase ospita esclusivamente l'ambiente di PRODUZIONE stabile e ufficiale (versione 6.408). Non ci sono ambienti intermedi o di sviluppo in questo repository. (Nota: Il repository è ora separato da LogiDesk).

## Struttura
- Root repository locale: `H:\Il mio Drive\APP\AppLogSolutions`
- Root applicativa: `H:\Il mio Drive\APP\AppLogSolutions\WebApp`
- Repository GitHub: `https://github.com/Diego-Stack-ai/AppLogSolutions.git`
- Branch ufficiale: `main`

### Componenti
- `WebApp/frontend/`: Frontend Produzione (HTML/JS/CSS no-build)
- `WebApp/functions/`: Backend. Utilizza `functions/main.py` (monolitico storico)
- `WebApp/firebase.json` & `WebApp/.firebaserc`: Configurazioni Firebase puntate esplicitamente alla Produzione.
