export const DEFAULT_PUBLIC_API_URL = 'http://localhost:8000';

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1']);
const INVALID_API_URL_MESSAGE =
  'NEXT_PUBLIC_API_URL must be an exact HTTPS origin, or an HTTP loopback origin for local development.';

export function validatePublicApiBaseUrl(value: string | undefined): string {
  const candidate = (value ?? DEFAULT_PUBLIC_API_URL).trim();
  if (!candidate) throw new Error(INVALID_API_URL_MESSAGE);

  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error(INVALID_API_URL_MESSAGE);
  }

  const protocol = parsed.protocol.toLowerCase();
  const hostname = parsed.hostname.toLowerCase();
  if (protocol !== 'http:' && protocol !== 'https:') throw new Error(INVALID_API_URL_MESSAGE);
  if (!hostname) throw new Error(INVALID_API_URL_MESSAGE);
  if (parsed.username || parsed.password) throw new Error(INVALID_API_URL_MESSAGE);
  if (parsed.pathname !== '/' || parsed.search || parsed.hash) throw new Error(INVALID_API_URL_MESSAGE);
  if (protocol === 'http:' && !LOOPBACK_HOSTS.has(hostname)) throw new Error(INVALID_API_URL_MESSAGE);

  return parsed.origin;
}
