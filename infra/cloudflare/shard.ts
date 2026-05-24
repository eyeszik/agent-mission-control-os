import { Env } from './bindings';

/**
 * Shard generation logic to route requests to the correct Durable Object.
 * Enforces shard by tenant_id + project_id to avoid global singletons.
 */
export function getDOIdForProject(env: Env, tenantId: string, projectId: string): DurableObjectId {
  const shardKey = `${tenantId}::${projectId}`;
  // @ts-ignore
  return env.PROJECT_COORDINATOR.idFromName(shardKey);
}
