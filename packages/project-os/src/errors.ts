/**
 * Error classes whose `name` is the Python exception class they mirror, so a
 * fixture's recorded `{type, message}` can be compared directly.
 */
export class PyValueError extends Error {
  override name = 'ValueError';
}

export class PyTypeError extends Error {
  override name = 'TypeError';
}

export class PyOverflowError extends Error {
  override name = 'OverflowError';
}

export class PyRuntimeError extends Error {
  override name = 'RuntimeError';
}

/** `str.encode('utf-8')` on a string with lone surrogates. */
export class PyUnicodeEncodeError extends PyValueError {
  override name = 'UnicodeEncodeError';
}

export class ContentTransitionError extends PyValueError {
  override name = 'ContentTransitionError';
}

export class ContentLineageError extends PyValueError {
  override name = 'ContentLineageError';
}

export class MemoryPolicyError extends PyValueError {
  override name = 'MemoryPolicyError';
}

export class WorkspacePathError extends PyValueError {
  override name = 'WorkspacePathError';
}

export class UnknownWorkstream extends PyValueError {
  override name = 'UnknownWorkstream';
}

export class VideoBridgeError extends PyValueError {
  override name = 'VideoBridgeError';
}

export class StorageUnavailable extends PyRuntimeError {
  override name = 'StorageUnavailable';
}

export class StorageIntegrityError extends PyRuntimeError {
  override name = 'StorageIntegrityError';
}

export class PublicationBlocked extends PyRuntimeError {
  override name = 'PublicationBlocked';
}
