/**
 * Error classes mirroring the Python exceptions `agency/compiled` (and the
 * RoleOS helpers it calls) raise. `name` carries the Python class name so the
 * parity suite, or a caller, can tell them apart without parsing messages.
 */

/** Python `ValueError`. */
export class CompiledValueError extends Error {
  override name = 'ValueError';
}

/** Python `KeyError`; `message` is already `str(KeyError(...))`, i.e. the repr of the key. */
export class CompiledKeyError extends Error {
  override name = 'KeyError';
}

/** Python `TypeError`. */
export class CompiledTypeError extends Error {
  override name = 'TypeError';
}

/** Python `AttributeError`. */
export class CompiledAttributeError extends Error {
  override name = 'AttributeError';
}

/** Python `IndexError`. */
export class CompiledIndexError extends Error {
  override name = 'IndexError';
}

/** `backchain.BackchainCycleError` (a ValueError). */
export class BackchainCycleError extends CompiledValueError {
  override name = 'BackchainCycleError';
}

/** `decisions.DecisionError` (a ValueError). */
export class DecisionError extends CompiledValueError {
  override name = 'DecisionError';
}

/** `execution.CellTransitionError` (a ValueError). */
export class CellTransitionError extends CompiledValueError {
  override name = 'CellTransitionError';
}

/** `learning.LearningLedgerError` (a ValueError). */
export class LearningLedgerError extends CompiledValueError {
  override name = 'LearningLedgerError';
}

/** `method_catalog.CatalogError` (a ValueError). */
export class CatalogError extends CompiledValueError {
  override name = 'CatalogError';
}

/** `method_mission.MethodCompileError`: message is `"<code>: <detail>"`. */
export class MethodCompileError extends CompiledValueError {
  override name = 'MethodCompileError';
  readonly code: string;

  constructor(code: string, detail: string) {
    super(`${code}: ${detail}`);
    this.code = code;
  }
}

/** `role_os.RoleResolutionError` (a RuntimeError). */
export class RoleResolutionError extends Error {
  override name = 'RoleResolutionError';
}

/** `role_os.WorkOrderError` (a RuntimeError). */
export class WorkOrderError extends Error {
  override name = 'WorkOrderError';
}

/** `role_os.MissionAdapterError` (a RuntimeError). */
export class MissionAdapterError extends Error {
  override name = 'MissionAdapterError';
}

/** One Pydantic error: where it happened and Pydantic's error type, where the twin can name it. */
export interface ValidationIssue {
  readonly loc: readonly (string | number)[];
  readonly message: string;
}

/**
 * Pydantic `ValidationError`. Pydantic's rendered message is not reproduced
 * (it embeds the Pydantic version URL); the parity suite compares the error
 * locations instead, which are what a caller can act on.
 */
export class CompiledValidationError extends Error {
  override name = 'ValidationError';
  readonly issues: readonly ValidationIssue[];

  constructor(model: string, issues: readonly ValidationIssue[]) {
    super(`${issues.length} validation error${issues.length === 1 ? '' : 's'} for ${model}`);
    this.issues = issues;
  }
}
