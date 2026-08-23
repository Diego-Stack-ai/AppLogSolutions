"""
Validatori Locali per Tenant, Channel e Import Profile Registry.
REF-001 FASE 2A
"""

import re
import json
import hashlib
from typing import Dict, List, Any
from .schemas import (
    PARSER_STRATEGY_ALLOWLIST,
    TRANSFORMATION_ALLOWLIST,
    PROFILE_STATUS_ENUM,
    ACCEPTED_FILE_TYPES_ENUM
)

class RegistryValidationError(Exception):
    """Eccezione sollevata quando una configurazione o relazione del Registry fallisce la validazione."""
    pass

def compute_profile_checksum(profile_dict: Dict[str, Any]) -> str:
    """
    Calcola l'hash SHA-256 stabile sul contenuto strutturale rilevante di un Import Profile.
    Esclude dal calcolo i campi metadato di tracciamento (checksum, createdAt, approvedAt).
    """
    profile_copy = dict(profile_dict)
    profile_copy.pop("checksum", None)
    profile_copy.pop("createdAt", None)
    profile_copy.pop("updatedAt", None)
    profile_copy.pop("approvedAt", None)
    profile_copy.pop("retiredAt", None)
    
    serialized = json.dumps(profile_copy, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

def _check_no_secrets(data_dict: Dict[str, Any], context_name: str) -> None:
    """Verifica che nessun campo contenga credenziali o segreti in chiaro."""
    forbidden_keys = {"password", "secret", "auth_token", "private_key", "credentials_secret"}
    for k, v in data_dict.items():
        if k.lower() in forbidden_keys:
            raise RegistryValidationError(f"[{context_name}] Rilevato campo vietato per credenziali o segreti: '{k}'")
        if isinstance(v, dict):
            _check_no_secrets(v, context_name)

def validate_tenant_schema(tenant: Dict[str, Any]) -> None:
    """Valida lo schema formale di un documento Tenant."""
    required_fields = [
        "tenantId", "displayName", "enabled", "schemaVersion",
        "createdAt", "createdBy", "updatedAt", "updatedBy"
    ]
    for field in required_fields:
        if field not in tenant or tenant[field] is None:
            raise RegistryValidationError(f"[TenantSchema] Campo obbligatorio mancante: '{field}'")
            
    tenant_id = str(tenant["tenantId"]).strip()
    if not tenant_id or not re.match(r"^[A-Z0-9_]+$", tenant_id):
        raise RegistryValidationError(f"[TenantSchema] tenantId '{tenant_id}' non valido. Deve essere maiuscolo ed alfanumerico.")
        
    if not isinstance(tenant["enabled"], bool):
        raise RegistryValidationError(f"[TenantSchema] 'enabled' deve essere un booleano per tenant '{tenant_id}'")
        
    aliases = tenant.get("legacyAliases", [])
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise RegistryValidationError(f"[TenantSchema] 'legacyAliases' deve essere una lista di stringhe per tenant '{tenant_id}'")
        
    _check_no_secrets(tenant, f"Tenant:{tenant_id}")

def validate_channel_schema(channel: Dict[str, Any]) -> None:
    """Valida lo schema formale di un documento Channel."""
    required_fields = [
        "channelId", "tenantId", "displayName", "enabled", "acceptedFileTypes",
        "schemaVersion", "createdAt", "createdBy", "updatedAt", "updatedBy"
    ]
    for field in required_fields:
        if field not in channel or channel[field] is None:
            raise RegistryValidationError(f"[ChannelSchema] Campo obbligatorio mancante: '{field}'")
            
    channel_id = str(channel["channelId"]).strip()
    if not channel_id or not re.match(r"^[A-Z0-9_]+$", channel_id):
        raise RegistryValidationError(f"[ChannelSchema] channelId '{channel_id}' non valido.")
        
    file_types = channel.get("acceptedFileTypes", [])
    if not isinstance(file_types, list) or not file_types:
        raise RegistryValidationError(f"[ChannelSchema] 'acceptedFileTypes' deve essere una lista non vuota per channel '{channel_id}'")
        
    for ft in file_types:
        if ft not in ACCEPTED_FILE_TYPES_ENUM:
            raise RegistryValidationError(f"[ChannelSchema] File type '{ft}' non ammesso per channel '{channel_id}'")
            
    _check_no_secrets(channel, f"Channel:{channel_id}")

def validate_import_profile_schema(profile: Dict[str, Any]) -> None:
    """Valida lo schema formale di un documento Import Profile versionato."""
    required_fields = [
        "profileId", "profileVersionId", "tenantId", "channelId", "version",
        "status", "fileType", "parserStrategy", "recognitionRules",
        "parsingRules", "normalizationRules", "validationRules",
        "configRevision", "checksum", "createdAt", "createdBy"
    ]
    for field in required_fields:
        if field not in profile or profile[field] is None:
            raise RegistryValidationError(f"[ImportProfileSchema] Campo obbligatorio mancante: '{field}'")
            
    version_id = str(profile["profileVersionId"]).strip()
    status = str(profile["status"]).upper().strip()
    if status not in PROFILE_STATUS_ENUM:
        raise RegistryValidationError(f"[ImportProfileSchema] Stato '{status}' non valido per profilo '{version_id}'")
        
    strategy = str(profile["parserStrategy"]).strip()
    if strategy not in PARSER_STRATEGY_ALLOWLIST:
        raise RegistryValidationError(
            f"[ImportProfileSchema] parserStrategy '{strategy}' non ammessa per profilo '{version_id}'. "
            f"Deve appartenere all'allowlist: {PARSER_STRATEGY_ALLOWLIST}"
        )
        
    # Validazione Trasformazioni nelle colonne
    column_mapping = profile.get("parsingRules", {}).get("columnMapping", {})
    if isinstance(column_mapping, dict):
        for field_name, rule in column_mapping.items():
            if isinstance(rule, dict) and "transform" in rule:
                trans = rule["transform"]
                if trans not in TRANSFORMATION_ALLOWLIST:
                    raise RegistryValidationError(
                        f"[ImportProfileSchema] Trasformazione '{trans}' non autorizzata sul campo '{field_name}'. "
                        f"Deve appartenere alla allowlist: {TRANSFORMATION_ALLOWLIST}"
                    )
                    
    # Validazione Sintassi Regex nelle regole di riconoscimento
    patterns = profile.get("recognitionRules", {}).get("fileNamePatterns", [])
    if isinstance(patterns, list):
        for pat in patterns:
            try:
                re.compile(pat)
            except re.error as e_regex:
                raise RegistryValidationError(f"[ImportProfileSchema] Regex non valida '{pat}' in profilo '{version_id}': {e_regex}")
                
    # Validazione Checksum
    computed = compute_profile_checksum(profile)
    if profile.get("checksum") != computed:
        raise RegistryValidationError(
            f"[ImportProfileSchema] Checksum non valido per profilo '{version_id}'. "
            f"Fornito: '{profile.get('checksum')}', Calcolato: '{computed}'"
        )
        
    _check_no_secrets(profile, f"ImportProfile:{version_id}")

def validate_registry_relations(
    tenants: List[Dict[str, Any]],
    channels: List[Dict[str, Any]],
    profiles: List[Dict[str, Any]]
) -> None:
    """Valida le relazioni d'integrità e l'assenza di sovrapposizioni o alias duplicati."""
    tenant_ids = set()
    alias_map = {}
    
    # 1. Verifica Tenant ed Alias Unici
    for t in tenants:
        tid = t["tenantId"]
        if tid in tenant_ids:
            raise RegistryValidationError(f"[RegistryRelations] tenantId duplicato: '{tid}'")
        tenant_ids.add(tid)
        
        aliases = t.get("legacyAliases", [])
        for alias in aliases:
            norm_alias = alias.upper().strip()
            if norm_alias in alias_map and alias_map[norm_alias] != tid:
                raise RegistryValidationError(
                    f"[RegistryRelations] Alias duplicato '{alias}' tra tenant '{alias_map[norm_alias]}' e '{tid}'"
                )
            alias_map[norm_alias] = tid

    # 2. Verifica Canali ed appartenenza ai Tenant
    channel_map = {}
    for c in channels:
        cid = c["channelId"]
        ctenant = c["tenantId"]
        if ctenant not in tenant_ids:
            raise RegistryValidationError(f"[RegistryRelations] Canale '{cid}' riferito a tenant inesistente '{ctenant}'")
        channel_map[cid] = c

    # 3. Verifica Profilo ed appartenenza Canale/Tenant
    profile_map = {}
    for p in profiles:
        pvid = p["profileVersionId"]
        ptenant = p["tenantId"]
        pchannel = p["channelId"]
        
        if ptenant not in tenant_ids:
            raise RegistryValidationError(f"[RegistryRelations] Profilo '{pvid}' riferito a tenant inesistente '{ptenant}'")
        if pchannel not in channel_map:
            raise RegistryValidationError(f"[RegistryRelations] Profilo '{pvid}' riferito a canale inesistente '{pchannel}'")
            
        c_obj = channel_map[pchannel]
        if c_obj["tenantId"] != ptenant:
            raise RegistryValidationError(
                f"[RegistryRelations] Incoerenza tenant: Profilo '{pvid}' dichiara tenant '{ptenant}' ma il canale '{pchannel}' appartiene a '{c_obj['tenantId']}'"
            )
        profile_map[pvid] = p

    # 4. Verifica Puntatori activeProfileVersionId sui Canali
    for c in channels:
        active_pvid = c.get("activeProfileVersionId")
        if active_pvid:
            if active_pvid not in profile_map:
                raise RegistryValidationError(
                    f"[RegistryRelations] Canale '{c['channelId']}' punta a profilo inesistente '{active_pvid}'"
                )
            prof_obj = profile_map[active_pvid]
            if prof_obj["status"] != "ACTIVE":
                raise RegistryValidationError(
                    f"[RegistryRelations] Canale '{c['channelId']}' punta a profilo '{active_pvid}' che non è in stato ACTIVE (Stato attuale: '{prof_obj['status']}')"
                )

def validate_profile_immutability(old_profile: Dict[str, Any], new_profile: Dict[str, Any]) -> None:
    """Verifica che una versione ACTIVE non venga modificata senza creare un nuovo profileVersionId."""
    if old_profile.get("status") == "ACTIVE":
        if old_profile.get("profileVersionId") == new_profile.get("profileVersionId"):
            if compute_profile_checksum(old_profile) != compute_profile_checksum(new_profile):
                raise RegistryValidationError(
                    f"[ImmutabilityError] Impossibile modificare direttamente la versione ACTIVE '{old_profile.get('profileVersionId')}'. "
                    f"Creare un nuovo profileVersionId (es. V2) per apportare modifiche."
                )
