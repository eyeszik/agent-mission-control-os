export function scrubPIIFromUI(data: Record<string, unknown>): Record<string, unknown> {
  const clone = { ...data };
  
  // Scaffold: Very naive keys matching
  const piiKeys = ['email', 'phone', 'ssn', 'password', 'token', 'secret'];
  
  for (const [key, value] of Object.entries(clone)) {
    if (piiKeys.some(p => key.toLowerCase().includes(p))) {
      clone[key] = '[REDACTED]';
    } else if (typeof value === 'object' && value !== null) {
      clone[key] = scrubPIIFromUI(value as Record<string, unknown>);
    }
  }
  
  return clone;
}
