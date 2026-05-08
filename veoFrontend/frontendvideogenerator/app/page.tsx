// src/app/page.tsx
import { getServerSession } from 'next-auth'
import { authOptions } from '@/lib/auth-options'
import { redirect } from 'next/navigation'

export default async function RootPage() {
  const session = await getServerSession(authOptions)
  if (session) redirect('/generate')
  redirect('/login')
}