import { mkdirSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { buildFingerprint } from './check-build.mjs';
import { loadAppConfig } from '@amc/config';

const config = loadAppConfig(process.env);
const destination = resolve('.next/amc-config.json');
rmSync(destination, { force: true });
const result = spawnSync(process.execPath, [resolve('node_modules/next/dist/bin/next'), 'build', ...process.argv.slice(2)], { stdio: 'inherit' });
if (result.error || result.status !== 0) process.exitCode = result.status || 1;
else {
  mkdirSync(resolve('.next'), { recursive: true });
  const temporary = `${destination}.tmp`;
  writeFileSync(temporary, JSON.stringify({ schema_version: 'amc-web-build/v1', apiBaseUrl: config.apiBaseUrl, authMode: config.authMode, fingerprint: buildFingerprint(config) }) + '\n', { mode: 0o600 });
  renameSync(temporary, destination);
}
