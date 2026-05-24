import { defineWorkspace } from 'vitest/config';

export default defineWorkspace([
  'apps/web',
  'packages/shared',
  'services/langgraph',
  'infra/cloudflare'
]);
