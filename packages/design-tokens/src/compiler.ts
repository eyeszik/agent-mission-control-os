/**
 * READ -> VALIDATE -> RESOLVE_ALIASES -> DETECT_CYCLES -> TYPECHECK -> NORMALIZE
 * -> GENERATE_CSS, each step fail-closed with the offending token path.
 */
import {
  MissingAliasError,
  TokenCycleError,
  TokenSchemaError,
  TokenTierError,
  TokenTypeError,
} from './errors';
import { sourceHash } from './json';
import { normalizeValue } from './normalize';
import {
  PythonRuntimeError,
  isMapping,
  pyGet,
  pyRepr,
  pyStrip,
  pyTypeName,
  sortedStrings,
  type Mapping,
} from './python';

export const COMPILER_VERSION = 'amc-dtcg-compiler/v1';
export const DTCG_FORMAT = 'DTCG 2025.10';

export const SUPPORTED_TYPES: ReadonlySet<string> = new Set([
  'color', 'dimension', 'duration', 'fontFamily', 'fontWeight', 'cubicBezier', 'number',
]);
const TOKEN_PROPERTIES: ReadonlySet<string> = new Set(['$value', '$type', '$description', '$extensions', '$deprecated']);
const GROUP_PROPERTIES: ReadonlySet<string> = new Set(['$type', '$description', '$extensions', '$deprecated', '$schema']);

// Python `re.match` with `$` also accepts one trailing "\n"; `\n?$` reproduces that.
const ALIAS = /^\{([^{}]+)\}\n?$/;
const NAME = /^[A-Za-z0-9_-]+\n?$/;
const CAMEL = /(?<=[a-z0-9])([A-Z])/g;

export const TIER_PRIMITIVE = 'primitive';
export const TIER_SEMANTIC = 'semantic';
export const TIER_COMPONENT = 'component';
export const TIERS: readonly string[] = [TIER_PRIMITIVE, TIER_SEMANTIC, TIER_COMPONENT];

export interface RawToken {
  readonly path: string;
  readonly value: unknown;
  readonly declaredType: string | null;
  readonly inheritedType: string | null;
  readonly description: unknown;
}

export class ResolvedToken {
  constructor(
    readonly path: string,
    readonly type: string,
    /** The literal (post-alias) DTCG value. */
    readonly value: unknown,
    /** Normalized CSS value of the literal. */
    readonly css: string,
    /** Direct alias target, preserved for var() emission. */
    readonly aliasOf: string | null,
    readonly description: unknown = null,
  ) {}

  get tier(): string | null {
    const head = this.path.split('.')[0] ?? '';
    return TIERS.includes(head) ? head : null;
  }
}

export class TokenGraph {
  constructor(
    /** Ordered by path (code-point order), like the Python dict. */
    readonly tokens: ReadonlyMap<string, ResolvedToken>,
    readonly sourceHash: string,
    readonly tiered = false,
    readonly warnings: readonly string[] = [],
  ) {}

  get(path: string): ResolvedToken {
    const token = this.tokens.get(path);
    if (token === undefined) throw new PythonRuntimeError('KeyError', pyRepr(path));
    return token;
  }
}

// --------------------------------------------------------------------------- READ / VALIDATE

function groupTypeOf(node: Mapping, inherited: string | null, here: string): string | null {
  if (!Object.hasOwn(node, '$type')) return inherited;
  const declared = node['$type'];
  if (typeof declared !== 'string') throw new TokenSchemaError('$type must be a string', here);
  return declared;
}

function readToken(child: Mapping, dotted: string, groupType: string | null): RawToken {
  const unknown = sortedStrings(Object.keys(child).filter((key) => !TOKEN_PROPERTIES.has(key)));
  if (unknown.length > 0) throw new TokenSchemaError(`unknown token properties ${pyRepr(unknown)}`, dotted);
  const declared = pyGet(child, '$type');
  const declaredType = typeof declared === 'string' ? declared : null;
  if (declared !== null && declaredType === null) throw new TokenSchemaError('$type must be a string', dotted);
  return {
    path: dotted,
    value: child['$value'],
    declaredType,
    inheritedType: groupType,
    description: pyGet(child, '$description'),
  };
}

function walkChild(child: unknown, path: readonly string[], groupType: string | null, out: Map<string, RawToken>): void {
  const dotted = path.join('.');
  if (isMapping(child) && Object.hasOwn(child, '$value')) {
    out.set(dotted, readToken(child, dotted, groupType));
  } else if (isMapping(child)) {
    walk(child, path, groupType, out);
  } else {
    throw new TokenSchemaError('expected a token (object with $value) or a group', dotted);
  }
}

function walk(node: unknown, prefix: readonly string[], inherited: string | null, out: Map<string, RawToken>): void {
  const here = prefix.join('.');
  if (!isMapping(node)) throw new TokenSchemaError('group must be an object', here);
  const groupType = groupTypeOf(node, inherited, here);
  for (const key of sortedStrings(Object.keys(node))) {
    if (key.startsWith('$')) {
      if (!GROUP_PROPERTIES.has(key)) throw new TokenSchemaError(`unknown group property ${pyRepr(key)}`, here);
      continue;
    }
    if (!NAME.test(key)) {
      throw new TokenSchemaError(`invalid token/group name ${pyRepr(key)} (letters, digits, '-', '_' only)`, here);
    }
    walkChild(node[key], [...prefix, key], groupType, out);
  }
}

/** Python `read_tokens`: path -> raw token, in walk order. */
export function readTokens(document: unknown): Map<string, RawToken> {
  if (!isMapping(document)) throw new TokenSchemaError('token document must be a JSON object');
  const out = new Map<string, RawToken>();
  walk(document, [], null, out);
  if (out.size === 0) throw new TokenSchemaError('token document defines no tokens');
  return out;
}

// --------------------------------------------------------------------------- RESOLVE_ALIASES / DETECT_CYCLES

function aliasTarget(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const match = ALIAS.exec(pyStrip(value));
  return match?.[1] ?? null;
}

function tierViolation(token: ResolvedToken, raw: RawToken): string | null {
  const tier = token.tier;
  const target = token.aliasOf;
  if (tier === null) return `tiered sources may only contain ${pyRepr(TIERS)} top-level groups`;
  if (tier === TIER_PRIMITIVE && target !== null) return 'primitive (T1) tokens must be literal values';
  if ((tier === TIER_SEMANTIC || tier === TIER_COMPONENT) && token.type === 'color' && target === null) {
    return `${tier} color tokens must alias a lower tier, not hold a raw value`;
  }
  if (tier === TIER_COMPONENT && target !== null && target.startsWith(`${TIER_PRIMITIVE}.`)) {
    return 'component (T3) tokens must alias semantic (T2) tokens, not primitives';
  }
  if (tier === TIER_PRIMITIVE && raw.declaredType === null && raw.inheritedType === null) {
    return 'primitive tokens must declare $type';
  }
  return null;
}

function enforceTiers(raw: ReadonlyMap<string, RawToken>, resolved: ReadonlyMap<string, ResolvedToken>): void {
  for (const [path, token] of resolved) {
    const raw_ = raw.get(path);
    const problem = raw_ === undefined ? null : tierViolation(token, raw_);
    if (problem !== null) throw new TokenTierError(problem, path);
  }
}

class Resolver {
  readonly resolved = new Map<string, ResolvedToken>();

  constructor(private readonly raw: ReadonlyMap<string, RawToken>) {}

  resolve(path: string, stack: readonly string[]): ResolvedToken {
    const done = this.resolved.get(path);
    if (done !== undefined) return done;
    if (stack.includes(path)) throw new TokenCycleError([...stack.slice(stack.indexOf(path)), path]);
    const token = this.raw.get(path);
    if (token === undefined) {
      throw new MissingAliasError(`alias references unknown token {${path}}`, stack[stack.length - 1] ?? path);
    }
    const target = aliasTarget(token.value);
    const explicit = token.declaredType || token.inheritedType;
    const result = target !== null ? this.viaAlias(token, target, explicit, stack) : literal(token, explicit);
    this.resolved.set(path, result);
    return result;
  }

  private viaAlias(token: RawToken, target: string, explicit: string | null, stack: readonly string[]): ResolvedToken {
    if (!this.raw.has(target)) throw new MissingAliasError(`alias references unknown token {${target}}`, token.path);
    const base = this.resolve(target, [...stack, token.path]);
    if (explicit !== null && explicit !== base.type) {
      throw new TokenTypeError(
        `declared $type ${pyRepr(explicit)} does not match alias target type ${pyRepr(base.type)} ({${target}})`,
        token.path,
      );
    }
    return new ResolvedToken(token.path, base.type, base.value, base.css, target, token.description);
  }
}

function literal(token: RawToken, explicit: string | null): ResolvedToken {
  const value = token.value;
  if (typeof value === 'string' && (value.includes('{') || value.includes('}'))) {
    throw new TokenSchemaError("malformed alias; expected exactly '{group.token}'", token.path);
  }
  if (explicit === null) throw new TokenTypeError('literal token has no $type (declared or inherited)', token.path);
  if (!SUPPORTED_TYPES.has(explicit)) throw new TokenTypeError(`unsupported $type ${pyRepr(explicit)}`, token.path);
  const css = normalizeValue(explicit, value, token.path);
  return new ResolvedToken(token.path, explicit, value, css, null, token.description);
}

function sortedByPath<T>(map: ReadonlyMap<string, T>): Map<string, T> {
  return new Map(sortedStrings(map.keys()).map((path): [string, T] => [path, map.get(path) as T]));
}

/** Python `compile_graph`. */
export function compileGraph(document: unknown, options: { readonly tiered?: boolean } = {}): TokenGraph {
  const tiered = options.tiered ?? false;
  const raw = readTokens(document);
  const resolver = new Resolver(raw);
  for (const path of sortedStrings(raw.keys())) resolver.resolve(path, []);
  if (tiered) enforceTiers(raw, resolver.resolved);
  return new TokenGraph(sortedByPath(resolver.resolved), sourceHash(document), tiered);
}

// --------------------------------------------------------------------------- GENERATE_CSS

/** Python `css_variable`: dotted camelCase path -> `--prefix-kebab-case`. */
export function cssVariable(path: string, prefix = ''): string {
  const segments = path.split('.').map((part) => part.replace(CAMEL, '-$1').toLowerCase().replaceAll('_', '-'));
  const name = segments.join('-');
  return prefix ? `--${prefix}-${name}` : `--${name}`;
}

function declarations(graph: TokenGraph, prefix: string, only: ReadonlySet<string> | null = null): string[] {
  const lines: string[] = [];
  for (const [path, token] of graph.tokens) {
    if (only !== null && !only.has(path)) continue;
    const value = token.aliasOf ? `var(${cssVariable(token.aliasOf, prefix)})` : token.css;
    lines.push(`  ${cssVariable(path, prefix)}: ${value};`);
  }
  return lines;
}

export interface GenerateCssOptions {
  readonly prefix?: string;
  readonly sourceLabel?: string;
  readonly selector?: string;
  readonly themes?: Readonly<Record<string, TokenGraph>> | null;
}

function themeBlock(name: string, theme: TokenGraph, graph: TokenGraph, prefix: string): string[] {
  const overridden = sortedStrings([...theme.tokens.keys()].filter((p) => graph.tokens.has(p)));
  const unknown = sortedStrings([...theme.tokens.keys()].filter((p) => !graph.tokens.has(p)));
  if (unknown.length > 0) {
    throw new TokenSchemaError(`theme ${pyRepr(name)} defines tokens absent from the base: ${pyRepr(unknown)}`);
  }
  for (const path of overridden) {
    if (theme.get(path).type !== graph.get(path).type) {
      throw new TokenTypeError(`theme ${pyRepr(name)} changes the token type`, path);
    }
  }
  return ['', `[data-amc-theme="${name}"] {`, ...declarations(theme, prefix, new Set(overridden)), '}'];
}

/**
 * Deterministic CSS custom properties. Aliases stay aliases (`var()`), so the
 * semantic layer keeps pointing at the primitive it names.
 */
export function generateCss(graph: TokenGraph, options: GenerateCssOptions = {}): string {
  const prefix = options.prefix ?? '';
  const themes = options.themes ?? {};
  const header = [
    '/* GENERATED FILE -- do not edit by hand.',
    ` * compiler: ${COMPILER_VERSION} (${DTCG_FORMAT})`,
    ` * source: ${options.sourceLabel ?? 'tokens'}`,
    ` * source-sha256: ${graph.sourceHash}`,
    ' */',
  ];
  const body = [`${options.selector ?? ':root'} {`, ...declarations(graph, prefix), '}'];
  for (const name of sortedStrings(Object.keys(themes))) {
    body.push(...themeBlock(name, themes[name] as TokenGraph, graph, prefix));
  }
  return `${[...header, ...body].join('\n')}\n`;
}

/** Python `_deep_merge`: override wins; nested groups (objects without `$value`) merge. */
export function deepMerge(base: unknown, override: unknown): Record<string, unknown> {
  if (!isMapping(base) || !isMapping(override)) {
    const bad = isMapping(base) ? override : base;
    throw new PythonRuntimeError('AttributeError', `'${pyTypeName(bad)}' object has no attribute 'items'`);
  }
  const merged: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
  for (const [key, value] of Object.entries(base)) merged[key] = value;
  for (const [key, value] of Object.entries(override)) {
    const current = merged[key];
    const nest = isMapping(value) && !Object.hasOwn(value, '$value') && isMapping(current);
    merged[key] = nest ? deepMerge(current, value) : value;
  }
  return merged;
}

export interface CompileCssOptions {
  readonly prefix?: string;
  readonly tiered?: boolean;
  readonly sourceLabel?: string;
  /** Theme name -> override document. Iterated in JS object order (see index.ts notes). */
  readonly themes?: Readonly<Record<string, unknown>> | null;
}

function themeGraph(document: unknown, themeDoc: unknown, tiered: boolean): TokenGraph {
  // A theme may alias base tokens, so it is resolved against base + override.
  const mergedGraph = compileGraph(deepMerge(document, themeDoc), { tiered });
  const overridePaths = sortedStrings(readTokens(themeDoc).keys());
  const tokens = new Map(overridePaths.map((p): [string, ResolvedToken] => [p, mergedGraph.get(p)]));
  return new TokenGraph(tokens, sourceHash(themeDoc), tiered);
}

/** Python `compile_css`: returns `[graph, css]`. */
export function compileCss(document: unknown, options: CompileCssOptions = {}): [TokenGraph, string] {
  const tiered = options.tiered ?? false;
  const graph = compileGraph(document, { tiered });
  const themes: Record<string, TokenGraph> = Object.create(null) as Record<string, TokenGraph>;
  for (const [name, themeDoc] of Object.entries(options.themes ?? {})) {
    themes[name] = themeGraph(document, themeDoc, tiered);
  }
  const css = generateCss(graph, { prefix: options.prefix ?? '', sourceLabel: options.sourceLabel ?? 'tokens', themes });
  return [graph, css];
}

/** Path -> normalized CSS literal, for reporting and contrast checks. */
export function flatten(graph: TokenGraph): Map<string, string> {
  return new Map([...graph.tokens].map(([path, token]): [string, string] => [path, token.css]));
}
