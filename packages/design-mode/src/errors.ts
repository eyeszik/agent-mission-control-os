/** The errors Design Mode raises, named after their Python classes. */
import { pyRepr } from '@amc/kernel';

/**
 * Pydantic `ValidationError`. `valueErrors` holds the messages of the custom
 * validators Design Mode itself raises (Pydantic's `value_error` entries), in
 * Python's order; Pydantic's own type/range wording is not reproduced.
 */
export class ValidationError extends Error {
  override name = 'ValidationError';

  constructor(
    readonly model: string,
    readonly valueErrors: readonly string[],
    readonly details: readonly string[],
  ) {
    super(`validation failed for ${model}: ${[...valueErrors, ...details].join('; ') || 'invalid input'}`);
  }
}

/** Python `InvalidSelectionError(ValueError)`: the selection set itself is malformed. */
export class InvalidSelectionError extends Error {
  override name = 'InvalidSelectionError';
}

/** Python `UnknownStyleError(KeyError)`; `str()` of a KeyError is the repr of its key. */
export class UnknownStyleError extends Error {
  override name = 'UnknownStyleError';

  constructor(readonly styleId: string) {
    super(pyRepr(styleId));
  }
}
