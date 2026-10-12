# October 2026 dependency integration

Integrates PRs #129–#134 on top of the merged #127/#128 implementation.

- Resolve dependency manifests and regenerate the lockfile with the repository's pinned pnpm 10.29.3.
- Keep TypeScript 7.0.2 for compilation, target ES2022, and retain TypeScript 5.9.3 under the explicit `typescript-api` alias for the legacy compiler-API-based UI gate. The alias is a development-only parser dependency; it does not replace the compiler or disable the gate.
- Use Tailwind 4.3.3's PostCSS package, explicitly load the existing token configuration, migrate removed directives, and preserve v3 utility sizes, accessible outlines and preflight defaults. Browser support follows Tailwind 4: Safari 16.4+, Chrome 111+, Firefox 128+.
- Pin the browser gate and lockfile assertions to Playwright 1.64.0 together.
- Retain the latest tenant/project-scoped recovery fixes and genome editor updates from master.
- Regenerate integrity hashes from reviewed file bytes without weakening any verifier.

Validation before remote CI: all seven verifier gates, workspace builds/typechecks/unit tests, 80 web tests, UI AST gate and production build passed in the repair workspace. After reconciling current master, all 79 action-plane tests passed. The local full-backend run was interrupted before completion and is not counted as a pass. Local Playwright browser download failed because the returned archive was invalid; remote browser CI is required before merging. A browser regression checks semantic Tailwind colors and migrated radius/blur sizes.

No production migrations, provider activation, spending or deployment are part of this change.
