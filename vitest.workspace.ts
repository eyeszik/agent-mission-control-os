import { defineWorkspace } from 'vitest/config';

export default defineWorkspace([
  'apps/web',
  'packages/shared',
  'packages/errors',
  'packages/config',
  'packages/logger',
  'packages/constants',
  'packages/db',
  'packages/testing',
  'services/langgraph',
  'infra/cloudflare'
]);
