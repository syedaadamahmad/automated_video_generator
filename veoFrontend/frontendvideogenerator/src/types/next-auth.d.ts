// src/types/next-auth.d.ts
// Augments NextAuth's built-in types to add role and email to
// session.user and the JWT — eliminating all `as any` casts.
//
// Role is inlined (not imported from './index') because relative
// imports inside ambient declaration files that augment external
// modules fail under TypeScript's "bundler" moduleResolution.

import type { DefaultSession, DefaultUser } from 'next-auth'
import type { DefaultJWT } from 'next-auth/jwt'

// Must stay in sync with Role in src/types/index.ts
type AppRole = 'admin' | 'editor' | 'viewer'

declare module 'next-auth' {
  interface Session {
    user: {
      role:  AppRole
      email: string
    } & DefaultSession['user']
  }

  // User is what authorize() returns. We store userRole (not role)
  // to avoid a Next.js 15 internal conflict where token.role is
  // called as a function inside the NextAuth JWT handler.
  interface User extends DefaultUser {
    userRole: AppRole
  }
}

declare module 'next-auth/jwt' {
  interface JWT extends DefaultJWT {
    userRole: AppRole
    email:    string
  }
}