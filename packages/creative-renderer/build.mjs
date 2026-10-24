import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
mkdirSync(new URL('./dist/', import.meta.url), { recursive: true });
const source = readFileSync(new URL('./worker.mjs', import.meta.url), 'utf8');
writeFileSync(new URL('./dist/worker.mjs', import.meta.url), source.replace("from 'roughjs'", "from './rough.cjs'"));
writeFileSync(new URL('./dist/rough.cjs', import.meta.url), readFileSync(require.resolve('roughjs')));
