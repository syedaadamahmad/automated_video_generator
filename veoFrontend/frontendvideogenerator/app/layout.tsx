// src/app/layout.tsx
import type { Metadata } from 'next'
import './globals.css'
import { SessionProvider } from './session-provider'
import { getServerSession } from 'next-auth'
import { authOptions } from '@/lib/auth-options'

export const metadata: Metadata = {
  title: 'Veo Studio',
  description: 'AI video generation platform',
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const session = await getServerSession(authOptions)
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <SessionProvider session={session}>
          {children}
        </SessionProvider>
      </body>
    </html>
  )
}