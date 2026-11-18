/**
 * Error classes mirroring the Python exceptions the guidance registry and the
 * prompt compiler raise. `name` carries the Python class name so a caller (and
 * the parity suite) can tell them apart without matching on message text.
 */

/** Python `ValueError`. */
export class PyValueError extends Error {
  override name = 'ValueError';
}

/** Python `json.JSONDecodeError` (a ValueError); `message` is Python's text. */
export class JSONDecodeError extends PyValueError {
  override name = 'JSONDecodeError';
}

/** Python `UnicodeEncodeError`, raised by `str.encode('utf-8')` on a lone surrogate. */
export class UnicodeEncodeError extends PyValueError {
  override name = 'UnicodeEncodeError';
}

/** Python `KeyError`; `message` is `repr(key)`. */
export class PyKeyError extends Error {
  override name = 'KeyError';
}

/** Raised where Python would call the UI/UX compiler but no adapter was supplied: fail closed. */
export class UiUxAdapterMissingError extends Error {
  override name = 'UiUxAdapterMissingError';
}

export type Loc = readonly (string | number)[];

/** One Pydantic `errors()` entry. `msg` is only exact for `value_error`. */
export interface ValidationIssue {
  readonly loc: Loc;
  readonly type: string;
  readonly msg: string;
}

/** Twin of `pydantic.ValidationError`: the issue list is the contract, not the rendered text. */
export class ValidationError extends PyValueError {
  override name = 'ValidationError';
  constructor(readonly issues: readonly ValidationIssue[]) {
    super(issues.map((issue) => `${issue.loc.join('.')}: ${issue.msg}`).join('\n'));
  }
}
