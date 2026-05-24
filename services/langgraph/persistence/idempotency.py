import hashlib
import json
import sqlite3
from services.langgraph.persistence.sqlite_db import DB_PATH, init_db

# Ensure table exists
init_db()

def generate_idempotency_key(project_id: str, node_id: str, input_dict: dict, attempt: int = 1) -> str:
    """
    Deterministic idempotency key generator based on the spec:
    hash(project_id + node_id + input_hash + attempt)
    """
    input_str = json.dumps(input_dict, sort_keys=True)
    input_hash = hashlib.sha256(input_str.encode("utf-8")).hexdigest()
    
    raw_key = f"{project_id}:{node_id}:{input_hash}:{attempt}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

def verify_idempotency(key: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("SELECT 1 FROM idempotency_keys WHERE key = ?", (key,))
        return cur.fetchone() is not None

def record_idempotency(key: str, result: any, ttlSeconds: int = 86400) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO idempotency_keys (key, result) VALUES (?, ?)", 
            (key, json.dumps(result))
        )
