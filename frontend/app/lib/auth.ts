import { api, setAccessToken } from './api';
import type { AccessTokenResponse } from './auth-types';

export async function login(email: string, password: string): Promise<AccessTokenResponse> {
  const response = await api.post<AccessTokenResponse>('/api/v1/auth/login', { email, password });
  setAccessToken(response.access_token);
  return response;
}

export async function logout(): Promise<void> {
  // Keep this bounded so a broken network cannot trap the user in the authenticated UI.
  await api.post<void>('/api/v1/auth/logout', undefined, { timeoutMs: 2000 });
}

export function clearAuthToken(): void {
  setAccessToken(null);
}
