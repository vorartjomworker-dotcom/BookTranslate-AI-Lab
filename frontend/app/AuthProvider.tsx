'use client';

import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { setAccessToken, setUnauthorizedHandler } from './lib/api';
import { login as apiLogin } from './lib/auth';
import type { AuthUser } from './lib/auth-types';

type AuthContextValue = {
  user: AuthUser | null;
  status: 'checking' | 'authenticated' | 'unauthenticated';
  sessionExpired: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  dismissSessionExpired: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<'checking' | 'authenticated' | 'unauthenticated'>('checking');
  const [sessionExpired, setSessionExpired] = useState(false);
  const hasSessionRef = useRef(false);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      // Do not force-unmount the workspace here: a 401 during an in-flight save must
      // surface a clear "session expired" message without discarding the user's
      // unsaved draft. The user re-authenticates explicitly via login/logout.
      if (hasSessionRef.current) setSessionExpired(true);
      setAccessToken(null);
    });
    setStatus('unauthenticated');
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
    setUser(null);
    setStatus('unauthenticated');
  }, []);

  const dismissSessionExpired = useCallback(() => setSessionExpired(false), []);

  return (
    <AuthContext.Provider value={{ user, status, sessionExpired, login, logout, dismissSessionExpired }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within an AuthProvider');
  return context;
}
