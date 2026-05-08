// src/components/Navbar.tsx
'use client'
import { useSession, signOut } from 'next-auth/react'

export function Navbar() {
  const { data: session } = useSession()
  // session.user typed via src/types/next-auth.d.ts
  const name = session?.user?.name ?? ''
  const role = session?.user?.role ?? ''

  return (
    <nav
      style={{
        borderBottom: '1px solid var(--border)',
        padding: '0 2rem',
        height: 52,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: 'var(--bg)',
        position: 'sticky',
        top: 0,
        zIndex: 40,
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
      }}
    >
      {/* Logo */}
      <div
        style={{
          fontSize: '1rem',
          fontWeight: 600,
          letterSpacing: '-0.02em',
          color: 'var(--text)',
        }}
      >
        Veo <span style={{ color: 'var(--text2)', fontWeight: 400 }}>Studio</span>
      </div>

      {/* Right side */}
      {session && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
          }}
        >
          <span
            style={{
              fontSize: 11,
              fontWeight: 500,
              padding: '2px 8px',
              borderRadius: 20,
              border: '1px solid var(--border)',
              color: 'var(--text2)',
              textTransform: 'capitalize',
            }}
          >
            {role}
          </span>
          <span style={{ fontSize: 13, color: 'var(--text2)' }}>{name}</span>
          <button
            onClick={() => signOut({ callbackUrl: '/login' })}
            style={{
              fontSize: 12,
              fontWeight: 500,
              padding: '4px 12px',
              borderRadius: 'var(--pill)',
              border: '1px solid var(--border)',
              background: 'none',
              color: 'var(--text2)',
              cursor: 'pointer',
              fontFamily: 'inherit',
              transition: 'background .15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface2)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'none')}
          >
            Sign out
          </button>
        </div>
      )}
    </nav>
  )
}