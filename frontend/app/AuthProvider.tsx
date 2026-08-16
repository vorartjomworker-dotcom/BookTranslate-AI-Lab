'use client';

import { Fragment, createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { setAccessToken, setUnauthorizedHandler } from './lib/api';
import { login as apiLogin } from './lib/auth';
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

  useEffect(() => {
    setUnauthorizedHandler(() => {
      // A 401 must not remount the workspace because the user may have an unsaved
      // translation draft. Reauthentication is explicit and preserves the mounted
      // workspace; a real logout uses a new workspace key and clears all local state.
      if (hasSessionRef.current) setSessionExpired(true);
      setAccessToken(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await apiLogin(email, password);
    hasSessionRef.current = true;
    setSessionExpired(false);
    setUser(response.user);
    setStatus('authenticated');
  }, []);

  const logout = useCallback(async () => {
    hasSessionRef.current = false;
    setAccessToken(null);
    setSessionExpired(false);
    setUser(null);
    setStatus('unauthenticated');
    // Change the keyed subtree so every workspace-local state value, ref, pending
    // controller, selection and unsaved draft is discarded before another user logs in.
    setWorkspaceVersion((current) => current + 1);
  }, []);

  const reauthenticate = useCallback(() => {
    hasSessionRef.current = false;
    setAccessToken(null);
    setUser(null);
    setStatus('unauthenticated');
    // Intentionally do not change workspaceVersion: the same HomePage instance must
    // survive the login gate so an unsaved draft can be restored after session expiry.
  }, []);

  const dismissSessionExpired = useCallback(() => setSessionExpired(false), []);

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
