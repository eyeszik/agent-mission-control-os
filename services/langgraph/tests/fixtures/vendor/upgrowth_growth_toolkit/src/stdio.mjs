#!/usr/bin/env node
// Local stdio transport for the Growth Toolkit, for MCP clients and directories
// that start servers as a local process (for example Glama's build checks).
// It reads newline-delimited JSON-RPC from stdin, passes each message to the
// same handler the Cloudflare Worker uses, and writes replies to stdout.
// Usage: node src/stdio.mjs
import { createInterface } from 'node:readline';
import worker from './worker.mjs';

const ENDPOINT = 'https://upgrowth.in/connected-app/mcp';

async function handle(line) {
  const text = line.trim();
  if (!text) return;
  let res;
  try {
    res = await worker.fetch(new Request(ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json', 'user-agent': 'upgrowth-stdio' },
      body: text,
    }));
  } catch (err) {
    process.stderr.write('stdio handler error: ' + (err && err.message ? err.message : String(err)) + '\n');
    return;
  }
  const body = (await res.text()).trim();
  if (!body) return; // notifications get no reply
  process.stdout.write(body.replace(/\n/g, ' ') + '\n');
}

let queue = Promise.resolve();
const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on('line', (line) => { queue = queue.then(() => handle(line)); });
rl.on('close', () => { queue.then(() => process.exit(0)); });
