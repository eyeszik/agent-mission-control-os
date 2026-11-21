#!/usr/bin/env python3
"""Production migration tooling: catalog snapshots, SQLite->PostgreSQL mapping, rollback, timed apply, backfill.

Subcommands (all PostgreSQL work refuses any host but localhost/127.0.0.1, so a
live or production database can never be targeted from here):

    mapping   --dsn D            write acceptance/migration_mapping.json and docs/migrations/sqlite-to-postgres-mapping.md
    rollback  --dsn D            regenerate supabase/rollback/<migration>.down.sql from catalog diffs
    apply     --dsn D [--down]   apply every migration (or every rollback, newest first) with lock/statement timeouts
    backfill  --dsn D --sqlite F copy a SQLite database into PostgreSQL in tenant-scoped chunks, then verify checksums

``--dsn`` names a maintenance database on an ephemeral server; scratch
databases are created and dropped on it.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit, urlunsplit

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MIGRATIONS = ROOT / "supabase/migrations"
ROLLBACK = ROOT / "supabase/rollback"
SHIM = ROOT / "supabase/ci/supabase_shim.sql"
MAPPING_JSON = ROOT / "acceptance/migration_mapping.json"
MAPPING_MD = ROOT / "docs/migrations/sqlite-to-postgres-mapping.md"
LOCK_TIMEOUT, STATEMENT_TIMEOUT = "5s", "120s"
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")
DML = re.compile(r"^\s*(update|insert into|delete from)\b", re.I | re.M)


# ----------------------------------------------------------------------------- connections
def assert_ephemeral(dsn: str) -> None:
    """Fail closed unless the DSN points at a local, disposable server."""
    host = urlsplit(dsn).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(f"refusing non-local PostgreSQL host {host!r}: migration tests run only on an ephemeral server")


def with_database(dsn: str, name: str) -> str:
    parts = urlsplit(dsn)
    return urlunsplit(parts._replace(path=f"/{name}"))


@contextlib.contextmanager
def scratch_database(dsn: str) -> Iterator[str]:
    assert_ephemeral(dsn)
    name = f"amc_mig_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f'create database "{name}"')
    try:
        yield with_database(dsn, name)
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'drop database if exists "{name}" with (force)')


def run_sql(dsn: str, sql: str) -> None:
    """One file, one transaction, bounded locks and statements."""
    with psycopg.connect(dsn) as conn:
        conn.execute(f"set local lock_timeout = '{LOCK_TIMEOUT}'")
        conn.execute(f"set local statement_timeout = '{STATEMENT_TIMEOUT}'")
        conn.execute(sql)


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def rollback_file(migration: Path) -> Path:
    return ROLLBACK / f"{migration.stem}.down.sql"


def apply_all(dsn: str, files: list[Path] | None = None) -> list[str]:
    run_sql(dsn, SHIM.read_text(encoding="utf-8"))
    applied = []
    for path in files or migration_files():
        run_sql(dsn, path.read_text(encoding="utf-8"))
        applied.append(path.name)
    return applied


def rollback_all(dsn: str, files: list[Path] | None = None) -> list[str]:
    reverted = []
    for path in reversed(files or migration_files()):
        run_sql(dsn, rollback_file(path).read_text(encoding="utf-8"))
        reverted.append(path.name)
    return reverted


# ----------------------------------------------------------------------------- catalog snapshot
_Q = {
    "schemas": "select nspname from pg_namespace where nspname not like 'pg\\_%' and nspname <> 'information_schema' and nspname <> 'public'",
    "tables": """select n.nspname||'.'||c.relname, c.relrowsecurity, c.relforcerowsecurity, coalesce(c.relacl::text,''),
                        coalesce(obj_description(c.oid,'pg_class'),'')
                   from pg_class c join pg_namespace n on n.oid=c.relnamespace
                  where c.relkind in ('r','p') and n.nspname <> all(%s) and n.nspname not like 'pg\\_%%'""",
    "columns": """select n.nspname||'.'||c.relname, a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull,
                         coalesce(pg_get_expr(d.adbin,d.adrelid),''), coalesce(col_description(c.oid,a.attnum),'')
                    from pg_attribute a join pg_class c on c.oid=a.attrelid join pg_namespace n on n.oid=c.relnamespace
                    left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum
                   where c.relkind in ('r','p') and a.attnum>0 and not a.attisdropped and n.nspname <> all(%s) and n.nspname not like 'pg\\_%%'""",
    "constraints": """select n.nspname||'.'||c.relname, k.conname, pg_get_constraintdef(k.oid)
                        from pg_constraint k join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace
                       where n.nspname <> all(%s) and n.nspname not like 'pg\\_%%'""",
    "indexes": """select schemaname||'.'||tablename, indexname, indexdef from pg_indexes
                   where schemaname <> all(%s) and schemaname not like 'pg\\_%%'""",
    "policies": "select schemaname||'.'||tablename, policyname, cmd, coalesce(qual,''), coalesce(with_check,'') from pg_policies",
    "functions": """select n.nspname||'.'||p.proname||'('||pg_get_function_identity_arguments(p.oid)||')', pg_get_functiondef(p.oid)
                      from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname <> all(%s) and n.nspname not like 'pg\\_%%'""",
    "triggers": """select c.relname, t.tgname, pg_get_triggerdef(t.oid) from pg_trigger t join pg_class c on c.oid=t.tgrelid
                    join pg_namespace n on n.oid=c.relnamespace where not t.tgisinternal and n.nspname <> all(%s)""",
    "schema_acl": "select nspname, coalesce(nspacl::text,'') from pg_namespace where nspname not like 'pg\\_%' and nspname <> 'information_schema'",
}


def snapshot(dsn: str) -> dict[str, list[tuple]]:
    """Every catalog object a migration can create or change, as sorted tuples."""
    out: dict[str, list[tuple]] = {}
    with psycopg.connect(dsn) as conn:
        for key, query in _Q.items():
            params = (list(SYSTEM_SCHEMAS),) if "%s" in query else None
            out[key] = sorted(tuple(row) for row in conn.execute(query, params).fetchall())
    return out


def snapshot_digest(snap: dict[str, list[tuple]]) -> str:
    return hashlib.sha256(json.dumps(snap, sort_keys=True, default=str).encode()).hexdigest()


# ----------------------------------------------------------------------------- rollback generation
def _by(rows: list[tuple], width: int) -> dict[tuple, tuple]:
    return {row[:width]: row for row in rows}


def _new_tables(before: dict, after: dict) -> list[str]:
    old = {r[0] for r in before["tables"]}
    return [r[0] for r in after["tables"] if r[0] not in old]


def _drop_order(tables: list[str], after: dict) -> list[str]:
    """Drop referencing tables before the tables they reference (no CASCADE)."""
    refs = {t: set() for t in tables}
    for table, _, definition in after["constraints"]:
        match = re.search(r"REFERENCES ([\w.]+)\(", definition)
        if table in refs and match:
            target = match.group(1) if "." in match.group(1) else f"{table.split('.')[0]}.{match.group(1)}"
            if target in refs and target != table:
                refs[table].add(target)
    order, remaining = [], set(tables)
    while remaining:
        leaves = sorted(t for t in remaining if not any(t in refs[o] for o in remaining if o != t))
        if not leaves:
            raise SystemExit(f"circular foreign keys among new tables: {sorted(remaining)}")
        order += leaves
        remaining -= set(leaves)
    return order


def _constraint_sql(before: dict, after: dict, kept: set[str]) -> list[str]:
    old, new = _by(before["constraints"], 2), _by(after["constraints"], 2)
    sql = []
    for key, row in sorted(new.items()):
        if key[0] in kept and (key not in old or old[key] != row):
            sql.append(f'alter table {key[0]} drop constraint if exists "{key[1]}";')
    for key, row in sorted(old.items()):
        if key[0] in kept and (key not in new or new[key] != row):
            sql.append(f'alter table {key[0]} add constraint "{key[1]}" {row[2]};')
    return sql


def _index_sql(before: dict, after: dict, kept: set[str]) -> list[str]:
    backing = {c[1] for c in before["constraints"] + after["constraints"]}
    old, new = _by(before["indexes"], 2), _by(after["indexes"], 2)
    sql = []
    for key, row in sorted(new.items()):
        if key[0] in kept and key[1] not in backing and (key not in old or old[key] != row):
            sql.append(f'drop index if exists {key[0].split(".")[0]}."{key[1]}";')
    for key, row in sorted(old.items()):
        if key[0] in kept and key[1] not in backing and (key not in new or new[key] != row):
            sql.append(f"{row[2]};")
    return sql


def _column_sql(before: dict, after: dict, kept: set[str]) -> list[str]:
    old, new = _by(before["columns"], 2), _by(after["columns"], 2)
    sql = []
    for key, row in sorted(new.items()):
        if key[0] not in kept:
            continue
        if key not in old:
            sql.append(f'alter table {key[0]} drop column if exists "{key[1]}";')
        elif old[key][2:5] != row[2:5]:
            raise SystemExit(f"column {key} changed type/nullability/default; write its rollback by hand")
        elif old[key][5] != row[5]:
            sql.append(f'comment on column {key[0]}."{key[1]}" is {_literal(old[key][5])};')
    for key in sorted(set(old) - set(new)):
        if key[0] in kept:
            raise SystemExit(f"column {key} was dropped; data cannot be restored by a generated rollback")
    return sql


def _unsupported(before: dict, after: dict, kept: set[str]) -> None:
    for kind in ("policies", "functions", "triggers"):
        if before[kind] != after[kind]:
            raise SystemExit(f"migration changes {kind}; extend the rollback generator before using it")
    old_tables = _by(before["tables"], 1)
    for row in after["tables"]:
        if row[0] in kept and old_tables[(row[0],)][:4] != row[:4]:
            raise SystemExit(f"migration changes RLS/ACL on existing table {row[0]}; extend the rollback generator")


def _literal(text: str) -> str:
    return "null" if not text else "'" + text.replace("'", "''") + "'"


def _table_comment_sql(before: dict, after: dict, kept: set[str]) -> list[str]:
    old = _by(before["tables"], 1)
    return [f"comment on table {row[0]} is {_literal(old[(row[0],)][4])};"
            for row in after["tables"] if row[0] in kept and old[(row[0],)][4] != row[4]]


def generate_down(before: dict, after: dict, up_sql: str, name: str) -> str:
    kept = {r[0] for r in before["tables"]} & {r[0] for r in after["tables"]}
    _unsupported(before, after, kept)
    body = (_constraint_sql(before, after, kept) + _index_sql(before, after, kept) + _column_sql(before, after, kept)
            + _table_comment_sql(before, after, kept))
    body += [f"drop table if exists {t};" for t in _drop_order(_new_tables(before, after), after)]
    old_schemas = {r[0] for r in before["schemas"]}
    body += [f"drop schema if exists {r[0]};" for r in after["schemas"] if r[0] not in old_schemas]
    header = [f"-- GENERATED by scripts/db_migrations.py rollback from the catalog diff of {name}.sql. Do not edit by hand.",
              "-- Reverses schema objects only; it never restores data."]
    if DML.search(up_sql):
        header.append("-- DATA CHANGE NOT REVERSED: the up migration rewrites rows; restore those from the pre-migration backup.")
    return "\n".join(header + ["begin;", f"set local lock_timeout = '{LOCK_TIMEOUT}';",
                               f"set local statement_timeout = '{STATEMENT_TIMEOUT}';", *body, "commit;", ""])


def build_rollbacks(dsn: str) -> dict[str, str]:
    """Apply migrations one by one on a scratch database and diff the catalog around each."""
    downs: dict[str, str] = {}
    with scratch_database(dsn) as db:
        run_sql(db, SHIM.read_text(encoding="utf-8"))
        before = snapshot(db)
        for path in migration_files():
            up = path.read_text(encoding="utf-8")
            run_sql(db, up)
            after = snapshot(db)
            downs[path.name] = generate_down(before, after, up, path.stem)
            before = after
    return downs


def write_rollbacks(dsn: str) -> None:
    ROLLBACK.mkdir(parents=True, exist_ok=True)
    for name, sql in build_rollbacks(dsn).items():
        (ROLLBACK / name.replace(".sql", ".down.sql")).write_text(sql, encoding="utf-8")
    print(f"wrote {len(migration_files())} rollback files to {ROLLBACK.relative_to(ROOT)}")


# ----------------------------------------------------------------------------- SQLite catalog + mapping
def sqlite_catalog() -> dict[str, list[dict]]:
    """Run the real SQLite migrations into a throwaway file and read every table's columns."""
    from services.langgraph.persistence import sqlite_db
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "catalog.db")
        previous = sqlite_db.DB_PATH
        sqlite_db.DB_PATH = path
        try:
            sqlite_db.init_db()
        finally:
            sqlite_db.DB_PATH = previous
        conn = sqlite3.connect(path)
        try:
            names = [r[0] for r in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
            return {n: [{"name": c[1], "type": (c[2] or "").upper(), "notnull": bool(c[3]), "pk": bool(c[5])}
                        for c in conn.execute(f'pragma table_info("{n}")')] for n in names}
        finally:
            conn.close()


def _translation(sqlite_type: str, pg_type: str) -> str:
    rules = {
        ("TEXT", "jsonb"): "TEXT holding JSON -> jsonb (json.loads, wrapped as Jsonb)",
        ("TEXT", "timestamp with time zone"): "TEXT ISO-8601 -> timestamptz (naive values are UTC)",
        ("TIMESTAMP", "timestamp with time zone"): "TIMESTAMP 'YYYY-MM-DD HH:MM:SS' -> timestamptz (UTC)",
        ("INTEGER", "boolean"): "INTEGER 0/1 -> boolean",
        ("TEXT", "uuid"): "TEXT -> uuid",
        ("BLOB", "bytea"): "BLOB -> bytea",
    }
    base = sqlite_type.split("(")[0] or "TEXT"
    if (base, pg_type) in rules:
        return rules[(base, pg_type)]
    same = {("TEXT", "text"), ("INTEGER", "integer"), ("INTEGER", "bigint"), ("REAL", "double precision"),
            ("REAL", "numeric"), ("INTEGER", "numeric"), ("TEXT", "numeric")}
    return "identity" if (base, pg_type) in same else f"{base} -> {pg_type} (explicit cast)"


def _pg_table_model(snap: dict) -> dict[str, dict]:
    tables: dict[str, dict] = {}
    for table, rls, force, acl, comment in snap["tables"]:
        tables[table] = {"rls_enabled": rls, "rls_forced": force, "acl": acl, "columns": {}, "constraints": [], "indexes": []}
    for table, col, typ, notnull, default, _ in snap["columns"]:
        tables[table]["columns"][col] = {"type": typ, "notnull": notnull, "default": default}
    for table, name, definition in snap["constraints"]:
        tables[table]["constraints"].append({"name": name, "definition": definition})
    for table, name, definition in snap["indexes"]:
        if table in tables:
            tables[table]["indexes"].append({"name": name, "definition": definition})
    return tables


def _column_rows(columns: list[dict], pg: dict | None) -> list[dict]:
    rows = []
    pg_cols = (pg or {}).get("columns", {})
    for col in columns:
        target = pg_cols.get(col["name"])
        rows.append({"column": col["name"], "sqlite_type": col["type"] or "TEXT", "sqlite_pk": col["pk"],
                     "pg_type": target["type"] if target else None, "pg_notnull": target["notnull"] if target else None,
                     "translation": _translation(col["type"], target["type"]) if target else None,
                     "status": "MAPPED" if target else ("NOT_IN_POSTGRES" if pg else "TABLE_NOT_IN_POSTGRES")})
    names = {c["name"] for c in columns}
    rows += [{"column": n, "sqlite_type": None, "pg_type": c["type"], "status": "POSTGRES_ONLY"}
             for n, c in sorted(pg_cols.items()) if n not in names]
    return rows


def _security(pg: dict | None) -> dict:
    if not pg:
        return {}
    keys = [c["name"] for c in pg["constraints"]]
    return {
        "tenant_scoped": "tenant_id" in pg["columns"],
        "tenant_fk": any("REFERENCES amc.tenants" in c["definition"] for c in pg["constraints"]),
        "idempotency_unique": [c["definition"] for c in pg["constraints"] if "UNIQUE" in c["definition"] and "tenant_id" in c["definition"]],
        "content_hash_columns": sorted(n for n in pg["columns"] if n.endswith("_hash") or n.endswith("sha256")),
        "lease_columns": sorted(n for n in pg["columns"] if "lease" in n or n in ("fence", "fencing_token", "attempt")),
        "rls_enabled": pg["rls_enabled"], "policies": [],
        "constraint_names": sorted(keys),
    }


# Every table that does not map by name carries an explicit, code-grounded disposition.
RENAMED = {"run_events_v2": "amc.run_events"}  # persistence/database.py::table() resolves run_events per backend
DISPOSITIONS = {
    "idempotency_keys": "LEGACY_UNUSED: the check-then-record path is forbidden by verify_repository_invariants.py; persistence/idempotency.py uses idempotency_records.",
    "schema_migrations": "LOCAL_LEDGER: SQLite's applied-version ledger; PostgreSQL applies supabase/migrations through the deployment's migration history.",
    "reliability_meta": "LOCAL_STORE: agency/reliability/store.py is a standalone SQLite store; production state uses the trust-kernel tables.",
    "reliability_bindings": "LOCAL_STORE: see reliability_meta; production counterpart amc.tenant_project_bindings.",
    "reliability_policy_decisions": "LOCAL_STORE: see reliability_meta; production counterpart amc.policy_decision_records.",
    "reliability_idempotency": "LOCAL_STORE: see reliability_meta; production counterpart amc.trust_idempotency_records.",
    "reliability_outbox": "LOCAL_STORE: see reliability_meta; production counterpart amc.outbox_messages.",
    "reliability_audit_chain": "LOCAL_STORE: see reliability_meta; production counterpart amc.audit_checkpoints.",
    "reliability_recovery": "LOCAL_STORE: see reliability_meta; production counterpart amc.recovery_cases.",
    "amc.tenant_memberships": "POSTGRES_ONLY_BY_DESIGN: local mode derives the principal from AMC_LOCAL_* env; production authorization reads memberships.",
    "amc.run_event_counters": "POSTGRES_ONLY_BY_DESIGN: concurrency-safe per-run sequence allocator; SQLite allocates under its single-writer lock.",
}


def _sqlite_table_row(name: str, columns: list[dict], pg: dict) -> dict:
    pg_name = RENAMED.get(name, f"amc.{name}")
    target = pg.get(pg_name)
    status = ("RENAMED" if name in RENAMED else "MAPPED") if target else "LOCAL_ONLY"
    return {"sqlite_table": name, "pg_table": pg_name if target else None, "status": status,
            "disposition": DISPOSITIONS.get(name), "columns": _column_rows(columns, target),
            "primary_key": [c["name"] for c in columns if c["pk"]], "security": _security(target)}


def build_mapping(dsn: str) -> dict:
    sqlite = sqlite_catalog()
    with scratch_database(dsn) as db:
        apply_all(db)
        snap = snapshot(db)
        privileges = schema_privileges(db)
    pg = _pg_table_model(snap)
    tables = [_sqlite_table_row(name, columns, pg) for name, columns in sorted(sqlite.items())]
    mapped = {t["pg_table"] for t in tables if t["pg_table"]}
    tables += [{"sqlite_table": None, "pg_table": t, "status": "POSTGRES_ONLY", "disposition": DISPOSITIONS.get(t),
                "columns": _column_rows([], pg[t]), "security": _security(pg[t])}
               for t in sorted(pg) if t.startswith("amc.") and t not in mapped]
    return {"schema": "amc-migration-mapping/v1", "migrations": [p.name for p in migration_files()],
            "postgres_catalog_sha256": snapshot_digest(snap), "row_level_security": _rls_summary(snap),
            "schema_privileges": privileges, "tables": tables, "summary": _mapping_summary(tables)}


def _rls_summary(snap: dict) -> dict:
    amc = [t for t in snap["tables"] if t[0].startswith("amc.")]
    return {"tables": len(amc), "rls_enabled": sum(1 for t in amc if t[1]), "policies": len(snap["policies"]),
            "isolation_model": "schema-level REVOKE from anon/authenticated + server-side amc.tenant_memberships authorization"}


def schema_privileges(dsn: str) -> dict:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("select r, has_schema_privilege(r, 'amc', 'USAGE') from unnest(array['anon','authenticated']) r").fetchall()
    return {role: {"amc_usage": usage} for role, usage in rows}


def _mapping_summary(tables: list[dict]) -> dict:
    cols = [c for t in tables for c in t["columns"]]
    count = lambda items, status: sum(1 for i in items if i["status"] == status)  # noqa: E731
    undisposed = [t["sqlite_table"] or t["pg_table"] for t in tables if t["status"] in ("LOCAL_ONLY", "POSTGRES_ONLY") and not t["disposition"]]
    return {"tables": {s: count(tables, s) for s in ("MAPPED", "RENAMED", "LOCAL_ONLY", "POSTGRES_ONLY")},
            "tables_without_disposition": undisposed,
            "columns": {s: count(cols, s) for s in ("MAPPED", "NOT_IN_POSTGRES", "TABLE_NOT_IN_POSTGRES", "POSTGRES_ONLY")},
            "type_translations": sorted({c["translation"] for c in cols if c.get("translation") not in (None, "identity")})}


def _markdown(mapping: dict) -> str:
    s = mapping["summary"]
    lines = ["# SQLite to PostgreSQL field mapping", "",
             "Generated by `python scripts/db_migrations.py mapping`; do not edit by hand. Machine-readable: `acceptance/migration_mapping.json`.", "",
             f"- Migrations: {len(mapping['migrations'])}; PostgreSQL catalog sha256 `{mapping['postgres_catalog_sha256']}`",
             f"- Tables: {s['tables']}", f"- Columns: {s['columns']}",
             f"- Row-level security: {mapping['row_level_security']}",
             f"- Schema privileges: {mapping['schema_privileges']}", "", "## Type translations", ""]
    lines += [f"- {t}" for t in s["type_translations"]] + ["", "## Tables", "",
              "| SQLite | PostgreSQL | Status | Columns mapped | Not in PostgreSQL | PostgreSQL only | Tenant FK | Disposition |", "|---|---|---|---|---|---|---|---|"]
    for t in mapping["tables"]:
        c = t["columns"]
        lines.append(f"| {t['sqlite_table'] or '—'} | {t['pg_table'] or '—'} | {t['status']} | "
                     f"{sum(1 for x in c if x['status'] == 'MAPPED')} | {sum(1 for x in c if x['status'] in ('NOT_IN_POSTGRES', 'TABLE_NOT_IN_POSTGRES'))} | "
                     f"{sum(1 for x in c if x['status'] == 'POSTGRES_ONLY')} | {t['security'].get('tenant_fk', '—')} | {t.get('disposition') or ''} |")
    return "\n".join(lines) + "\n"


def write_mapping(dsn: str) -> None:
    mapping = build_mapping(dsn)
    MAPPING_JSON.write_text(json.dumps(mapping, indent=1, default=str) + "\n", encoding="utf-8")
    MAPPING_MD.parent.mkdir(parents=True, exist_ok=True)
    MAPPING_MD.write_text(_markdown(mapping), encoding="utf-8")
    print(json.dumps(mapping["summary"]))


# ----------------------------------------------------------------------------- backfill
def _pg_columns(conn: psycopg.Connection, table: str) -> dict[str, str]:
    rows = conn.execute("""select a.attname, format_type(a.atttypid,a.atttypmod) from pg_attribute a
                           where a.attrelid = %s::regclass and a.attnum > 0 and not a.attisdropped""", (table,)).fetchall()
    return dict(rows)


def coerce(value: Any, pg_type: str) -> Any:
    """Translate one SQLite value to its PostgreSQL column type (see the mapping document)."""
    if value is None:
        return None
    if pg_type == "jsonb":
        return Jsonb(json.loads(value) if isinstance(value, str) else value)
    if pg_type.startswith("timestamp"):
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if pg_type == "boolean":
        return bool(value)
    return value


def canonical(value: Any) -> Any:
    """One normal form for both sides of the checksum."""
    if isinstance(value, Jsonb):
        value = value.obj
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, sort_keys=True, default=str))
    return value


def _fk_order(conn: psycopg.Connection, tables: list[str]) -> list[str]:
    snap = {"constraints": [tuple(r) for r in conn.execute(
        "select n.nspname||'.'||c.relname, k.conname, pg_get_constraintdef(k.oid) from pg_constraint k "
        "join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='amc'").fetchall()]}
    return list(reversed(_drop_order(tables, snap)))


def _copy_table(src: sqlite3.Connection, dst: psycopg.Connection, table: str, chunk: int, tenant: str | None) -> int:
    cols = _pg_columns(dst, f"amc.{table}")
    names = [r[1] for r in src.execute(f'pragma table_info("{table}")') if r[1] in cols]
    where, params = ("where tenant_id = ?", [tenant]) if tenant and "tenant_id" in names else ("", [])
    rowid, copied = 0, 0
    while True:
        rows = src.execute(f'select rowid, {", ".join(names)} from "{table}" {where} {"and" if where else "where"} rowid > ? '
                           f"order by rowid limit {chunk}", [*params, rowid]).fetchall()
        if not rows:
            return copied
        with dst.transaction():
            for row in rows:
                values = [coerce(v, cols[n]) for n, v in zip(names, row[1:])]
                dst.execute(f'insert into amc.{table} ({", ".join(names)}) values ({", ".join(["%s"] * len(names))}) on conflict do nothing', values)
        rowid, copied = rows[-1][0], copied + len(rows)


def table_checksum(rows: list[tuple]) -> str:
    return hashlib.sha256(json.dumps(sorted(json.dumps([canonical(v) for v in r], sort_keys=True, default=str) for r in rows)).encode()).hexdigest()


def _verify_table(src: sqlite3.Connection, dst: psycopg.Connection, table: str, tenant: str | None) -> dict:
    cols = _pg_columns(dst, f"amc.{table}")
    names = [r[1] for r in src.execute(f'pragma table_info("{table}")') if r[1] in cols]
    where, params = ("where tenant_id = ?", [tenant]) if tenant and "tenant_id" in names else ("", [])
    source = [tuple(coerce(v, cols[n]) for n, v in zip(names, r)) for r in src.execute(f'select {", ".join(names)} from "{table}" {where}', params)]
    pg_where = "where tenant_id = %s" if params else ""
    target = dst.execute(f'select {", ".join(names)} from amc.{table} {pg_where}', params).fetchall()
    ok = len(source) == len(target) and table_checksum(source) == table_checksum(target)
    return {"table": table, "rows": len(source), "pg_rows": len(target), "checksum": table_checksum(source), "verified": ok}


def backfill(sqlite_path: str, pg_dsn: str, tables: list[str], tenant: str | None = None, chunk: int = 500) -> list[dict]:
    """Idempotent, chunked, tenant-scoped copy followed by row-count and SHA-256 verification."""
    assert_ephemeral(pg_dsn)
    src = sqlite3.connect(sqlite_path)
    try:
        with psycopg.connect(pg_dsn) as dst:
            ordered = _fk_order(dst, [f"amc.{t}" for t in tables])
            for table in ordered:
                _copy_table(src, dst, table.split(".", 1)[1], chunk, tenant)
            return [_verify_table(src, dst, t.split(".", 1)[1], tenant) for t in ordered]
    finally:
        src.close()


# ----------------------------------------------------------------------------- cli
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["mapping", "rollback", "apply", "backfill"])
    parser.add_argument("--dsn", required=True, help="maintenance DSN on an ephemeral local server")
    parser.add_argument("--down", action="store_true")
    parser.add_argument("--sqlite")
    parser.add_argument("--tables", default="tenants,projects,runs,approvals")
    parser.add_argument("--tenant")
    args = parser.parse_args(argv)
    assert_ephemeral(args.dsn)
    if args.command == "mapping":
        write_mapping(args.dsn)
    elif args.command == "rollback":
        write_rollbacks(args.dsn)
    elif args.command == "apply":
        print(json.dumps(rollback_all(args.dsn) if args.down else apply_all(args.dsn)))
    else:
        print(json.dumps(backfill(args.sqlite, args.dsn, args.tables.split(","), args.tenant), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
