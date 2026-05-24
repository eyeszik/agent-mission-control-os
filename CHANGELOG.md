# CHANGELOG.md

## 1.0.0 — Repo-ready artifact bundle

### Added
- Added complete deterministic agent operating spec artifact files.
- Added Codex implementation prompt.
- Added Codex phase plan.
- Added Codex file handoff matrix.
- Added GitHub setup guide.
- Added repo bootstrap command script.
- Added `.codex/config.toml` starter config.
- Added GitHub pull request template.

### Decision
- Bundle is complete as an architecture/specification package.
- Bundle is not production-release approved.
- Repository audit is required before implementation.
- Cloudflare binding verification is required before edge deployment.
- Provider/tool contract verification is required before production adapters.

### Open Flags
- FLAG-REPO-NOT-PROVIDED
- FLAG-VERSIONS-NULL-UNTIL-REPO-AUDIT
- FLAG-CLOUDFLARE-BINDINGS-UNVERIFIED
- FLAG-OBSERVABILITY-ADAPTERS-UNVERIFIED
- FLAG-MCP-TRANSPORTS-UNVERIFIED
- FLAG-SEC-DISSENT-BLOCKS-PRODUCTION
- FLAG-RUNTIME-SCHEMA-VALIDATION-NOT-EXECUTED
