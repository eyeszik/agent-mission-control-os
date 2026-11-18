/**
 * @amc/vnexus-directions: the pure core of VNEXUS creative directions, behaviour-for-behaviour with
 * `services/langgraph/agency/vnexus/directions` (Python is the reference).
 *
 * Ported: record vocabularies and validation, the intent compiler (intake decisions, direction slots, handoff), the
 * route registry and spend rules, the 14-lens review board (findings, five non-compensatory gates, verdicts,
 * comparison, refinement, work orders), reconstruction rules and storage key derivation.
 *
 * Left in Python (taken as typed input): image analysis (PNG decode, Chromium raster, Lab distances, perceptual
 * hash), SVG parsing and the safety verifier (`CandidateMeasurement`, `Geometry`), the prompt compiler and the AVIC
 * prompt filters (`IntentHooks`), env/browser probing (`RouteEnv`), the AVIC trace, persistence, approvals and the
 * Project OS ledger. Hosted generation routes stay DISABLED; NOT_RUN / NOT_VERIFIED / PROVIDER_GAP are never a pass.
 */
export * from './records';
export * from './validate';
export * from './measure';
export * from './intent';
export * from './providers';
export * from './board';
export * from './verdict';
export * from './session';
export * from './reconstruct';
