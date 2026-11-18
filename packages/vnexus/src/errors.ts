/**
 * Error classes whose `name` matches the Python exception class the reference
 * raises, so a caller (and the parity suite) can tell them apart exactly.
 */

/** Python `ValueError`. The VNEXUS domain errors below subclass it, as in Python. */
export class PyValueError extends Error {
  override name: string = 'ValueError';
}

/** `genome.GenomeTransitionError`: a lifecycle move the version's status does not allow. */
export class GenomeTransitionError extends PyValueError {
  override name = 'GenomeTransitionError';
}

/** `multiverse.BranchTransitionError`. */
export class BranchTransitionError extends PyValueError {
  override name = 'BranchTransitionError';
}

/** `graph.GraphError`. */
export class GraphError extends PyValueError {
  override name = 'GraphError';
}

/** `statistics.StatisticsError` (a ValueError subclass). */
export class StatisticsError extends PyValueError {
  override name = 'StatisticsError';
}

/** Python `OverflowError` (date arithmetic beyond year 9999). */
export class PyOverflowError extends Error {
  override name = 'OverflowError';
}

export interface ValidationIssue {
  readonly loc: string;
  readonly msg: string;
  /** The message of a model's own `ValueError` (Pydantic's "Value error, ..." without the prefix). */
  readonly custom: boolean;
}

/**
 * Pydantic `ValidationError` (a ValueError subclass). Every issue is collected,
 * as Pydantic does; `customMessages` are the messages the Python models' own
 * validators raise, which the parity suite compares verbatim. Built-in checks
 * (types, lengths, patterns) are reported in this package's own words.
 */
export class ValidationError extends PyValueError {
  override name = 'ValidationError';
  readonly issues: readonly ValidationIssue[];

  constructor(title: string, issues: readonly ValidationIssue[]) {
    super(`${issues.length} validation error(s) for ${title}\n${issues.map((i) => `${i.loc}: ${i.msg}`).join('\n')}`);
    this.issues = issues;
  }

  get customMessages(): string[] {
    return this.issues.filter((i) => i.custom).map((i) => i.msg);
  }
}

/**
 * Thrown where the Python reference would accept an input whose behaviour this
 * twin cannot reproduce faithfully. Refusing is the explicit alternative to a
 * silent divergence; each refusal has a fixture case.
 */
export class VnexusDivergenceError extends Error {
  override name = 'VnexusDivergenceError';
}

/** Python `KeyError` (its message is the repr of the missing key). */
export class PyKeyError extends Error {
  override name = 'KeyError';
}

/** Python `TypeError`. */
export class PyTypeError extends Error {
  override name = 'TypeError';
}

/** Python `ZeroDivisionError`. */
export class PyZeroDivisionError extends Error {
  override name = 'ZeroDivisionError';
}
