"""Durable job state.

Two representations are kept deliberately:

* ``.freevideoforge/state.db`` - the authoritative SQLite store (transactional,
  safe across concurrent readers, survives a kill -9 mid render).
* ``.freevideoforge/state.json`` - a human/agent readable snapshot mirror so a
  different process, session or tool can inspect and resume a run without
  speaking SQL.

Resumption rule: a run reuses every scene asset whose ``input_hash`` still
matches its current spec and whose file is still present and non-empty. Anything
else is recomputed. That is what makes an interrupted run cheap to restart and
what makes a re-run with identical inputs idempotent.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .errors import StateError
from .models import JobState, Project, project_from_dict, to_jsonable

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    state        TEXT NOT NULL,
    topic        TEXT NOT NULL,
    config_hash  TEXT NOT NULL,
    request      TEXT NOT NULL,
    project      TEXT,
    output_dir   TEXT NOT NULL,
    work_dir     TEXT NOT NULL,
    providers    TEXT NOT NULL DEFAULT '{}',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    completed_at REAL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS scene_states (
    run_id     TEXT NOT NULL,
    scene_id   TEXT NOT NULL,
    idx        INTEGER NOT NULL,
    state      TEXT NOT NULL,
    clip_hash  TEXT,
    audio_hash TEXT,
    clip_path  TEXT,
    audio_path TEXT,
    duration   REAL,
    attempts   INTEGER NOT NULL DEFAULT 0,
    error      TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (run_id, scene_id)
);

CREATE TABLE IF NOT EXISTS assets (
    run_id     TEXT NOT NULL,
    kind       TEXT NOT NULL,
    path       TEXT NOT NULL,
    sha256     TEXT NOT NULL,
    bytes      INTEGER NOT NULL,
    provider   TEXT NOT NULL,
    scene_id   TEXT,
    duration   REAL,
    created_at REAL NOT NULL,
    PRIMARY KEY (run_id, kind, path)
);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    at         REAL NOT NULL,
    level      TEXT NOT NULL,
    stage      TEXT NOT NULL,
    message    TEXT NOT NULL,
    data       TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_run ON events (run_id, id);
CREATE INDEX IF NOT EXISTS idx_runs_updated ON runs (updated_at DESC);
"""


def new_run_id(prefix: str = "run") -> str:
    """Time-ordered, collision-resistant, filesystem-safe run id."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6]}"


class RunStore:
    """SQLite-backed run store with a JSON mirror."""

    def __init__(self, db_path: Path, mirror_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path)
        self.mirror_path = Path(mirror_path) if mirror_path else None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # -- low level -------------------------------------------------------
    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            # executescript() implicitly commits, so only commit when a
            # transaction is genuinely still open.
            if conn.in_transaction:
                conn.execute("COMMIT")
        except Exception:
            try:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # -- runs ------------------------------------------------------------
    def create_run(
        self,
        *,
        run_id: str,
        topic: str,
        config_hash: str,
        request: dict[str, Any],
        output_dir: Path,
        work_dir: Path,
    ) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO runs
                   (run_id, state, topic, config_hash, request, project, output_dir,
                    work_dir, providers, created_at, updated_at, completed_at, attempts, error)
                   VALUES (?,?,?,?,?,NULL,?,?, '{}', ?, ?, NULL, 0, NULL)""",
                (
                    run_id,
                    JobState.CREATED.value,
                    topic,
                    config_hash,
                    json.dumps(to_jsonable(request), sort_keys=True),
                    str(output_dir),
                    str(work_dir),
                    now,
                    now,
                ),
            )
        self.log(run_id, "info", "state", "run created", {"state": JobState.CREATED.value})
        self._mirror()

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise StateError(f"Unknown run_id {run_id!r}. Try `freevideoforge runs`.")
        record = dict(row)
        record["request"] = json.loads(record["request"] or "{}")
        record["project"] = json.loads(record["project"]) if record["project"] else None
        record["providers"] = json.loads(record["providers"] or "{}")
        return record

    def run_exists(self, run_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return row is not None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT run_id, state, topic, created_at, updated_at, completed_at, error
                   FROM runs ORDER BY created_at DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_state(self, run_id: str, state: JobState, error: str | None = None) -> None:
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """UPDATE runs SET state = ?, updated_at = ?, error = ?,
                       completed_at = CASE WHEN ? = 'COMPLETED' THEN ? ELSE completed_at END
                   WHERE run_id = ?""",
                (state.value, now, error, state.value, now, run_id),
            )
        self.log(run_id, "error" if error else "info", "state", f"-> {state.value}",
                 {"error": error} if error else None)
        self._mirror()

    def get_state(self, run_id: str) -> JobState:
        return JobState(self.get_run(run_id)["state"])

    def bump_attempts(self, run_id: str) -> int:
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET attempts = attempts + 1, updated_at = ? WHERE run_id = ?",
                (time.time(), run_id),
            )
            row = conn.execute(
                "SELECT attempts FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return int(row["attempts"]) if row else 0

    def save_project(self, project: Project) -> None:
        payload = json.dumps(to_jsonable(project), sort_keys=False)
        with self._conn() as conn:
            conn.execute(
                "UPDATE runs SET project = ?, providers = ?, updated_at = ? WHERE run_id = ?",
                (payload, json.dumps(project.providers, sort_keys=True),
                 time.time(), project.run_id),
            )
        self._mirror()

    def load_project(self, run_id: str) -> Optional[Project]:
        record = self.get_run(run_id)
        if not record["project"]:
            return None
        return project_from_dict(record["project"])

    # -- scenes ----------------------------------------------------------
    def upsert_scene(
        self,
        run_id: str,
        *,
        scene_id: str,
        index: int,
        state: str,
        clip_hash: str | None = None,
        audio_hash: str | None = None,
        clip_path: str | None = None,
        audio_path: str | None = None,
        duration: float | None = None,
        attempts: int | None = None,
        error: str | None = None,
    ) -> None:
        """Merge scene progress.

        Stages write different columns of the same row - voice writes the audio
        pair, media writes the clip pair - so an omitted argument means "leave
        this alone", never "clear it". Clobbering here is what silently defeats
        reuse on a resumed run.
        """
        now = time.time()
        updates: dict[str, Any] = {"idx": index, "state": state, "updated_at": now}
        for column, value in (
            ("clip_hash", clip_hash),
            ("audio_hash", audio_hash),
            ("clip_path", clip_path),
            ("audio_path", audio_path),
            ("duration", duration),
            ("attempts", attempts),
        ):
            if value is not None:
                updates[column] = value
        # `error` is meaningful when cleared, so it is always written.
        updates["error"] = error

        with self._conn() as conn:
            existing = conn.execute(
                "SELECT 1 FROM scene_states WHERE run_id = ? AND scene_id = ?",
                (run_id, scene_id),
            ).fetchone()
            if existing:
                assignments = ", ".join(f"{column} = ?" for column in updates)
                conn.execute(
                    f"UPDATE scene_states SET {assignments} "
                    "WHERE run_id = ? AND scene_id = ?",
                    (*updates.values(), run_id, scene_id),
                )
            else:
                updates.setdefault("attempts", 0)
                columns = ["run_id", "scene_id", *updates]
                placeholders = ", ".join("?" for _ in columns)
                conn.execute(
                    f"INSERT INTO scene_states ({', '.join(columns)}) "
                    f"VALUES ({placeholders})",
                    (run_id, scene_id, *updates.values()),
                )

    def get_scene_states(self, run_id: str) -> dict[str, dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM scene_states WHERE run_id = ? ORDER BY idx", (run_id,)
            ).fetchall()
        return {row["scene_id"]: dict(row) for row in rows}

    def reusable_scene(
        self, run_id: str, scene_id: str, input_hash: str, kind: str = "clip"
    ) -> Optional[str]:
        """Return a reusable artifact path for this scene, or None.

        Reuse requires all three: a recorded DONE state, a matching input hash
        for *this* kind of artifact, and a file still on disk with a non-zero
        size. Anything less is recomputed.
        """
        if kind not in {"clip", "audio"}:
            raise StateError(f"Unknown artifact kind {kind!r}")
        path_column = f"{kind}_path"
        hash_column = f"{kind}_hash"
        with self._conn() as conn:
            row = conn.execute(
                f"""SELECT {path_column} AS path, {hash_column} AS hash, state
                    FROM scene_states WHERE run_id = ? AND scene_id = ?""",
                (run_id, scene_id),
            ).fetchone()
        if not row or row["state"] != "DONE" or row["hash"] != input_hash:
            return None
        if not row["path"]:
            return None
        candidate = Path(row["path"])
        if candidate.exists() and candidate.stat().st_size > 0:
            return str(candidate)
        return None

    # -- assets ----------------------------------------------------------
    def record_asset(self, run_id: str, asset: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO assets
                     (run_id, kind, path, sha256, bytes, provider, scene_id, duration, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    asset["kind"],
                    asset["path"],
                    asset["sha256"],
                    int(asset["bytes"]),
                    asset["provider"],
                    asset.get("scene_id"),
                    asset.get("duration"),
                    asset.get("created_at", time.time()),
                ),
            )

    def list_assets(self, run_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM assets WHERE run_id = ? ORDER BY created_at", (run_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    # -- events ----------------------------------------------------------
    def log(
        self,
        run_id: str,
        level: str,
        stage: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (run_id, at, level, stage, message, data) VALUES (?,?,?,?,?,?)",
                (
                    run_id,
                    time.time(),
                    level,
                    stage,
                    message,
                    json.dumps(to_jsonable(data), sort_keys=True) if data else None,
                ),
            )

    def events(self, run_id: str, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, at, level, stage, message, data FROM events
                   WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?""",
                (run_id, int(after_id), int(limit)),
            ).fetchall()
        out = []
        for row in rows:
            record = dict(row)
            record["data"] = json.loads(record["data"]) if record["data"] else None
            out.append(record)
        return out

    # -- JSON mirror -----------------------------------------------------
    def _mirror(self) -> None:
        """Write the cross-session snapshot atomically.

        Best-effort: a failure to mirror must never fail a render, because the
        SQLite store remains authoritative.
        """
        if not self.mirror_path:
            return
        try:
            runs = self.list_runs(limit=25)
            snapshot = {
                "schema_version": f"freevideoforge/state/v{SCHEMA_VERSION}",
                "db_path": str(self.db_path),
                "updated_at": time.time(),
                "runs": runs,
            }
            self.mirror_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.mirror_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, self.mirror_path)
        except OSError:
            pass
