import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadAppConfig } from '@amc/config';

export const buildFingerprint = config => createHash('sha256').update(JSON.stringify(config)).digest('hex');

export function validateBuild(directory = resolve('.next')) {
  const config = loadAppConfig(process.env);
  const stored = JSON.parse(readFileSync(resolve(directory, 'amc-config.json'), 'utf8'));
  if (!readFileSync(resolve(directory, 'BUILD_ID'), 'utf8').trim() ||
      stored.schema_version !== 'amc-web-build/v1' || stored.fingerprint !== buildFingerprint(config) ||
      stored.apiBaseUrl !== config.apiBaseUrl || stored.authMode !== config.authMode) {
    throw new Error('BUILD_CONFIGURATION_MISMATCH');
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { validateBuild(process.argv[2]); }
  catch { console.error('Frontend build configuration is missing or differs. Rebuild with the intended NEXT_PUBLIC_* configuration.'); process.exitCode = 1; }
}
