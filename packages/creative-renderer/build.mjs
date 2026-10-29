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

// Each browser adapter is a separate sealed bundle; no input supplies code or URLs.
const {build} = await import('esbuild');
const engines=['p5_js','pixi_js','react_three_fiber','remotion','motion_canvas'];
await build({entryPoints:Object.fromEntries(engines.map(name=>[name,new URL(`./adapters/${name}.mjs`,import.meta.url).pathname])),outdir:new URL('./dist/browser/',import.meta.url).pathname,bundle:true,format:'iife',globalName:'AMCAdapter',platform:'browser',target:'es2022',minify:true,legalComments:'inline',define:{'process.env.NODE_ENV':'"production"'}});
const manifest={packages:{},files:[]};
for(const [name] of Object.entries(JSON.parse(readFileSync(new URL('./package.json',import.meta.url))).dependencies)) {
 let directory=new URL('./',`file://${require.resolve(name)}`);
 while(true) {
  const location=new URL('package.json',directory);
  try {
   const meta=JSON.parse(readFileSync(location));
   if(meta.name===name) {
    const license=readdirSync(directory).find(file=>/^licen[sc]e(?:\.|$)/i.test(file));
    const fallback=name==='@react-three/fiber' ? new URL('./licenses/react-three-fiber.txt',import.meta.url) : null;
    if(fallback){const source=JSON.parse(readFileSync(new URL('./licenses/sources.json',import.meta.url)))[name];if(source.version!==meta.version)throw new Error(`LICENSE_VERSION_MISMATCH:${name}`);}
    if(!license && !fallback)throw new Error(`LICENSE_NOT_FOUND:${name}`);
    const filename=`LICENSE.${name.replaceAll('/','_').replaceAll('@','')}`;
    writeFileSync(new URL(`./dist/browser/${filename}`,import.meta.url),readFileSync(license ? new URL(license,directory) : fallback));
    manifest.packages[name]={version:meta.version,license:meta.license,license_file:filename};break;
   }
  }catch(error){if(error.message.startsWith('LICENSE_NOT_FOUND:'))throw error;}
  const parent=new URL('../',directory);if(parent.href===directory.href)throw new Error(`PACKAGE_NOT_FOUND:${name}`);directory=parent;
 }
}
manifest.files=readdirSync(new URL('./dist/browser/',import.meta.url)).sort();
writeFileSync(new URL('./dist/browser/manifest.json',import.meta.url),JSON.stringify(manifest,null,2));
