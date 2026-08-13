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
    from main import core_processa_job_pdf
    
    return core_processa_job_pdf(job_id, tenant=tenant)
