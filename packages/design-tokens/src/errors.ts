/** Python `TokenError` hierarchy: every failure names the token path that caused it. */
export class TokenError extends Error {
  static readonly CODE: string = 'TOKEN_ERROR';
  override name = 'TokenError';
  /** The machine code, e.g. `TOKEN_SCHEMA`. */
  readonly code: string;
  /** The offending token path, or `''` when the error is document-wide. */
  readonly path: string;
  /** The message without the `CODE: path: ` prefix. */
  readonly detail: string;

  constructor(message: string, path = '') {
    const code = (new.target as typeof TokenError).CODE;
    super(`${code}: ${path ? `${path}: ` : ''}${message}`);
    this.code = code;
    this.path = path;
    this.detail = message;
  }
}

export class TokenSchemaError extends TokenError {
  static override readonly CODE: string = 'TOKEN_SCHEMA';
  override name = 'TokenSchemaError';
}

export class MissingAliasError extends TokenError {
  static override readonly CODE: string = 'TOKEN_MISSING_ALIAS';
  override name = 'MissingAliasError';
}

export class TokenCycleError extends TokenError {
  static override readonly CODE: string = 'TOKEN_ALIAS_CYCLE';
  override name = 'TokenCycleError';
  readonly chain: readonly string[];

  constructor(chain: readonly string[]) {
    super(chain.join(' -> '), chain[0] ?? '');
    this.chain = [...chain];
  }
}

export class TokenTypeError extends TokenError {
  static override readonly CODE: string = 'TOKEN_TYPE';
  override name = 'TokenTypeError';
}

export class TokenTierError extends TokenError {
  static override readonly CODE: string = 'TOKEN_TIER';
  override name = 'TokenTierError';
}

/**
 * TypeScript only: a value JS cannot carry unambiguously (an integral `number`
 * beyond 2^53 reaching the source hash). Python never raises this; it exists so
 * the twin refuses instead of hashing a guess. Pass a `bigint` or `CanonicalFloat`.
 */
export class TokenAmbiguityError extends TokenError {
  static override readonly CODE: string = 'TOKEN_AMBIGUOUS';
  override name = 'TokenAmbiguityError';
}
