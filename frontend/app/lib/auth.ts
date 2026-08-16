import { api, setAccessToken } from './api';
import type { AccessTokenResponse } from './auth-types';

export async function login(email: string, password: string): Promise<AccessTokenResponse> {
  const response = await api.post<AccessTokenResponse>('/api/v1/auth/login', { email, password });
  setAccessToken(response.access_token);
  return response;
}

