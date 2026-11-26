import { readFileSync } from 'node:fs';
const { detect } = await import(process.argv[2] + '/dist/lib/detectors.js');
const cases = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const opt = { detectPii: true, detectSecrets: true, detectNames: false, detectAddresses: false, entropyScan: false,
  minEntropy: 3.5, defaultPhoneRegion: 'US', entityTypes: [], allowList: [] };
const out = [];
for (const c of cases) {
  const f = await detect(c.text, opt);
  const s = c.sensitive ? c.text.indexOf(c.sensitive) : -1;
  const covered = s >= 0 && f.some((x) => x.start <= s + 2 && x.end >= s + c.sensitive.length - 2);
  out.push({ kind: c.kind, positive: c.positive, flagged: f.length > 0, covered, types: [...new Set(f.map((x) => x.type))] });
}
console.log(JSON.stringify(out));
