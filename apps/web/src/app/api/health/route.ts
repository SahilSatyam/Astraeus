import { NextResponse } from 'next/server';

/**
 * Health check endpoint for the BFF layer.
 * Used by load balancers and monitoring.
 */
export async function GET() {
  return NextResponse.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    version: process.env.npm_package_version || '0.1.0',
  });
}
