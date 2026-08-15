import { api, setAccessToken } from './api';
import type { AccessTokenResponse, AuthUser } from './auth-types';

export async function login(email: string, password: string): Promise<AccessTokenResponse> {
  const response = await api.post<AccessTokenResponse>('/api/v1/auth/login', { email, password });
  setAccessToken(response.access_token);
  return response;
}

export async function logout(): Promise<void> {
  try {
    await api.post('/api/v1/auth/logout');
  } catch {
    // Logging out client-side must always succeed even if the session already expired.
  } finally {
    setAccessToken(null);
  }
}

export async function refresh(): Promise<AccessTokenResponse> {
  const response = await api.post<AccessTokenResponse>('/api/v1/auth/refresh');
  setAccessToken(response.access_token);
  return response;
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  return api.get<AuthUser>('/api/v1/auth/me');
}
