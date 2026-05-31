'use client';

import { useState } from 'react';
import { signIn } from 'next-auth/react';

/**
 * Login page — single-user operator login.
 * Minimal form; no registration flow needed.
 */
export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    const result = await signIn('credentials', {
      username,
      password,
      redirect: true,
      callbackUrl: '/',
    });

    if (result?.error) {
      setError('Invalid credentials');
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)]">
      <div className="w-full max-w-sm p-6 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)]">
        <div className="mb-6 text-center">
          <h1 className="text-lg font-bold text-[var(--color-text-primary)]">ASTRAEUS</h1>
          <p className="text-xs text-[var(--color-text-muted)] mt-1">Operator Terminal</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-xs text-[var(--color-text-muted)] block mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-primary)]"
              autoFocus
            />
          </div>

          <div>
            <label className="text-xs text-[var(--color-text-muted)] block mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-primary)]"
            />
          </div>

          {error && (
            <p className="text-xs text-[var(--color-negative)]">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !username || !password}
            className="w-full px-3 py-2 text-sm font-medium rounded bg-[var(--color-status-info)]/20 text-[var(--color-status-info)] border border-[var(--color-status-info)]/30 hover:bg-[var(--color-status-info)]/30 disabled:opacity-50"
          >
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}
