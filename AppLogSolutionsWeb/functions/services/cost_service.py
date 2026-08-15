import re
from infrastructure.firebase_setup import get_db, get_bucket
from firebase_admin import firestore
from firebase_functions import https_fn
import typing

def handle_elabora_centro_costi(req: https_fn.CallableRequest) -> typing.Any:
    file_path = req.data.get("filePath")
    mese_riferimento = req.data.get("meseRiferimento")
    
    if not file_path or not mese_riferimento:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="Parametri mancanti.")

        # Pass the data payload instead of req because we changed the signature of core_elabora_centro_costi
    return core_elabora_centro_costi(req.data, req.auth.uid)

def core_elabora_centro_costi(req_data: dict, uid: str) -> typing.Any:
    if not uid:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.UNAUTHENTICATED, message="Non autorizzato.")
    
    file_path = req_data.get("filePath")
    mese_riferimento = req_data.get("meseRiferimento")
    
    if not file_path or not mese_riferimento:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="Parametri mancanti.")

    try:
        anno, mese_str = mese_riferimento.split("-")
        mese_index = int(mese_str) - 1
    except Exception:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="Formato mese non valido (atteso YYYY-MM).")

    def estrai_valore_pdf(linea, mese_idx):
        matches = re.findall(r'-?\d{1,3}(?:\.\d{3})*,\d{2}', linea)
        if matches and mese_idx < len(matches):
            try:
                return float(matches[mese_idx].replace('.', '').replace(',', '.'))
            except Exception:
                pass
        return 0.0

    try:
        from pypdf import PdfReader
        import tempfile
        import os
        import traceback

        bucket = get_bucket()
        blob = bucket.blob(file_path)
        if not blob.exists():
            raise Exception(f"File PDF non trovato nello Storage: {file_path}")

        _, tmp_path = tempfile.mkstemp(suffix=".pdf")
        blob.download_to_filename(tmp_path)

        db = get_db()
        batch = db.batch()
        importati = 0
        pagine_totali = 0

        reader = PdfReader(tmp_path)
        pagine_totali = len(reader.pages)
        
        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text: continue
            if "* Totale azienda *" in text: continue

            cf = None
            nome = None
            for line in text.split('\n'):
                m = re.search(r"([A-Z][A-Z\s']+?)\s+([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])\b", line)
                if m:
                    nome = m.group(1).strip()
                    cf = m.group(2)
                    break

            if not cf:
                for line in text.split('\n'):
                    m = re.search(r'\b([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])\b', line)
                    if m:
                        cf = m.group(1)
                        nome = line[:line.find(cf)].strip() or cf
                        break

            if not cf: continue

            costo_totale = 0.0
            costo_ordinario = 0.0
            costo_straordinario = 0.0
            ore_ordinarie = 0.0
            ore_straordinarie = 0.0

            for line in text.split('\n'):
                lu = line.upper()
                if 'C O S T O' in lu and 'T O T A L E' in lu:
                    costo_totale = estrai_valore_pdf(line, mese_index)
                elif 'COSTO TOTALE' in lu:
                    costo_totale = estrai_valore_pdf(line, mese_index)
                elif 'COSTO ORARIO ORDINARIO' in lu:
                    costo_ordinario = estrai_valore_pdf(line, mese_index)
                elif 'COSTO ORARIO STRAORDIN' in lu:
                    costo_straordinario = estrai_valore_pdf(line, mese_index)
                elif 'STRAORDINARI' in lu:
                    ore_straordinarie = estrai_valore_pdf(line, mese_index)
                elif 'ORDINARI' in lu:
                    ore_ordinarie = estrai_valore_pdf(line, mese_index)

            doc_ref = (
                db.collection('clienti').document('DNR')
                .collection('costi_personale').document(mese_riferimento)
                .collection('dipendenti').document(cf)
            )
            batch.set(doc_ref, {
                'nome': nome,
                'codice_fiscale': cf,
                'costo_totale': costo_totale,
                'costo_orario_ordinario': costo_ordinario,
                'costo_orario_straordinario': costo_straordinario,
                'ore_ordinarie': ore_ordinarie,
                'ore_straordinarie': ore_straordinarie,
                'aggiornato_il': firestore.SERVER_TIMESTAMP
            }, merge=True)
            importati += 1

        if importati > 0:
            batch.commit()

        try:
            os.remove(tmp_path)
        except Exception:
            pass
        try:
            blob.delete()
        except Exception:
            pass

        return {"importati": importati, "status": "success", "pagine": pagine_totali}
    
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        print(f"[CC] ERRORE: {type(e).__name__}: {e}\n{trace}")
        return {
            "status": "error",
            "message": f"Errore Python: {type(e).__name__} - {str(e)}"
        }
