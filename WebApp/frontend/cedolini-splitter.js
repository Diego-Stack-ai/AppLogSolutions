import { getApps, initializeApp } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-app.js";
import { getStorage, ref, uploadBytes } from "https://www.gstatic.com/firebasejs/10.8.0/firebase-storage.js";
import { firebaseConfig } from "./firebase-config.js";

const app = getApps().length > 0 ? getApps()[0] : initializeApp(firebaseConfig);

const storage = getStorage(app);

window.handleCedoloneUpload = async function(event) {
    const file = event.target.files[0];
    if (!file) return;

    // Reset input per permettere di ricaricare lo stesso file se si vuole
    event.target.value = '';

    const monthInput = document.getElementById("inputMonth").value;
    if (!monthInput) {
        alert("Per favore, seleziona il Mese di Riferimento prima di dividere il cedolone.");
        return;
    }

    // Modal UI elements
    const modal = document.getElementById("cedoliniLoadingModal");
    const progressText = document.getElementById("cedoliniProgressText");
    const progressBar = document.getElementById("cedoliniProgressBar");
    
    modal.style.display = "flex";
    progressText.innerText = "Lettura del PDF in corso...";
    progressBar.style.width = "10%";

    try {
        const fileBuffer = await file.arrayBuffer();

        // 1. Estrai testo per identificare le pagine (usando pdfjsLib)
        const pdf = await pdfjsLib.getDocument(fileBuffer).promise;
        const totalPages = pdf.numPages;
        
        let generalPages = [];
        let pagesByName = {};

        progressText.innerText = `Analisi testo (0/${totalPages} pagine)...`;

        for (let i = 1; i <= totalPages; i++) {
            const page = await pdf.getPage(i);
            const textContent = await page.getTextContent();
            
            // Ricostruisce le righe di testo unendo gli item con stessa coordinata Y approssimativa
            // oppure semplicemente concatenando le stringhe
            // (L'approccio basato su stringhe funziona se i blocchi di testo mantengono gli spazi)
            // Poichè pdf.js non preserva i newline come un estractor di python, usiamo un fallback:
            // concateniamo gli item con uno spazio e cerchiamo match specifici.
            
            let fullText = textContent.items.map(item => item.str).join(' ');
            
            // Logica alternativa di ricerca nome: 
            // In PDF.js, il nome del dipendente è spesso preceduto da stringhe fisse (come I100 o 100,00 o dipendente)
            // oppure possiamo fare un parsing più attento per righe Y-based.
            let linesMap = {};
            textContent.items.forEach(item => {
                let y = Math.round(item.transform[5]);
                if (!linesMap[y]) linesMap[y] = [];
                linesMap[y].push(item);
            });

            let sortedYs = Object.keys(linesMap).map(Number).sort((a,b) => b - a);
            
            let name = null;
            let foundCnel = false;
            let cnelY = null;
            
            for (let y of sortedYs) {
                // Ordina gli elementi della riga per coordinata X
                let lineItems = linesMap[y].sort((a,b) => a.transform[4] - b.transform[4]);
                let lineStr = lineItems.map(it => it.str).join(' ');
                
                if (lineStr.includes('Cnel')) {
                    foundCnel = true;
                    cnelY = y;
                }
            }
            
            if (foundCnel) {
                for (let y of sortedYs) {
                    // Controlliamo le righe appena sotto Cnel
                    if (y < cnelY && y > cnelY - 40) { 
                        let lineItems = linesMap[y].sort((a,b) => a.transform[4] - b.transform[4]);
                        let lineStr = lineItems.map(it => it.str).join(' ');
                        
                        // Cerca una sequenza di lettere maiuscole alla fine
                        let match = lineStr.match(/([A-Z\s\']{5,})$/);
                        if (match) {
                            name = match[1].trim();
                            // Filtro falsi positivi
                            if (name.includes('CEDOLONE') || name.includes('DIPENDENTE')) name = null;
                        }
                    }
                }
            }
            
            if (name) {
                if (!pagesByName[name]) pagesByName[name] = [];
                pagesByName[name].push(i - 1); // 0-indexed per pdf-lib
            } else {
                generalPages.push(i - 1);
            }

            if (i % 2 === 0) {
                progressText.innerText = `Analisi testo (${i}/${totalPages} pagine)...`;
                progressBar.style.width = `${10 + (40 * i / totalPages)}%`;
            }
        }
        
        console.log("Pages by name:", pagesByName);
        console.log("General pages:", generalPages);

        // 2. Suddividi e carica i PDF
        progressText.innerText = "Preparazione PDF in corso...";
        progressBar.style.width = "50%";

        const pdfDoc = await PDFLib.PDFDocument.load(fileBuffer);
        const folderPath = `cedolini/${monthInput}`;
        let uploadedCount = 0;
        let totalToUpload = Object.keys(pagesByName).length + (generalPages.length > 0 ? 2 : 1); // +1 master, +1 generali

        // Funzione helper per l'upload
        const uploadSinglePdf = async (newPdf, fileName) => {
            const pdfBytes = await newPdf.save();
            const storageRef = ref(storage, `${folderPath}/${fileName}`);
            await uploadBytes(storageRef, pdfBytes);
            uploadedCount++;
            progressBar.style.width = `${50 + (50 * uploadedCount / totalToUpload)}%`;
            progressText.innerText = `Caricamento ${fileName} (${uploadedCount}/${totalToUpload})...`;
        };

        // Upload master originario
        const originalRef = ref(storage, `${folderPath}/Originale_Mese.pdf`);
        await uploadBytes(originalRef, fileBuffer);
        uploadedCount++;

        // Upload per dipendente
        for (const [name, pageIndices] of Object.entries(pagesByName)) {
            const newPdf = await PDFLib.PDFDocument.create();
            const copiedPages = await newPdf.copyPages(pdfDoc, pageIndices);
            copiedPages.forEach((page) => newPdf.addPage(page));
            
            const safeName = name.split(/\s+/).map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join('_') + ".pdf";
            await uploadSinglePdf(newPdf, safeName);
        }

        // Upload Generali
        if (generalPages.length > 0) {
            const newPdf = await PDFLib.PDFDocument.create();
            const copiedPages = await newPdf.copyPages(pdfDoc, generalPages);
            copiedPages.forEach((page) => newPdf.addPage(page));
            await uploadSinglePdf(newPdf, "Generali.pdf");
        }

        modal.style.display = "none";
        alert(`Operazione completata con successo!\nArchiviati in Firebase Storage: ${folderPath}/\n- Originale_Mese.pdf\n- ${Object.keys(pagesByName).length} Cedolini dipendenti` + (generalPages.length > 0 ? `\n- Generali.pdf` : ""));

    } catch (err) {
        console.error(err);
        alert("Si è verificato un errore durante l'elaborazione del file: " + err.message);
        modal.style.display = "none";
    }
};
