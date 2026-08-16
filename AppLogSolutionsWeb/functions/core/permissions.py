from firebase_functions import https_fn
from infrastructure.firebase_setup import get_db

def require_page_permission(req: https_fn.CallableRequest, page_key: str, required_permission: str = "write") -> None:
    """
    Verifica se l'utente chiamante ha il permesso specificato per la pagina specificata.
    Amministratore bypassa il controllo dei permessi.
    Solleva HttpsError (UNAUTHENTICATED o PERMISSION_DENIED) in caso di esito negativo.
    """
    if getattr(req, 'auth', None) is None or getattr(req.auth, 'uid', None) is None:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
            message="Non autorizzato."
        )
    
    uid = req.auth.uid
    db = get_db()
    
    # 1. Recupera ruolo utente
    caller_doc = db.collection("dipendenti").document(uid).get()
    if not caller_doc.exists:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Profilo utente mancante."
        )
        
    caller_data = caller_doc.to_dict()
    ruolo = caller_data.get("ruolo")
    if not ruolo:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Ruolo utente mancante."
        )
        
    if ruolo == "amministratore":
        return
        
    # 2. Recupera config permessi
    config_doc = db.collection("config").document("permessi_dashboard").get()
    if not config_doc.exists:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Configurazione permessi mancante."
        )
        
    config_data = config_doc.to_dict()
    page_perms = config_data.get(page_key, {})
    user_perm = page_perms.get(ruolo)
    
    if user_perm != required_permission:
        raise https_fn.HttpsError(
            code=https_fn.FunctionsErrorCode.PERMISSION_DENIED,
            message="Permesso negato per questa operazione."
        )
