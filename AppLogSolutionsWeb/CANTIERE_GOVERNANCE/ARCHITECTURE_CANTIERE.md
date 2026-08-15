# AppLogSolutionsWeb — Architecture Cantiere

## DOCUMENT STATUS
DOCUMENT_SCOPE = CANTIERE ONLY
ARCHITECTURE_STATUS = CURRENT VERIFIED SNAPSHOT
PRODUCTION_EQUIVALENCE = NOT ASSUMED
PRODUCTION_READY = FALSE

## 1. Scope Cantiere
This architecture applies EXCLUSIVELY to the `cantiere` branch and `log-solutions-cantiere` project.
PRODUZIONE = READ ONLY
MULETTO = NO TOUCH
SVILUPPO LEGACY = DISMESSO

## 2. Principi Architetturali
- Modularization of business logic into `services/`.
- `main.py` acts strictly as an HTTP/Firebase Cloud Functions gateway.
- `core/` contains shared utilities.
- `infrastructure/` handles Firebase init and third-party setups.

## 3. Backend Reale
- **Services (15)**: admin_service.py, billing_service.py, cleanup_service.py, cost_service.py, driver_service.py, email_service.py, history_service.py, map_service.py, monitoring_service.py, operations_service.py, pdf_service.py, reporting_service.py, routing_service.py, tenant_service.py, traffic_service.py
- **Core Modules**: utils.py
- **Infrastructure Modules**: firebase_setup.py, google_maps_api.py

## 4. Main.py
MAIN_TOTAL_LINES = 979
MAIN_BUSINESS_LOGIC_RESIDUAL = TRUE

PRIMARY ROLE:
Firebase Gateway / Entry Point / Composition Root

MA conserva ancora 6 helper/residui:
1. get_tenant_from_viaggio_id
2. _cerca_cliente_cloud
3. _salva_nuovo_cliente_tripla_chiave
4. _ordina_job_ids_gc
5. _genera_url_storage_token
6. get_tenant_from_cz

Classificazione: CURRENT MIGRATION RESIDUE (gap rispetto al TARGET di un main.py gateway sottile senza helper di dominio/residui).

## 5. Cloud Functions
FUNCTION_COUNT_REAL = 32

## 6. PDF Service
PDF_SERVICE_STATUS = FULLY_RESOLVED STATICALLY
PDF_UNRESOLVED_SYMBOLS = 0
(STATICALLY RESOLVED ≠ FULL END-TO-END VALIDATION)

## 7. Service Status
operations_service: static dependency status resolved
routing_service: static dependency status resolved
map_service: static dependency status resolved
reporting_service: static dependency status resolved

## 8. Current Architecture
Frontend
→ 32 Cloud Functions
→ main.py gateway
→ 15 services
→ core/infrastructure
→ Firestore/Storage/API
(main.py contiene ancora 6 helper/residui)

## 9. Target Architecture
Frontend
→ Cloud Functions
→ main.py thin gateway
→ services
→ core/infrastructure
(con zero business/helper residue in main.py)

## 10. Known Gaps Reali
A. 6 helper/residui ancora presenti in main.py
B. Cantiere ancora in fase di collaudo funzionale
C. necessità di completare test end-to-end delle 32 Functions
D. necessità di validare i 15 service nei flussi reali
E. Produzione non ancora allineata né sostituita

RESIDUAL_WRAPPERS = NONE
MAP_KNOWN_EDGE_CASES = NO_EVIDENCE
REPORTING_KNOWN_EDGE_CASES = NO_EVIDENCE
