import sys
import re

with open('frontend/elaborazione.html', 'r', encoding='utf-8') as f:
    content = f.read()
    
# Extract the function
start_marker = "window.cancellaGiornataTotale = async function(data_consegna) {"
if start_marker not in content:
    sys.exit(1)

start_idx = content.find(start_marker)
# Find the end of this function (it ends right before unction listenToReports() {)
end_marker = "function listenToReports() {"
end_idx = content.find(end_marker, start_idx)

new_func = """window.cancellaGiornataTotale = async function(data_consegna) {
            Swal.fire({
                title: 'Generazione Preview...',
                html: 'Recupero elenco dei file e record da eliminare.',
                allowOutsideClick: false,
                didOpen: () => Swal.showLoading()
            });

            try {
                const eliminaFn = httpsCallable(functions, 'elimina_giornata_logistica');
                // DRY RUN
                const dryRunRes = await eliminaFn({ data_consegna: data_consegna, soft_delete: false, dry_run: true });
                if (dryRunRes.data.status !== 'ok') {
                    Swal.fire('Errore', dryRunRes.data.message || 'Errore generazione manifest', 'error');
                    return;
                }
                
                const man = dryRunRes.data.manifest;
                const manId = dryRunRes.data.manifestId;
                const manHash = dryRunRes.data.manifestHash;
                
                const counts = {
                    inputFiles: man.storage.filter(x => x.cat === 'inputFiles').length,
                    intermediateFiles: man.storage.filter(x => x.cat === 'intermediateFiles').length,
                    processingJobs: man.firestore.filter(x => x.cat === 'processingJobs').length,
                    trips: man.firestore.filter(x => x.cat === 'trips').length,
                    titleLocks: man.firestore.filter(x => x.cat === 'titleLocks').length,
                    orphanTitleLocks: man.firestore.filter(x => x.cat === 'orphanTitleLocks').length,
                    maps: man.firestore.filter(x => x.cat === 'maps').length,
                    distinte: man.firestore.filter(x => x.cat === 'distinte').length,
                    reports: man.firestore.filter(x => x.cat === 'dailyReports').length
                };
                
                const pres = man.preserved.map(x => x.categoria).join(', ');

                const result = await Swal.fire({
                    title: '⚠️ ELIMINAZIONE DEFINITIVA (Tabula Rasa)',
                    html: <div style="text-align:left; font-size: 0.95em;">
                           Stai per eliminare <b>DEFINITIVAMENTE</b> i dati del <b>\</b>.<br><br>
                           <b>Elementi che verranno ELIMINATI:</b><br>
                           - File Input Originali: \<br>
                           - Processing Jobs: \<br>
                           - Viaggi e Percorsi: \<br>
                           - Locks operativi (\ orfani): \<br>
                           - Mappe, Distinte, Report e file intermedi: \<br><br>
                           <b style="color:green;">Dati che verranno PRESERVATI:</b><br>
                           Anagrafiche clienti, indirizzi, geolocalizzazioni, articoli, orari, cache distanze, configurazioni e dati estranei.<br><br>
                           <span style="color:#dc2626;font-weight:700;">⚠️ Verranno eliminati anche i file originali Excel/PDF collegati alla giornata. Per ricreare la giornata sarà necessario importarli nuovamente.</span><br><br>
                           Digita <b>\</b> per confermare:</div>,
                    input: 'text',
                    inputPlaceholder: s. \,
                    icon: 'warning',
                    showCancelButton: true,
                    confirmButtonColor: '#dc2626',
                    cancelButtonColor: '#64748b',
                    confirmButtonText: '🗑️ Esegui Tabula Rasa',
                    cancelButtonText: 'Annulla',
                    reverseButtons: true,
                    preConfirm: (inputVal) => {
                        if (inputVal !== data_consegna) {
                            Swal.showValidationMessage(Devi digitare esattamente: \);
                            return false;
                        }
                        return true;
                    }
                });
                
                if (!result.isConfirmed) return;

                Swal.fire({
                    title: 'Distruzione in corso...',
                    html: Cancellazione batch di tutti gli elementi in corso.<br>Attendere prego.,
                    allowOutsideClick: false,
                    allowEscapeKey: false,
                    showConfirmButton: false,
                    didOpen: () => { Swal.showLoading(); }
                });
                
                // EXECUTION
                const execRes = await eliminaFn({ data_consegna: data_consegna, soft_delete: false, dry_run: false, manifestId: manId, manifestHash: manHash });
                const rData = execRes.data;
                
                if (rData && rData.status === 'success') {
                    Swal.fire({
                        title: 'Tabula Rasa Completata!',
                        html: rData.message,
                        icon: 'success'
                    }).then(() => location.reload());
                } else if (rData && rData.status === 'partial') {
                    console.warn(rData.residuals);
                    Swal.fire('Parziale', rData.message + '<br>Residui trovati. (Vedi console)', 'warning');
                } else {
                    Swal.fire('Errore', rData ? rData.message : 'Errore sconosciuto', 'error');
                }

            } catch (error) {
                console.error(error);
                Swal.fire('Errore', error.message, 'error');
            }
        };

        """

new_content = content[:start_idx] + new_func + content[end_idx:]

with open('frontend/elaborazione.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("UI Replace success")
