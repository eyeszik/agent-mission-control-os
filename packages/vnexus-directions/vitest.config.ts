import { defineConfig } from 'vitest/config';

// The workspace packages build to CommonJS and resolve to their real paths under /packages/. Inlining them keeps one
// copy of `CanonicalFloat` (an `instanceof` check in @amc/canonical decides how a float is hashed) shared by the tests,
// this package and its dependencies.
export default defineConfig({ test: { server: { deps: { inline: [/\/packages\/(canonical|kernel|vnexus-brandbook)\//] } } } });
