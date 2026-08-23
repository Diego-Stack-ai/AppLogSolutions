"""
Fixture Locali per i Tenant Storici (DNR, CATTEL, GRAN_CHEF, BAUER).
REF-001 FASE 2A
"""

from typing import Dict, List, Any
from .validators import compute_profile_checksum

# --- FIXTURES TENANT ---
FIXTURE_TENANTS: List[Dict[str, Any]] = [
    {
        "tenantId": "DNR",
        "displayName": "DNR Distribuzione",
        "enabled": True,
        "firestoreFolderLegacy": "DNR",
        "legacyAliases": ["DNR_LATTE", "DNR_FRUTTA"],
        "customerCodeFields": {
            "fruttaCodeKey": "codice_frutta",
            "latteCodeKey": "codice_latte"
        },
        "features": { "supportsMixedTrips": True },
        "schemaVersion": "1.0",
        "createdAt": "2026-01-01T00:00:00Z",
        "createdBy": "system_init",
        "updatedAt": "2026-07-26T10:00:00Z",
        "updatedBy": "system_init"
    },
    {
        "tenantId": "CATTEL",
        "displayName": "Cattel Ristorazione",
        "enabled": True,
        "firestoreFolderLegacy": "CATTEL",
        "legacyAliases": ["CATTEL_SOMMA"],
        "customerCodeFields": { "primaryCodeKey": "codice_cliente" },
        "features": { "supportsMixedTrips": True },
        "schemaVersion": "1.0",
        "createdAt": "2026-01-01T00:00:00Z",
        "createdBy": "system_init",
        "updatedAt": "2026-07-26T10:00:00Z",
        "updatedBy": "system_init"
    },
    {
        "tenantId": "GRAN_CHEF",
        "displayName": "Gran Chef",
        "enabled": True,
        "firestoreFolderLegacy": "GRAN CHEF",
        "legacyAliases": ["GRAND_CHEF", "GRAND CHEF", "GRAN CHEF", "GRANCHEF"],
        "customerCodeFields": { "primaryCodeKey": "codice_cliente" },
        "features": { "supportsMixedTrips": True },
        "schemaVersion": "1.0",
        "createdAt": "2026-01-01T00:00:00Z",
        "createdBy": "system_init",
        "updatedAt": "2026-07-26T10:00:00Z",
        "updatedBy": "system_init"
    },
    {
        "tenantId": "BAUER",
        "displayName": "Bauer Spa",
        "enabled": True,
        "firestoreFolderLegacy": "BAUER",
        "legacyAliases": ["BAUER_LOGISTICA"],
        "customerCodeFields": { "primaryCodeKey": "codice_cliente" },
        "features": { "supportsMixedTrips": True },
        "schemaVersion": "1.0",
        "createdAt": "2026-01-01T00:00:00Z",
        "createdBy": "system_init",
        "updatedAt": "2026-07-26T10:00:00Z",
        "updatedBy": "system_init"
    }
]

# --- FIXTURES CANALI ---
FIXTURE_CHANNELS: List[Dict[str, Any]] = [
    {
        "channelId": "FRUTTA",
        "tenantId": "DNR",
        "displayName": "Flusso PDF Frutta DNR",
        "enabled": True,
        "acceptedFileTypes": ["PDF"],
        "defaultImportType": "PDF_DNR_FRUTTA",
        "activeProfileVersionId": "PROFILE_PDF_DNR_FRUTTA_V1",
        "credentialsPolicy": { "requiresCredentials": False },
        "schemaVersion": "1.0",
        "createdAt": "2026-01-01T00:00:00Z",
        "createdBy": "system_init",
        "updatedAt": "2026-07-26T10:00:00Z",
        "updatedBy": "system_init"
    },
    {
        "channelId": "LATTE",
        "tenantId": "DNR",
        "displayName": "Flusso PDF Latte DNR",
        "enabled": True,
        "acceptedFileTypes": ["PDF"],
        "defaultImportType": "PDF_DNR_LATTE",
        "activeProfileVersionId": "PROFILE_PDF_DNR_LATTE_V1",
        "credentialsPolicy": { "requiresCredentials": False },
        "schemaVersion": "1.0",
        "createdAt": "2026-01-01T00:00:00Z",
        "createdBy": "system_init",
        "updatedAt": "2026-07-26T10:00:00Z",
        "updatedBy": "system_init"
    },
    {
        "channelId": "EXCEL_CATTEL",
        "tenantId": "CATTEL",
        "displayName": "Flusso Excel Ordini Cattel",
        "enabled": True,
        "acceptedFileTypes": ["XLSX"],
        "defaultImportType": "EXCEL_CATTEL",
        "activeProfileVersionId": "PROFILE_EXCEL_CATTEL_V1",
        "credentialsPolicy": { "requiresCredentials": True, "portalReference": "CATTEL_PORTAL" },
        "schemaVersion": "1.0",
        "createdAt": "2026-01-01T00:00:00Z",
        "createdBy": "system_init",
        "updatedAt": "2026-07-26T10:00:00Z",
        "updatedBy": "system_init"
    },
    {
        "channelId": "EXCEL_GRAN_CHEF",
        "tenantId": "GRAN_CHEF",
        "displayName": "Flusso Excel Ordini Gran Chef",
        "enabled": True,
        "acceptedFileTypes": ["XLSX"],
        "defaultImportType": "EXCEL_GRAN_CHEF",
        "activeProfileVersionId": "PROFILE_EXCEL_CHEF_V1",
        "credentialsPolicy": { "requiresCredentials": False },
        "schemaVersion": "1.0",
        "createdAt": "2026-01-01T00:00:00Z",
        "createdBy": "system_init",
        "updatedAt": "2026-07-26T10:00:00Z",
        "updatedBy": "system_init"
    }
]

# --- FIXTURES PROFILI DI IMPORTAZIONE ---
_p1: Dict[str, Any] = {
    "profileId": "PROFILE_PDF_DNR_FRUTTA",
    "profileVersionId": "PROFILE_PDF_DNR_FRUTTA_V1",
    "tenantId": "DNR",
    "channelId": "FRUTTA",
    "version": "1.0",
    "configRevision": 1,
    "status": "ACTIVE",
    "fileType": "PDF",
    "parserStrategy": "PDF_TEXT_STRATEGY",
    "recognitionRules": {
        "fileNamePatterns": ["^FRUTTA_.*\\.pdf$"],
        "requiredHeaders": ["DISTINTA DI CARICO FRUTTA"]
    },
    "parsingRules": {
        "columnMapping": {
            "customerCode": { "col": "A", "transform": "STRIP_UPPER" },
            "quantityPackages": { "col": "B", "transform": "PARSE_INT" }
        }
    },
    "normalizationRules": { "trimWhitespace": True },
    "validationRules": { "mandatoryFields": ["customerCode"] },
    "createdAt": "2026-01-01T00:00:00Z",
    "createdBy": "system_init"
}
_p1["checksum"] = compute_profile_checksum(_p1)

_p2: Dict[str, Any] = {
    "profileId": "PROFILE_PDF_DNR_LATTE",
    "profileVersionId": "PROFILE_PDF_DNR_LATTE_V1",
    "tenantId": "DNR",
    "channelId": "LATTE",
    "version": "1.0",
    "configRevision": 1,
    "status": "ACTIVE",
    "fileType": "PDF",
    "parserStrategy": "PDF_TEXT_STRATEGY",
    "recognitionRules": {
        "fileNamePatterns": ["^LATTE_.*\\.pdf$"],
        "requiredHeaders": ["DISTINTA DI CARICO LATTE"]
    },
    "parsingRules": {
        "columnMapping": {
            "customerCode": { "col": "A", "transform": "STRIP_UPPER" },
            "quantityPackages": { "col": "B", "transform": "PARSE_INT" }
        }
    },
    "normalizationRules": { "trimWhitespace": True },
    "validationRules": { "mandatoryFields": ["customerCode"] },
    "createdAt": "2026-01-01T00:00:00Z",
    "createdBy": "system_init"
}
_p2["checksum"] = compute_profile_checksum(_p2)

_p3: Dict[str, Any] = {
    "profileId": "PROFILE_EXCEL_CATTEL",
    "profileVersionId": "PROFILE_EXCEL_CATTEL_V1",
    "tenantId": "CATTEL",
    "channelId": "EXCEL_CATTEL",
    "version": "1.0",
    "configRevision": 1,
    "status": "ACTIVE",
    "fileType": "XLSX",
    "parserStrategy": "EXCEL_GENERIC_STRATEGY",
    "recognitionRules": {
        "fileNamePatterns": ["^CATTEL_.*\\.xlsx$"],
        "sheetNames": ["Foglio1"]
    },
    "parsingRules": {
        "headerRowIndex": 1,
        "columnMapping": {
            "customerCode": { "col": "A", "transform": "STRIP_UPPER" },
            "customerName": { "col": "B", "transform": "CLEAN_TEXT" }
        }
    },
    "normalizationRules": { "uppercaseCodes": True },
    "validationRules": { "mandatoryFields": ["customerCode"] },
    "createdAt": "2026-01-01T00:00:00Z",
    "createdBy": "system_init"
}
_p3["checksum"] = compute_profile_checksum(_p3)

_p4: Dict[str, Any] = {
    "profileId": "PROFILE_EXCEL_CHEF",
    "profileVersionId": "PROFILE_EXCEL_CHEF_V1",
    "tenantId": "GRAN_CHEF",
    "channelId": "EXCEL_GRAN_CHEF",
    "version": "1.0",
    "configRevision": 1,
    "status": "ACTIVE",
    "fileType": "XLSX",
    "parserStrategy": "EXCEL_GENERIC_STRATEGY",
    "recognitionRules": {
        "fileNamePatterns": ["^GRAND_CHEF_.*\\.xlsx$", "^GRAN_CHEF_.*\\.xlsx$"],
        "sheetNames": ["Ordini"]
    },
    "parsingRules": {
        "headerRowIndex": 2,
        "columnMapping": {
            "customerCode": { "col": "A", "transform": "STRIP_UPPER" },
            "customerName": { "col": "B", "transform": "CLEAN_TEXT" }
        }
    },
    "normalizationRules": { "uppercaseCodes": True },
    "validationRules": { "mandatoryFields": ["customerCode"] },
    "createdAt": "2026-01-01T00:00:00Z",
    "createdBy": "system_init"
}
_p4["checksum"] = compute_profile_checksum(_p4)

FIXTURE_IMPORT_PROFILES: List[Dict[str, Any]] = [_p1, _p2, _p3, _p4]
