import { afterEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_PUBLIC_API_URL, validatePublicApiBaseUrl } from '../config/public-api-url';

const unsafeValues = [
  'http://api.example.com',
  'ftp://api.example.com',
  'https://user:password@api.example.com',
  'https://api.example.com/api',
  'https://api.example.com/?token=secret',
  'https://api.example.com/#fragment',
  'https://api.example.com:99999',
  '//api.example.com',
  'api.example.com',
  '',
];

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe('validatePublicApiBaseUrl', () => {
  it('uses the local development origin when the variable is unset', () => {
    expect(validatePublicApiBaseUrl(undefined)).toBe(DEFAULT_PUBLIC_API_URL);
  });

  it.each([
    ['https://api.example.com', 'https://api.example.com'],
    ['https://api.example.com:8443/', 'https://api.example.com:8443'],
    [' http://localhost:8000/ ', 'http://localhost:8000'],
    ['http://127.0.0.1:8001', 'http://127.0.0.1:8001'],
    ['http://[::1]:8002', 'http://[::1]:8002'],
  ])('accepts and canonicalizes safe origin %s', (value, expected) => {
    expect(validatePublicApiBaseUrl(value)).toBe(expected);
  });

  it.each(unsafeValues)('rejects unsafe or ambiguous API base %s', (value) => {
    expect(() => validatePublicApiBaseUrl(value)).toThrow(
      'NEXT_PUBLIC_API_URL must be an exact HTTPS origin, or an HTTP loopback origin for local development.',
    );
  });

  it('does not echo credentials from an invalid configured URL', () => {
    const password = 'frontend-password-must-not-leak';
    const token = 'frontend-token-must-not-leak';
    let message = '';
    try {
      validatePublicApiBaseUrl(`https://user:${password}@api.example.com/?token=${token}`);
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
    }

    expect(message).not.toContain(password);
    expect(message).not.toContain(token);
    expect(message).not.toContain('api.example.com');
  });

  it('makes next.config fail closed for an insecure remote HTTP API', async () => {
    vi.stubEnv('NEXT_PUBLIC_API_URL', 'http://api.example.com');
    vi.resetModules();

    await expect(import('../next.config')).rejects.toThrow(
      'NEXT_PUBLIC_API_URL must be an exact HTTPS origin, or an HTTP loopback origin for local development.',
    );
  });
});
