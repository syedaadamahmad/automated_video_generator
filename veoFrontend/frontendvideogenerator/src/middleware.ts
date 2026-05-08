// src/middleware.ts
// Uses getToken (edge-safe) instead of next-auth/middleware re-export.
// The built-in withAuth export has JWT decryption issues on Next.js 15 + Turbopack.
import { getToken } from 'next-auth/jwt'
import { NextRequest, NextResponse } from 'next/server'

export async function middleware(req: NextRequest) {
  const token = await getToken({
    req,
    secret: process.env.NEXTAUTH_SECRET ?? 'veo-studio-dev-secret-change-in-production',
  })

  if (!token) {
    const loginUrl = new URL('/login', req.url)
    loginUrl.searchParams.set('callbackUrl', req.nextUrl.pathname)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!login|api/auth|_next|favicon.ico|robots.txt).*)'],
}