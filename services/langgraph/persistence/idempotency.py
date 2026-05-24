import hashlib
import json

def generate_idempotency_key(project_id: str, node_id: str, input_dict: dict, attempt: int = 1) -> str:
    """
    Deterministic idempotency key generator based on the spec:
    hash(project_id + node_id + input_hash + attempt)
    """
    input_str = json.dumps(input_dict, sort_keys=True)
    input_hash = hashlib.sha256(input_str.encode("utf-8")).hexdigest()
    
    raw_key = f"{project_id}:{node_id}:{input_hash}:{attempt}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
