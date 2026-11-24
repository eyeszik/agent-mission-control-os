// Network denial preload for reviewed Node MCP profiles (agency/council/mcp_profiles.py).
//
// Loaded with `node --import <this file>` before the server's own code. It replaces the web-platform
// network globals with a function that throws, and makes them non-writable and non-configurable so the
// server cannot restore them. A reviewed server that only reaches the network through these globals
// (verified per profile; see tests/test_mcp_upgrowth_profile.py) therefore cannot make a request.
//
// This is defence in depth, not a sandbox: it does not stop code that imports node:net or node:http.
// Profiles that use it must also pass a source check that the server imports neither, and run under the
// Node permission model (no child processes, workers, native addons or file writes).
const refuse = () => {
  throw new Error('network access is disabled for this MCP server');
};
for (const name of ['fetch', 'WebSocket', 'EventSource', 'XMLHttpRequest']) {
  Object.defineProperty(globalThis, name, { value: refuse, writable: false, configurable: false, enumerable: false });
}
