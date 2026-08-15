'use client';

import { FormEvent, useState } from 'react';
import { useAuth } from '../AuthProvider';
import { ApiError, ApiTimeoutError } from '../lib/api';

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof ApiTimeoutError || error instanceof Error) return error.message;
  return 'Unable to sign in. Please try again.';
}

export function LoginView() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await login(email, password);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="loginShell">
      <form className="panel loginPanel" onSubmit={handleSubmit}>
        <div className="brandMark">
          <span className="brandGlyph">BT</span>
          <span>
            <strong>BookTranslate</strong>
            <small>AI LAB / WORKSPACE</small>
          </span>
        </div>
        <h1>Sign in</h1>
        <p className="mutedText">Sign in with your workspace account to continue.</p>
        {error && (
          <div className="alert alertError" role="alert">
            <strong>Sign-in failed</strong>
            <span>{error}</span>
          </div>
        )}
        <label className="fieldLabel" htmlFor="loginEmail">
          Email
          <input id="loginEmail" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label className="fieldLabel" htmlFor="loginPassword">
          Password
          <input id="loginPassword" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        <button className="primaryButton" type="submit" disabled={busy}>
          {busy ? 'Signing in...' : 'Sign in'} <span>-&gt;</span>
        </button>
      </form>
    </main>
  );
}
