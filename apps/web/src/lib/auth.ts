/**
 * NextAuth configuration — single-user scope mode.
 *
 * Uses Credentials provider with a single hardcoded operator account.
 * RBAC scaffolding stays for resume-relevance; the user table has one row.
 *
 * In production multi-user mode, swap to OAuth/OIDC provider.
 */

import type { NextAuthOptions } from 'next-auth';
import CredentialsProvider from 'next-auth/providers/credentials';

export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: 'Operator Login',
      credentials: {
        username: { label: 'Username', type: 'text' },
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        // Single-user: validate against env vars
        const validUser = process.env.AUTH_USERNAME || 'operator';
        const validPass = process.env.AUTH_PASSWORD || 'astraeus';

        if (
          credentials?.username === validUser &&
          credentials?.password === validPass
        ) {
          return {
            id: '1',
            name: 'Operator',
            email: 'operator@astraeus.local',
            role: 'operator',
          };
        }
        return null;
      },
    }),
  ],
  session: {
    strategy: 'jwt',
    maxAge: 24 * 60 * 60, // 24 hours
  },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.role = (user as { role?: string }).role || 'operator';
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        (session.user as { role?: string }).role = token.role as string;
      }
      return session;
    },
  },
  pages: {
    signIn: '/login',
  },
};
