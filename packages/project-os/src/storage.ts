/**
 * Pure parts of `agency/project_os/storage.py`: content-hash validation,
 * local object locations, backend selection and the fail-closed R2
 * description.
 *
 * Left in Python (they read or write bytes): `LocalStorageAdapter.put_bytes /
 * get_bytes / exists`. The R2 adapter writes nothing in either language: it
 * reports `UNVERIFIED_EXTERNAL_BINDING` and refuses.
 */
import { pyRepr } from '@amc/kernel';
import { StorageIntegrityError, StorageUnavailable } from './errors';
import { pyStrip } from './pytext';
import { STORAGE_BACKENDS, parseEnum } from './vocabulary';
import { projectRootRelative, safeSegment } from './workspace';

const HEX64 = /^[0-9a-f]{64}$/;
const LOCAL_PREFIX = 'local://';

export function isHash(value: string): boolean {
  return HEX64.test(value);
}

export interface LocalObjectLocation {
  /** Relative to the export root. */
  readonly relative_path: string;
  readonly storage_uri: string;
}

/** Where `LocalStorageAdapter` keeps (and names) the object with this hash. */
export function localObjectLocation(tenantId: string, projectId: string, contentHash: string): LocalObjectLocation {
  if (!isHash(contentHash)) throw new StorageIntegrityError('content hash must be a sha256 hex digest');
  const root = projectRootRelative(tenantId, projectId);
  return {
    relative_path: `${root}/.amc/objects/${contentHash.slice(0, 2)}/${contentHash}`,
    storage_uri: `${LOCAL_PREFIX}${tenantId}/${projectId}/${contentHash}`,
  };
}

/** `LocalStorageAdapter._parse`: `[tenant_id, project_id, content_hash]` of a local URI. */
export function parseLocalUri(storageUri: string): [string, string, string] {
  if (!storageUri.startsWith(LOCAL_PREFIX)) throw new StorageUnavailable('not a local storage URI');
  const parts = storageUri.slice(LOCAL_PREFIX.length).split('/');
  if (parts.length !== 3) throw new StorageUnavailable('malformed local storage URI');
  const [tenantId, projectId, contentHash] = parts as [string, string, string];
  safeSegment(tenantId, 'tenant_id');
  safeSegment(projectId, 'project_id');
  return [tenantId, projectId, contentHash];
}

/**
 * `object_storage_backend()` from the raw `AMC_OBJECT_STORAGE_BACKEND` value.
 * Case mapping of non-ASCII text uses the JS engine; it only reaches the
 * error message, since no non-ASCII text can spell LOCAL or R2.
 */
export function objectStorageBackend(raw: string | undefined): (typeof STORAGE_BACKENDS)[number] {
  const value = pyStrip(raw || 'local').toUpperCase();
  try {
    return parseEnum('StorageBackend', STORAGE_BACKENDS, value);
  } catch {
    throw new StorageUnavailable(`Unsupported AMC_OBJECT_STORAGE_BACKEND=${pyRepr(value.toLowerCase())}`);
  }
}

export interface R2Status {
  readonly backend: 'R2';
  readonly available: false;
  readonly binding: 'UNVERIFIED_EXTERNAL_BINDING';
  readonly bucket_configured: boolean;
  readonly account_configured: boolean;
  readonly credentials_configured: boolean;
}

const configured = (value: string | undefined): boolean => pyStrip(value || '') !== '';

/** Presence booleans only; never echoes a credential value. */
export function r2Status(env: Readonly<Record<string, string | undefined>>): R2Status {
  return {
    backend: 'R2',
    available: false,
    binding: 'UNVERIFIED_EXTERNAL_BINDING',
    bucket_configured: configured(env.AMC_R2_BUCKET),
    account_configured: configured(env.AMC_R2_ACCOUNT_ID),
    credentials_configured: configured(env.AMC_R2_ACCESS_KEY_ID) && configured(env.AMC_R2_SECRET_ACCESS_KEY),
  };
}

/** Every R2 operation fails closed with this; no write is ever pretended. */
export function r2Refusal(): StorageUnavailable {
  return new StorageUnavailable(
    'UNVERIFIED_EXTERNAL_BINDING: R2 object storage has no reviewed client adapter; ' +
      'use AMC_OBJECT_STORAGE_BACKEND=local until one is installed',
  );
}
