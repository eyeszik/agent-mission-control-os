import { loadEnv } from '../config/env.js';
import { createDatabase } from './pool.js';
import { runMigrations } from './migrate.js';

/** Standalone migration runner: `npm run migrate`. */
async function main(): Promise<void> {
  const env = loadEnv();
  const db = createDatabase(env);
  try {
    const result = await runMigrations(db);
    for (const name of result.applied) {
      process.stdout.write(`applied  ${name}\n`);
    }
    for (const name of result.skipped) {
      process.stdout.write(`skipped  ${name}\n`);
    }
    process.stdout.write(`${result.applied.length} migration(s) applied, ${result.skipped.length} already present\n`);
  } finally {
    await db.close();
  }
}

main().catch((error: unknown) => {
  process.stderr.write(`migration failed: ${error instanceof Error ? (error.stack ?? error.message) : String(error)}\n`);
  process.exit(1);
});
