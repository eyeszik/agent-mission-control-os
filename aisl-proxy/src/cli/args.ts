/** Minimal `--key value` / `--flag` parsing shared by the operator CLIs. */
export function parseArgs(argv: readonly string[]): Map<string, string> {
  const parsed = new Map<string, string>();
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token?.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[index + 1];
    if (next !== undefined && !next.startsWith('--')) {
      parsed.set(key, next);
      index += 1;
    } else {
      parsed.set(key, 'true');
    }
  }
  return parsed;
}

export function numberArg(args: Map<string, string>, key: string): number | undefined {
  const value = args.get(key);
  if (value === undefined) return undefined;
  const parsed = Number(value);
  if (!Number.isInteger(parsed)) {
    throw new Error(`--${key} must be an integer`);
  }
  return parsed;
}

export function boolArg(args: Map<string, string>, key: string): boolean {
  const value = args.get(key);
  return value !== undefined && value !== 'false';
}

export async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString('utf8');
}

/** Console logger shaped like the services' pino-style `(obj, msg)` interface. */
export const cliLogger = {
  info: (obj: object, msg: string) => process.stdout.write(`${msg} ${JSON.stringify(obj)}\n`),
  warn: (obj: object, msg: string) => process.stderr.write(`WARN ${msg} ${JSON.stringify(obj)}\n`),
  error: (obj: object, msg: string) => process.stderr.write(`ERROR ${msg} ${JSON.stringify(obj)}\n`),
};
