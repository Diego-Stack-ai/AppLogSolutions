/**
 * ui-render.js — v1.32
 * Rendering dinamico delle card dei viaggi recuperati da Firestore.
 * Gestisce anche la rimozione della card dalla DOM dopo eliminazione.
 */

/**
 * Renderizza la lista dei viaggi come card nell'elemento indicato.
 *
 * @param {Array}   trips       - Array di oggetti viaggio (da Firestore)
 * @param {string}  containerId - ID del contenitore HTML dove inserire le card
 * @param {boolean} isAdmin     - Se true, mostra il pulsante "Elimina Viaggio"
 */
export function renderTripList(trips, containerId, isAdmin = false) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = '';

    // Gestione stato vuoto
    const emptyState = document.getElementById('emptyState');
    if (trips.length === 0) {
        if (emptyState) emptyState.style.display = 'block';
        return;
    }
    if (emptyState) emptyState.style.display = 'none';

    trips.forEach(r => {
        // Formattazione data leggibile in italiano
        const dataStr = r.data ? new Date(r.data).toLocaleDateString('it-IT') : '-';

        // Crea l'elemento card con data-trip-id per identificarla nella DOM
        const card = document.createElement('div');
        card.className = 'data-card';
        card.dataset.tripId = r.id; // ← attributo usato per rimozione DOM senza reload

        card.innerHTML = `
            <div class="card-header">
                <div>
                    <span style="font-weight: 700; color: var(--primary); font-size: 16px;">${dataStr}</span>
                    <span style="margin-left: 12px; color: var(--text-muted); font-size: 13px;">${r.autista || 'Sconosciuto'}</span>
                </div>
                <div style="display:flex; align-items:center; gap:12px;">
                    <span class="status-badge badge-success">${r.automezzo || '-'}</span>

                    ${isAdmin ? `
                    <!-- Pulsante visibile SOLO ad amministratore e impiegata -->
                    <button
                        id="btn-delete-${r.id}"
                        onclick="confirmDeleteTrip('${r.id}', this)"
                        style="border:none; background:none; color:#f87171; cursor:pointer; display:flex; align-items:center; padding:4px;"
                        title="Elimina viaggio">
                        <span class="material-icons-round" style="font-size:20px;">delete_outline</span>
                    </button>` : ''}
                </div>
            </div>

            <!-- Griglia dati principali -->
            <div class="card-grid">
                <div class="data-item">
                    <span class="data-label">Cliente</span>
                    <span class="data-value">${(r.cliente || '-').toUpperCase()}</span>
                </div>
                <div class="data-item">
                    <span class="data-label">Km Percorsi</span>
                    <span class="data-value">${r.delta_km || '-'} km</span>
                </div>
                <div class="data-item">
                    <span class="data-label">Ore Totali</span>
                    <span class="data-value">${r.ore_totali || '-'}h</span>
                </div>
                <div class="data-item">
                    <span class="data-label">Viaggio</span>
                    <span class="data-value" style="font-size:11px;">
                        ${r.mappaUrl ? `<a href="${r.mappaUrl}" target="_blank" style="color: var(--primary); text-decoration: underline; font-weight: 600; display: inline-flex; align-items: center; gap: 4px;">
                            <span class="material-icons-round" style="font-size: 14px;">map</span> ${r.viaggio}
                        </a>` : (r.viaggio || '-')}
                    </span>
                </div>
            </div>

            <!-- Note (opzionale) -->
            ${r.nota ? `
                <div style="margin-top:16px; padding-top:12px; border-top:1px dashed #e2e8f0;">
                    <span class="data-label">Note</span>
                    <p style="font-size:13px; color:#475569; margin-top:4px;">${r.nota}</p>
                </div>
            ` : ''}

            <!-- Azioni: Log GPS e Percorso mappa -->
            <div style="margin-top:16px; padding-top:16px; border-top:1px solid #f1f5f9; display:flex; gap:12px;">
                <button class="btn-primary"
                    onclick="loadAndShowLogs('${r.id}')"
                    style="padding:8px 12px; font-size:12px; height:auto; background:#f8fafc; color:#475569; border:1px solid #e2e8f0; box-shadow:none;">
                    <span class="material-icons-round" style="font-size:16px;">list_alt</span> Log GPS
                </button>
                <button class="btn-primary"
                    onclick="loadAndShowPath('${r.id}')"
                    style="padding:8px 12px; font-size:12px; height:auto; background:#f8fafc; color:#475569; border:1px solid #e2e8f0; box-shadow:none;">
                    <span class="material-icons-round" style="font-size:16px;">map</span> Percorso
                </button>
            </div>
        `;

        container.appendChild(card);
    });
}

/**
 * Rimuove la card di un viaggio dalla DOM in modo animato.
 * Chiamata da confirmDeleteTrip() dopo eliminazione Firestore andata a buon fine.
 *
 * @param {string} tripId - ID del viaggio da rimuovere
 */
export function removeTripCard(tripId) {
    // Cerca la card tramite l'attributo data-trip-id impostato in renderTripList()
    const card = document.querySelector(`.data-card[data-trip-id="${tripId}"]`);
    if (!card) return;

    // Animazione fade-out + slide-up prima della rimozione fisica
    card.style.transition = 'opacity 0.35s ease, transform 0.35s ease, max-height 0.4s ease';
    card.style.overflow   = 'hidden';
    card.style.maxHeight  = card.offsetHeight + 'px';

    requestAnimationFrame(() => {
        card.style.opacity   = '0';
        card.style.transform = 'translateY(-8px)';
        card.style.maxHeight = '0';
        card.style.margin    = '0';
        card.style.padding   = '0';
    });

    // Rimuove dal DOM dopo la transizione
    setTimeout(() => {
        card.remove();

        // Se non ci sono più card, mostra lo stato vuoto
        const container = document.getElementById('listaDati');
        if (container && container.children.length === 0) {
            const emptyState = document.getElementById('emptyState');
            if (emptyState) emptyState.style.display = 'block';
        }
    }, 400);
}
