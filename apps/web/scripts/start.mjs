import { resolve } from 'node:path';
import { spawn } from 'node:child_process';
import { validateBuild } from './check-build.mjs';

try { validateBuild(); }
catch {
  console.error('Frontend build configuration is missing or differs. Rebuild with the intended NEXT_PUBLIC_* configuration.');
  process.exit(1);
}
const child = spawn(process.execPath, [resolve('node_modules/next/dist/bin/next'), 'start', ...process.argv.slice(2)], { stdio: 'inherit' });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('error', () => { console.error('Frontend could not start'); process.exitCode = 1; });
child.on('exit', (code, signal) => { process.exitCode = code ?? (signal === 'SIGINT' ? 130 : 143); });
