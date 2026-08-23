# Governance e Regole Operative - AppLogSolutions Produzione

Questa codebase è **SOLO Produzione**.

## Regole Inviolabili
- **Ambiente Unico**: Nessuna operazione verso LogiDesk o Cantiere.
- **Puntamento Esplicito**: Ogni comando Firebase deve puntare esplicitamente a `log-solution-60007`.
- **Deploy Selettivi**: È VIETATO il `firebase deploy` totale. Usare sempre deploy selettivi (es. `--only hosting` o `--only functions:nome_funzione`).
- **Nessun Deploy Automatico**: L'Hosting automatico tramite GitHub Actions è ATTUALMENTE DISABILITATO. Nessun push deve essere considerato automaticamente un deploy.
- **Autorizzazione**: Qualsiasi deploy (Hosting o Functions) va autorizzato esplicitamente.
- **Versionamento**: Nessun bump di versione per modifiche solo documentali o strutturali.
