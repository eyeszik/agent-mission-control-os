import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, writeFileSync, readdirSync, cpSync } from 'node:fs';
const require = createRequire(import.meta.url);
mkdirSync(new URL('./dist/', import.meta.url), { recursive: true });
const source = readFileSync(new URL('./worker.mjs', import.meta.url), 'utf8');
writeFileSync(new URL('./dist/worker.mjs', import.meta.url), source
  .replace("from 'roughjs'", "from './rough.cjs'")
  .replace("from 'paper/dist/paper-core.js'", "from './paper.cjs'")
  .replace("from '@svgdotjs/svg.js'", "from './svg.cjs'"));
writeFileSync(new URL('./dist/rough.cjs', import.meta.url), readFileSync(require.resolve('roughjs')));

const packageRoot = new URL('./node_modules/roughjs/', import.meta.url);
const license = readdirSync(packageRoot).find(name => /^license(?:\.|$)/i.test(name));
if (!license) throw new Error('ROUGH_LICENSE_NOT_FOUND');
writeFileSync(new URL('./dist/LICENSE.roughjs', import.meta.url), readFileSync(new URL(license, packageRoot)));
writeFileSync(new URL('./dist/paper.cjs', import.meta.url), readFileSync(require.resolve('paper/dist/paper-core.js')));
cpSync(new URL('./node_modules/paper/dist/node/', import.meta.url), new URL('./dist/node/', import.meta.url), { recursive: true });
writeFileSync(new URL('./dist/LICENSE.paper', import.meta.url), readFileSync(new URL('./node_modules/paper/LICENSE.txt', import.meta.url)));
// Paper's Node helpers are CommonJS, even though the workspace is ESM.
writeFileSync(new URL('./dist/node/package.json', import.meta.url), JSON.stringify({ type: 'commonjs' }));
writeFileSync(new URL('./dist/svg.cjs', import.meta.url), readFileSync(require.resolve('@svgdotjs/svg.js')));
writeFileSync(new URL('./dist/LICENSE.svgjs', import.meta.url), readFileSync(new URL('./node_modules/@svgdotjs/svg.js/LICENSE.txt', import.meta.url)));
