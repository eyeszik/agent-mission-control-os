import { describe, it, expect } from 'vitest';
import { scrubPIIFromUI } from '../lib/security/sanitize';

describe('Client-Side PII Scrubbing', () => {
  it('should redact exact matches for known PII keys', () => {
    const result = scrubPIIFromUI({ email: 'a@b.com', phone: '555-1234', ssn: '123-45-6789' });
    expect(result).toEqual({ email: '[REDACTED]', phone: '[REDACTED]', ssn: '[REDACTED]' });
  });

  it('should recursively scrub nested objects', () => {
    const result = scrubPIIFromUI({
      user: { name: 'Isaac', email: 'isaac@example.com' },
      auth: { token: 'abc123' },
    });
    expect(result).toEqual({
      user: { name: 'Isaac', email: '[REDACTED]' },
      auth: { token: '[REDACTED]' },
    });
  });

  it('should leave non-PII keys intact', () => {
    const result = scrubPIIFromUI({ brand_name: 'Acme', target_audience: 'Devs' });
    expect(result).toEqual({ brand_name: 'Acme', target_audience: 'Devs' });
  });
});
