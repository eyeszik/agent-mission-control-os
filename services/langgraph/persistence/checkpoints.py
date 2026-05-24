from typing import Dict, Any, Optional

class InMemoryCheckpointStore:
    """
    Mock store for LangGraph State checkpoints.
    Will be replaced by SQLite/Postgres or Durable Objects.
    """
    def __init__(self):
        self._store: Dict[str, Any] = {}

    def save_checkpoint(self, run_id: str, node_id: str, state: dict) -> None:
        key = f"{run_id}:{node_id}"
        self._store[key] = state

    def load_checkpoint(self, run_id: str, node_id: str) -> Optional[dict]:
        key = f"{run_id}:{node_id}"
        return self._store.get(key)
