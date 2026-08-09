import base64
import smtplib
import imaplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def send_and_save_email(smtp_host, smtp_port, imap_host, imap_port, email_user, email_password, to_email, subject, body_text, attachments=[], sender_name=None, smtp_security="auto"):
    # 1. Composizione Email
    msg = MIMEMultipart()
    
    if sender_name:
        from email.utils import formataddr
        msg['From'] = formataddr((sender_name, email_user))
    else:
        msg['From'] = email_user
    msg['To'] = to_email
    msg['Subject'] = subject
    
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
    
    for filename, file_data_base64 in attachments:
        if file_data_base64:
            try:
                file_data = base64.b64decode(file_data_base64)
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(file_data)
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                msg.attach(part)
            except Exception as err_attach:
                logger.error(f"[EMAIL-ATTACH] Errore codifica allegato {filename}: {str(err_attach)}")
            
    # 2. Invio via SMTP
    try:
        # Se esplicitamente 'ssl' oppure se 'auto' su porta 465
        if smtp_security == "ssl" or (smtp_security == "auto" and smtp_port == 465):
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            if smtp_security == "tls" or smtp_security == "auto":
                server.starttls()
            
        server.login(email_user, email_password)
        server.sendmail(email_user, [to_email], msg.as_string())
        server.close()
    except Exception as e:
        logger.error(f"[EMAIL-SMTP] Errore invio SMTP: {str(e)}")
        raise RuntimeError(f"Errore connessione SMTP o credenziali errate: {str(e)}")
        
    # 3. Salvataggio via IMAP nella cartella Posta Inviata (Sent)
    try:
        mail = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=30)
        mail.login(email_user, email_password)
        
        status, folder_list = mail.list()
        sent_folder = None
        if status == 'OK':
            for f in folder_list:
                f_str = f.decode('utf-8')
                # Analizza nome cartella standard
                parts = f_str.split(' "/" ')
                if len(parts) < 2:
                    parts = f_str.split(' "." ')
                
                folder_name = parts[-1].replace('"', '').strip() if len(parts) >= 2 else f_str
                fn_lower = folder_name.lower()
                if "invia" in fn_lower or "sent" in fn_lower or "inviati" in fn_lower:
                    sent_folder = folder_name
                    break
                    
        if not sent_folder:
            sent_folder = "Sent"
            
        mail.append(sent_folder, '\\Seen', imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        mail.logout()
        return True
    except Exception as e:
        logger.error(f"[EMAIL-IMAP] Errore salvataggio IMAP: {str(e)}")
        return False

def handle_invia_email_fattura(data, db):
    azione = data.get("azione")
    
    if azione == "test_smtp":
        test_config = data.get("test_config", {})
        smtp_host = test_config.get("smtp_host")
        smtp_port = test_config.get("smtp_port")
        imap_host = test_config.get("imap_host")
        imap_port = test_config.get("imap_port")
        email_user = test_config.get("email_user")
        email_password = test_config.get("email_password")
        sender_name = test_config.get("sender_name", "")
        smtp_security = test_config.get("smtp_security", "auto")
        
        if not all([smtp_host, smtp_port, imap_host, imap_port, email_user, email_password]):
            return {"status": "errore", "message": "Configurazione email per il test incompleta."}
            
        try:
            subject = "Log Solution - Test Connessione Servizio Email"
            body = "Messaggio di test autogenerato per collaudo SMTP e IMAP."
            
            res_imap = send_and_save_email(
                smtp_host, int(smtp_port), imap_host, int(imap_port),
                email_user, email_password, email_user, subject, body
            )
            
            msg_res = "Connessione SMTP riuscita ed email di test inviata!"
            if not res_imap:
                msg_res += " Nota: Invio riuscito, ma impossibile salvare nella cartella 'Posta Inviata' via IMAP (verifica indirizzo IMAP)."
                
            return {"status": "ok", "message": msg_res}
        except Exception as e:
            return {"status": "errore", "message": str(e)}
            
    elif azione == "invia_fattura":
        destinatario = data.get("destinatario")
        oggetto = data.get("oggetto")
        corpo = data.get("corpo")
        cliente = data.get("cliente")
        periodo = data.get("periodo")
        allegato_pdf = data.get("allegato_pdf")
        allegato_excel = data.get("allegato_excel")
        
        if not destinatario or not oggetto or not corpo:
            return {"status": "errore", "message": "I campi destinatario, oggetto e corpo sono obbligatori."}
            
        try:
            settings_doc = db.collection("config").document("email_settings").get()
            if not settings_doc.exists:
                return {"status": "errore", "message": "Configura prima le credenziali email in Impostazioni."}
                
            d = settings_doc.to_dict()
            smtp_host = d.get("smtp_host")
            smtp_port = d.get("smtp_port")
            imap_host = d.get("imap_host")
            imap_port = d.get("imap_port")
            email_user = d.get("email_user")
            email_password = d.get("email_password")
            sender_name = d.get("sender_name", "")
            smtp_security = d.get("smtp_security", "auto")
            
            if not all([smtp_host, smtp_port, imap_host, imap_port, email_user, email_password]):
                return {"status": "errore", "message": "Configurazione email su Firestore incompleta."}
                
            attachments = []
            if allegato_pdf:
                filename_pdf = f"Fatturazione_{cliente.replace(' ', '_')}_{periodo.replace(' ', '_')}.pdf"
                attachments.append((filename_pdf, allegato_pdf))
            if allegato_excel:
                filename_xls = f"Fatturazione_{cliente.replace(' ', '_')}_{periodo.replace(' ', '_')}.xlsx"
                attachments.append((filename_xls, allegato_excel))
                
            res_imap = send_and_save_email(
                smtp_host, int(smtp_port), imap_host, int(imap_port),
                email_user, email_password, destinatario, oggetto, corpo, attachments
            )
            
            # Scrive registro storico in Firestore
            log_ref = db.collection("clienti").document("DNR").collection("emails_inviate")
            log_ref.add({
                "cliente": cliente,
                "periodo": periodo,
                "destinatario": destinatario,
                "oggetto": oggetto,
                "inviato_da": email_user,
                "ha_pdf": bool(allegato_pdf),
                "ha_excel": bool(allegato_excel),
                "timestamp": datetime.now(),
                "status": "inviato",
                "imap_saved": res_imap
            })
            
            msg_res = "Email inviata con successo!"
            if not res_imap:
                msg_res += " Nota: Invio riuscito, ma impossibile inserire la copia in Posta Inviata del server."
                
            return {"status": "ok", "message": msg_res}
        except Exception as e:
            return {"status": "errore", "message": str(e)}
            
    return {"status": "errore", "message": "Azione non riconosciuta"}
