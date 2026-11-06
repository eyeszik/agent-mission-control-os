# Provider matrix

Generated from `catalog()` at the time of writing. `GET /actions/catalog` returns the current matrix. The
capability-drift radar (`GET /actions/drift`) compares each declaration with what a probe observes on the host.

"Risk" is the nominal class in SANDBOX. A real request can only be **raised** above this by its facts (scope,
audience, data class, bulk size), never lowered.

| Action | Dispatch owner | Risk | Status | Live | Reason |
|---|---|---|---|---|---|
| `sandbox.research.fetch_public` | actions.gateway | R0 | TESTED | UNAVAILABLE | sandbox fake; serves documentation fixtures only (`example.com`, `example.org`); no network |
| `sandbox.cms.create_draft` | actions.gateway | R2 | TESTED | LIVE_GATED | sandbox fake; outputs are SIMULATED |
| `sandbox.cms.publish_page` | actions.gateway | R3 | TESTED | LIVE_GATED | sandbox fake; outputs are SIMULATED |
| `sandbox.email.send` | actions.gateway | R3 | TESTED | LIVE_GATED | sandbox fake; outputs are SIMULATED |
| `sandbox.ads.commit_spend` | actions.gateway | R4 | TESTED | LIVE_GATED | sandbox ledger; no money moves |
| `sandbox.storage.delete_assets` | actions.gateway | R5 | TESTED | LIVE_GATED | always BLOCKED with `STEP_UP_UNAVAILABLE`: step-up authentication does not exist |
| `sandbox.governance.grant_role` | actions.gateway | R6 | TESTED | LIVE_GATED | sandbox fake; needs an independent owner/admin governance approval |
| `publication.dry_run` | api.operations | R1 | IMPLEMENTED | LIVE_GATED | existing dry-run publication |
| `publication.publish` | none (no live adapter) | R3 | LIVE_GATED | NOT_IMPLEMENTED | `AMC_PUBLICATION_MODE` beyond `dry_run` raises; no reviewed adapter |
| `project_os.scheduled_publish` | project_os.scheduler | R3 | LIVE_GATED | NOT_IMPLEMENTED | the live publication registry ships empty |
| `paid_media.request_authorization` | api.operations | R1 | IMPLEMENTED | LIVE_GATED | records a request only |
| `paid_media.execute_spend` | none (no live adapter) | R4 | LIVE_GATED | NOT_IMPLEMENTED | `spend_execution_available()` returns False unconditionally |
| `fabric.brand_logo_svg` | execution_fabric | R1 | IMPLEMENTED | LIVE_GATED | deterministic SVG |
| `fabric.dtcg_token_compile` | execution_fabric | R1 | IMPLEMENTED | LIVE_GATED | |
| `fabric.design_system_spec_compile` | execution_fabric | R1 | IMPLEMENTED | LIVE_GATED | |
| `fabric.uiux_dom_audit` | execution_fabric | R1 | IMPLEMENTED | LIVE_GATED | stdlib-DOM WCAG 2.2 audit |
| `fabric.code_patch_sandbox` | execution_fabric | R1 | IMPLEMENTED | LIVE_GATED | Python-only code sandbox |
| `fabric.seo_audit` | execution_fabric | R1 | IMPLEMENTED | LIVE_GATED | local checks |
| `fabric.fvf_ingest_verify` | execution_fabric | R1 | IMPLEMENTED | LIVE_GATED | needs `ffprobe` on the host |
| `fabric.t2i_image_generate` | execution_fabric | R1 | PROVIDER_GAP | LIVE_GATED | provider `t2i` is not installed |
| `fabric.ai_video_generate` | execution_fabric | R1 | PROVIDER_GAP | LIVE_GATED | provider `ai_video` is not installed |
| `fabric.seo_search_volume` | execution_fabric | R1 | PROVIDER_GAP | LIVE_GATED | provider `search_volume` is not installed |
| `fabric.zo_ask` | execution_fabric | R0 | PROVIDER_GAP | UNAVAILABLE | provider `zo` is not installed |
| `vnexus.local_svg` | vnexus.media_fabric | R1 | IMPLEMENTED | LIVE_GATED | |
| `vnexus.local_svg_motion` | vnexus.media_fabric | R1 | IMPLEMENTED | LIVE_GATED | |
| `vnexus.local_chromium_raster` | vnexus.media_fabric | R1 | IMPLEMENTED | LIVE_GATED | local Chromium |
| `vnexus.local_chromium_pdf` | vnexus.media_fabric | R1 | IMPLEMENTED | LIVE_GATED | local Chromium |
| `vnexus.local_pillow_webp` | vnexus.media_fabric | R1 | IMPLEMENTED | LIVE_GATED | |
| `vnexus.mock_simulated` | vnexus.media_fabric | R1 | UNAVAILABLE | LIVE_GATED | `MOCK_PROVIDERS_DISABLED` |
| `vnexus.hosted_text_to_image` | vnexus.media_fabric | R4 | PROVIDER_GAP | PROVIDER_GAP | adapter not implemented; no credentials; paid calls not authorized |
| `vnexus.hosted_text_to_video` | vnexus.media_fabric | R4 | PROVIDER_GAP | PROVIDER_GAP | same |
| `vnexus.hosted_image_to_video` | vnexus.media_fabric | R4 | PROVIDER_GAP | PROVIDER_GAP | same |

## Reserved namespaces

| Namespace | Status | Lookup result |
|---|---|---|
| `EXT-001` … `EXT-090` | VOID_DETECTED | `NOT_IMPLEMENTED`: no source definition exists in the repository; no description is invented |
| `ART-001` … `ART-012` | VOID_DETECTED | same |

## Only one owner dispatches each action

Only `actions.gateway` entries can be proposed through `/actions`. Fabric and VNEXUS entries keep their own
dispatch paths and are described here so that the matrix is complete. Proposing one of them through the gateway
returns `409 NOT_GATEWAY_OWNED` (T08, I02).

## Plugins and connectors are not providers

Connectors or plugins available to an assistant session (for example design, CMS, commerce or ad tools) are
**not** callable by this runtime. None is a dependency, none is listed above, and none is invoked by any test.
Adding one means writing and reviewing a provider adapter behind the gateway, not configuration.
