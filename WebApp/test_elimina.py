import datetime
import hashlib
import json

def _get_tenant_storage_aliases(tenant_id):
    if tenant_id == 'GRAN CHEF':
        return ['GRAN CHEF', 'GRAN_CHEF', 'GRAND CHEF', 'GRAND_CHEF', 'GRANCHEF']
    if tenant_id == 'GRAND_CHEF':
        return ['GRAND_CHEF', 'GRAN_CHEF', 'GRAN CHEF', 'GRAND CHEF', 'GRANCHEF']
    return [tenant_id, tenant_id.replace(' ', '_')]

def canonical_hash(data):
    s = json.dumps(data, sort_keys=True)
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

print("Compile success")
