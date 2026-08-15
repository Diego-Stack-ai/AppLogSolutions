import re
import json
import uuid
import datetime
import time
import io
from io import BytesIO
from firebase_admin import firestore, storage
from firebase_functions import https_fn
from infrastructure.firebase_setup import get_db

from firebase_functions import https_fn

def handle_processa_job_pdf(req: https_fn.CallableRequest):
    # Retrieve job_id and tenant from the request payload
    data = req.data
    job_id = data.get("job_id")
    tenant = data.get("tenant", "DNR")
    
    if not job_id:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT,
            message="job_id mancante."
        )
        
    # Local import to avoid circular dependency since core_processa_job_pdf is still in main.py
        
    return core_processa_job_pdf(job_id, tenant=tenant)


def _estrai_data_luogo(text):
    data = None
    m = DATA_DDT_RE.search(text)
    if m:
        data = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    luogo_m = LUOGO_RE.search(text)
    luogo = luogo_m.group(1).lower() if luogo_m else None
    
    num_m = NUM_DDT_RE.search(text)
    num_ddt = num_m.group(1).replace("/", "-") if num_m else "UNK"
    
    # Estrazione dinamica della zona
    idx_c = text.upper().find("CAUSALE DEL TRASPORTO")
    zona = ""
    if idx_c >= 0:
        sezione = text[idx_c:idx_c+200]
        m_z = CAUSALE_RE.search(sezione)
        if m_z:
            zona = m_z.group(1)[1:5]
            
    return data, luogo, num_ddt, zona

def _estrai_dati_consegna_completi(text: str, codice: str, da_frutta: bool) -> dict:
    """Estrae indirizzo, cap, citta, prov e orari per nuovi clienti."""
    res = {"dest": "", "ind": "", "cap": "", "cit": "", "prov": "", "om": "", "oM": "14:00"}
    if codice.lower() not in text.lower(): return res
    
    idx_l = text.find("Luogo di destinazione")
    if idx_l < 0: return res

    if da_frutta:
        blocco = text[idx_l : idx_l + 650]
        lines = [ln.strip() for ln in blocco.split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            if LUOGO_RE.search(ln):
                if i + 1 < len(lines): res["dest"] = lines[i + 1].strip().title()
                if i + 2 < len(lines): res["ind"] = lines[i + 2].strip().title()
                break
    else:
        idx_causale = text.upper().find("CAUSALE DEL TRASPORTO")
        blocco = text[:idx_causale] if idx_causale > 0 else text[idx_l : idx_l + 900]
        for ln in blocco.split("\n"):
            ln = ln.strip()
            cf_m = re.match(r"^[Cc]\.?[Ff]\.?\s+", ln)
            if cf_m: res["dest"] = ln[cf_m.end():].strip().title()
            else:
                albo_m = re.match(r"^[Aa]lbo\s+", ln, re.I)
                if albo_m: res["ind"] = ln[albo_m.end():].strip().title()

    idx_resp = text.upper().find("RESPONSABILE DEL TRASPORTO")
    blocco_prov = text[idx_resp:] if idx_resp >= 0 else text
    for prov_m in PROVINCIA_RE.finditer(blocco_prov):
        sigla = prov_m.group(1)
        if sigla == "MN" and ("Pomponesco" in blocco_prov[max(0, prov_m.start()-40):prov_m.start()] or "46030" in blocco_prov): continue
        res["prov"] = sigla
        caps = list(CAP_RE.finditer(blocco_prov[:prov_m.start()]))
        if caps:
            res["cap"] = caps[-1].group(1)
            pre = blocco_prov[caps[-1].end() : caps[-1].end() + 60]
            citta_m = re.search(r"\s*[-]?\s*([A-Za-zÀ-ÿ\s'.]+?)\s*\([A-Z]{2}\)", pre)
            if citta_m: res["cit"] = citta_m.group(1).strip().title()
        break
        
    idx_c = text.upper().find("CAUSALE DEL TRASPORTO")
    if idx_c >= 0:
        sezione = text[idx_c:idx_c+150]
        m = CAUSALE_RE.search(sezione)
        if m:
            if m.group(2): res["oM"] = f"{int(m.group(2)):02d}:00"
            if m.group(3):
                s = m.group(3)
                if len(s) == 3: res["om"] = f"{int(s[0]):02d}:{int(s[1:3]):02d}"
    return res

def _normalizza_cella_codice_base(raw: str) -> str:
    righe = [l.strip() for l in str(raw).split('\n') if l.strip() and not l.strip().startswith("Codice:")]
    if not righe: return ""
    codice_base = righe[0]
    if len(righe) > 1 and codice_base.endswith('-'):
        pezzi = righe[1].split()
        if pezzi: codice_base += pezzi[0]
    return codice_base

def _processa_pdf_core_logic(pdf_bytes: bytes, etichetta: str, db_mappati: dict, db_articoli: dict) -> dict:
    from pypdf import PdfReader, PdfWriter
    import pdfplumber
    nuovi_dati = {}
    nuovi_orari = {}
    nuovi_articoli = {}
    deliveries_list = []
    split_files = {}
    visti = {}
    blocchi = {}
    chiave_zona = {}
    
    reader = PdfReader(io.BytesIO(pdf_bytes))
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i in range(len(pdf.pages)):
            pg = pdf.pages[i]
            text = pg.extract_text() or ""
            d, l, num_ddt, zona = _estrai_data_luogo(text)
            if not d or not l:
                print(f"[WARN] Pagina {i+1} saltata. Data estratta: {d or 'MANCANTE'}, Codice estratto: {l or 'MANCANTE'}. Motivo: Elementi identificativi assenti.")
                continue
            
            chiave = (l, d, num_ddt)
            if chiave not in chiave_zona and zona:
                chiave_zona[chiave] = zona
            
            if l not in db_mappati and l not in nuovi_dati:
                info = _estrai_dati_consegna_completi(text, l, etichetta == "FRUTTA")
                info["tipo"] = etichetta
                nuovi_dati[l] = info
            elif l in db_mappati and l not in nuovi_orari:
                # Confronto Orari
                om_mappa = db_mappati[l].get(f"orario_min_{etichetta.lower()}") or ""
                oM_mappa = db_mappati[l].get(f"orario_max_{etichetta.lower()}") or ""
                idx_c = text.upper().find("CAUSALE DEL TRASPORTO")
                if idx_c >= 0:
                    m_c = CAUSALE_RE.search(text[idx_c:idx_c+150])
                    if m_c:
                        oM_ddt = f"{int(m_c.group(2)):02d}:00" if m_c.group(2) else ""
                        om_ddt = ""
                        if m_c.group(3):
                            s = m_c.group(3)
                            if len(s) == 3: om_ddt = f"{int(s[0]):02d}:{int(s[1:3]):02d}"
                            elif len(s) == 4: om_ddt = f"{int(s[:2]):02d}:{int(s[2:]):02d}"
                        
                        if (oM_ddt and oM_ddt != oM_mappa) or (om_ddt and om_ddt != om_mappa):
                            nuovi_orari[l] = {
                                "cliente": db_mappati[l].get("cliente", ""),
                                "citta": db_mappati[l].get("citta", ""),
                                "orario_min_mappa": om_mappa,
                                "orario_max_mappa": oM_mappa,
                                "orario_min_ddt": om_ddt,
                                "orario_max_ddt": oM_ddt,
                                "data_rilevazione": d,
                                "tipo": etichetta
                            }

            # Estrazione Articoli
            try:
                tables = pg.extract_tables()
                if tables:
                    tab = next((t for t in tables if t and len(t) > 1 and "Cod. Articolo" in " ".join(str(c or "") for c in t[0])), None)
                    if tab:
                        for row in tab[1:]:
                            if row and row[0]:
                                cod_base = _normalizza_cella_codice_base(str(row[0]))
                                if cod_base and cod_base not in nuovi_articoli:
                                    if not _is_primary_code(cod_base, db_articoli):
                                        nuovi_articoli[cod_base] = {
                                            "codice_rilevato": cod_base,
                                            "rilevato_il": d,
                                            "ddt_rif": num_ddt,
                                            "cliente_rif": l,
                                            "tipo": etichetta
                                        }
            except Exception as e:
                print(f"[WARN] Errore estrazione articoli pagina {i}: {e}")
                
            chiave = (l, d, num_ddt)
            if chiave not in blocchi: blocchi[chiave] = []
            blocchi[chiave].append((text, reader.pages[i]))
            
            # --- PROTEZIONE RAM (Chunking) ---
            pg.flush_cache()
            if i > 0 and i % 50 == 0:
                gc.collect()
            

    for chiave, lista_pagine in blocchi.items():
        writer = PdfWriter()
        l, d, num_ddt = chiave
        pagine_da_salvare = [p[1] for p in lista_pagine]
        for pg in pagine_da_salvare: writer.add_page(pg)
            
        cnt = visti.get(chiave, 0) + 1
        visti[chiave] = cnt
        fname = f"{l}_{d}_{num_ddt}_{cnt}.pdf" if cnt > 1 else f"{l}_{d}_{num_ddt}.pdf"
        
        out_stream = io.BytesIO()
        writer.write(out_stream)
        out_stream.seek(0)
        split_files[fname] = out_stream
        
        deliveries_list.append({
            "codice_consegna": l,
            "data": d,
            "num_ddt": num_ddt,
            "pdf_name": fname,
            "tipo": etichetta,
            "zona": chiave_zona.get(chiave, "")
        })

    return {
        "split_files": split_files,
        "nuovi_dati": nuovi_dati,
        "nuovi_orari": nuovi_orari,
        "nuovi_articoli": nuovi_articoli,
        "deliveries": deliveries_list
    }

def parse_fascia_oraria(val):
    if val is None or (hasattr(val, "isna") and val.isna()) or val == "":
        return "", ""
    val_str = str(val).strip()
    match_range = re.findall(r'(\d{2}:\d{2})', val_str)
    if len(match_range) == 2:
        return match_range[0], match_range[1]
    match_dopo = re.search(r'(?:Dopo le|dopo le)\s*(\d{2}:\d{2})', val_str)
    if match_dopo:
        return match_dopo.group(1), ""
    match_entro = re.search(r'(?:Entro le|entro le)\s*(\d{2}:\d{2})', val_str)
    if match_entro:
        return "", match_entro.group(1)
    return "", ""

def _genera_pdf_placeholder_grand_chef_io(codice: str, nome: str, ind: str, cit: str, prov: str, note: str, om: str, oM: str, data: str) -> io.BytesIO:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    out_stream = io.BytesIO()
    doc = SimpleDocTemplate(out_stream, pagesize=A4, leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('gc_title', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#0f172a'), spaceAfter=15)
    body_style = ParagraphStyle('gc_body', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#334155'))
    label_style = ParagraphStyle('gc_label', parent=styles['Normal'], fontSize=10, leading=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#0f172a'))
    
    elements = []
    elements.append(Paragraph(f"SCHEDA DI CONSEGNA - CANALE GRAND CHEF", title_style))
    elements.append(Spacer(1, 10))
    
    data_table = [
        [Paragraph("Codice Cliente:", label_style), Paragraph(codice, body_style)],
        [Paragraph("Destinatario:", label_style), Paragraph(nome, body_style)],
        [Paragraph("Indirizzo:", label_style), Paragraph(ind, body_style)],
        [Paragraph("Città:", label_style), Paragraph(f"{cit} ({prov})", body_style)],
        [Paragraph("Data Consegna:", label_style), Paragraph(data, body_style)],
        [Paragraph("Fascia Oraria:", label_style), Paragraph(f"Da {om or '—'} A {oM or '14:00'}", body_style)],
        [Paragraph("Note Consegna:", label_style), Paragraph(note or "Nessuna nota", body_style)]
    ]
    
    t = Table(data_table, colWidths=[120, 380])
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f8fafc')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 40))
    
    elements.append(Paragraph("<b>FIRMA PER RICEVUTA</b>", label_style))
    elements.append(Spacer(1, 15))
    sig_table = [
        [Paragraph("Data: ____________________", body_style), Paragraph("Firma Leggibile: ___________________________", body_style)]
    ]
    t_sig = Table(sig_table, colWidths=[200, 300])
    t_sig.setStyle(TableStyle([
        ('PADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(t_sig)
    
    doc.build(elements)
    out_stream.seek(0)
    return out_stream

def _genera_pdf_placeholder_cattel_io(codice: str, nome: str, ind: str, cit: str, prov: str, note: str, om: str, oM: str, data: str) -> io.BytesIO:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    
    out_stream = io.BytesIO()
    doc = SimpleDocTemplate(out_stream, pagesize=A4, leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle('cattel_title', parent=styles['Heading1'], fontSize=16, leading=20, textColor=colors.HexColor('#0f172a'), spaceAfter=15)
    body_style = ParagraphStyle('cattel_body', parent=styles['Normal'], fontSize=10, leading=14, textColor=colors.HexColor('#334155'))
    label_style = ParagraphStyle('cattel_label', parent=styles['Normal'], fontSize=10, leading=14, fontName='Helvetica-Bold', textColor=colors.HexColor('#0f172a'))
    
    elements = []
    elements.append(Paragraph(f"SCHEDA DI CONSEGNA - CANALE CATTEL", title_style))
    elements.append(Spacer(1, 10))
    
    data_table = [
        [Paragraph("Codice Cliente:", label_style), Paragraph(codice, body_style)],
        [Paragraph("Destinatario:", label_style), Paragraph(nome, body_style)],
        [Paragraph("Indirizzo:", label_style), Paragraph(ind, body_style)],
        [Paragraph("Città:", label_style), Paragraph(f"{cit} ({prov})", body_style)],
        [Paragraph("Data Consegna:", label_style), Paragraph(data, body_style)],
        [Paragraph("Fascia Oraria:", label_style), Paragraph(f"Da {om or '—'} A {oM or '14:00'}", body_style)],
        [Paragraph("Note Consegna:", label_style), Paragraph(note or "Nessuna nota", body_style)]
    ]
    
    t = Table(data_table, colWidths=[120, 380])
    t.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f8fafc')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 40))
    
    elements.append(Paragraph("<b>FIRMA PER RICEVUTA</b>", label_style))
    elements.append(Spacer(1, 15))
    sig_table = [
        [Paragraph("Data: ____________________", body_style), Paragraph("Firma Leggibile: ___________________________", body_style)]
    ]
    t_sig = Table(sig_table, colWidths=[200, 300])
    t_sig.setStyle(TableStyle([
        ('PADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(t_sig)
    
    doc.build(elements)
    out_stream.seek(0)
    return out_stream

def _processa_excel_dac_core_logic(excel_bytes: bytes, db_mappati: dict, data_consegna: str, job_id: str, tenant_name: str) -> dict:
    import pandas as pd
    
    nuovi_dati = {}
    split_files = {}
    deliveries_list = []
    
    f_io = io.BytesIO(excel_bytes)
    df = pd.read_excel(f_io, sheet_name=0)
    df_clean = df.dropna(how='all')
    
    def _str_val(val):
        return str(val).strip() if pd.notna(val) and str(val).strip() not in ("", "nan") else ""

    for idx, row in df_clean.iterrows():
        # Map columns by name if possible, otherwise skip
        if 'Codice' not in row:
            continue
            
        codice = clean_client_code(_str_val(row.get('Codice', '')))
        if not codice:
            continue
            
        ragione_sociale = _str_val(row.get('Ragione Sociale', ''))
        indirizzo = _str_val(row.get('Indirizzo', ''))
        cap = _str_val(row.get('CAP', ''))
        localita = _str_val(row.get('Città', ''))
        provincia = _str_val(row.get('Provincia', ''))
        
        # Parse orari
        ap_mat = _str_val(row.get('Apertura Mattina', ''))
        ch_mat = _str_val(row.get('Chiusura Mattina', ''))
        ap_pom = _str_val(row.get('Apertura Pomeriggio', ''))
        ch_pom = _str_val(row.get('Chiusura Pomeriggio', ''))
        
        orario_min = ap_mat if ap_mat else (ap_pom if ap_pom else "")
        orario_max = ch_pom if ch_pom else (ch_mat if ch_mat else "")
        if not orario_max and (orario_min != ""):
            orario_max = "18:00" # fallback
            
        note = _str_val(row.get('Giorno Chiusura', ''))
        colli = _str_val(row.get('Colli', ''))
        peso_kg = _str_val(row.get('Peso', ''))
        
        codice_l = codice.lower()
        # Se è il magazzino, va comunque aggiunto come "consegna" per creare il giro
        if codice_l not in db_mappati:
            nuovi_dati[codice] = {
                "dest": ragione_sociale,
                "ind": indirizzo,
                "cap": cap,
                "cit": localita,
                "prov": provincia,
                "om": orario_min,
                "oM": orario_max,
                "tipo": tenant_name
            }
        else:
            # Crea placeholder PDF
            fname = f"{codice}_{data_consegna}.pdf"
            pdf_io = _genera_pdf_placeholder_grand_chef_io(
                codice, ragione_sociale, indirizzo,
                localita, provincia, note, orario_min, orario_max, data_consegna
            )
            split_files[fname] = pdf_io
            
            deliveries_list.append({
                "codice_consegna": codice,
                "data": data_consegna,
                "num_ddt": f"{tenant_name}_{codice}",
                "ragsoc": ragione_sociale,
                "ind": indirizzo,
                "loc": localita,
                "prv": provincia,
                "cap": cap,
                "colli": colli,
                "peso": peso_kg,
                "bancali": "",
                "note": note,
                "orari": f"{orario_min} - {orario_max}" if (orario_min or orario_max) else "",
                "om": orario_min,
                "oM": orario_max,
                "pdf_url": "", 
                "storage_path": f"split_ddt/{data_consegna}/{tenant_name}/{fname}",
                "job_id": job_id,
                "tipo": tenant_name,
                "zona": f"{tenant_name}_{job_id}"
            })
            
    return {
        "split_files": split_files,
        "nuovi_dati": nuovi_dati,
        "nuovi_orari": {},
        "nuovi_articoli": {},
        "deliveries": deliveries_list
    }

def _processa_excel_cattel_core_logic(excel_bytes: bytes, db_mappati: dict, data_consegna: str, job_id: str, tenant_name: str) -> dict:
    import pandas as pd
    import re
    
    nuovi_dati = {}
    split_files = {}
    deliveries_list = []
    
    f_io = io.BytesIO(excel_bytes)
    xl = pd.ExcelFile(f_io)
    
    def normalize_address(addr):
        if not addr:
            return ""
        addr = str(addr).lower().strip()
        addr = re.sub(r'\(\s*[a-zA-Z]{2}\s*\)', '', addr)
        addr = re.sub(r'\b\d{5}\b', '', addr)
        addr = re.sub(r'[^\w\s]', '', addr)
        addr = re.sub(r'\b(via|viale|piazza|corso|localita|loc|strada|vicolo|lato|piaz)\b', '', addr)
        return " ".join(addr.split())

    indirizzi_master = {}
    for code_db, cust in db_mappati.items():
        addr_raw = cust.get("ind") or cust.get("indirizzo") or ""
        norm_addr = normalize_address(addr_raw)
        if norm_addr and cust.get("lat") and cust.get("lon"):
            indirizzi_master[norm_addr] = cust

    print(f"[Parser Cattel] Inizio estrazione dai fogli ({xl.sheet_names}) ignorando 'Riepilogo'.")
    
    for s_name in xl.sheet_names:
        if s_name.lower() == "riepilogo":
            continue
            
        targa = s_name.strip()
        df = xl.parse(s_name, header=None)
        
        # Estrarre autista dalla cella C2 (Riga 2, Colonna 3, quindi indice row 1, col 2)
        autista = ""
        if len(df) > 1 and len(df.columns) > 2:
            autista_val = df.iloc[1, 2]
            autista = str(autista_val).strip() if pd.notna(autista_val) else ""
            
        # L'intestazione è alla riga 4 (indice 3). I dati partono dalla riga 6 (indice 5).
        # L'ultima riga è il magazzino d'arrivo, quindi ci fermiamo a len(df) - 1.
        if len(df) <= 5:
            continue
            
        last_idx = len(df) - 1
        
        for i in range(5, last_idx):
            row = df.iloc[i]
            
            codice = clean_client_code(row.iloc[0]) if len(row) > 0 else ""
            if not codice or str(codice).lower() == 'nan' or str(codice).upper() == 'SOMMACAMPAGNA':
                continue
                
            ragione_sociale = str(row.iloc[1]).strip() if len(row) > 1 and pd.notna(row.iloc[1]) else ""
            indirizzo = str(row.iloc[2]).strip() if len(row) > 2 and pd.notna(row.iloc[2]) else ""
            colli = str(row.iloc[9]).strip() if len(row) > 9 and pd.notna(row.iloc[9]) else ""
            
            # Estrazione località e provincia dall'indirizzo (se presenti)
            localita = ""
            provincia = ""
            if indirizzo:
                m_prov = re.search(r'\(([^)]+)\)', indirizzo)
                if m_prov:
                    provincia = m_prov.group(1).strip().upper()
                parts = indirizzo.split(',')
                if len(parts) > 1:
                    cit_part = parts[-1].strip()
                    if re.search(r'[a-zA-Z]{2,}', cit_part):
                        cit_part = re.sub(r'\(.*?\)', '', cit_part).strip()
                        cit_part = re.sub(r'\d{5}', '', cit_part).strip()
                        localita = cit_part
                        
            orario_min = "08:00"
            orario_max = "14:00"
            note = ""
            
            codice_l = codice.lower()
            if codice_l not in db_mappati:
                if codice not in nuovi_dati:
                    norm_new_addr = normalize_address(indirizzo)
                    match_found = False
                    matched_cust = None
                    if norm_new_addr and norm_new_addr in indirizzi_master:
                        matched_cust = indirizzi_master[norm_new_addr]
                        match_found = True
                        
                    if match_found and matched_cust:
                        nuovi_dati[codice] = {
                            "dest": ragione_sociale,
                            "ind": indirizzo,
                            "cap": matched_cust.get("cap") or "",
                            "cit": matched_cust.get("cit") or matched_cust.get("citta") or localita,
                            "prov": matched_cust.get("prov") or matched_cust.get("provincia") or provincia,
                            "om": matched_cust.get("om") or orario_min,
                            "oM": matched_cust.get("oM") or orario_max,
                            "tipo": tenant_name,
                            "lat": matched_cust.get("lat"),
                            "lon": matched_cust.get("lon"),
                            "stato_suggerito": "giallo",
                            "matched_name": matched_cust.get("cliente") or matched_cust.get("nome_consegna") or "",
                            "matched_brand": matched_cust.get("tipologia_grado") or "MASTER"
                        }
                    else:
                        nuovi_dati[codice] = {
                            "dest": ragione_sociale,
                            "ind": indirizzo,
                            "cap": "",
                            "cit": localita,
                            "prov": provincia,
                            "om": orario_min,
                            "oM": orario_max,
                            "tipo": tenant_name,
                            "stato_suggerito": "rosso",
                            "codice_frutta": codice,
                            "codice_latte": "p00000"
                        }
            else:
                cust_d = db_mappati[codice_l]
                fname = f"{codice}_{data_consegna}.pdf"
                pdf_io = _genera_pdf_placeholder_cattel_io(
                    codice,
                    cust_d.get("cliente") or cust_d.get("nome_consegna") or ragione_sociale,
                    cust_d.get("ind") or cust_d.get("indirizzo") or indirizzo,
                    cust_d.get("cit") or cust_d.get("citta") or localita,
                    cust_d.get("prov") or cust_d.get("provincia") or provincia,
                    cust_d.get("note") or note,
                    cust_d.get("om") or orario_min,
                    cust_d.get("oM") or orario_max,
                    data_consegna
                )
                split_files[fname] = pdf_io
                
                # Zona logistica include solo targa per Cattel (rimosso autista come richiesto)
                zona_cod = f"{tenant_name}_{targa}"
                
                deliveries_list.append({
                    "codice_consegna": codice,
                    "data": data_consegna,
                    "num_ddt": f"{tenant_name}_{codice}",
                    "pdf_name": fname,
                    "tipo": tenant_name,
                    "zona": zona_cod,
                    "gc_colli": colli,
                    "gc_peso_kg": "",
                    "gc_num_cartone": "",
                    "cattel_zona_viaggio": targa,
                    "autista": autista
                })
                
    return {
        "split_files": split_files,
        "nuovi_dati": nuovi_dati,
        "nuovi_orari": {},
        "nuovi_articoli": {},
        "deliveries": deliveries_list
    }

def _processa_excel_chef_core_logic(excel_bytes: bytes, db_mappati: dict, data_consegna: str, job_id: str, tenant_name: str) -> dict:
    import pandas as pd
    
    nuovi_dati = {}
    split_files = {}
    deliveries_list = []
    
    f_io = io.BytesIO(excel_bytes)
    df = pd.read_excel(f_io, sheet_name=0, header=None)
    df_clean = df.dropna(how='all')
    
    header_row_idx = None
    for idx, row in df_clean.iterrows():
        row_vals = [str(val).strip().lower() for val in row.values if pd.notna(val)]
        if any('ragione sociale' in rv for rv in row_vals) or any('codice' in rv for rv in row_vals):
            header_row_idx = idx
            break
            
    if header_row_idx is not None:
        df_data = df_clean.loc[header_row_idx + 1:]
        
        def _cell(row_data, col_idx):
            return str(row_data.iloc[col_idx]).strip() if len(row_data) > col_idx and pd.notna(row_data.iloc[col_idx]) and str(row_data.iloc[col_idx]).strip() not in ("", "nan") else ""
            
        for _, row in df_data.iterrows():
            if str(row.iloc[0]).lower().strip() == 'totale':
                continue
                
            codice = clean_client_code(row.iloc[0])
            if not codice:
                continue
                
            ragione_sociale = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ""
            indirizzo = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else ""
            localita = str(row.iloc[7]).strip() if pd.notna(row.iloc[7]) else ""
            provincia = str(row.iloc[8]).strip() if pd.notna(row.iloc[8]) else ""
            note = str(row.iloc[14]).strip() if len(row) > 14 and pd.notna(row.iloc[14]) else ""
            fascia = str(row.iloc[15]).strip() if len(row) > 15 and pd.notna(row.iloc[15]) else ""
            
            orario_min, orario_max = parse_fascia_oraria(fascia)
            if not orario_min and not orario_max and note:
                orario_min, orario_max = parse_fascia_oraria(note)
                
            if not orario_max:
                orario_max = "14:00"
                
            colli = _cell(row, 9)
            peso_kg = _cell(row, 10)
            num_cartone = _cell(row, 13)
                
            codice_l = codice.lower()
            if codice_l not in db_mappati:
                nuovi_dati[codice] = {
                    "dest": ragione_sociale,
                    "ind": indirizzo,
                    "cap": "",
                    "cit": localita,
                    "prov": provincia,
                    "om": orario_min,
                    "oM": orario_max,
                    "tipo": tenant_name
                }
            else:
                fname = f"{codice}_{data_consegna}.pdf"
                pdf_io = _genera_pdf_placeholder_grand_chef_io(
                    codice, ragione_sociale, indirizzo,
                    localita, provincia, note, orario_min, orario_max, data_consegna
                )
                split_files[fname] = pdf_io
                
                deliveries_list.append({
                    "codice_consegna": codice,
                    "data": data_consegna,
                    "num_ddt": f"{tenant_name}_{codice}",
                    "pdf_name": fname,
                    "tipo": tenant_name,
                    "zona": f"{tenant_name}_{job_id}",
                    "gc_colli": colli,
                    "gc_peso_kg": peso_kg,
                    "gc_num_cartone": num_cartone,
                    "orario_min": orario_min,
                    "orario_max": orario_max,
                    "note": note
                })
                
    return {
        "split_files": split_files,
        "nuovi_dati": nuovi_dati,
        "nuovi_orari": {},
        "nuovi_articoli": {},
        "deliveries": deliveries_list
    }

def enrich_delivery_with_canonical_schema(
    legacy_delivery,
    tenant,
    competenza,
    job_id,
    delivery_index,
    data_elab,
    etichetta
):
    enriched = dict(legacy_delivery)
    
    # Costruisci l'identificativo univoco
    base_id = f"{tenant}_{competenza}_{job_id}_{delivery_index:04d}"
    sanitized_id = re.sub(r'[^a-zA-Z0-9_\-]', '', base_id)
    
    # Document storage path
    pdf_name = legacy_delivery.get("pdf_name", "")
    storage_path = legacy_delivery.get("storage_path", "")
    if not storage_path and pdf_name:
        storage_path = f"split_ddt/{data_elab}/{etichetta}/{pdf_name}"
        
    # Logistics handling
    colli = legacy_delivery.get("colli")
    if colli in (None, ""):
        colli = legacy_delivery.get("gc_colli")
        
    peso_kg = legacy_delivery.get("peso")
    if peso_kg in (None, ""):
        peso_kg = legacy_delivery.get("gc_peso_kg")
        
    # Time windows
    time_windows = []
    start = legacy_delivery.get("orario_min") or legacy_delivery.get("om") or ""
    end = legacy_delivery.get("orario_max") or legacy_delivery.get("oM") or ""
    if start or end:
        time_windows.append({
            "start": start,
            "end": end
        })
        
    # Aggiungi campi canonici
    enriched["schema_version"] = "1.0"
    enriched["delivery_id"] = sanitized_id
    
    enriched["source"] = {
        "tenant": tenant,
        "competenza": competenza,
        "job_id": job_id,
        "parser_type": etichetta
    }
    
    enriched["customer"] = {
        "codice_originale": legacy_delivery.get("codice_consegna", ""),
        "ragione_sociale": legacy_delivery.get("ragsoc", ""),
        "indirizzo": legacy_delivery.get("ind", ""),
        "cap": legacy_delivery.get("cap", ""),
        "citta": legacy_delivery.get("loc", ""),
        "provincia": legacy_delivery.get("prv", "")
    }
    
    enriched["document"] = {
        "numero_ddt": legacy_delivery.get("num_ddt", ""),
        "data": legacy_delivery.get("data", data_elab),
        "pdf_name": pdf_name,
        "storage_path": storage_path
    }
    
    enriched["logistics"] = {
        "colli": colli,
        "peso_kg": peso_kg,
        "cartoni": legacy_delivery.get("gc_num_cartone"),
        "bancali": legacy_delivery.get("bancali"),
        "targa": legacy_delivery.get("cattel_zona_viaggio", ""),
        "autista": legacy_delivery.get("autista", ""),
        "zona_origine": legacy_delivery.get("zona", "")
    }
    
    enriched["time_windows"] = time_windows
    
    return enriched

def core_processa_job_pdf(job_id, tenant="DNR"):
    start_time = time.time()
    db = get_db()
    job_ref = db.collection('clienti').document(tenant).collection('processing_jobs').document(job_id)
    
    @firestore.transactional
    def acquire_job(transaction, ref):
        snapshot = ref.get(transaction=transaction)
        if not snapshot.exists:
            return None
        doc_data = snapshot.to_dict()
        if doc_data.get("status") != "uploaded":
            return doc_data
        transaction.update(ref, {
            "status": "processing",
            "updated_at": firestore.SERVER_TIMESTAMP,
            "started_at": firestore.SERVER_TIMESTAMP
        })
        return doc_data

    transaction = db.transaction()
    data = acquire_job(transaction, job_ref)
    
    if not data: return {"status": "errore", "message": "Job non trovato"}
    if data.get("status") != "uploaded": return {"status": "errore", "message": "Stato job non valido per elaborazione"}
    data_lavoro_forzata = data.get('data_lavoro')
    
    competenza = data.get("competenza") or data.get("type", "FRUTTA").upper()
    if competenza in ("GRAND_CHEF", "GRAND CHEF", "GRAN CHEF"):
        competenza = "GRAN_CHEF"
    print(f"[INFO] Elaborazione job {job_id} con competenza {competenza}")
    
    try:
        bucket = storage.bucket(name=BUCKET_NAME)
        path = data.get("storage_path")
        etichetta = data.get("type", "FRUTTA").upper()
        is_excel = data.get("is_excel", False) or etichetta == "GRAND_CHEF"
        
        # 1. Carica Mappatura dal tenant corretto per isolare i dati
        db_mappati = {}
        clienti_ref = db.collection('clienti').document(tenant).collection('raccolta clienti')
        for doc in clienti_ref.stream():
            d = doc.to_dict()
            cf = str(d.get('codice_frutta') or '').strip().lower()
            cl = str(d.get('codice_latte') or '').strip().lower()
            if cf and cf != 'p00000' and cf != 'nan': db_mappati[cf] = d
            if cl and cl != 'p00000' and cl != 'nan': db_mappati[cl] = d
        
        articoli_ref = db.collection('clienti').document(tenant).collection('codici articoli')
        db_articoli = {doc.id: doc.to_dict() for doc in articoli_ref.stream()}
        
        # 2. Download
        blob = bucket.blob(path)
        file_bytes = blob.download_as_bytes()
        
        # 3. Processing
        if is_excel:
            data_elab = data_lavoro_forzata or datetime.now().strftime("%d-%m-%Y")
            if competenza == "CATTEL":
                risultato = _processa_excel_cattel_core_logic(file_bytes, db_mappati, data_elab, job_id, competenza)
            elif competenza == "DAC":
                risultato = _processa_excel_dac_core_logic(file_bytes, db_mappati, data_elab, job_id, competenza)
            else:
                risultato = _processa_excel_chef_core_logic(file_bytes, db_mappati, data_elab, job_id, competenza)
        else:
            risultato = _processa_pdf_core_logic(file_bytes, etichetta, db_mappati, db_articoli)
        
        split_files = risultato["split_files"]
        deliveries = risultato["deliveries"]
        
        deliveries = [
            enrich_delivery_with_canonical_schema(
                legacy_delivery=delivery,
                tenant=tenant,
                competenza=competenza,
                job_id=job_id,
                delivery_index=index,
                data_elab=data_elab,
                etichetta=etichetta
            )
            for index, delivery in enumerate(deliveries)
        ]
        
        nuovi_dati = risultato["nuovi_dati"]
        nuovi_orari = risultato.get("nuovi_orari", {})
        nuovi_articoli = risultato.get("nuovi_articoli", {})
        
        # 5. Salvataggio nuovi dati dinamici nel tenant corretto
        for l, info in nuovi_dati.items():
            db.collection('clienti').document(tenant).collection('nuovi codici consegna').document(l).set(info, merge=True)
            
        for l, info in nuovi_orari.items():
            db.collection('clienti').document(tenant).collection('nuovi orari mancanti').document(l).set(info, merge=True)
            
        for c, info in nuovi_articoli.items():
            doc_id = str(c).replace('/', '-').replace(' ', '_')
            db.collection('clienti').document(tenant).collection('nuovi articoli rilevati').document(doc_id).set(info, merge=True)
            
        if not deliveries:
            job_ref.update({
                "status": "completed", 
                "completed_at": firestore.SERVER_TIMESTAMP,
                "message": "Nessun DDT trovato (Clienti da mappare?)",
                "nuovi_clienti": len(nuovi_dati),
                "nuovi_articoli": len(nuovi_articoli),
                "nuovi_orari": len(nuovi_orari),
                "nuovi_clienti_list": list(nuovi_dati.keys()),
                "nuovi_articoli_list": list(nuovi_articoli.keys()),
                "nuovi_orari_list": list(nuovi_orari.keys()),
                "updated_at": firestore.SERVER_TIMESTAMP
            })
            return {"status": "ok", "pdf_generati": 0}
            
        # Applica il campo competenza a ciascun DDT
        for ddt in deliveries:
            ddt["competenza"] = competenza

        # Se l'utente ha scelto una data nel calendario, ha la precedenza
        if data_lavoro_forzata:
            data_elab = data_lavoro_forzata
            print(f"[INFO] Uso data forzata dal calendario: {data_elab}")
        else:
            data_elab = deliveries[0]["data"]
            print(f"[INFO] Uso data estratta dal file: {data_elab}")
        
        # --- PULIZIA PREVENTIVA RIMOSSA (Gestita centralmente al caricamento) ---
        print(f"[INFO] Elaborazione file per {data_elab} - {etichetta}")

        # 4. Upload split e salvataggio DDT
        for fname, out_stream in split_files.items():
            out_path = f"split_ddt/{data_elab}/{etichetta}/{fname}"
            split_blob = bucket.blob(out_path)
            if hasattr(out_stream, "seek"):
                out_stream.seek(0)
            split_blob.upload_from_file(out_stream, content_type='application/pdf')

            
        # 6. Salvataggio Metadati Temporanei (per Step 2)
        metadata_ddt = {
            "data_elab": data_elab,
            "tipo": etichetta,
            "competenza": competenza,
            "deliveries": deliveries
        }
        meta_path = f"split_ddt/{data_elab}/{etichetta}/ddt_estratti_{job_id}.json"
        bucket.blob(meta_path).upload_from_string(
            json.dumps(metadata_ddt, indent=2), 
            content_type='application/json'
        )
        
        elapsed = time.time() - start_time
        job_ref.update({
            "status": "completed",
            "completed_at": firestore.SERVER_TIMESTAMP,
            "data_rilevata": data_elab,
            "meta_path_json": meta_path,
            "pdf_generati": len(split_files),
            "nuovi_clienti": len(nuovi_dati),
            "nuovi_articoli": len(nuovi_articoli),
            "nuovi_orari": len(nuovi_orari),
            "nuovi_clienti_list": list(nuovi_dati.keys()),
            "nuovi_articoli_list": list(nuovi_articoli.keys()),
            "nuovi_orari_list": list(nuovi_orari.keys()),
            "tempo_sec": round(elapsed, 2),
            "updated_at": firestore.SERVER_TIMESTAMP
        })
        
        return {"status": "ok", "pdf_generati": len(split_files), "tempo_sec": round(elapsed, 2)}
        
    except Exception as e:
        job_ref.update({"status": "error", "error_message": str(e), "updated_at": firestore.SERVER_TIMESTAMP, "failed_at": firestore.SERVER_TIMESTAMP})
        return {"status": "errore", "message": str(e)}