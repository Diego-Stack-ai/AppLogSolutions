/**
 * BillingEngine - Motore puro per la fatturazione (V2)
 * Calcola l'importo della fatturazione basandosi su UNA SINGOLA sorgente di dati alla volta.
 */
export class BillingEngine {
    constructor(config) {
        this.config = config || {};
    }

    /**
     * Elabora il mese usando il metodo impostato per il cliente.
     * Non fa controlli incrociati: la sorgente dati passata è l'unica fonte di verità.
     * 
     * @param {Object} clienteData - Le impostazioni del cliente (tariffe, metodo)
     * @param {String} mese - 'YYYY-MM'
     * @param {Array} datiSorgente - Array dei dati (presenze, viaggi o kpi)
     * @param {Object} mezziMap - Mappa targhe -> patenti (opzionale)
     */
    elaboraMese(clienteData, mese, datiSorgente, mezziMap = {}) {
        let totali = {
            importo_totale: 0,
            conteggio_elementi: datiSorgente.length,
            dettaglio_giornaliero: {}
        };

        const metodo = clienteData.metodo_fatturazione || 'PRESENZE';

        // Estrazione tariffe legacy cliente (con fallback a 0) per retrocompatibilità
        const t_patB = parseFloat(clienteData.patente_b) || 0;
        const t_patC = parseFloat(clienteData.patente_c) || 0;
        const navetteCustom = clienteData.navette_personalizzate || [];
        const t_collo = parseFloat(clienteData.cattel_collo) || 0;
        const t_forfait = parseFloat(clienteData.viaggio_forfait) || 0;

        // Nuova struttura V2 (Rubrica)
        const zoneFatturazione = clienteData.zone_fatturazione || [];

        datiSorgente.forEach(item => {
            let dateKey = '';
            let importoItem = 0;
            let tipoTariffa = 'Non Definito';
            let nomeViaggioOut = '';
            
            if (metodo === 'PRESENZE') {
                dateKey = item.data;
                const targa = (item.targa || "").toUpperCase();
                const viaggioStr = (item.viaggio || "").trim().toUpperCase();
                nomeViaggioOut = viaggioStr || targa;
                
                // 0) Controllo Override Prezzo (Regola V2 Fatturazione Navette)
                if (item.prezzo_override !== undefined && item.prezzo_override !== null) {
                    importoItem = parseFloat(item.prezzo_override) || 0;
                    tipoTariffa = 'Tariffa Specifica (Override)';
                }
                // 1) Cerchiamo match esatto nella nuova rubrica V2
                else {
                    const matchedZona = zoneFatturazione.find(z => (z.nome_zona || "").trim().toUpperCase() === viaggioStr);
                    
                    if (matchedZona) {
                        if (matchedZona.tipo_calcolo === 'viaggio') {
                            let p = parseFloat(matchedZona.prezzo_viaggio);
                            if (isNaN(p)) {
                                importoItem = 0;
                                tipoTariffa = 'ERRORE: Prezzo Mancante';
                            } else {
                                importoItem = p;
                                tipoTariffa = 'A Viaggio';
                            }
                        } else if (matchedZona.tipo_calcolo === 'ddt') {
                        // Al momento le logiche DDT dal registro presenze non sono attive, forza a 0 (o implementa la quantita)
                        importoItem = 0; 
                        tipoTariffa = 'A DDT (Attualmente 0)';
                    } else if (matchedZona.is_mensile) {
                        importoItem = 0;
                        tipoTariffa = 'Mensile (Quota Fissa)';
                    } else {
                        importoItem = 0;
                        tipoTariffa = 'Nessun Tipo Configurato';
                    }
                } else {
                    // Nessun match esatto nella rubrica V2 per questa zona
                    if (clienteData.is_navetta && clienteData.prezzo_navetta !== undefined) {
                        importoItem = parseFloat(clienteData.prezzo_navetta) || 0;
                        tipoTariffa = 'Tariffa Navetta (Fissa)';
                    } else {
                            importoItem = 0;
                            tipoTariffa = 'ZONA NON TROVATA';
                        }
                    }
                }
            } 
            else if (metodo === 'VIAGGI') {
                dateKey = item.data_lavoro || item.data_consegna || item.data;
                nomeViaggioOut = 'DDT/Giro';
                
                if (t_forfait > 0) {
                    importoItem = t_forfait;
                    tipoTariffa = 'Legacy Forfait';
                } else {
                    const targa = (item.targa || "").toUpperCase();
                    const patente = mezziMap[targa] || 'B';
                    importoItem = patente === 'C' ? t_patC : t_patB;
                    tipoTariffa = 'Legacy (Patente ' + patente + ')';
                }
                
                if (t_collo > 0 && item.colli) {
                    const numColli = parseInt(item.colli) || 0;
                    importoItem = numColli * t_collo; 
                    tipoTariffa = 'Legacy Collo';
                }
            } 
            else if (metodo === 'KPI') {
                dateKey = item.data_lavoro || item.Data || item.data;
                nomeViaggioOut = item.cliente || 'KPI';
                const importoKpi = parseFloat(item.Importo) || parseFloat(item.importo) || 0;
                importoItem = importoKpi;
                tipoTariffa = 'Importo Fisso KPI';
                if (importoItem === 0 && t_collo > 0 && item.Colli) {
                    importoItem = (parseInt(item.Colli) || 0) * t_collo;
                    tipoTariffa = 'KPI Colli x Tariffa';
                }
            }

            if (dateKey) {
                if (!totali.dettaglio_giornaliero[dateKey]) {
                    totali.dettaglio_giornaliero[dateKey] = {
                        voci: [],
                        importo_giornaliero: 0
                    };
                }
                totali.dettaglio_giornaliero[dateKey].voci.push({
                    viaggio: nomeViaggioOut,
                    tipo: tipoTariffa,
                    importo: importoItem,
                    is_navetta_injected: item.is_navetta_injected || false
                });
                totali.dettaglio_giornaliero[dateKey].importo_giornaliero += importoItem;
                totali.importo_totale += importoItem;
            }
        });

        // Ordiniamo le date in modo crescente prima di restituire
        const sortedDettaglio = {};
        Object.keys(totali.dettaglio_giornaliero).sort().forEach(k => {
            sortedDettaglio[k] = totali.dettaglio_giornaliero[k];
        });
        totali.dettaglio_giornaliero = sortedDettaglio;

        return {
            cliente: clienteData.nome,
            mese,
            metodo_utilizzato: metodo,
            totali,
            dati_processati: datiSorgente
        };
    }
}
