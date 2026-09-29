#!/usr/bin/env node
/**
 * `tsc` emits only JavaScript, so the SQL migrations that live next to the
 * migration runner have to be copied into `dist` for the compiled image to
 * find them at `dist/db/migrations`.
 */
import { cp, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const source = join(root, 'src', 'db', 'migrations');
const target = join(root, 'dist', 'db', 'migrations');

await mkdir(target, { recursive: true });
await cp(source, target, { recursive: true });
process.stdout.write(`copied migrations -> ${target}\n`);
