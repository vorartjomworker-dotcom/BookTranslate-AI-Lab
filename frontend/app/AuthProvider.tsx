'use client';

import { Fragment, createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { setAccessToken, setUnauthorizedHandler } from './lib/api';
import { login as apiLogin, logout as apiLogout } from './lib/auth';
import type { AuthUser } from './lib/auth-types';

type AuthContextValue = {
  user: AuthUser | null;
  status: 'checking' | 'authenticated' | 'unauthenticated';
  sessionExpired: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  reauthenticate: () => void;
  dismissSessionExpired: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<'checking' | 'authenticated' | 'unauthenticated'>('unauthenticated');
  const [sessionExpired, setSessionExpired] = useState(false);
  const [workspaceVersion, setWorkspaceVersion] = useState(0);
  const hasSessionRef = useRef(false);
  // Owner of the currently mounted workspace subtree (identity boundary for reauth).
  const workspaceOwnerIdRef = useRef<number | null>(null);
  // True only while a session-expiry reauthentication is pending a fresh login.
  const pendingReauthRef = useRef(false);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAccessToken(null);
      if (!hasSessionRef.current) return;
      // A 401 invalidates visible auth without remounting the workspace. Its owner
      // identity stays available until the next login can compare user ids.
      hasSessionRef.current = false;
      setSessionExpired(true);
      setUser(null);
      setStatus('unauthenticated');
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await apiLogin(email, password);
    if (pendingReauthRef.current) {
      // Same-user reauth keeps the workspace; a different user must never see it,
      // so remount before the new user/status become visible.
      if (workspaceOwnerIdRef.current !== null && workspaceOwnerIdRef.current !== response.user.id) {
        setWorkspaceVersion((current) => current + 1);
      }
      pendingReauthRef.current = false;
    }
    workspaceOwnerIdRef.current = response.user.id;
    hasSessionRef.current = true;
    setSessionExpired(false);
    setUser(response.user);
    setStatus('authenticated');
  }, []);

  const logout = useCallback(async () => {
    // Disable the expiry callback before the revoke request so a 401 from an already
    // expired/revoked token cannot turn an explicit logout into a session-expired dialog.
    hasSessionRef.current = false;
    pendingReauthRef.current = false;
    workspaceOwnerIdRef.current = null;

    try {
      // Best effort: when reachable, the backend increments token_version and revokes
      // every outstanding access token for this user. Local logout must still complete
      // if the network or backend is unavailable.
      await apiLogout();
    } catch {
      // Intentionally ignored; client-side identity/workspace teardown is unconditional.
    } finally {
      setAccessToken(null);
      setSessionExpired(false);
      setUser(null);
      setStatus('unauthenticated');
      // Change the keyed subtree so every workspace-local state value, ref, pending
      // controller, selection and unsaved draft is discarded before another user logs in.
      setWorkspaceVersion((current) => current + 1);
    }
  }, []);

  const reauthenticate = useCallback(() => {
    hasSessionRef.current = false;
    pendingReauthRef.current = true;
    setAccessToken(null);
    setSessionExpired(false);
    setUser(null);
    setStatus('unauthenticated');
    // Intentionally do not change workspaceVersion here: only `login` may decide to
    // remount, once it knows whether the same user reauthenticated.
  }, []);

  // Kept only for compatibility with existing consumers. It must never unlock a
  // confirmed expired session; reauthentication is the only path out of the gate.
  const dismissSessionExpired = useCallback(() => undefined, []);

  return (
    <AuthContext.Provider value={{ user, status, sessionExpired, login, logout, reauthenticate, dismissSessionExpired }}>
      <Fragment key={workspaceVersion}>{children}</Fragment>
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
}
