/**
 * @amc/vnexus-brandbook: the pure core of the VNEXUS brand book, byte-for-byte with
 * `services/langgraph/agency/vnexus/brandbook` (Python is the reference).
 *
 * Ported: the 24-page manifest, field states and the gap register, the canonical-master resolution rules, the page
 * compiler (packages, dependency hashes, prompts), the deterministic HTML/CSS renderer with its pagination estimate,
 * the page checks and the pure helpers of the build service.
 *
 * Left in Python: authorization, Project OS storage and the process cache (`service.py`), the deterministic mark
 * composition (`foundry.compose`), the SVG safety verifier (an XML parser), and the Chromium layout measurement,
 * overflow ladder and PDF render. Those enter the twin as typed input (`MarkSources`, `PageMeasurement`).
 *
 * Divergences from Python are recorded in `tests/fixtures/brandbook-parity.json` (explicit "Python accepts, TS
 * refuses" cases) and listed in docs/typescript-migration.md.
 *
 * - JS `number` cannot say `2` from `2.0`; genome values that are integral floats must be `CanonicalFloat`.
 * - Python's regex classes (`\s`, `\w`, `\d`) and `str.isdigit` come from `python-unicode.ts`, generated from
 *   Python's own engine, so the JS engine's Unicode version never decides a match.
 * - Exact half-even number formatting (`round`, `:.2f`, `:g`) is rebuilt on BigInt arithmetic, as in Wave 1.
 */
export * from './manifest';
export * from './fields';
export * from './assets';
export * from './contrast';
export * from './compiler';
export * from './pages';
export * from './compile';
export * from './render';
export * from './html';
export * from './checks';
export * from './service';
export * from './python';
export { canonicalHash, sha256 } from './hash';
