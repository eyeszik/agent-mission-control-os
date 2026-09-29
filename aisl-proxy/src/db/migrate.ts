import { readdir, readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { Database } from './pool.js';

const MIGRATIONS_DIR = join(dirname(fileURLToPath(import.meta.url)), 'migrations');

/** Namespaced advisory lock so two booting replicas cannot migrate concurrently. */
const MIGRATION_LOCK_ID = 8_251_974_120_031n;

export interface MigrationResult {
  applied: string[];
  skipped: string[];
}

export async function runMigrations(db: Database, dir: string = MIGRATIONS_DIR): Promise<MigrationResult> {
  const files = (await readdir(dir)).filter((name) => name.endsWith('.sql')).sort();
  const applied: string[] = [];
  const skipped: string[] = [];

  await db.query(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      name VARCHAR(255) PRIMARY KEY,
      applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);

  await db.query('SELECT pg_advisory_lock($1)', [MIGRATION_LOCK_ID.toString()]);
  try {
    const { rows } = await db.query<{ name: string }>('SELECT name FROM schema_migrations');
    const done = new Set(rows.map((row) => row.name));

    for (const file of files) {
      if (done.has(file)) {
        skipped.push(file);
        continue;
      }
      const sql = await readFile(join(dir, file), 'utf8');
      await db.transaction(async (tx) => {
        await tx.query(sql);
        await tx.query('INSERT INTO schema_migrations (name) VALUES ($1)', [file]);
      });
      applied.push(file);
    }
  } finally {
    await db.query('SELECT pg_advisory_unlock($1)', [MIGRATION_LOCK_ID.toString()]);
  }

  return { applied, skipped };
}
