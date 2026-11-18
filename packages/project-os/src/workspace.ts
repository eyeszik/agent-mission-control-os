/**
 * Pure parts of `agency/project_os/workspace.py`: path-segment safety, slugs,
 * the legacy-export folder map, workspace-relative paths and the project
 * manifest with its hash.
 *
 * Left in Python (they touch the filesystem): `materialize_manifest`,
 * `mirror_legacy_export`, `tree`, `existing_folders`, `sha256_file` and the
 * `Path.resolve()` containment check. That check can never fail for a path
 * built from `safeSegment` output (no separator or `..` survives it), so the
 * twin builds the relative path directly.
 */
import { z } from 'zod';
import { ProjectManifestSchema } from '@amc/shared';
import { WorkspacePathError } from './errors';
import { canonicalSha256, type PyJson } from './json';
import { lowerView, pyStrip } from './pytext';
import { PROJECT_LIFECYCLE_STATES, SYSTEM_FOLDERS, WORKSPACE_FOLDERS, parseEnum } from './vocabulary';
import { pyRepr } from '@amc/kernel';

export type ProjectManifest = z.infer<typeof ProjectManifestSchema>;

const SAFE_SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

/** Legacy run-first export subpaths → project semantic folders. The first matching prefix wins. */
export const LEGACY_FOLDER_MAP: readonly (readonly [string, string])[] = [
  ['business/', '03_strategy/business/'],
  ['branding/design-system/', '06_design/design-system/'],
  ['branding/rendered/', '08_creative/rendered/'],
  ['branding/prompts/', '07_prompts/run-prompts/'],
  ['branding/', '04_brand/'],
  ['design-system/', '06_design/design-system/'],
];

export const MANIFEST_AUTHORITY_NOTE =
  'The relational store is canonical. This manifest and the workspace mirror are materialized views ' +
  'and are never transactional authority.';

export function safeSegment(value: string, label: string): string {
  const text = pyStrip(value);
  if (!SAFE_SEGMENT.test(text) || text === '.' || text === '..') {
    throw new WorkspacePathError(`${label} is not a safe workspace path segment`);
  }
  return text;
}

export function slugify(value: string, fallback = 'project'): string {
  const dashed = lowerView(value).replace(/[^a-z0-9]+/g, '-');
  const slug = dashed.replace(/^-+|-+$/g, '').slice(0, 64).replace(/^-+|-+$/g, '');
  return slug || fallback;
}

/** `<export root>/projects/<tenant>/<project>` relative to the export root. */
export function projectRootRelative(tenantId: string, projectId: string): string {
  return `projects/${safeSegment(tenantId, 'tenant_id')}/${safeSegment(projectId, 'project_id')}`;
}

function cleanParts(parts: readonly string[]): string[] {
  return parts.map((part) => safeSegment(part, 'path segment'));
}

/** `folder_path(root, folder, *parts)` relative to the project root. */
export function folderRelativePath(folder: string, parts: readonly string[]): string {
  if (!(WORKSPACE_FOLDERS as readonly string[]).includes(folder)) {
    throw new WorkspacePathError(`unknown workspace folder ${pyRepr(folder)}`);
  }
  return [folder, ...cleanParts(parts)].join('/');
}

/** `system_path(root, folder, *parts)` relative to the project root. */
export function systemRelativePath(folder: string, parts: readonly string[]): string {
  if (!(SYSTEM_FOLDERS as readonly string[]).includes(folder)) {
    throw new WorkspacePathError(`unknown system folder ${pyRepr(folder)}`);
  }
  return ['.amc', folder, ...cleanParts(parts)].join('/');
}

/** Map a legacy run-first export path to its project-workspace location. */
export function mapLegacyRelative(relative: string): string {
  for (const [prefix, target] of LEGACY_FOLDER_MAP) {
    if (relative.startsWith(prefix)) return target + relative.slice(prefix.length);
  }
  return relative;
}

export interface BuildManifestArgs {
  readonly project_id: string;
  readonly tenant_id: string;
  readonly slug: string;
  readonly display_name: string;
  readonly lifecycle_state?: string;
  readonly brand_id?: string | null;
}

export function buildManifest(args: BuildManifestArgs): ProjectManifest {
  const { project_id, tenant_id } = args;
  return {
    schema_version: 'amc-workspace/v2',
    project_id,
    tenant_id,
    slug: args.slug,
    display_name: args.display_name,
    brand_id: args.brand_id ?? null,
    lifecycle_state: parseEnum('ProjectLifecycle', PROJECT_LIFECYCLE_STATES, args.lifecycle_state ?? 'ACTIVE'),
    folders: [...WORKSPACE_FOLDERS],
    system_folders: [...SYSTEM_FOLDERS],
    memory_namespace: `memory://${tenant_id}/${project_id}`,
    artifact_index_ref: `db://agency_artifacts?project_id=${project_id}`,
    source_registry_ref: `db://knowledge_items?project_id=${project_id}`,
    rights_registry_ref: `db://asset_rights?project_id=${project_id}`,
    authority_note: MANIFEST_AUTHORITY_NOTE,
  };
}

/** SHA-256 of the manifest's canonical JSON. A proof of identity, never an approval. */
export function manifestHash(manifest: ProjectManifest): string {
  return canonicalSha256(manifest as unknown as PyJson);
}
