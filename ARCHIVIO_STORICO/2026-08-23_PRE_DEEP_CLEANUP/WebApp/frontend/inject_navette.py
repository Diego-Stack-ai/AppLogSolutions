import re
import sys

def main():
    file_path = 'presenze.html'
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Modify the navetta-table headers
    content = content.replace(
        '<th>Foto DDT</th>',
        '<th>Foto DDT</th>\n                                                  <th>Azioni</th>'
    )

    # 2. Modify the navetta-table row to include Azioni
    row_replace = '''                                      <td></td>
                                      <td>
                                          <div style="display:flex; gap:6px;">
                                              <button class="btn-edit" onclick="openNavettaModal('', )" title="Modifica Navetta" style="padding:4px 8px; font-size:12px;">??</button>
                                              <button class="btn-edit" onclick="deleteNavetta('', )" title="Elimina Navetta" style="padding:4px 8px; font-size:12px; background:#fee2e2; color:#b91c1c; border-color:#fca5a5;">???</button>
                                          </div>
                                      </td>
                                  </tr>'''
    
    content = content.replace(
        'record.attivitaAggiuntive.forEach(att => {',
        'record.attivitaAggiuntive.forEach((att, idx) => {'
    )
    
    content = content.replace(
        '''                                      <td></td>
                                  </tr>''',
        row_replace
    )

    # 3. Add the 'Aggiungi Navetta' button at the bottom of the table
    table_end = '''                                          </tbody>
                                      </table>
                                      <div style="margin-top: 10px; text-align: right;">
                                          <button class="btn-primary" onclick="openNavettaModal('', -1)" style="font-size: 12px; padding: 4px 10px;">? Aggiungi Navetta</button>
                                      </div>
                                  </div>
                              </td>
                          ;'''
                          
    content = content.replace(
        '''                                          </tbody>
                                      </table>
                                  </div>
                              </td>
                          ;''',
        table_end
    )
    
    # Also add the Aggiungi button when there are NO navette initially?
    # Right now, sub-row is ONLY created if hasNavette is true.
    # We should change hasNavette so the sub-row is ALWAYS created!
    content = content.replace(
        'const hasNavette = record.attivitaAggiuntive && record.attivitaAggiuntive.length > 0;',
        '''const hasNavette = record.attivitaAggiuntive && record.attivitaAggiuntive.length > 0;
                      // Costringiamo la generazione della riga navette per permettere l'aggiunta
                      const showNavetteRow = true;'''
    )
    content = content.replace(
        'if (hasNavette) {',
        'if (showNavetteRow) { // Modificato per renderizzare sempre la riga'
    )
    # Also we must fix the record.attivitaAggiuntive.forEach if it's undefined
    content = content.replace(
        'record.attivitaAggiuntive.forEach((att, idx) => {',
        '(record.attivitaAggiuntive || []).forEach((att, idx) => {'
    )

    # 4. Insert Modal HTML
    modal_html = '''
    <!-- NAVETTA MODAL -->
    <div id="navettaModal" class="presenze-modal-overlay">
        <div class="presenze-modal-box" style="max-width: 600px;">
            <div class="modal-header">
                <h3 id="navettaModalTitle">Gestione Navetta</h3>
                <button class="modal-close" onclick="closeNavettaModal()">?</button>
            </div>
            <div class="modal-body" style="max-height: 70vh; overflow-y: auto; padding-right: 10px;">
                <input type="hidden" id="navettaDocId">
                <input type="hidden" id="navettaIndex">
                
                <div style="display:flex; gap:10px; margin-bottom:15px;">
                    <div style="flex:1;">
                        <label style="font-size:12px; font-weight:bold; color:var(--text-muted);">Ora Inizio</label>
                        <input type="time" id="navOraInizio" class="glass-input" style="width:100%;">
                    </div>
                    <div style="flex:1;">
                        <label style="font-size:12px; font-weight:bold; color:var(--text-muted);">Ora Fine</label>
                        <input type="time" id="navOraFine" class="glass-input" style="width:100%;">
                    </div>
                </div>
                
                <div style="margin-bottom:15px;">
                    <label style="font-size:12px; font-weight:bold; color:var(--text-muted);">Partenza</label>
                    <input type="text" id="navPartenza" class="glass-input" style="width:100%;" placeholder="Luogo di partenza">
                </div>
                
                <div style="display:flex; gap:10px; margin-bottom:15px;">
                    <div style="flex:1;">
                        <label style="font-size:12px; font-weight:bold; color:var(--text-muted);">Km Iniziali</label>
                        <input type="number" id="navKmIniziali" class="glass-input" style="width:100%;" onchange="calcNavDelta()">
                    </div>
                    <div style="flex:1;">
                        <label style="font-size:12px; font-weight:bold; color:var(--text-muted);">Km Finali</label>
                        <input type="number" id="navKmFinali" class="glass-input" style="width:100%;" onchange="calcNavDelta()">
                    </div>
                    <div style="flex:1;">
                        <label style="font-size:12px; font-weight:bold; color:var(--text-muted);">Delta Km</label>
                        <input type="number" id="navDeltaKm" class="glass-input" style="width:100%; background:#f1f5f9;" readonly>
                    </div>
                </div>
                
                <div style="margin-bottom:15px;">
                    <label style="font-size:12px; font-weight:bold; color:var(--text-muted);">Foto (URL)</label>
                    <input type="text" id="navFotoUrl" class="glass-input" style="width:100%;" placeholder="Incolla l'URL della foto se presente">
                </div>
                
                <div style="border-top: 1px solid #e2e8f0; padding-top:15px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <h4 style="margin:0; font-size:14px; color:var(--primary);">Tappe</h4>
                        <button class="btn-primary" onclick="addNavettaTappa()" style="font-size:11px; padding:4px 8px;">? Aggiungi Tappa</button>
                    </div>
                    <div id="navettaTappeContainer">
                        <!-- Tappe dinamiche -->
                    </div>
                </div>
            </div>
            <div class="modal-footer" style="margin-top:20px; text-align:right;">
                <button class="btn-primary" onclick="saveNavetta()" id="btnSaveNavetta">?? Salva Navetta</button>
            </div>
        </div>
    </div>
    '''
    
    content = content.replace('<!-- DETTAGLI MODAL -->', modal_html + '\n    <!-- DETTAGLI MODAL -->')

    # 5. Insert Modal JS Logic
    js_logic = '''
        // --- GESTIONE NAVETTE CRUD ---
        let currentNavettaTappe = [];
        
        window.calcNavDelta = function() {
            const start = parseFloat(document.getElementById('navKmIniziali').value) || 0;
            const end = parseFloat(document.getElementById('navKmFinali').value) || 0;
            const delta = end - start;
            document.getElementById('navDeltaKm').value = delta > 0 ? delta : 0;
        };
        
        window.renderNavettaTappe = function() {
            const container = document.getElementById('navettaTappeContainer');
            container.innerHTML = '';
            
            if (currentNavettaTappe.length === 0) {
                container.innerHTML = '<div style="font-size:12px; color:#94a3b8; font-style:italic;">Nessuna tappa inserita.</div>';
                return;
            }
            
            currentNavettaTappe.forEach((t, i) => {
                const row = document.createElement('div');
                row.style.cssText = "display:flex; gap:6px; margin-bottom:8px; align-items:center; background:#f8fafc; padding:8px; border-radius:6px; border:1px solid #e2e8f0;";
                
                row.innerHTML = 
                    <div style="flex:1;">
                        <input type="text" class="glass-input" style="width:100%; padding:4px; font-size:11px;" placeholder="Carico" value="" onchange="currentNavettaTappe[].carico=this.value">
                    </div>
                    <div style="flex:1;">
                        <input type="text" class="glass-input" style="width:100%; padding:4px; font-size:11px;" placeholder="Cliente Merce" value="" onchange="currentNavettaTappe[].cliente_merce=this.value">
                    </div>
                    <div style="flex:1;">
                        <input type="text" class="glass-input" style="width:100%; padding:4px; font-size:11px;" placeholder="Destinazione" value="" onchange="currentNavettaTappe[].destinazione_merce=this.value">
                    </div>
                    <button onclick="removeNavettaTappa()" style="background:none; border:none; color:#dc2626; cursor:pointer; font-size:16px;" title="Rimuovi">?</button>
                ;
                container.appendChild(row);
            });
        };
        
        window.addNavettaTappa = function() {
            currentNavettaTappe.push({ carico: '', cliente_merce: '', destinazione_merce: '' });
            renderNavettaTappe();
        };
        
        window.removeNavettaTappa = function(idx) {
            currentNavettaTappe.splice(idx, 1);
            renderNavettaTappe();
        };
        
        window.openNavettaModal = function(docId, idx) {
            const overlay = document.getElementById('navettaModal');
            document.getElementById('navettaDocId').value = docId;
            document.getElementById('navettaIndex').value = idx;
            
            // Popola i dati
            let navData = {};
            if (idx >= 0 && currentPresenzeData && currentPresenzeData[docId]) {
                const arr = currentPresenzeData[docId].attivitaAggiuntive || [];
                if (arr[idx]) {
                    navData = JSON.parse(JSON.stringify(arr[idx])); // Copia
                }
            }
            
            document.getElementById('navOraInizio').value = navData.oraInizio || '';
            document.getElementById('navOraFine').value = navData.oraFine || '';
            document.getElementById('navPartenza').value = navData.partenza || '';
            document.getElementById('navKmIniziali').value = navData.kmIniziali || '';
            document.getElementById('navKmFinali').value = navData.kmFinali || '';
            document.getElementById('navFotoUrl').value = navData.fotoUrl || '';
            
            calcNavDelta();
            
            currentNavettaTappe = Array.isArray(navData.tappe) ? navData.tappe : [];
            renderNavettaTappe();
            
            overlay.style.display = 'flex';
        };
        
        window.closeNavettaModal = function() {
            document.getElementById('navettaModal').style.display = 'none';
        };
        
        import { setDoc, doc } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-firestore.js";
        
        window.saveNavetta = async function() {
            const btn = document.getElementById('btnSaveNavetta');
            const docId = document.getElementById('navettaDocId').value;
            const idx = parseInt(document.getElementById('navettaIndex').value);
            
            if (!docId || !currentPresenzeData || !currentPresenzeData[docId]) {
                alert("Errore: documento non trovato in locale.");
                return;
            }
            
            calcNavDelta();
            
            const newNav = {
                oraInizio: document.getElementById('navOraInizio').value,
                oraFine: document.getElementById('navOraFine').value,
                partenza: document.getElementById('navPartenza').value,
                kmIniziali: parseFloat(document.getElementById('navKmIniziali').value) || 0,
                kmFinali: parseFloat(document.getElementById('navKmFinali').value) || 0,
                deltaKm: parseFloat(document.getElementById('navDeltaKm').value) || 0,
                fotoUrl: document.getElementById('navFotoUrl').value,
                tappe: currentNavettaTappe
            };
            
            let arr = currentPresenzeData[docId].attivitaAggiuntive || [];
            if (idx >= 0) {
                arr[idx] = newNav;
            } else {
                arr.push(newNav);
            }
            
            try {
                btn.disabled = true;
                btn.innerText = "Salvataggio...";
                const db = window.db; // Need to ensure db is accessible globally, or use a workaround
                
                await setDoc(doc(db, "presenze", docId), {
                    attivitaAggiuntive: arr
                }, { merge: true });
                
                closeNavettaModal();
                // onSnapshot aggiornera' la UI
            } catch (err) {
                console.error(err);
                alert("Errore durante il salvataggio: " + err.message);
            } finally {
                btn.disabled = false;
                btn.innerText = "?? Salva Navetta";
            }
        };
        
        window.deleteNavetta = async function(docId, idx) {
            if (!confirm("Sei sicuro di voler eliminare definitivamente questa navetta?")) return;
            
            if (!docId || !currentPresenzeData || !currentPresenzeData[docId]) return;
            
            let arr = currentPresenzeData[docId].attivitaAggiuntive || [];
            if (idx >= 0 && idx < arr.length) {
                arr.splice(idx, 1);
                
                try {
                    const db = window.db; 
                    await setDoc(doc(db, "presenze", docId), {
                        attivitaAggiuntive: arr
                    }, { merge: true });
                } catch (err) {
                    console.error(err);
                    alert("Errore durante l'eliminazione: " + err.message);
                }
            }
        };
        // ------------------------------
'''
    
    # Expose db globally near module initialization
    content = content.replace(
        'const app = getApps().length > 0 ? getApps()[0] : initializeApp(firebaseConfig);',
        'const app = getApps().length > 0 ? getApps()[0] : initializeApp(firebaseConfig);\n          window.db = getFirestore(app);'
    )
    
    content = content.replace(
        'window.openDettagli = function(btn) {',
        js_logic + '\n        window.openDettagli = function(btn) {'
    )

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print("Success: presenze.html modified!")

if __name__ == '__main__':
    main()
