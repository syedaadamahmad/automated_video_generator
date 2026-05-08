// src/lib/auth-options.ts
import type { NextAuthOptions } from 'next-auth'
import CredentialsProvider from 'next-auth/providers/credentials'
import type { Role } from '@/types'

const STUB_USERS: Record<string, { name: string; email: string; role: Role; password: string }> = {
  'admin@veo.local':  { name: 'Admin',  email: 'admin@veo.local',  role: 'admin',  password: 'admin'  },
  'editor@veo.local': { name: 'Editor', email: 'editor@veo.local', role: 'editor', password: 'editor' },
  'viewer@veo.local': { name: 'Viewer', email: 'viewer@veo.local', role: 'viewer', password: 'viewer' },
}

function _authenticate(email: string, password: string) {
  const user = STUB_USERS[email.toLowerCase().trim()]
  if (user && user.password === password) {
    return { id: user.email, name: user.name, email: user.email, userRole: user.role }
  }
  return null
}

export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: 'credentials',
      credentials: {
        email:    { label: 'Email',    type: 'email'    },
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null
        return _authenticate(credentials.email, credentials.password)
      },
    }),
  ],

  callbacks: {
    // Persist role into the JWT — use 'userRole' key to avoid any NextAuth
    // internal conflict with a 'role' property on the JWT type.
    async jwt({ token, user }) {
      if (user) {
        // user is typed via next-auth.d.ts to include userRole and email
        token.userRole = user.userRole
        token.email    = user.email ?? ''
      }
      return token
    },
    async session({ session, token }) {
      // session.user is typed via next-auth.d.ts — no cast needed
      session.user.role  = token.userRole
      // token.email is string; DefaultSession email is string | null — coerce
      session.user.email = token.email ?? ''​
      return session
    },
  },

  pages: {
    signIn: '/login',
  },

  session: {
    strategy: 'jwt',
    maxAge: 8 * 60 * 60, // 8 hours
  },

  secret: process.env.NEXTAUTH_SECRET ?? 'veo-studio-dev-secret-change-in-production',
}