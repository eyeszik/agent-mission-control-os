/**
 * Error classes mirroring the Python exceptions the kernel raises.
 *
 * `name` carries the Python class name (`OntologyError`, `ValueError`, ...) so a
 * caller, or the parity suite, can tell them apart without string matching on
 * messages. The hierarchy follows Python: every kernel error is a ValueError.
 */

/** Python `ValueError`, raised directly by enum lookups and `int()` parsing. */
export class KernelValueError extends Error {
  override name = 'ValueError';
}

/** Python `KeyError`. `message` is `repr(key)`, exactly as `str(KeyError(key))` renders it. */
export class KernelKeyError extends Error {
  override name = 'KeyError';
}

/** Python `TypeError`, raised when a value has a type the operation cannot take. */
export class KernelTypeError extends Error {
  override name = 'TypeError';
}

/** N1: a value outside the closed department / artifact-type vocabulary. */
export class OntologyError extends KernelValueError {
  override name = 'OntologyError';
}

/** N2: an illegal or unguarded lifecycle move. */
export class TransitionError extends KernelValueError {
  override name = 'TransitionError';
}

/** N3: a role dispatched outside its declared contract. */
export class RoleContractError extends KernelValueError {
  override name = 'RoleContractError';
}

/** N4: a merge or registry operation across incompatible artifacts. */
export class MergeError extends KernelValueError {
  override name = 'MergeError';
}
