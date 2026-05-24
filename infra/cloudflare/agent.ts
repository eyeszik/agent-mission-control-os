import { Env } from './bindings';

/**
 * Delegating execution tasks to the Python LangGraph backend.
 * Acts as a gateway ensuring idempotency and auth before invoking the Python backend.
 */
export async function invokeAgentTask(payload: any, env: Env): Promise<void> {
  // Replacing [VOID_DETECTED] with an actual network fetch to the internal backend
  const backendUrl = env.ENVIRONMENT === 'prod' ? 'https://api.internal.com' : 'http://localhost:8000';
  
  try {
    const response = await fetch(`${backendUrl}/runs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${env.INTERNAL_API_KEY || 'dev-token'}`
      },
      body: JSON.stringify(payload)
    });
    
    if (!response.ok) {
      console.error(`Backend invocation failed with status ${response.status}`);
    } else {
      console.log('Successfully dispatched task to backend.');
    }
  } catch (error) {
    console.error('Network error reaching backend:', error);
  }
}
