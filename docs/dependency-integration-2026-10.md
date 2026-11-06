# October 2026 dependency integration

Reconciles #136 with current master while retaining the commits from #129–#134.
Already merged setup-node 7.1.0, Lucide 1.53.0, Tailwind 4.3.3 and Playwright
1.64.0 remain pinned; Framer Motion 14.0.0 and TypeScript 7.0.2 are integrated.

- Compile with TypeScript 7 and target ES2022. Keep the legacy compiler API used
  by the UI AST gate under the development-only `typescript-api` 5.9.3 alias.
- Preserve Tailwind v3 radius/blur sizes, accessible outlines and preflight
  defaults with v4 utilities. Keep the v4 PostCSS adapter and semantic token
  configuration; remove unused Autoprefixer. Tailwind 4 requires Safari 16.4+,
  Chrome 111+ or Firefox 128+.
- Use Node 22.12.0 in frontend, browser and JavaScript audit CI. Vitest 5's
  engine (`^22.12.0 || ^24.0.0 || >=26.0.0`) sets the workspace minimum;
  Node 20.20.2 satisfies Next but does not satisfy Vitest. Match the root
  engine, README and repository invariant. Retain pinned pnpm 10.29.3.
- Preserve current master's accessibility test and backend changes. Keep the
  browser gate single-worker with zero retries; no tests are newly skipped.

## Reproduce

With Node 22.12.0 and Corepack enabled, run from the repository root:

```sh
pnpm install --frozen-lockfile
pnpm build
pnpm typecheck
pnpm test
pnpm --filter @amc/web verify:ui
```

The production build, typechecks, all 271 workspace unit tests, UI AST gate and
all eight Chromium E2E tests passed locally on Node 22.12.0. The CI browser job
in `.github/workflows/ci.yml` contains the complete backend/frontend startup
and environment settings needed to rerun `pnpm --filter @amc/web test:e2e`.

For backend checks, install `./services/langgraph[dev]` into a virtual environment.
If local Chromium is available, install Pillow as well for the optional SVG
capture verifier. Blender-dependent tests require the separate visual extra.

## Regenerate and revert

Regenerate the dependency lockfile with `pnpm install --lockfile-only`, then
verify with `pnpm install --frozen-lockfile`. After reviewing changes to files
covered by the integrity manifest, refresh their existing entries without
changing the manifest's scope:

```sh
python - <<'PY'
import json
from pathlib import Path
from scripts.verify_manifest import git_blob_sha
p = Path('manifest.json')
payload = json.loads(p.read_text())
for entry in payload['files']:
    entry['git_blob_sha'] = git_blob_sha(Path(entry['path']).read_bytes())
p.write_text(json.dumps(payload, indent=2) + '\n')
PY
python scripts/verify_manifest.py
```

The repair is a merge commit whose first parent is current master. To undo the
repair after merging, use `git revert -m 1 <repair-commit>` and rerun the checks
above. No separate non-minimal migrations or follow-up issues are required.
