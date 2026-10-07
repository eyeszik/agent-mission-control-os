# Contract 01 — Brand Policy

Core constraint: convert the approved brand brief into consistent creative decisions; no unsupported public claims or copied distinctive reference expression. Use one main message/CTA per region; pair status color with text or icons. Bind claims to source, owner, market, expiry and approval. Missing evidence blocks affected public use, not safe drafting. Preserve accessible type, imagery and motion. Deliver policy, claim ledger and version-specific decision record. At most three attempts per correction; unresolved gaps go to the accountable owner. Publication requires separate explicit authorization.

## Required output contract

Schemas describe types; they are not completed evidence. Document non-applicability without violating field types.

```yaml
brand_policy:
  brand: {name: string, approved_marks: [asset_ref]}
  audience: {segments: [string], accessibility_needs: [string]}
  positioning: {category: string, promise: string, differentiation: string}
  voice: {traits: [string], approved_terms: [string], restricted_terms: [string]}
  visual_system:
    atmosphere: string
    colors: {brand: [token], neutral: [token], semantic: [token]}
    type: {display: token, body: token, data: token}
    imagery: {modes: [photo|illustration|3d|collage], treatment: string}
    composition: {grid: string, density: sparse|balanced|dense, motion: string}
  claims: [{id: string, text: string, source_ref: string, owner: string, expiry: date|null}]
  approvals: [{role: brand_owner|legal|client, decision: approved|rejected, ts_utc: RFC3339}]
```

`brand-policy.yaml`, `claim-ledger.csv`, approved asset references and decision record are required. The ledger adds applicable geography and approval/version references; do not overload `source_ref`. Tokens resolve to actual palette/type definitions: role, scale, line height and fallback. Imagery defines subject, crop anchor, lighting, grade, background and treatment.

## Creative decisions

Record signature tension, silhouette, edges, rhythm, material/information logic and image/type/motion behavior. Choose dominant tension/material/information rules; justify deviations. Abstract references into contrast, density, pacing, framing, material and semantic role. Review marks, composition, trade dress, characters and distinctive expression; no global novelty or clearance guarantee.

State a falsifiable distinction from supplied references. Select narrative movements: arrival/atmosphere, friction/problem, evidence/proof, participation/action, resonance/memory; not all are mandatory.

## Gates and completion proof

Done: evidenced field completeness, current claims, system coherence, channel fit, signature integrity and exact-version brand approval. Index outputs; record each check/result/evidence/reviewer. Text creation establishes neither approval nor compliance.

## Edge cases

1. Unknown/expired claim evidence: omit the claim or block its public use pending owner review.
2. Conflicting brand/reference direction: approved brand policy and rights restrictions prevail; log the conflict.
3. Inapplicable visual or CTA role: document the reason; do not invent an asset or action to fill a field.
