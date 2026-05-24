export interface Env {
  // Key-Value store for rapid lookups and idempotency cache
  KV_CACHE: KVNamespace;

  // Durable Object namespace binding
  PROJECT_COORDINATOR: DurableObjectNamespace;

  // R2 bucket for artifact storage (Canonical state outside DO memory)
  R2_ARTIFACTS: R2Bucket;

  // Background queue for async tasks
  BACKGROUND_TASKS: Queue;

  // Environment variables
  ENVIRONMENT: 'dev' | 'staging' | 'prod';
  INTERNAL_API_KEY: string;
}
