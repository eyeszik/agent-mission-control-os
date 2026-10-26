import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync, readdirSync } from 'node:fs';
const require = createRequire(import.meta.url);
mkdirSync(new URL('./dist/', import.meta.url), { recursive: true });
const source = readFileSync(new URL('./worker.mjs', import.meta.url), 'utf8');
writeFileSync(new URL('./dist/worker.mjs', import.meta.url), source.replace("from 'roughjs'", "from './rough.cjs'"));
writeFileSync(new URL('./dist/rough.cjs', import.meta.url), readFileSync(require.resolve('roughjs')));

const packageRoot = new URL('./node_modules/roughjs/', import.meta.url);
const license = readdirSync(packageRoot).find(name => /^license(?:\.|$)/i.test(name));
if (!license) throw new Error('ROUGH_LICENSE_NOT_FOUND');
writeFileSync(new URL('./dist/LICENSE.roughjs', import.meta.url), readFileSync(new URL(license, packageRoot)));
