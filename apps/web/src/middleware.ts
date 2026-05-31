/**
 * Next.js middleware — enforces authentication on all protected routes.
 *
 * Unauthenticated requests to protected routes are redirected to /login.
 * Public routes (login, health, static assets) are allowed through.
 */

import { getToken } from 'next-auth/jwt';
import { NextRequest, NextResponse } from 'next/server';

// Routes that don't require authentication
const PUBLIC_PATHS = [
  '/login',
  '/api/auth',  // NextAuth endpoints
  '/api/health',
  '/_next',     // Next.js internals
  '/favicon.ico',
];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths
  if (PUBLIC_PATHS.some((path) => pathname.startsWith(path))) {
    return NextResponse.next();
  }

  // Allow static files
  if (pathname.includes('.') && !pathname.startsWith('/api/')) {
    return NextResponse.next();
  }

  // Check for valid session token
  const token = await getToken({
    req: request,
    secret: process.env.NEXTAUTH_SECRET,
  });

  if (!token) {
    // Redirect to login with callback URL
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('callbackUrl', pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Attach user info to headers for downstream use
  const response = NextResponse.next();
  response.headers.set('x-user-subject', token.sub || token.name as string || 'unknown');
  response.headers.set('x-user-role', (token.role as string) || 'operator');

  return response;
}

export const config = {
  // Match all routes except static files and Next.js internals
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico).*)',
  ],
};
