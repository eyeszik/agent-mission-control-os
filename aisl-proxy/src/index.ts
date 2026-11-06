import { buildServer } from './app.js';
import { loadEnv } from './config/env.js';
import { createContainer } from './container.js';
import { runMigrations } from './db/migrate.js';

async function main(): Promise<void> {
  const env = loadEnv();
  const deps = createContainer(env);
  const app = await buildServer(deps);

  // Migrations run at boot behind a Postgres advisory lock, so a rolling
  // deploy of N replicas applies them exactly once.
  const migrations = await runMigrations(deps.db);
  app.log.info({ applied: migrations.applied, skipped: migrations.skipped.length }, 'database migrations complete');

  let shuttingDown = false;
  const shutdown = async (signal: string): Promise<void> => {
    if (shuttingDown) return;
    shuttingDown = true;
    app.log.info({ signal }, 'shutting down');
    try {
      // Close the HTTP server first so in-flight checkouts finish against a
      // live database and Redis connection.
      await app.close();
      await deps.shutdown();
      process.exit(0);
    } catch (error) {
      app.log.error({ err: error }, 'graceful shutdown failed');
      process.exit(1);
    }
  };

  for (const signal of ['SIGTERM', 'SIGINT'] as const) {
    process.on(signal, () => {
      void shutdown(signal);
    });
  }

  await app.listen({ host: env.HOST, port: env.PORT });
  app.log.info({ host: env.HOST, port: env.PORT }, 'AISL proxy gateway listening');
}

main().catch((error: unknown) => {
  process.stderr.write(`fatal: ${error instanceof Error ? (error.stack ?? error.message) : String(error)}\n`);
  process.exit(1);
});
