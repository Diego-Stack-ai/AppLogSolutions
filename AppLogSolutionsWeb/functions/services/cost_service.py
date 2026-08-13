from firebase_functions import https_fn
import typing

def handle_elabora_centro_costi(req: https_fn.CallableRequest) -> typing.Any:
    file_path = req.data.get("filePath")
    mese_riferimento = req.data.get("meseRiferimento")
    
    if not file_path or not mese_riferimento:
        raise https_fn.HttpsError(code=https_fn.FunctionsErrorCode.INVALID_ARGUMENT, message="Parametri mancanti.")

    from main import core_elabora_centro_costi
    # Pass the data payload instead of req because we changed the signature of core_elabora_centro_costi
    return core_elabora_centro_costi(req.data, req.auth.uid)
