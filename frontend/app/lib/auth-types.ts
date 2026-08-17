export type UserRole = 'admin' | 'editor' | 'viewer';

export type AuthUser = {
  id: number;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
};

export type AccessTokenResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
};

export function canEdit(role: UserRole | null | undefined): boolean {
  return role === 'editor' || role === 'admin';
}

export function canAdminister(role: UserRole | null | undefined): boolean {
  return role === 'admin';
}
