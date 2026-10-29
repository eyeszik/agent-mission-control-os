/**
 * N4 — artifact registry: branch lineage, serialization, and merge resolution
 * (twin of `agency/kernel/registry.py`).
 *
 * Pure and in-memory, exactly like the Python module: nothing here touches a
 * database. Versions are immutable; a merge is resolved by the declared
 * matrix, never by "last write wins".
 */
import { KernelKeyError, KernelTypeError, KernelValueError, MergeError } from './errors';
import { ARTIFACT_STATUSES, isMember, type ArtifactStatus } from './models';
import { assertDepartmentOwns, resolveArtifactType, resolveDepartment, type ArtifactType, type Department } from './ontology';
import { isPlainObject, PyFloat, pyRepr, pyStr, pyTruthy, pyTypeName } from './pyformat';
import { pyJsonDumps, type PyJsonValue } from './pyjson';
import { sha256Hex } from './sha256';

export const REGISTRY_VERSION = 'amc-agency-registry/n4-v1';
export const MAIN_BRANCH = 'main';

export const MERGE_RESOLUTIONS = ['fast_forward', 'take_incoming', 'keep_base', 'merge_content', 'escalate'] as const;
export type MergeResolution = (typeof MERGE_RESOLUTIONS)[number];

/** One immutable point in an artifact's lineage. Field names match the Python serialization. */
export interface ArtifactVersion {
  readonly artifact_id: string;
  readonly branch: string;
  readonly version: number;
  readonly status: ArtifactStatus;
  readonly artifact_type: ArtifactType;
  readonly owner_department: Department;
  readonly content_hash: string;
  readonly parent_version: number | null;
  /** The version on the base branch this branch forked from. Null on main. */
  readonly forked_from: number | null;
  readonly generation_mode: string | null;
  readonly assumptions: readonly string[];
  readonly metadata: Record<string, unknown>;
}

export interface SerializedVersion extends Omit<ArtifactVersion, 'assumptions'> {
  readonly assumptions: string[];
}

export function serializeVersion(version: ArtifactVersion): SerializedVersion {
  return { ...version, assumptions: [...version.assumptions] };
}

/** Stable content hash: SHA-256 of Python's `json.dumps(content, sort_keys=True, separators=(",", ":"))`. */
export function contentFingerprint(content: PyJsonValue): string {
  const encoded = pyJsonDumps(content);
  return sha256Hex(Uint8Array.from(encoded, (ch) => ch.charCodeAt(0)));
}

// --------------------------------------------------------------------------
// Deserialization (mirrors Python's coercions; anything Python would only
// store un-coerced, such as a non-string artifact_id, is refused instead)
// --------------------------------------------------------------------------

function requireKey(payload: Record<string, unknown>, key: string): unknown {
  if (!Object.prototype.hasOwnProperty.call(payload, key)) throw new KernelKeyError(pyRepr(key));
  return payload[key];
}

function requireString(payload: Record<string, unknown>, key: string): string {
  const value = requireKey(payload, key);
  if (typeof value !== 'string') throw new KernelTypeError(`${key} must be a string, got '${pyTypeName(value)}'`);
  return value;
}

const INT_LITERAL = /^\s*[+-]?\d+(?:_\d+)*\s*$/;

function intFromString(value: string): number {
  if (!INT_LITERAL.test(value)) throw new KernelValueError(`invalid literal for int() with base 10: ${pyRepr(value)}`);
  const parsed = Number(value.trim().replace(/_/g, ''));
  if (!Number.isSafeInteger(parsed)) throw new KernelValueError(`int ${pyRepr(value)} is outside the safe range`);
  return parsed;
}

function intFromNumber(value: number): number {
  if (Number.isNaN(value)) throw new KernelValueError('cannot convert float NaN to integer');
  if (!Number.isFinite(value)) throw new KernelValueError('cannot convert float infinity to integer');
  const truncated = Math.trunc(value) + 0;
  if (!Number.isSafeInteger(truncated)) throw new KernelValueError(`int ${value} is outside the safe range`);
  return truncated;
}

/** Python `int(value)` for the JSON-shaped values a payload can carry. */
export function pyInt(value: unknown): number {
  if (typeof value === 'boolean') return value ? 1 : 0;
  if (typeof value === 'number') return intFromNumber(value);
  if (value instanceof PyFloat) return intFromNumber(value.value);
  if (typeof value === 'bigint') return intFromNumber(Number(value));
  if (typeof value === 'string') return intFromString(value);
  throw new KernelTypeError(
    `int() argument must be a string, a bytes-like object or a real number, not '${pyTypeName(value)}'`,
  );
}

function optionalNumber(payload: Record<string, unknown>, key: string): number | null {
  const value = payload[key] ?? null;
  if (value === null || typeof value === 'number') return value;
  throw new KernelTypeError(`${key} must be an int or None, got '${pyTypeName(value)}'`);
}

function optionalString(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key] ?? null;
  if (value === null || typeof value === 'string') return value;
  throw new KernelTypeError(`${key} must be a str or None, got '${pyTypeName(value)}'`);
}

function assumptionsFrom(raw: unknown): string[] {
  if (!pyTruthy(raw)) return [];
  if (typeof raw === 'string') return Array.from(raw); // tuple("ab") iterates code points
  if (Array.isArray(raw) && raw.every((item): item is string => typeof item === 'string')) return [...raw];
  throw new KernelTypeError(`assumptions must be a list of str, got '${pyTypeName(raw)}'`);
}

function metadataFrom(raw: unknown): Record<string, unknown> {
  if (!pyTruthy(raw)) return {};
  if (isPlainObject(raw)) return raw;
  throw new KernelTypeError(`metadata must be a dict, got '${pyTypeName(raw)}'`);
}

function statusFrom(value: unknown): ArtifactStatus {
  if (isMember(ARTIFACT_STATUSES, value)) return value;
  const shown = typeof value === 'string' ? pyRepr(value) : pyStr(value);
  throw new KernelValueError(`${shown} is not a valid ArtifactStatus`);
}

function asRecord(payload: unknown): Record<string, unknown> {
  if (isPlainObject(payload)) return payload;
  throw new KernelTypeError(`payload must be a dict, got '${pyTypeName(payload)}'`);
}

/** Python `ArtifactVersion.deserialize`. Fields are read in Python's order, so the first failure matches. */
export function deserializeVersion(raw: unknown): ArtifactVersion {
  const payload = asRecord(raw);
  return {
    artifact_id: requireString(payload, 'artifact_id'),
    branch: requireString(payload, 'branch'),
    version: pyInt(requireKey(payload, 'version')),
    status: statusFrom(requireKey(payload, 'status')),
    artifact_type: resolveArtifactType(requireKey(payload, 'artifact_type')),
    owner_department: resolveDepartment(requireKey(payload, 'owner_department')),
    content_hash: requireString(payload, 'content_hash'),
    parent_version: optionalNumber(payload, 'parent_version'),
    forked_from: optionalNumber(payload, 'forked_from'),
    generation_mode: optionalString(payload, 'generation_mode'),
    assumptions: assumptionsFrom(payload['assumptions']),
    metadata: metadataFrom(payload['metadata']),
  };
}

// --------------------------------------------------------------------------
// Merge resolution matrix, keyed by (base status, incoming status)
// --------------------------------------------------------------------------

type MatrixRow = Readonly<Record<ArtifactStatus, MergeResolution>>;

function row(
  draft: MergeResolution, validating: MergeResolution, approved: MergeResolution, releaseEligible: MergeResolution,
  released: MergeResolution, reviewRequired: MergeResolution, invalidated: MergeResolution, archived: MergeResolution,
): MatrixRow {
  return {
    draft, validating, approved, release_eligible: releaseEligible, released,
    review_required: reviewRequired, invalidated, archived,
  };
}

const TI = 'take_incoming';
const KB = 'keep_base';
const MC = 'merge_content';
const ES = 'escalate';

/** `MERGE_MATRIX[base][incoming]`. Asymmetric on purpose: released work is never silently replaced. */
export const MERGE_MATRIX: Readonly<Record<ArtifactStatus, MatrixRow>> = {
  draft: row(MC, TI, TI, TI, TI, TI, KB, KB),
  validating: row(ES, MC, TI, TI, TI, TI, TI, KB),
  approved: row(ES, ES, ES, TI, TI, TI, TI, KB),
  release_eligible: row(ES, ES, ES, ES, TI, TI, TI, KB),
  released: row(ES, ES, ES, ES, ES, TI, TI, ES),
  review_required: row(KB, KB, ES, ES, ES, MC, TI, KB),
  invalidated: row(TI, TI, ES, ES, ES, TI, KB, TI),
  archived: row(KB, KB, KB, KB, KB, KB, KB, KB),
};

/** Every (base, incoming) pair has a resolution, and an archived base is terminal. */
export function validateMergeMatrix(): string[] {
  const problems: string[] = [];
  for (const base of ARTIFACT_STATUSES) {
    for (const incoming of ARTIFACT_STATUSES) {
      const resolution = MERGE_MATRIX[base]?.[incoming];
      if (resolution === undefined) {
        problems.push(`merge matrix missing resolution for base '${base}' + incoming '${incoming}'`);
      } else if (base === 'archived' && resolution !== 'keep_base') {
        problems.push(`archived base must be terminal, but (${base}, ${incoming}) resolves to ${resolution}`);
      }
    }
  }
  return problems;
}

export interface MergeOutcome {
  readonly resolution: MergeResolution;
  readonly winner: ArtifactVersion | null;
  readonly reason: string;
  readonly requires_human: boolean;
}

export function serializeOutcome(outcome: MergeOutcome): Record<string, unknown> {
  return { ...outcome, winner: outcome.winner ? serializeVersion(outcome.winner) : null };
}

function matrixOutcome(base: ArtifactVersion, incoming: ArtifactVersion): MergeOutcome {
  const resolution = MERGE_MATRIX[base.status][incoming.status];
  const winner = resolution === 'escalate' ? null : resolution === 'keep_base' ? base : incoming;
  return {
    resolution,
    winner,
    reason: `base '${base.status}' + incoming '${incoming.status}' resolves to ${resolution}`,
    requires_human: resolution === 'escalate',
  };
}

/** Resolve `incoming` into `base`. Checks run in Python's order: degraded, identical, unmoved base, matrix. */
export function resolveMerge(base: ArtifactVersion, incoming: ArtifactVersion): MergeOutcome {
  if (incoming.artifact_type !== base.artifact_type) {
    throw new MergeError(`cannot merge artifact type '${incoming.artifact_type}' into '${base.artifact_type}'`);
  }
  if ((incoming.generation_mode ?? '') === 'FALLBACK_DEGRADED') {
    return { resolution: 'escalate', winner: null, reason: 'incoming branch carries FALLBACK_DEGRADED provenance',
      requires_human: true };
  }
  if (incoming.content_hash === base.content_hash) {
    return { resolution: 'fast_forward', winner: base, reason: 'incoming content is identical to base',
      requires_human: false };
  }
  if (incoming.forked_from !== null && incoming.forked_from === base.version) {
    return { resolution: 'fast_forward', winner: incoming, reason: 'base has not advanced since the branch forked',
      requires_human: false };
  }
  return matrixOutcome(base, incoming);
}

export interface CommitInput {
  readonly branch: string;
  readonly status: ArtifactStatus;
  readonly artifact_type: string;
  readonly owner_department: string;
  readonly content: PyJsonValue;
  readonly generation_mode?: string | null;
  readonly assumptions?: Iterable<string>;
  readonly metadata?: Record<string, unknown> | null;
}

export interface SerializedRegistry {
  readonly registry_version: string;
  readonly artifact_id: string;
  readonly versions: SerializedVersion[];
}

/** In-memory lineage over one artifact's versions across branches. */
export class ArtifactRegistry {
  private versions: ArtifactVersion[] = [];

  constructor(readonly artifactId: string) {}

  /** Append an immutable version to a branch. N1 ownership is enforced at write time. */
  commit(input: CommitInput): ArtifactVersion {
    const artifactType = resolveArtifactType(input.artifact_type);
    const department = resolveDepartment(input.owner_department);
    assertDepartmentOwns(department, artifactType);
    // Python types `status` as an ArtifactStatus member and does not check it; the twin fails closed.
    const status = statusFrom(input.status);
    const head = this.head(input.branch);
    const forkedFrom = this.forkPoint(input.branch, head);
    const version: ArtifactVersion = {
      artifact_id: this.artifactId, branch: input.branch, version: this.versions.length + 1, status,
      artifact_type: artifactType, owner_department: department, content_hash: contentFingerprint(input.content),
      parent_version: head ? head.version : null, forked_from: forkedFrom,
      generation_mode: input.generation_mode ?? null, assumptions: [...(input.assumptions ?? [])],
      metadata: input.metadata && pyTruthy(input.metadata) ? input.metadata : {},
    };
    this.versions.push(version);
    return version;
  }

  private forkPoint(branch: string, head: ArtifactVersion | null): number | null {
    if (head) return head.forked_from;
    if (branch === MAIN_BRANCH) return null;
    const mainHead = this.head(MAIN_BRANCH);
    if (!mainHead) throw new MergeError(`cannot open branch '${branch}' before '${MAIN_BRANCH}' has a version`);
    return mainHead.version;
  }

  head(branch: string): ArtifactVersion | null {
    for (let i = this.versions.length - 1; i >= 0; i -= 1) {
      const version = this.versions[i];
      if (version && version.branch === branch) return version;
    }
    return null;
  }

  /** Branch names in first-seen order. */
  branches(): string[] {
    return [...new Set(this.versions.map((v) => v.branch))];
  }

  lineage(branch: string): ArtifactVersion[] {
    return this.versions.filter((v) => v.branch === branch);
  }

  allVersions(): ArtifactVersion[] {
    return [...this.versions];
  }

  /** Resolve `incomingBranch` into `baseBranch` via the matrix. */
  merge(incomingBranch: string, baseBranch: string = MAIN_BRANCH): MergeOutcome {
    const incoming = this.head(incomingBranch);
    const base = this.head(baseBranch);
    if (!incoming) throw new MergeError(`branch '${incomingBranch}' has no versions to merge`);
    if (!base) throw new MergeError(`base branch '${baseBranch}' has no versions`);
    return resolveMerge(base, incoming);
  }

  serialize(): SerializedRegistry {
    return { registry_version: REGISTRY_VERSION, artifact_id: this.artifactId, versions: this.versions.map(serializeVersion) };
  }

  static deserialize(raw: unknown): ArtifactRegistry {
    const payload = asRecord(raw);
    if (payload['registry_version'] !== REGISTRY_VERSION) {
      throw new MergeError(
        `unsupported registry version '${pyStr(payload['registry_version'])}'; expected ${REGISTRY_VERSION}`,
      );
    }
    const registry = new ArtifactRegistry(requireString(payload, 'artifact_id'));
    const versions = requireKey(payload, 'versions');
    if (!Array.isArray(versions)) throw new KernelTypeError(`versions must be a list, got '${pyTypeName(versions)}'`);
    registry.versions = versions.map(deserializeVersion);
    return registry;
  }
}
