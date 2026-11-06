# Governed rendering

Eight render engines now have bounded **data-only primitive profiles**, not arbitrary source-code execution. Existing SVG profiles and legacy identities remain supported. The browser profiles add still PNG and frame-based MP4/WebM output. GPU-backed libraries use Chromium's explicitly selected software WebGL path; physical GPU execution is not claimed.

| Engine | Implemented profile | Outputs |
| --- | --- | --- |
| Rough.js | seeded paths | SVG |
| Paper.js | headless paths, no PaperScript/DOM/text | SVG |
| SVG.js | PathArray geometry | SVG |
| p5 | seeded P2D instance, explicit frame drawing | PNG, MP4, WebM |
| Pixi | WebGL Graphics, manual render calls | PNG, MP4, WebM |
| React Three Fiber | React-19-compatible orthographic shapes and strokes | PNG, MP4, WebM |
| Remotion | Player frame seeking and useCurrentFrame composition | PNG, MP4, WebM, **license-gated** |
| Motion Canvas | Scene2D rendering at an explicit playback frame | PNG, MP4, WebM |

The frame encoder is local FFmpeg, not Remotion Lambda or Motion Canvas's Vite exporter. MP4 is H.264/yuv420p; WebM is VP9/yuv420p. Audio, fonts, imported assets, arbitrary JS/TSX, general 3D scenes, shaders, browser URLs and remote object storage remain unsupported. A request cannot enable them. Browser profiles require a working network namespace and refuse execution if it cannot be established.

## Install and run

```sh
pnpm install --frozen-lockfile
pnpm --filter @amc/creative-renderer build
python -m pip install -e './services/langgraph[dev,rendering]'
pnpm --filter @amc/web exec playwright install --with-deps chromium
# Install ffmpeg and ffprobe through your host's package manager.
```

Use the normal backend/web setup and open `/creative`. The selected engine determines valid output choices. Video defaults to 30 frames at 30 fps and a bounded horizontal translation; API callers may specify the rational frame rate, frame count and optional motion.x/motion.y end offsets. Browser requests are limited to 120 frames and 64 million total pixels; video requires even dimensions. No long render runs inside the submit endpoint.

The existing trusted local driver still works:

```sh
python -m services.langgraph.agency.rendering.worker --job RENDER_JOB_ID
python -m services.langgraph.agency.rendering.worker --once
```

Existing SVG fields and omitted optional fields preserve legacy spec-hash projections. New media identities bind the browser bundles, direct dependency license bytes, actual Chromium/FFmpeg/ffprobe binaries, driver/contract code, pinned package graph and request/frame parameters. Transitive implementation code is bundled with legal comments retained. This records identity and notices; it does not constitute organization-specific license clearance. The R3F npm archive omitted a license; its exact release-source license and provenance are checked into packages/creative-renderer/licenses.

## Remotion license decisions

Installing Remotion does not authorize use. Its pinned license distinguishes free eligibility and company licensing. An authorized approver must record a scoped decision through `POST /foundry/projects/{project_id}/render-license`, with `permitted`, a substantive `basis`, and nonempty `evidence_refs` to the applicable eligibility or license records. The server binds the actual pinned license hash to that decision. This is an accountable operator decision, not automatic legal verification. Revocation, conflicting memory or changed license bytes blocks dispatch; it does not supply artifact-release approval.

The capability endpoint accepts an optional `project_id`; it authorizes access before checking that project's decision. Without a decision, Remotion does not execute even its capability probe. Tests use explicitly fictional projects and the pinned license's non-commercial evaluation provision, never an invented production entitlement.

## Remote execution

A remote worker pulls one explicit job over the existing authenticated API. It needs a narrowly project-scoped operator/service principal, the exact repository/bundles and matching runtime binaries. It receives no database connection, storage credentials, export-root path or permission to release. The control plane retains storage and verification authority.

- `POST /foundry/projects/{project}/renders/{job}/claim`: atomically allocates a 300-second lease/fence and persists the durable intent before returning the sealed spec. An immutable saved candidate is recovered by server readback rather than blindly rerendered.
- `POST .../{job}/heartbeat`: extends only that authenticated worker's unexpired lease.
- `POST .../{job}/complete`: accepts a fence, SHA-256 and bounded base64 bytes (16 MB decoded maximum), independently verifies the received bytes, and registers an artifact under the live fence. No worker-supplied URI/path is accepted.

```sh
# Obtain the token through your established identity system. Do not put it in CLI args.
# AMC_RENDER_WORKER_TOKEN is read only by the authenticated HTTP client.
python -m services.langgraph.agency.rendering.remote_worker \
  --url https://CONTROL_PLANE --tenant TENANT_ID --project PROJECT_ID \
  --job RENDER_JOB_ID --out /private/render-receipt
```

HTTPS is mandatory outside explicit loopback tests. Redirects are refused before forwarding Authorization. Child render/encoder processes receive a scrubbed environment and no worker token. Same-worker completion retries for identical bytes are idempotent; different bytes, other workers, expired leases and cancelled/taken-over fences are refused. The local receipt contains candidate data, not credentials, and is written with private permissions. A lost response can be retried without rendering again:

```sh
python -m services.langgraph.agency.rendering.remote_worker \
  --url https://CONTROL_PLANE --tenant TENANT_ID --project PROJECT_ID \
  --job RENDER_JOB_ID --out /private/render-receipt \
  --completion /private/render-receipt/completion.json
```

This implements transport, not a deployment: no remote worker fleet, queue broker, presigned object store, production credentials, paid compute or always-on supervisor has been provisioned. Use existing production auth and TLS. The current role model uses project-scoped operators; it does not introduce a separate worker-only permission vocabulary. Deployment hardening, quotas and large streaming uploads require separate review.

## Verification and lifecycle

Compute success is recorded separately from artifact verification. PNG checks fully decode persisted pixels, verify dimensions/CRC and refuse blank/flat output. Video checks actual container, codec, dimensions, rational fps and decoded frame count, then independently decodes every frame. These checks do not certify semantic equivalence to every scene constraint, brand approval or full accessibility conformance. The final artifact always needs current, exact, scoped human release approval.

Cancellation revokes canonical acceptance; it does not claim a remote process stopped. A late worker may finish computing but cannot register an accepted artifact. Release checks re-read current stored bytes, subject/version/hash and purpose-bound approval. Authenticated existing SSE observes committed events; GET never executes work. The preview uses video controls without autoplay for video artifacts.

Quarantine remains approver-only through `POST /foundry/projects/{id}/render-quarantine`: new dispatch and canonical acceptance are blocked; scoped cancellation revokes active leases; accepted historical bytes and audit records remain.

## Tests and rollback

```sh
python -m pytest services/langgraph/tests/test_rendering.py services/langgraph/tests/test_rendering_media_remote.py -q -rs
pnpm --filter @amc/creative-renderer test
pnpm typecheck
pnpm test
pnpm build
python scripts/verify_manifest.py
```

The dedicated `Rendering adapters + video + remote protocol` CI job builds the actual dependencies, installs Chromium/FFmpeg/Pillow, establishes namespaces and fails if any capability test skips. Other backend cohorts may explicitly skip unavailable media; their counts are not equivalent coverage. Local HTTP tests validate transport and refusal behavior with a fictional principal; production bearer-token verification remains owned by the existing authentication stack.

Revert this feature's commit to remove it; no database migration is required. Preserve artifacts, approvals and audit history already written. Regenerate affected manifest entries with scripts.verify_manifest.git_blob_sha (Git blob SHA-1), never raw SHA-256. No project foundations, creative-direction decisions or production approvals are synthesized by installation.
